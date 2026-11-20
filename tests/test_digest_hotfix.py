"""Hotfix against the verbatim runner: dated digest file, no glob, no whitelist."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "integrations" / "external_runner"
VERBATIM = (ROOT / "fixtures" / "run_ta_verbatim.py").read_text(encoding="utf-8")
ORIGINAL = """sent_path=RUN/f'sentiment_digest_{TICKER}_2026-11-15.md'
if not sent_path.exists():
    candidates=sorted(RUN.glob(f'sentiment_digest_{TICKER}_*.md'))
    sent_path=candidates[-1] if candidates else sent_path
sent=sent_path.read_text() if sent_path.exists() else ''
"""
PATCHED = """sent_path=RUN/f'sentiment_digest_{TICKER}_{DATE}.md'
sent=sent_path.read_text() if sent_path.exists() else (
    f'MISSING sentiment_digest_{TICKER}_{DATE}.md in {RUN}. '
    'No older file was substituted. This run did not fetch a replacement.'
)
"""
SYMBOLS = ("0700", "BABA", "LI", "NVDA", "0981", "601169", "601398")


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_ta_hotfix", ROOT / "run_ta.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(run: Path, ticker: str, date: str, body: str) -> Path:
    path = run / f"sentiment_digest_{ticker}_{date}.md"
    path.write_text(body, encoding="utf-8")
    return path


def _original_sent(run: Path, ticker: str) -> str:
    namespace = {"RUN": run, "TICKER": ticker}
    exec(ORIGINAL, namespace)
    return namespace["sent"]


def _tools():
    captured = {}

    class Tools:
        def route_to_vendor(self, method, *args, **kwargs):
            captured["method"] = method
            captured["args"] = args
            return f"VENDOR:{method}"

    return Tools(), captured


@pytest.mark.unit
def test_verbatim_source_is_the_pinned_snippet():
    assert "import sys, os, json, re, pathlib" in VERBATIM
    assert "TICKER = sys.argv[1]; DATE = sys.argv[2] if len(sys.argv)>2 else '2026-11-13'" in VERBATIM
    assert "import tradingagents.agents.tools as T" in VERBATIM
    assert "from tradingagents.graph.trading_graph import TradingAgentsGraph" in VERBATIM
    assert ORIGINAL in VERBATIM
    assert "T.route_to_vendor=patched" in VERBATIM


@pytest.mark.unit
def test_original_snippet_uses_pinned_file_or_glob_and_exists_check(tmp_path):
    pinned = _write(tmp_path, "BABA", "2026-11-15", "PINNED_15 https://example.invalid/pinned")
    _write(tmp_path, "BABA", "2026-11-17", "DATED_17 https://example.invalid/dated")
    assert _original_sent(tmp_path, "BABA") == pinned.read_text(encoding="utf-8")
    pinned.unlink()
    later = _write(tmp_path, "NVDA", "2099-01-01", "GLOB_LAST")
    assert _original_sent(tmp_path, "NVDA") == later.read_text(encoding="utf-8")
    assert "sent_path.exists()" in ORIGINAL


@pytest.mark.unit
@pytest.mark.parametrize("ticker", SYMBOLS)
def test_dated_file_is_verbatim_for_every_symbol(tmp_path, ticker):
    body = (
        f"Operator summary {ticker} decision 2026-11-17.\n"
        f"Official URL: https://example.invalid/{ticker}/filing\n"
        "Disclosed 2026-08-20.\n"
    )
    path = _write(tmp_path, ticker, "2026-11-17", body)
    old = _write(tmp_path, ticker, "2026-11-15", "OLD_FILE_MUST_NOT_BE_READ")
    runner = _load_runner()
    tools, seen = _tools()
    try:
        prepared = runner.prepare(["run_ta.py", ticker, "2026-11-17"], tools=tools, run=tmp_path)
        assert prepared["sent_path"].exists()
        assert prepared["sent"] == body
        assert old.read_text(encoding="utf-8") == "OLD_FILE_MUST_NOT_BE_READ"
        news = tools.route_to_vendor("get_news", ticker, "2026-11-10", "2026-11-17")
        assert news == f"VENDOR:get_news{body}"
        assert f"https://example.invalid/{ticker}/filing" in news
        assert "Disclosed 2026-08-20." in news
        assert seen["method"] == "get_news"
        manifest = json.loads((tmp_path / f"{ticker}_2026-11-17" / "digest_manifest.json").read_text())
        assert manifest["fetched"] is False
        assert manifest["kind"] == "operator_summary"
        assert manifest["date"] == "2026-11-17"
        assert manifest["path"] == str(path)
        assert manifest["sha256"] == hashlib.sha256(body.encode()).hexdigest()
        assert manifest["mtime"] == path.stat().st_mtime
    finally:
        import tradingagents.agents.tools as real_tools
        if tools is real_tools:
            pass


@pytest.mark.unit
def test_missing_dated_file_stays_readable_and_skips_older_digest(tmp_path):
    _write(tmp_path, "601398", "2026-11-15", "SILENT_OLD_FALLBACK")
    runner = _load_runner()
    tools, _seen = _tools()
    prepared = runner.prepare(["run_ta.py", "601398", "2026-11-17"], tools=tools, run=tmp_path)
    assert prepared["sent_path"].exists() is False
    assert prepared["sent"].startswith("MISSING sentiment_digest_601398_2026-11-17.md")
    assert "No older file was substituted" in prepared["sent"]
    assert "SILENT_OLD_FALLBACK" not in prepared["sent"]
    news = tools.route_to_vendor("get_news", "601398", "2026-11-01", "2026-11-17")
    assert news.startswith("VENDOR:get_newsMISSING")
    assert "did not fetch" in news
    manifest = json.loads((tmp_path / "601398_2026-11-17" / "digest_manifest.json").read_text())
    assert manifest["exists"] is False
    assert manifest["sha256"] is None
    assert manifest["fetched"] is False
    assert (tmp_path / "sentiment_digest_601398_2026-11-15.md").read_text() == "SILENT_OLD_FALLBACK"


@pytest.mark.unit
def test_stock_hook_still_appends_options_block(tmp_path):
    runner = _load_runner()
    runner.opt_block = "OPTIONS_BLOCK"
    tools, _seen = _tools()
    try:
        runner.prepare(["run_ta.py", "0981", "2026-11-13"], tools=tools, run=tmp_path)
        assert tools.route_to_vendor("get_stock_data", "0981", "2026-11-01", "2026-11-13").endswith("OPTIONS_BLOCK")
    finally:
        runner.opt_block = ""


@pytest.mark.unit
def test_hotfix_diff_only_replaces_the_pinned_block():
    runner_src = (ROOT / "run_ta.py").read_text(encoding="utf-8")
    assert "sentiment_digest_{TICKER}_2026-11-15.md" not in runner_src
    assert ".glob(" not in runner_src
    assert "sent_path.exists()" in runner_src
    assert "TradingAgentsGraph" in runner_src
    assert "route_to_vendor" in runner_src
    assert ORIGINAL not in runner_src
    assert "sentiment_digest_{ticker}_{date}.md" in runner_src
