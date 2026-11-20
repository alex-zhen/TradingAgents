"""US and issuer filings reach get_fundamentals. No model call."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from patch_us_official import main, patch_bytes  # noqa: E402

LIVE_SHA = "6d2691173afd287dd9b69fcd0f77b4518089c81cd56e8eb595f21f51f6d7842a"
RUNNER = HERE / "fixtures" / "run_ta_6d269117.py"
NVDA = HERE / "fixtures" / "nvda_operator_2026-11-18.md"
AAPL = HERE / "fixtures" / "aapl_operator_2026-11-17.md"
XIAOMI = HERE / "fixtures" / "xiaomi_1810_operator_2026-11-18.md"
META = """# Official material (operator-verified) — META
document_coverage: three months and nine months ended September 30, 2026
ticker: META
decision_at: 2026-11-18T22:41:00.822725+08:00
latest_discovery_verified: false
SEC was not queried. No HKEX listing datetime exists for this US listing and none is invented.
- form: 10-Q, quarter and nine months ended September 30, 2026, filed/accepted 2026-10-22
## Financial report
quarter ended September 30, 2026
Revenue 64,601
Nine months ended September 30, 2026 revenue 181,712. Do not treat the nine-month total as the quarter.
source_url: https://www.sec.gov/Archives/edgar/data/1326801/meta-20260930.htm
"""


def _runner_namespace(ticker: str, sent: str):
    staged = patch_bytes(RUNNER.read_bytes()).decode()
    start = staged.find("def _norm_listing")
    end = staged.find("T.route_to_vendor = patched\n") + len("T.route_to_vendor = patched\n")
    funcs = staged[start:end]

    def vendor(method, *args, **kwargs):
        return "VENDOR_Q2_FY2027 ended 2026-07-26 revenue 96221"

    namespace = {
        "T": type("T", (), {"route_to_vendor": staticmethod(vendor)})(),
        "TICKER": ticker,
        "sent": sent,
        "sent_block": "\nSENTINEL_NEWS\n",
        "opt_block": "\nSENTINEL_OPTIONS\n",
    }
    exec(funcs, namespace)
    return namespace


def test_patch_keeps_hooks_and_backup_order(tmp_path):
    source = RUNNER.read_bytes()
    assert hashlib.sha256(source).hexdigest() == LIVE_SHA
    updated = patch_bytes(source)
    original = source.decode()
    staged = updated.decode()
    assert original.split("# === XUEQIU HOOK START", 1)[1].split("# === XUEQIU HOOK END", 1)[0] == (
        staged.split("# === XUEQIU HOOK START", 1)[1].split("# === XUEQIU HOOK END", 1)[0]
    )
    assert "def _load_options_digest" in staged
    assert staged.index("_archive_same_date(RUN, TICKER, DATE)") < staged.index("ta.propagate(TICKER, DATE)")
    assert "output_status.txt" in staged
    backup = tmp_path / "run_ta.py.backup"
    out = tmp_path / "run_ta.py.staged"
    assert main([str(RUNNER), "--output", str(out), "--backup", str(backup)]) == 0
    assert backup.read_bytes() == source
    assert out.read_bytes() == updated
    assert RUNNER.read_bytes() == source


def test_nvda_meta_aapl_bodies_reach_fundamentals_without_an_hkex_clock():
    nvda = NVDA.read_text(encoding="utf-8")
    ns = _runner_namespace("NVDA", nvda)
    shown = ns["patched"]("get_fundamentals", "NVDA")
    assert "115,844" in shown
    assert "65,287" in shown
    assert "VENDOR_Q2" in shown
    assert "availability_clock: not stated" in shown
    assert "availability_precision: date" in shown
    assert "16:30" not in shown
    assert "metric_period: unknown" in shown
    assert "Nine months ended October 25, 2026" in shown
    assert "latest_discovery_verified: not established by this hook" in shown
    assert "latest_discovery_verified: true" not in shown
    hidden = ns["_official_fundamentals_block"](nvda, "2026-11-17T12:00:00+08:00")
    assert "115,844" not in hidden
    assert "MISSING:" in hidden
    same_day = ns["_official_fundamentals_block"](nvda, "2026-11-17T23:00:00-05:00")
    assert "115,844" not in same_day
    aapl = AAPL.read_text(encoding="utf-8")
    aapl_ns = _runner_namespace("AAPL", aapl)
    aapl_out = aapl_ns["patched"]("get_fundamentals", ticker="AAPL")
    assert "478,834" in aapl_out
    assert "availability_clock: not stated" in aapl_out
    assert "16:30" not in aapl_out
    assert "metric_period: quarter" not in aapl_out
    assert "digest_latest_discovery_verified: false" in aapl_out
    assert "latest_discovery_verified: true" not in aapl_out
    assert "478,834" not in aapl_ns["_official_fundamentals_block"](aapl, "2026-11-03T22:00:00+08:00")
    meta_ns = _runner_namespace("META", META)
    meta_out = meta_ns["patched"]("get_income_statement", symbol="META", freq="quarterly")
    assert "64,601" in meta_out
    assert "181,712" in meta_out
    assert "metric_period: unknown" in meta_out
    assert "availability_clock: not stated" in meta_out
    assert "16:30" not in meta_out
    leaked = meta_ns["patched"]("get_fundamentals", "NVDA")
    assert "64,601" not in leaked
    assert "not applicable" in leaked
    assert leaked.startswith("VENDOR_Q2")


def test_xiaomi_dateline_is_not_the_period_end_and_not_the_url():
    digest = XIAOMI.read_text(encoding="utf-8")
    ns = _runner_namespace("1810.HK", digest)
    block = ns["_official_fundamentals_block"]
    before = block(digest, "2026-08-01T12:00:00+08:00")
    same = block(digest, "2026-08-18T12:00:00+08:00")
    nxt = block(digest, "2026-08-19T12:00:00+08:00")
    for withheld in (before, same):
        assert "108,921.6" not in withheld
        assert "208,063.2" not in withheld
        assert "availability: 2026-06-30" not in withheld
        assert "MISSING:" in withheld
    assert "108,921.6" in nxt
    assert "208,063.2" in nxt
    assert "availability: 2026-08-18" in nxt
    assert "publication_dateline: August 18, 2026" in nxt
    assert "availability: 2026-06-30" not in nxt
    assert "availability_clock: not stated" in nxt
    assert "metric_period: unknown" in nxt
    assert "2026081801014" not in nxt.split("availability:", 1)[0]
    leaked = ns["patched"]("get_fundamentals", "0700.HK")
    assert "108,921.6" not in leaked
    assert "not applicable" in leaked
    ambiguous = """ticker: 1810.HK
decision_at: 2026-11-18T12:00:00+08:00
dateline August 18, 2026
dateline September 2, 2026
## Financial report
Revenue 108,921.6
"""
    mixed = block(ambiguous, "2026-11-18T12:00:00+08:00")
    assert "108,921.6" not in mixed
    assert "disagree" in mixed
    catl = """ticker: 300750.SZ
decision_at: 2026-11-19T10:00:00+08:00
董事会落款 2026年10月15日
http://static.cninfo.com.cn/finalpage/2026-10-15/123.pdf
## Financial report
Revenue 100,000
"""
    absent = block(catl, "2026-11-19T10:00:00+08:00")
    assert "100,000" not in absent
    assert "MISSING:" in absent
    assert "2026-10-15" not in absent
    announced = """ticker: 300750.SZ
decision_at: 2026-11-19T10:00:00+08:00
公告日期：2026年10月20日
## Financial report
Revenue 50,000
"""
    early = block(announced, "2026-10-20T12:00:00+08:00")
    later = block(announced, "2026-10-21T12:00:00+08:00")
    assert "50,000" not in early
    assert "50,000" in later
    assert "availability: 2026-10-20" in later
    assert "publication_dateline: 2026年10月20日" in later
    assert "availability_clock: not stated" in later
    ended_only = """ticker: 1810.HK
decision_at: 2026-11-18T12:00:00+08:00
dateline for the period ended June 30, 2026
## Financial report
Revenue 108,921.6
"""
    no_pub = block(ended_only, "2026-11-18T12:00:00+08:00")
    assert "108,921.6" not in no_pub
    assert "MISSING:" in no_pub


def test_tencent_hkex_clock_still_blocks_an_earlier_cutoff():
    tencent = (HERE / "fixtures" / "tencent_operator_2026-11-18.md").read_text(encoding="utf-8")
    ns = _runner_namespace("0700.HK", tencent)
    early = ns["_official_fundamentals_block"](tencent, "2026-11-18T16:00:00+08:00")
    assert "207,336" not in early
    late = ns["_official_fundamentals_block"](tencent, "2026-11-18T19:34:57+08:00")
    assert "207,336" in late
    assert "availability_precision: timestamp" in late
    assert "metric_period: unknown" in late


def test_placeholder_decision_is_incomplete_and_not_replaced(tmp_path):
    staged = patch_bytes(RUNNER.read_bytes()).decode()
    stub = '''import sys, os, json, re, pathlib
class _Tools:
    @staticmethod
    def route_to_vendor(method, *a, **k):
        return "VENDOR"
T = _Tools()
DEFAULT_CONFIG = {}
class TradingAgentsGraph:
    def __init__(self, *a, **k):
        pass
    def propagate(self, ticker, date):
        return {
            "fundamentals_report": "FUND " + ticker,
            "investment_plan": "Reduce the overweight and keep a core position for " + ticker + ".",
            "final_trade_decision": "...",
        }, "..."
'''
    old_import = """import sys, os, json, re, pathlib
sys.path.insert(0, "/workspace/tradingagents")
import tradingagents.agents.tools as T
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
"""
    script = staged.replace(old_import, stub, 1).replace(
        'RUN = pathlib.Path("/workspace/tradingagents-runs")',
        f"RUN = pathlib.Path({str(tmp_path)!r})",
        1,
    )
    path = tmp_path / "run_ta.py"
    path.write_text(script, encoding="utf-8")
    done = subprocess.run([sys.executable, str(path), "AAPL", "2026-11-17"], cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == 3
    assert "INCOMPLETE" in done.stdout
    assert "DECISION" not in done.stdout
    report = tmp_path / "AAPL_2026-11-17"
    assert (report / "decision.txt").read_text(encoding="utf-8") == "..."
    assert (report / "final_trade_decision.md").read_text(encoding="utf-8") == "..."
    assert "core position" in (report / "investment_plan.md").read_text(encoding="utf-8")
    status = (report / "output_status.txt").read_text(encoding="utf-8")
    assert "placeholder" in status
    assert "No result was invented" in status
    assert "Underweight" not in (report / "decision.txt").read_text(encoding="utf-8")
