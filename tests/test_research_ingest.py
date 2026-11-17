"""Point-in-time research selection for the external runner.

Fixtures are local files. Nothing is fetched, and no live credential is used.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda

from tradingagents.agents.analysts.fundamentals_analyst import create_fundamentals_analyst
from tradingagents.agents.analysts.news_analyst import create_news_analyst
from tradingagents.agents.analysts.sentiment_analyst import create_sentiment_analyst
from tradingagents.dataflows.date_window import withhold_live_profile

ROOT = Path(__file__).resolve().parents[1] / "integrations" / "external_runner"
sys.path.insert(0, str(ROOT))

from research_ingest import (  # noqa: E402
    install_research_state,
    last_completed_session,
    parse_decision_at,
    prepare_run,
    resolve_instrument,
    retained_runs,
)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stamp(value: str) -> str:
    return value


def _record(**overrides) -> dict:
    base = {
        "symbol": "BABA",
        "market": "US",
        "kind": "financial_extract",
        "statement_scope": "per_share",
        "unit": "ADS",
        "currency": "CNY",
        "period_end": "2026-03-31",
        "published_at": "2026-05-20T12:00:00Z",
        "available_at": "2026-05-20T12:00:00Z",
        "captured_at": "2026-05-21T00:00:00Z",
        "source_url": "https://example.invalid/baba/20-f",
        "provenance": "fixture extract of a company filing",
        "generated": False,
        "original_urls": [],
        "company": "alibaba",
        "body": "BABA_FY2026_FIXTURE",
    }
    base.update(overrides)
    return base


def _write(corpus: Path, name: str, **overrides) -> Path:
    path = corpus / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_record(**overrides)), encoding="utf-8")
    return path


def _run(corpus: Path, runs: Path, symbol: str, market: str, decision: str, mode: str = "current", **kwargs):
    return prepare_run(
        symbol=symbol,
        market=market,
        decision_at=decision,
        mode=mode,
        corpus=corpus,
        runs_dir=runs,
        **kwargs,
    )


def _category(prepared, kind: str) -> dict:
    return next(item for item in prepared.manifest["categories"] if item["kind"] == kind)


class _RecordingLLM:
    def __init__(self):
        self.seen = []

    def bind_tools(self, tools, **kwargs):
        def run(value):
            messages = value.to_messages() if hasattr(value, "to_messages") else value
            self.seen.append(messages)
            return AIMessage(content="recorded")

        return RunnableLambda(run)

    def invoke(self, messages, *args, **kwargs):
        self.seen.append(messages)
        return AIMessage(content="recorded")

    def with_structured_output(self, *args, **kwargs):
        raise NotImplementedError


def _seen_text(llm: _RecordingLLM) -> str:
    parts = []
    for batch in llm.seen:
        for message in batch:
            content = getattr(message, "content", message)
            parts.append(content if isinstance(content, str) else str(content))
    return "\n".join(parts)


@pytest.mark.unit
def test_aliases_keep_ads_and_ordinary_listings_apart():
    assert resolve_instrument("BABA", "US").canonical == "BABA"
    assert resolve_instrument("09988", "HK").canonical == "9988.HK"
    assert resolve_instrument("700.HK", "HK").canonical == "0700.HK"
    assert resolve_instrument("02015.HK").listing_unit == "ordinary"
    assert resolve_instrument("LI").ordinary_per_listing == 2
    with pytest.raises(ValueError, match="not a HK"):
        resolve_instrument("BABA", "HK")
    with pytest.raises(ValueError, match="not a US"):
        resolve_instrument("0700", "US")
    with pytest.raises(ValueError, match="not a US"):
        resolve_instrument("2015", "US")


@pytest.mark.unit
def test_naive_cutoff_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        parse_decision_at("2026-11-17T09:00:00")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("market", "stamp", "expected"),
    [
        ("US", "2026-11-17T09:00:00-05:00", date(2026, 11, 16)),
        ("US", "2026-11-17T16:00:00-05:00", date(2026, 11, 17)),
        ("US", "2026-11-16T09:00:00-05:00", date(2026, 11, 13)),
        ("US", "2026-11-14T12:00:00-05:00", date(2026, 11, 13)),
        ("HK", "2026-11-17T15:59:00+08:00", date(2026, 11, 16)),
        ("HK", "2026-11-17T16:00:00+08:00", date(2026, 11, 17)),
    ],
)
def test_last_completed_session_dates(market, stamp, expected):
    assert last_completed_session(market, parse_decision_at(stamp)) == expected


@pytest.mark.unit
def test_holiday_walks_back_to_the_previous_open_session():
    # 2026-11-27 is a Friday. Before the close, with Thanksgiving closed,
    # the previous open session is Wednesday 2026-11-25.
    found = last_completed_session(
        "US",
        parse_decision_at("2026-11-27T10:00:00-05:00"),
        holidays={date(2026, 11, 26)},
    )
    assert found == date(2026, 11, 25)


@pytest.mark.unit
def test_newer_file_is_selected_and_filename_is_not_a_key(tmp_path):
    corpus, runs = tmp_path / "corpus", tmp_path / "runs"
    corpus.mkdir()
    _write(
        corpus, "digests/BABA_2026-11-15.md.json",
        kind="news", statement_scope="item", unit="item", currency="USD",
        period_end=None, published_at="2026-08-01T00:00:00Z",
        available_at="2026-08-01T00:00:00Z", captured_at="2026-08-01T01:00:00Z",
        source_url="https://example.invalid/baba/old-digest",
        body="STALE_FIXED_NAME",
    )
    _write(
        corpus, "news/later.json",
        kind="news", statement_scope="item", unit="item", currency="USD",
        period_end=None, published_at="2026-11-16T23:00:00Z",
        available_at="2026-11-16T23:00:00Z", captured_at="2026-11-16T23:05:00Z",
        source_url="https://example.invalid/baba/later-news",
        original_urls=["https://example.invalid/baba/source-article"],
        generated=True, provenance="generated digest of the article",
        body="BABA_NEWS_AFTER_MONDAY_CLOSE",
    )
    prepared = _run(corpus, runs, "BABA", "US", "2026-11-17T09:00:00-05:00")
    news = _category(prepared, "news")
    assert news["status"] == "selected"
    assert news["selected"]["source_url"] == "https://example.invalid/baba/later-news"
    assert "STALE_FIXED_NAME" not in prepared.analyst_text
    assert "BABA_NEWS_AFTER_MONDAY_CLOSE" in prepared.analyst_text
    assert "generated summary, not an official source" in prepared.analyst_text
    assert "https://example.invalid/baba/source-article" in prepared.analyst_text
    assert prepared.manifest["selection_rule"].startswith("latest eligible")
    assert "filename is not a key" in prepared.manifest["selection_rule"]
    assert prepared.price_as_of == date(2026, 11, 16)
    assert prepared.graph_trade_date == "2026-11-17"
    assert prepared.manifest["freshness_prerequisite"]["fetches_latest"] is False


@pytest.mark.unit
def test_post_close_news_is_kept_when_price_session_is_previous(tmp_path):
    corpus, runs = tmp_path / "corpus", tmp_path / "runs"
    corpus.mkdir()
    _write(
        corpus, "news.json",
        kind="news", statement_scope="item", unit="item", currency="USD",
        period_end=None, published_at="2026-11-16T23:30:00Z",
        available_at="2026-11-16T23:30:00Z", captured_at="2026-11-16T23:31:00Z",
        source_url="https://example.invalid/baba/after-close",
        body="AFTER_US_CLOSE_STILL_BEFORE_DECISION",
    )
    prepared = _run(corpus, runs, "BABA", "US", "2026-11-17T09:00:00-05:00", mode="historical")
    assert prepared.price_as_of.isoformat() == "2026-11-16"
    assert "AFTER_US_CLOSE_STILL_BEFORE_DECISION" in prepared.analyst_text
    assert _category(prepared, "news")["status"] == "selected"


@pytest.mark.unit
def test_future_release_and_missing_corpus_are_explicit(tmp_path):
    corpus, runs = tmp_path / "corpus", tmp_path / "runs"
    corpus.mkdir()
    _write(
        corpus, "future.json",
        published_at="2026-08-20T21:00:00Z",
        available_at="2026-08-20T21:00:00Z",
        captured_at="2026-08-20T22:00:00Z",
        period_end="2026-06-30",
        source_url="https://example.invalid/baba/6k",
        body="FUTURE_6K_NOT_YET_PUBLIC",
    )
    _write(
        corpus, "eligible.json",
        published_at="2026-05-20T12:00:00Z",
        body="MAY_FILING_STILL_THE_LATEST_ELIGIBLE",
    )
    historical = _run(
        corpus, runs, "BABA", "US", "2026-06-01T15:00:00-04:00", mode="historical",
    )
    financial = _category(historical, "financial_extract")
    assert financial["status"] == "selected"
    assert financial["selected"]["source_url"].endswith("/20-f")
    assert "newer_unavailable" in financial["warnings"]
    assert "FUTURE_6K_NOT_YET_PUBLIC" not in historical.analyst_text
    assert "MAY_FILING_STILL_THE_LATEST_ELIGIBLE" in historical.analyst_text
    assert any(item["reason"] == "published_after_cutoff" for item in financial["rejected"])

    empty = tmp_path / "empty"
    empty.mkdir()
    missing = _run(empty, tmp_path / "runs2", "LI", "US", "2026-11-17T09:00:00-05:00")
    assert _category(missing, "financial_extract")["status"] == "missing"
    assert "MISSING: no eligible file" in missing.analyst_text
    assert "A fixed filename was not substituted" in missing.analyst_text
    assert "financial_extract" in missing.manifest["freshness_prerequisite"]["missing_categories"]


@pytest.mark.unit
def test_capture_after_cutoff_rejects_and_old_capture_keeps_a_quarter(tmp_path):
    corpus, runs = tmp_path / "corpus", tmp_path / "runs"
    corpus.mkdir()
    _write(
        corpus, "quarter.json",
        captured_at="2026-05-21T00:00:00Z",
        body="OLD_CAPTURE_VALID_QUARTER",
    )
    _write(
        corpus, "late-capture.json",
        published_at="2026-05-20T12:00:00Z",
        available_at="2026-11-20T00:00:00Z",
        captured_at="2026-11-20T00:00:00Z",
        source_url="https://example.invalid/baba/late-capture",
        body="NOT_YET_CAPTURED",
    )
    _write(
        corpus, "old-news.json",
        kind="news", statement_scope="item", unit="item", currency="USD",
        period_end=None, published_at="2026-05-20T12:00:00Z",
        available_at="2026-05-20T12:00:00Z", captured_at="2026-05-21T00:00:00Z",
        source_url="https://example.invalid/baba/old-news",
        body="OLD_NEWS_STALE_BUT_ELIGIBLE",
    )
    prepared = _run(corpus, runs, "BABA", "US", "2026-11-17T09:00:00-05:00")
    financial = _category(prepared, "financial_extract")
    assert financial["selected"]["sha256"]
    assert "OLD_CAPTURE_VALID_QUARTER" in prepared.analyst_text
    assert "NOT_YET_CAPTURED" not in prepared.analyst_text
    assert "stale_news" not in financial["warnings"]
    assert "capture age is not a rejection" in prepared.manifest["financial_stale_policy"]
    news = _category(prepared, "news")
    assert news["status"] == "selected_stale"
    assert "stale_news" in news["warnings"]
    assert "OLD_NEWS_STALE_BUT_ELIGIBLE" in prepared.analyst_text


@pytest.mark.unit
def test_timezone_boundary_uses_the_instant_not_the_market_date(tmp_path):
    corpus, runs = tmp_path / "corpus", tmp_path / "runs"
    corpus.mkdir()
    # 2026-11-17 09:00 +08 is 2026-11-16 20:00 ET, before the 09:30 +08 cutoff.
    _write(
        corpus, "before.json",
        kind="news", statement_scope="item", unit="item", currency="USD",
        period_end=None, published_at="2026-11-17T09:00:00+08:00",
        available_at="2026-11-17T09:00:00+08:00", captured_at="2026-11-17T09:00:00+08:00",
        source_url="https://example.invalid/baba/before-boundary",
        body="INSIDE_HK_CUTOFF",
    )
    # 10:00 +08 is 21:00 ET on 2026-11-16. A US date filter of that session would keep it.
    _write(
        corpus, "after.json",
        kind="news", statement_scope="item", unit="item", currency="USD",
        period_end=None, published_at="2026-11-17T10:00:00+08:00",
        available_at="2026-11-17T10:00:00+08:00", captured_at="2026-11-17T10:00:00+08:00",
        source_url="https://example.invalid/baba/after-boundary",
        body="OUTSIDE_HK_CUTOFF",
    )
    prepared = _run(corpus, runs, "BABA", "US", "2026-11-17T09:30:00+08:00")
    assert "INSIDE_HK_CUTOFF" in prepared.analyst_text
    assert "OUTSIDE_HK_CUTOFF" not in prepared.analyst_text
    assert any(item["reason"] == "published_after_cutoff" for item in _category(prepared, "news")["rejected"])


@pytest.mark.unit
def test_listings_do_not_share_per_share_units(tmp_path):
    corpus, runs = tmp_path / "corpus", tmp_path / "runs"
    corpus.mkdir()
    _write(corpus, "baba-ads.json", body="BABA_ADS_PER_SHARE", source_url="https://example.invalid/baba/ads")
    _write(
        corpus, "hk-ordinary.json",
        symbol="9988", market="HK", unit="ordinary",
        source_url="https://example.invalid/9988/ordinary",
        body="HK_9988_ORDINARY_PER_SHARE",
    )
    _write(
        corpus, "group.json",
        statement_scope="group", unit="group", symbol="BABA",
        source_url="https://example.invalid/alibaba/group",
        published_at="2026-05-19T00:00:00Z",
        available_at="2026-05-19T00:00:00Z",
        captured_at="2026-05-19T01:00:00Z",
        body="ALIBABA_GROUP_OLDER",
    )
    _write(
        corpus, "li-ads.json",
        symbol="LI", market="US", company="li_auto", unit="ADS",
        source_url="https://example.invalid/li/ads",
        body="LI_ADS_PER_SHARE",
    )
    _write(
        corpus, "2015.json",
        symbol="2015", market="HK", company="li_auto", unit="ordinary",
        source_url="https://example.invalid/2015/ordinary",
        body="LI_HK_ORDINARY_PER_SHARE",
    )
    _write(
        corpus, "0700-hkex.json",
        symbol="0700", market="HK", company="tencent", unit="ordinary",
        kind="hkex_summary", period_end=None,
        source_url="https://example.invalid/hkex/0700",
        provenance="fixture HKEX summary",
        body="HKEX_0700_OFFICIAL_SUMMARY_FIXTURE",
    )
    baba = _run(corpus, runs, "BABA", "US", "2026-11-17T09:00:00-05:00")
    hk = _run(corpus, tmp_path / "runs-hk", "09988", "HK", "2026-11-17T17:00:00+08:00")
    li = _run(corpus, tmp_path / "runs-li", "LI", "US", "2026-11-17T09:00:00-05:00")
    ordinary = _run(corpus, tmp_path / "runs-2015", "2015.HK", "HK", "2026-11-17T17:00:00+08:00")
    tencent = _run(corpus, tmp_path / "runs-0700", "700.HK", "HK", "2026-11-17T17:00:00+08:00")

    assert "BABA_ADS_PER_SHARE" in baba.analyst_text
    assert "HK_9988_ORDINARY_PER_SHARE" not in baba.analyst_text
    assert "1 ADS = 8 ordinary" in baba.analyst_text
    assert "HK_9988_ORDINARY_PER_SHARE" in hk.analyst_text
    assert "BABA_ADS_PER_SHARE" not in hk.analyst_text
    assert "ALIBABA_GROUP_OLDER" not in hk.analyst_text
    assert any(
        item["source_url"] == "https://example.invalid/alibaba/group"
        for item in _category(hk, "financial_extract")["older_eligible"]
    )

    shared, shared_runs = tmp_path / "shared", tmp_path / "runs-shared"
    shared.mkdir()
    _write(
        shared, "group-latest.json",
        statement_scope="group", unit="group", symbol="BABA",
        source_url="https://example.invalid/alibaba/group-latest",
        published_at="2026-08-01T00:00:00Z",
        available_at="2026-08-01T00:00:00Z",
        captured_at="2026-08-01T01:00:00Z",
        body="ALIBABA_GROUP_RMB",
    )
    _write(shared, "baba-ads.json", body="BABA_ADS_OLDER", source_url="https://example.invalid/baba/ads-older")
    _write(
        shared, "hk-ordinary.json",
        symbol="9988", market="HK", unit="ordinary",
        source_url="https://example.invalid/9988/ordinary-older",
        body="HK_9988_OLDER",
    )
    baba_group = _run(shared, shared_runs, "BABA", "US", "2026-11-17T09:00:00-05:00")
    hk_group = _run(shared, tmp_path / "runs-shared-hk", "9988.HK", "HK", "2026-11-17T17:00:00+08:00")
    assert "ALIBABA_GROUP_RMB" in baba_group.analyst_text
    assert "ALIBABA_GROUP_RMB" in hk_group.analyst_text
    assert "BABA_ADS_OLDER" not in hk_group.analyst_text
    assert "HK_9988_OLDER" not in baba_group.analyst_text
    assert "cross_listing_group_statement" in _category(baba_group, "financial_extract")["warnings"]
    assert "cross_listing_group_statement" in _category(hk_group, "financial_extract")["warnings"]
    assert "LI_ADS_PER_SHARE" in li.analyst_text
    assert "LI_HK_ORDINARY_PER_SHARE" not in li.analyst_text
    assert "LI_HK_ORDINARY_PER_SHARE" in ordinary.analyst_text
    assert "LI_ADS_PER_SHARE" not in ordinary.analyst_text
    assert "1 ADS = 2 ordinary" in ordinary.analyst_text
    assert "HKEX_0700_OFFICIAL_SUMMARY_FIXTURE" in tencent.analyst_text
    assert tencent.canonical == "0700.HK"
    assert "BABA_ADS_PER_SHARE" not in tencent.analyst_text


@pytest.mark.unit
def test_official_extract_is_in_the_analyst_input_and_full_state(tmp_path, monkeypatch):
    corpus, runs = tmp_path / "corpus", tmp_path / "runs"
    corpus.mkdir()
    _write(
        corpus, "ir.json",
        kind="official_ir",
        source_url="https://example.invalid/baba/ir-6k",
        provenance="fixture company IR extract",
        body="BABA_OFFICIAL_IR_FIXTURE_6K",
    )
    _write(
        corpus, "hkex.json",
        symbol="0700", market="HK", company="tencent", unit="ordinary",
        kind="hkex_summary", period_end=None,
        source_url="https://example.invalid/hkex/0700-summary",
        provenance="fixture HKEX summary",
        body="HKEX_0700_OFFICIAL_SUMMARY_FIXTURE",
    )
    prepared = _run(corpus, runs, "BABA", "US", "2026-06-01T15:00:00-04:00", mode="historical")
    state_path = prepared.run_dir / "full_state.json"
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    joined = "\n".join(message["content"] for message in saved["messages"])
    assert "BABA_OFFICIAL_IR_FIXTURE_6K" in joined
    assert "https://example.invalid/baba/ir-6k" in joined
    manifest = json.loads((prepared.run_dir / "input_manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_sha256"] == prepared.manifest["manifest_sha256"]
    # The sentence the analyst reads is in the state, not only in a sidecar field.
    assert "BABA_OFFICIAL_IR_FIXTURE_6K" not in json.dumps(manifest)

    withheld = withhold_live_profile("2026-06-01", "BABA")
    assert withheld and "withheld" in withheld
    assert "BABA_OFFICIAL_IR_FIXTURE_6K" not in withheld

    llm = _RecordingLLM()
    state = {
        "messages": [
            HumanMessage(content=prepared.canonical),
            HumanMessage(content=prepared.analyst_text),
        ],
        "company_of_interest": prepared.canonical,
        "trade_date": prepared.graph_trade_date,
        "asset_type": "stock",
        "instrument_context": "",
    }
    create_fundamentals_analyst(llm)(state)
    create_news_analyst(llm)(state)
    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.jev_screen",
        lambda ticker: None,
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.get_news",
        type("Tool", (), {"func": staticmethod(lambda *a, **k: "vendor news withheld")})(),
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.fetch_stocktwits_messages",
        lambda *a, **k: "no stocktwits",
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.sentiment_analyst.fetch_reddit_posts",
        lambda *a, **k: "no reddit",
    )
    create_sentiment_analyst(llm)(state)
    seen = _seen_text(llm)
    assert "BABA_OFFICIAL_IR_FIXTURE_6K" in seen
    assert "https://example.invalid/baba/ir-6k" in seen
    assert "withholds present-day fundamentals" in seen

    tencent = _run(corpus, tmp_path / "runs-0700", "0700", "HK", "2026-06-01T16:30:00+08:00", mode="historical")
    hk_llm = _RecordingLLM()
    hk_state = {
        "messages": [HumanMessage(content=tencent.analyst_text)],
        "company_of_interest": tencent.canonical,
        "trade_date": tencent.graph_trade_date,
        "asset_type": "stock",
        "instrument_context": "",
    }
    create_fundamentals_analyst(hk_llm)(hk_state)
    assert "HKEX_0700_OFFICIAL_SUMMARY_FIXTURE" in _seen_text(hk_llm)


@pytest.mark.unit
def test_runs_are_retained_and_sources_stay_unchanged(tmp_path):
    corpus, runs = tmp_path / "corpus", tmp_path / "runs"
    corpus.mkdir()
    source = _write(corpus, "quarter.json", body="STABLE_SOURCE")
    before = source.read_bytes()
    first = _run(corpus, runs, "BABA", "US", "2026-11-17T09:00:00-05:00")
    first_manifest = (first.run_dir / "input_manifest.json").read_bytes()
    second = _run(corpus, runs, "BABA", "US", "2026-11-17T10:00:00-05:00")
    assert first.run_dir != second.run_dir
    assert (first.run_dir / "input_manifest.json").read_bytes() == first_manifest
    assert source.read_bytes() == before
    assert len(retained_runs(runs)) == 2
    assert first.run_dir in retained_runs(runs)


@pytest.mark.unit
def test_concurrent_runs_do_not_share_directories(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    corpus, runs = tmp_path / "corpus", tmp_path / "runs"
    corpus.mkdir()
    source = _write(corpus, "quarter.json", body="CONCURRENT_SOURCE")
    before = source.read_bytes()

    def once():
        return _run(corpus, runs, "LI", "US", "2026-11-17T09:00:00-05:00")

    with ThreadPoolExecutor(max_workers=8) as pool:
        prepared = list(pool.map(lambda _: once(), range(8)))
    directories = {item.run_dir for item in prepared}
    assert len(directories) == 8
    assert all((path / "input_manifest.json").is_file() for path in directories)
    assert source.read_bytes() == before
    assert len(retained_runs(runs)) == 8


@pytest.mark.unit
def test_runner_prepare_and_patch(tmp_path):
    corpus, runs = tmp_path / "corpus", tmp_path / "runs"
    corpus.mkdir()
    _write(
        corpus, "li.json",
        symbol="LI", market="US", company="li_auto",
        kind="official_ir",
        source_url="https://example.invalid/li/ir",
        body="LI_OFFICIAL_IR_FIXTURE",
    )
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "analysts": ["fundamentals"],
        "output_language": "English",
        "api_key": "do-not-copy",
    }), encoding="utf-8")
    run_ta = _load("run_ta")
    code = run_ta.main([
        "--symbol", "LI",
        "--market", "US",
        "--decision-at", "2026-11-17T09:00:00-05:00",
        "--mode", "current",
        "--corpus", str(corpus),
        "--runs-dir", str(runs),
        "--config", str(config),
        "--prepare-only",
    ])
    assert code == 0
    saved = json.loads(next(runs.iterdir()).joinpath("input_manifest.json").read_text(encoding="utf-8"))
    assert saved["config"]["config_allowlist"]["analysts"] == ["fundamentals"]
    assert "api_key" not in json.dumps(saved["config"])
    full = json.loads(next(runs.iterdir()).joinpath("full_state.json").read_text(encoding="utf-8"))
    assert "LI_OFFICIAL_IR_FIXTURE" in full["messages"][1]["content"]

    patcher = _load("patch_run_ta")
    fixture = (ROOT / "fixtures" / "defective_run_ta.py").read_text(encoding="utf-8")
    patched = patcher.patch_source(fixture)
    assert "BABA_2026-11-15" not in patched
    assert "prepare_run(" in patched
    with pytest.raises(patcher.PatchError):
        patcher.patch_source("print('nothing to do')\n")

    calls = {}

    def fake_prepare(**kwargs):
        calls.update(kwargs)
        return type("P", (), {"analyst_text": "PATCHED_BUNDLE"})()

    sys.modules["research_ingest"].prepare_run = fake_prepare
    try:
        namespace = {"__name__": "patched_fixture"}
        exec(patched, namespace)
        assert namespace["load_research"]("0700", "2026-11-17T17:00:00+08:00", mode="historical") == "PATCHED_BUNDLE"
    finally:
        sys.modules["research_ingest"].prepare_run = prepare_run
    assert calls["symbol"] == "0700"
    assert calls["mode"] == "historical"
    assert calls["decision_at"] == "2026-11-17T17:00:00+08:00"


@pytest.mark.unit
def test_execute_hook_puts_the_bundle_in_create_run_state(tmp_path):
    corpus, runs = tmp_path / "corpus", tmp_path / "runs"
    corpus.mkdir()
    _write(corpus, "ir.json", kind="official_ir", body="HOOK_SEES_OFFICIAL_IR")
    prepared = _run(corpus, runs, "BABA", "US", "2026-11-17T09:00:00-05:00")

    class Graph:
        def create_run_state(self, company, trade_date, asset_type="stock", portfolio=None):
            return {
                "messages": [("human", company)],
                "trade_date": trade_date,
                "company_of_interest": company,
            }

    graph = Graph()
    install_research_state(graph, prepared.analyst_text)
    state = graph.create_run_state(prepared.canonical, prepared.graph_trade_date)
    assert state["messages"][-1] == ("human", prepared.analyst_text)
    assert "HOOK_SEES_OFFICIAL_IR" in state["messages"][-1][1]
    saved = json.loads((prepared.run_dir / "full_state.json").read_text(encoding="utf-8"))
    assert "HOOK_SEES_OFFICIAL_IR" in saved["messages"][1]["content"]


@pytest.mark.unit
def test_producer_gap_is_a_prerequisite_not_a_fetch(tmp_path):
    corpus, runs = tmp_path / "corpus", tmp_path / "runs"
    corpus.mkdir()
    (corpus / "producer_status.json").write_text(json.dumps({
        "last_success_at": "2026-11-15T00:00:00Z",
    }), encoding="utf-8")
    prepared = _run(corpus, runs, "0700", "HK", "2026-11-17T17:00:00+08:00")
    prerequisite = prepared.manifest["freshness_prerequisite"]
    assert prerequisite["fetches_latest"] is False
    assert prerequisite["producer_invoked"] is False
    assert prerequisite["producer_last_success_at"] == "2026-11-15T00:00:00Z"
    assert "producer_not_run_for_decision" in prepared.manifest["warnings"]
    assert "does not call" in prerequisite["detail"]
