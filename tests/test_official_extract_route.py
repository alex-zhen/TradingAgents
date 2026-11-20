"""The real route_to_vendor returns the official extract the preflight selected.

These tests do not treat a handwritten full_state.json as evidence, and they
do not start TradingAgentsGraph or a model provider.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tradingagents.agents.tools import get_fundamentals, get_news
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.router import route_to_vendor

ROOT = Path(__file__).resolve().parents[1] / "integrations" / "external_runner"
sys.path.insert(0, str(ROOT))

from research_ingest import (  # noqa: E402
    official_extract_vendor,
    preflight_acquire,
    select_sentiment_digest,
    vendor_config,
)


def _write(directory: Path, name: str, **fields) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(fields), encoding="utf-8")


def _official(**overrides) -> dict:
    base = {
        "symbol": "BABA",
        "market": "US",
        "kind": "official_ir",
        "statement_scope": "per_share",
        "unit": "ADS",
        "currency": "CNY",
        "period_end": "2026-06-30",
        "published_at": "2026-08-20T21:00:00Z",
        "available_at": "2026-08-20T21:00:00Z",
        "captured_at": "2026-08-20T22:00:00Z",
        "source_url": "https://example.invalid/baba/old-6k",
        "provenance": "fixture extract; official source is source_url",
        "generated": False,
        "company": "alibaba",
        "body": "OLD_OFFICIAL_EXTRACT",
    }
    base.update(overrides)
    return base


@pytest.mark.unit
def test_sentiment_digest_ignores_frozen_name_and_future_glob(tmp_path):
    run = tmp_path / "RUN"
    run.mkdir()
    frozen = run / "sentiment_digest_BABA_2026-11-15.md"
    frozen.write_text("FROZEN_2026_11_15_BODY", encoding="utf-8")
    before = frozen.read_bytes()
    _write(
        run, "sentiment_digest_BABA_2026-11-16.json",
        **{
            "symbol": "BABA", "market": "US", "kind": "sentiment",
            "statement_scope": "item", "unit": "item", "currency": "USD",
            "published_at": "2026-11-16T23:30:00Z",
            "available_at": "2026-11-16T23:31:00Z",
            "captured_at": "2026-11-16T23:32:00Z",
            "source_url": "https://example.invalid/baba/after-close",
            "provenance": "generated summary",
            "generated": True,
            "original_urls": ["https://example.invalid/baba/article"],
            "body": "AFTER_MONDAY_CLOSE",
        },
    )
    _write(
        run, "sentiment_digest_BABA_2099-01-01.json",
        **{
            "symbol": "BABA", "market": "US", "kind": "sentiment",
            "statement_scope": "item", "unit": "item", "currency": "USD",
            "published_at": "2099-01-01T00:00:00Z",
            "available_at": "2099-01-01T00:00:00Z",
            "captured_at": "2099-01-01T00:00:00Z",
            "source_url": "https://example.invalid/baba/future",
            "provenance": "future file",
            "body": "FUTURE_GLOB_WINNER",
        },
    )
    choice = select_sentiment_digest(
        run, "BABA", "2026-11-17", now=datetime(2026, 11, 17, 14, 0, tzinfo=UTC),
    )
    assert choice.path is not None
    assert choice.path.name == "sentiment_digest_BABA_2026-11-16.json"
    assert choice.price_as_of.isoformat() == "2026-11-16"
    assert choice.decision_at == datetime(2026, 11, 17, 14, 0, tzinfo=UTC)
    assert frozen.read_bytes() == before


@pytest.mark.unit
def test_route_to_vendor_returns_extract_after_official_producer(tmp_path, monkeypatch):
    corpus, runs = tmp_path / "corpus", tmp_path / "runs"
    corpus.mkdir()
    _write(corpus, "old.json", **_official())
    calls = []

    def official_extract(symbol, decision_at, corpus):
        calls.append(symbol)
        _write(
            corpus, "fresh.json",
            **_official(
                published_at="2026-11-16T23:30:00Z",
                available_at="2026-11-16T23:31:00Z",
                captured_at="2026-11-16T23:32:00Z",
                source_url="https://example.invalid/baba/fresh-6k",
                body="FRESH_OFFICIAL_EXTRACT",
            ),
        )

    def options_digest(symbol, decision_at, corpus):
        calls.append("options_digest")

    def xueqiu_digest(symbol, decision_at, corpus):
        calls.append("xueqiu_digest")

    monkeypatch.setattr(
        "tradingagents.dataflows.vendors.yahoo.fundamentals.get_fundamentals",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("yfinance fundamentals called")),
    )
    prepared = preflight_acquire(
        symbol="BABA",
        market="US",
        decision_at="2026-11-17T14:00:00Z",
        mode="current",
        corpus=corpus,
        runs_dir=runs,
        producers={
            "official_extract": official_extract,
            "options_digest": options_digest,
            "xueqiu_digest": xueqiu_digest,
        },
    )
    assert prepared.manifest["acquisition"]["automatic_latest"] is True
    assert prepared.price_as_of.isoformat() == "2026-11-16"
    assert prepared.graph_trade_date == "2026-11-17"
    assert calls == ["options_digest", "xueqiu_digest", "BABA"]

    with official_extract_vendor(prepared), run_config(vendor_config()):
        routed = route_to_vendor("get_fundamentals", "BABA", prepared.graph_trade_date)
        via_tool = get_fundamentals.func("BABA", prepared.graph_trade_date, prepared.graph_trade_date)
        news = get_news.func("BABA", "2026-11-10", "2026-11-17", prepared.graph_trade_date)
    assert "FRESH_OFFICIAL_EXTRACT" in routed
    assert "https://example.invalid/baba/fresh-6k" in routed
    assert "OLD_OFFICIAL_EXTRACT" not in routed
    assert "price_last_completed_session: 2026-11-16" in routed
    assert via_tool == routed
    assert "OFFICIAL_EXTRACT_MISSING" in news or "get_news" in news


@pytest.mark.unit
def test_route_to_vendor_refuses_preexisting_file_when_producer_did_not_run(tmp_path):
    corpus, runs = tmp_path / "corpus", tmp_path / "runs"
    corpus.mkdir()
    _write(corpus, "old.json", **_official())
    prepared = preflight_acquire(
        symbol="BABA",
        market="US",
        decision_at="2026-11-17T14:00:00Z",
        mode="current",
        corpus=corpus,
        runs_dir=runs,
        producers={},
    )
    assert prepared.manifest["acquisition"]["automatic_latest"] is False
    with official_extract_vendor(prepared), run_config(vendor_config()):
        routed = route_to_vendor("get_fundamentals", "BABA", "2026-11-17")
    assert routed.startswith("OFFICIAL_EXTRACT_NOT_REFRESHED")
    assert "OLD_OFFICIAL_EXTRACT" not in routed


@pytest.mark.unit
def test_historical_mode_does_not_call_producers_and_serves_cutoff_file(tmp_path):
    corpus, runs = tmp_path / "corpus", tmp_path / "runs"
    corpus.mkdir()
    _write(corpus, "old.json", **_official())
    _write(
        corpus, "later.json",
        **_official(
            published_at="2026-11-20T00:00:00Z",
            available_at="2026-11-20T00:00:00Z",
            captured_at="2026-11-20T00:00:00Z",
            source_url="https://example.invalid/baba/after-cutoff",
            body="AFTER_HISTORICAL_CUTOFF",
        ),
    )

    def forbidden(**kwargs):
        raise AssertionError("historical preflight called a producer")

    prepared = preflight_acquire(
        symbol="BABA",
        market="US",
        decision_at="2026-09-01T20:00:00Z",
        mode="historical",
        corpus=corpus,
        runs_dir=runs,
        producers={"official_extract": forbidden, "options_digest": forbidden, "xueqiu_digest": forbidden},
    )
    assert prepared.manifest["acquisition"]["automatic_latest"] is False
    with official_extract_vendor(prepared), run_config(vendor_config()):
        routed = route_to_vendor("get_fundamentals", "BABA", prepared.graph_trade_date)
    assert "OLD_OFFICIAL_EXTRACT" in routed
    assert "AFTER_HISTORICAL_CUTOFF" not in routed
    assert "https://example.invalid/baba/old-6k" in routed
