"""Fundamentals route on the attached runner. No model call."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from patch_fundamentals_route import HELPER, NEW, OLD, patch_bytes, unified_diff  # noqa: E402

import tradingagents.agents.tools as tools  # noqa: E402

RUNNER_CANDIDATES = (
    HERE / "fixtures" / "run_ta_live.py",
    Path("/workspace/tradingagents-runs/run_ta.py"),
    Path("/home/ubuntu/.cursor/projects/workspace/uploads/run_ta_c59f.py"),
)
DIGEST_FILE = Path("/home/ubuntu/.cursor/projects/workspace/uploads/sentiment_digest_0700.HK_2026-11-18_cb73.md")
LIVE_SHA = "beef300337da517ae2d4f166abae8d4c1dd972e1b3fef5fd28dcd6bddf0bd30c"


def _runner() -> Path:
    for path in RUNNER_CANDIDATES:
        if path.is_file():
            return path
    raise FileNotFoundError("attached live runner was not found")
SOURCE_URL = "https://www.tencent.com/wp-content/uploads/2026/11/Tencent-Announces-2026-Third-Quarter-Results.pdf"

DIGEST = """# Official material (operator-verified) — 0700.HK
decision_at: 2026-11-18T19:34:57.536861+08:00
- HKEX listing datetime for the results announcement: 18/11/2026 16:30 (title: ANNOUNCEMENT OF THE RESULTS FOR THE THREE AND NINE MONTHS ENDED 30 SEPTEMBER 2026).
- Official results dateline in the press release: Hong Kong, 18 November 2026.
- Report period: unaudited results for the quarter (and nine months) ended 30 September 2026. Do not treat the 2026 Interim Report (dateline 12 August 2026; HKEX listing 25/08/2026 16:53) as the current quarter.
1) Issuer press release PDF: https://www.tencent.com/wp-content/uploads/2026/11/Tencent-Announces-2026-Third-Quarter-Results.pdf
## 3Q2026 official figures (RMB)
- Revenues 207,336 million, vs 2Q2026 revenues 204,785 million.
- IFRS profit attributable to equity holders 63,612 million.
## Options and social
equity volume only
"""

VENDOR_Q2 = "最新已披露财报期：2026年Q2（2026-06-30） revenue 204785. 2026Q3 should be re-checked after the official quarterly report."


def _block(digest: str, cutoff: str) -> str:
    namespace = {}
    exec(HELPER, namespace)
    return namespace["_official_fundamentals_block"](digest, cutoff)


def test_patch_matches_the_attached_runner_and_keeps_the_other_hooks(tmp_path):
    runner = _runner()
    source = runner.read_bytes()
    assert hashlib.sha256(source).hexdigest() == LIVE_SHA
    assert source.count(OLD.encode()) == 1
    updated = patch_bytes(source)
    text = updated.decode()
    original = source.decode()
    assert original.split(OLD, 1)[0] == text.split(NEW, 1)[0]
    assert original.split(OLD, 1)[1] == text.split(NEW, 1)[1]
    assert "# === XUEQIU HOOK START" in text
    assert "get_fundamentals" in NEW
    assert "OFFICIAL FUNDAMENTALS" not in original
    backup = tmp_path / "run_ta.py.bak"
    staged = tmp_path / "run_ta.py.staged"
    from patch_fundamentals_route import main
    code = main([str(runner), "--output", str(staged), "--backup", str(backup)])
    assert code == 0
    assert backup.read_bytes() == source
    assert staged.read_bytes() == updated
    assert runner.read_bytes() == source
    diff = unified_diff(original, text, "a/run_ta.py", "b/run_ta.py")
    assert diff.startswith("--- a/run_ta.py\n+++ b/run_ta.py\n@@ ")


def test_q3_is_visible_after_publication_and_hidden_before_it():
    evening = _block(DIGEST, "2026-11-18T19:34:57+08:00")
    assert SOURCE_URL in evening
    assert "207,336" in evening
    assert "63,612" in evening
    assert "30 september 2026" in evening.casefold()
    assert "18 November 2026" in evening
    assert "availability: 2026-11-18T16:30:00+08:00" in evening
    assert "as_of: 2026-11-18T19:34:57.536861+08:00" in evening
    assert "vendor_conflict:" in evening
    early = _block(DIGEST, "2026-11-18T16:00:00+08:00")
    assert "MISSING:" in early
    assert "207,336" not in early
    assert SOURCE_URL not in early
    assert "63,612" not in early
    undeclared = _block("Revenues 1\n", "")
    assert "MISSING:" in undeclared
    assert "not declared" in undeclared


def test_attached_operator_digest_uses_its_own_decision_time():
    if not DIGEST_FILE.is_file():
        return
    text = DIGEST_FILE.read_text(encoding="utf-8")
    shown = _block(text, "")
    assert SOURCE_URL in shown
    assert "207,336" in shown
    assert "as_of: 2026-11-18T19:34:57.536861+08:00" in shown
    hidden = _block(text, "2026-11-18T16:00:00+08:00")
    assert SOURCE_URL not in hidden
    assert "207,336" not in hidden


def _install(sent: str):
    previous = tools.route_to_vendor

    def vendor(method, *args, **kwargs):
        if method in {"get_fundamentals", "get_balance_sheet", "get_cashflow", "get_income_statement"}:
            return VENDOR_Q2
        if method == "get_news":
            return "VENDOR_NEWS"
        if method == "get_stock_data":
            return "VENDOR_PRICES"
        return "VENDOR_OTHER"

    tools.route_to_vendor = vendor
    namespace = {"T": tools, "sent": sent, "sent_block": "\nSENTINEL_NEWS\n", "opt_block": "\nSENTINEL_OPTIONS\n"}
    exec(NEW, namespace)
    return previous


def test_get_fundamentals_keeps_vendor_q2_and_adds_official_q3():
    previous = _install(DIGEST)
    try:
        fundamentals = tools.get_fundamentals.func("0700.HK", "2026-11-18", "2026-11-18")
        news = tools.route_to_vendor("get_news", "0700.HK", "2026-11-01", "2026-11-18")
        prices = tools.route_to_vendor("get_stock_data", "0700.HK", "2026-11-01", "2026-11-18")
        statement = tools.get_income_statement.func("0700.HK", "quarterly", "2026-11-18", "2026-11-18")
    finally:
        tools.route_to_vendor = previous
    assert "204785" in fundamentals
    assert "207,336" in fundamentals
    assert SOURCE_URL in fundamentals
    assert "vendor_conflict:" in fundamentals
    assert "OFFICIAL FUNDAMENTALS" in fundamentals
    assert "OFFICIAL FUNDAMENTALS" in statement
    assert "SENTINEL_NEWS" in news
    assert "OFFICIAL FUNDAMENTALS" not in news
    assert "SENTINEL_OPTIONS" in prices
    assert "OFFICIAL FUNDAMENTALS" not in prices


def test_missing_digest_does_not_claim_current_for_another_symbol():
    previous = _install(
        "MISSING sentiment_digest_NVDA_2026-11-18.md in /workspace/tradingagents-runs. "
        "No older file was substituted."
    )
    try:
        out = tools.get_fundamentals.func("NVDA", "2026-11-18", "2026-11-18")
    finally:
        tools.route_to_vendor = previous
    assert "MISSING:" in out
    assert "207,336" not in out
    assert "204785" in out
