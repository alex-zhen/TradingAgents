"""Direct-run archive and symbol match. No model call."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from patch_direct_run import main, patch_bytes  # noqa: E402

LIVE_SHA = "0b6de641a9a31697f832529a10db0d504ff340f6af0d30752b277b62f37ef0c1"
CANDIDATES = (
    HERE / "fixtures" / "run_ta_current.py",
    Path("/home/ubuntu/.cursor/projects/workspace/uploads/run_ta_4307.py"),
)
DIGEST_FILE = HERE / "fixtures" / "tencent_operator_2026-11-18.md"
SOURCE_URL = "https://www.tencent.com/wp-content/uploads/2026/11/Tencent-Announces-2026-Third-Quarter-Results.pdf"
CODES = (
    "0700", "BABA", "LI", "NVDA", "0981", "601169", "601398",
    "9988", "2015", "3690", "1810", "9618", "1211", "9888",
    "9992", "600519", "601318", "300750", "002594", "AAPL",
    "TSM", "AMD", "2318", "0883", "0388", "0941", "9868", "1024", "O",
)


def _runner() -> Path:
    for path in CANDIDATES:
        if path.is_file():
            return path
    raise FileNotFoundError("attached live runner was not found")


def _funcs():
    tail = (HERE / "direct_run_tail.txt").read_text(encoding="utf-8")
    return tail.split("# RUN_BODY\n", 1)[0]


def _load_funcs(ticker: str, sent: str, vendor):
    namespace = {
        "T": type("T", (), {"route_to_vendor": staticmethod(vendor)})(),
        "TICKER": ticker,
        "sent": sent,
        "sent_block": "\nSENTINEL_NEWS\n",
        "opt_block": "\nSENTINEL_OPTIONS\n",
    }
    exec(_funcs(), namespace)
    return namespace


def test_patch_matches_attached_runner_and_keeps_hooks(tmp_path):
    runner = _runner()
    source = runner.read_bytes()
    assert hashlib.sha256(source).hexdigest() == LIVE_SHA
    updated = patch_bytes(source)
    original = source.decode()
    staged = updated.decode()
    assert "=== XUEQIU HOOK START" in staged
    assert original.split("# === XUEQIU HOOK START", 1)[1].split("# === XUEQIU HOOK END", 1)[0] == (
        staged.split("# === XUEQIU HOOK START", 1)[1].split("# === XUEQIU HOOK END", 1)[0]
    )
    assert "_archive_same_date(RUN, TICKER, DATE)" in staged
    assert staged.index("_archive_same_date(RUN, TICKER, DATE)") < staged.index("ta.propagate(TICKER, DATE)")
    backup = tmp_path / "run_ta.py.backup"
    out = tmp_path / "run_ta.py.staged"
    assert main([str(runner), "--output", str(out), "--backup", str(backup)]) == 0
    assert backup.read_bytes() == source
    assert out.read_bytes() == updated
    assert runner.read_bytes() == source


def test_periods_stay_raw_and_do_not_collapse_to_nine_months():
    namespace = _load_funcs("0700.HK", "", lambda *a, **k: "VENDOR")
    block = namespace["_official_fundamentals_block"]
    digest = DIGEST_FILE.read_text(encoding="utf-8")
    shown = block(digest, "")
    assert "metric_period: unknown" in shown
    assert "NINE MONTHS ENDED 30 SEPTEMBER 2026" in shown
    assert "quarter (and nine months) ended 30 September 2026" in shown
    assert "metric_period: NINE MONTHS" not in shown
    assert "metric_period: THREE AND NINE" not in shown
    assert "207,336" in shown
    assert SOURCE_URL in shown
    baba = """ticker: BABA
decision_at: 2026-11-17T12:00:00+08:00
hkex_listing_datetime: 20/08/2026 12:00
publication_dateline: August 20, 2026
## Financial report
quarter ended June 30, 2026
Revenue was RMB100 million (US$15 million).
"""
    baba_block = block(baba, "2026-11-17T12:00:00+08:00")
    assert "metric_period: quarter ended June 30, 2026" in baba_block
    assert "metric_period: unknown" not in baba_block
    assert "207,336" not in baba_block
    assert "NINE MONTHS" not in baba_block
    li = """ticker: LI
decision_at: 2026-11-17T12:00:00+08:00
hkex_listing_datetime: 15/08/2026 12:00
## Financial report
quarter ended June 30, 2026
Revenue was RMB100 million.
"""
    li_block = block(li, "2026-11-17T12:00:00+08:00")
    assert "metric_period: quarter ended June 30, 2026" in li_block
    assert "207,336" not in li_block
    no_hk = """ticker: BABA
decision_at: 2026-11-17T12:00:00+08:00
publication_dateline: August 20, 2026
quarter ended June 30, 2026
Revenue was RMB100 million.
"""
    withheld = block(no_hk, "2026-11-17T12:00:00+08:00")
    assert "MISSING:" in withheld
    assert "16:30" not in withheld
    assert "RMB100" not in withheld


def test_tool_symbol_must_match_and_calling_convention_does_not_crash():
    digest = DIGEST_FILE.read_text(encoding="utf-8")

    def vendor(method, *args, **kwargs):
        return "VENDOR_Q2"

    namespace = _load_funcs("0700.HK", digest, vendor)
    patched = namespace["patched"]
    same = namespace["_same_listing"]
    positional = patched("get_fundamentals", "HK.00700", "2026-11-18")
    keyword = patched("get_fundamentals", ticker="0700.HK", curr_date="2026-11-18")
    named = patched("get_income_statement", symbol="00700.HK", freq="quarterly")
    assert "207,336" in positional and "VENDOR_Q2" in positional
    assert "207,336" in keyword and "207,336" in named
    wrong = patched("get_fundamentals", "BABA", "2026-11-18")
    assert wrong.startswith("VENDOR_Q2")
    assert "not applicable" in wrong
    assert "207,336" not in wrong
    assert SOURCE_URL not in wrong
    li = _load_funcs("LI", "MISSING sentiment_digest_LI_2026-11-17.md in RUN. No older file was substituted.", vendor)
    crossed = li["patched"]("get_fundamentals", "NIO")
    assert crossed.startswith("VENDOR_Q2")
    assert "not applicable" in crossed
    assert same("LI", "NIO") is False
    assert same("0700.HK", "HK.00700") is True
    blank = patched("get_fundamentals")
    assert "VENDOR_Q2" in blank and "not provided" in blank
    for code in CODES:
        box = _load_funcs(code, "MISSING sentiment_digest. No older file was substituted.", vendor)
        out = box["patched"]("get_fundamentals", ticker=code)
        assert "VENDOR_Q2" in out
        assert "OFFICIAL FUNDAMENTALS" in out


def test_direct_runs_archive_before_write_for_two_tickers_and_a_rerun(tmp_path):
    runner = _runner()
    staged = patch_bytes(runner.read_bytes()).decode()
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
        log = RUN / "logs" / ticker / "TradingAgentsStrategy_logs"
        log.mkdir(parents=True, exist_ok=True)
        (log / f"full_states_log_{date}.json").write_text("NEW " + ticker + " " + os.environ.get("STUB_GEN", "1"))
        return {"fundamentals_report": "FUND " + ticker, "market_report": "M " + ticker}, "HOLD"
'''
    old_import = """import sys, os, json, re, pathlib
sys.path.insert(0, "/workspace/tradingagents")
import tradingagents.agents.tools as T
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
"""
    script = staged.replace(old_import, stub, 1)
    script = script.replace(
        'RUN = pathlib.Path("/workspace/tradingagents-runs")',
        f"RUN = pathlib.Path({str(tmp_path)!r})",
        1,
    )
    path = tmp_path / "run_ta.py"
    path.write_text(script, encoding="utf-8")
    for ticker, old in (("0700.HK", "OLD0700"), ("BABA", "OLDBABA")):
        report = tmp_path / f"{ticker}_2026-11-18"
        report.mkdir()
        (report / "decision.txt").write_text(old, encoding="utf-8")
        log = tmp_path / "logs" / ticker / "TradingAgentsStrategy_logs"
        log.mkdir(parents=True)
        (log / "full_states_log_2026-11-18.json").write_text("OLDLOG " + ticker, encoding="utf-8")
    env = os.environ.copy()
    env["STUB_GEN"] = "1"
    procs = [
        subprocess.Popen([sys.executable, str(path), ticker, "2026-11-18"], env=env, cwd=tmp_path)
        for ticker in ("0700.HK", "BABA")
    ]
    assert [proc.wait(timeout=30) for proc in procs] == [0, 0]
    for ticker, old in (("0700.HK", "OLD0700"), ("BABA", "OLDBABA")):
        backups = list((tmp_path / "backups").glob(f"{ticker}_2026-11-18_*"))
        assert len(backups) == 1
        assert (backups[0] / "report" / "decision.txt").read_text(encoding="utf-8") == old
        assert (backups[0] / "framework_log" / "full_states_log_2026-11-18.json").read_text(encoding="utf-8") == "OLDLOG " + ticker
        assert (tmp_path / f"{ticker}_2026-11-18" / "decision.txt").read_text(encoding="utf-8") == "HOLD"
        assert (tmp_path / f"{ticker}_2026-11-18" / "fundamentals_report.md").read_text(encoding="utf-8") == "FUND " + ticker
        other = "OLDBABA" if ticker == "0700.HK" else "OLD0700"
        assert other not in (backups[0] / "report" / "decision.txt").read_text(encoding="utf-8")
    env["STUB_GEN"] = "2"
    again = subprocess.run([sys.executable, str(path), "0700.HK", "2026-11-18"], env=env, cwd=tmp_path, check=False)
    assert again.returncode == 0
    rerun = sorted((tmp_path / "backups").glob("0700.HK_2026-11-18_*"))
    assert len(rerun) == 2
    assert (rerun[0] / "report" / "decision.txt").read_text(encoding="utf-8") == "OLD0700"
    assert (rerun[1] / "report" / "fundamentals_report.md").read_text(encoding="utf-8") == "FUND 0700.HK"
    assert (tmp_path / "BABA_2026-11-18" / "fundamentals_report.md").read_text(encoding="utf-8") == "FUND BABA"
    assert len(list((tmp_path / "backups").glob("BABA_2026-11-18_*"))) == 1
