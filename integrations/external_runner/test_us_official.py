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
META = """# Official material (operator-verified) — META
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
