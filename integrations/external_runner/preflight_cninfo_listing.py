"""Execute the staged runner route for listing evidence. No graph and no model.

The cutoff written into the stub digest is --decision-at. --session-date is
only the runner DATE and is not used when the digest has no decision_at.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

VENDOR = "VENDOR FUNDAMENTALS"


def execute_staged(staged: Path, evidence: Path, symbol: str, session_date: str, decision_at: str) -> str:
    text = staged.read_text(encoding="utf-8")
    start = text.find("def _norm_listing")
    end = text.find("# === CNINFO LISTING HOOK END")
    if start < 0 or end < 0:
        raise SystemExit("staged runner has no cninfo listing hook")
    module_dir = str(Path(__file__).resolve().parent)
    os.environ["TRADINGAGENTS_CNINFO_LISTING_DIR"] = module_dir
    os.environ["TRADINGAGENTS_CNINFO_LISTING"] = str(evidence.resolve())
    os.environ.pop("TRADINGAGENTS_DECISION_AT", None)
    os.environ.pop("TRADINGAGENTS_PUBLIC_EVIDENCE", None)
    sent = (
        f"ticker: {symbol}\nprice_session_date: {session_date}\n"
        f"decision_at: {decision_at}\n"
        "公告时间：2026年10月20日\n"
        "## Financial report\nRevenue 100,000\n"
    )
    namespace = {
        "sys": sys,
        "T": type("T", (), {"route_to_vendor": staticmethod(lambda *a, **k: VENDOR)})(),
        "TICKER": symbol,
        "DATE": session_date,
        "sent": sent,
        "sent_block": "",
        "opt_block": "",
    }
    exec(text[start:end] + "\n", namespace)
    route = namespace["T"].route_to_vendor
    fundamentals = route("get_fundamentals", symbol)
    prices = route("get_stock_data", symbol)
    news = route("get_news", symbol)
    return (
        "=== get_fundamentals ===\n" + fundamentals + "\n"
        + "=== get_stock_data ===\n" + prices + "\n"
        + "=== get_news ===\n" + news + "\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preflight the staged CNINFO listing route. No model call.")
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--session-date", required=True)
    parser.add_argument("--decision-at", required=True)
    args = parser.parse_args(argv)
    printed = execute_staged(args.runner, args.file, args.symbol, args.session_date, args.decision_at)
    sys.stdout.write(printed)
    fundamentals = printed.split("=== get_stock_data ===", 1)[0]
    return 0 if "status: admitted" in fundamentals else 2


if __name__ == "__main__":
    raise SystemExit(main())
