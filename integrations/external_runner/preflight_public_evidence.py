"""Execute the staged runner's tool route. No graph and no model.

The cutoff is the digest decision_at passed in --decision-at and written into
the stub digest. The session date is --session-date. They are not substituted
for each other.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

VENDOR = "VENDOR. Hong Kong listed options are not available from the free OpenBB providers."


def execute_staged(staged: Path, evidence: Path, symbol: str, session_date: str, decision_at: str, currency: str) -> str:
    text = staged.read_text(encoding="utf-8")
    start = text.find("def _norm_listing")
    end = text.find("# === PUBLIC EVIDENCE HOOK END")
    if start < 0 or end < 0:
        raise SystemExit("staged runner has no public evidence hook")
    module_dir = str(Path(__file__).resolve().parent)
    os.environ["TRADINGAGENTS_PUBLIC_EVIDENCE_DIR"] = module_dir
    os.environ["TRADINGAGENTS_PUBLIC_EVIDENCE"] = str(evidence.resolve())
    if currency:
        os.environ["TRADINGAGENTS_EVIDENCE_CURRENCY"] = currency
    else:
        os.environ.pop("TRADINGAGENTS_EVIDENCE_CURRENCY", None)
    os.environ.pop("TRADINGAGENTS_DECISION_AT", None)
    sent = f"ticker: {symbol}\nprice_session_date: {session_date}\ndecision_at: {decision_at}\n"
    namespace = {
        "sys": sys,
        "T": type("T", (), {"route_to_vendor": staticmethod(lambda *a, **k: VENDOR)})(),
        "TICKER": symbol,
        "DATE": session_date,
        "sent": sent,
        "sent_block": "\nSENTINEL_NEWS\n",
        "opt_block": "\nSENTINEL_OPTIONS\n",
    }
    exec(text[start:end] + "\n", namespace)
    route = namespace["T"].route_to_vendor
    prices = route("get_stock_data", symbol)
    news = route("get_news", symbol)
    fundamentals = route("get_fundamentals", symbol)
    return (
        "=== get_stock_data ===\n" + prices + "\n"
        + "=== get_news ===\n" + news + "\n"
        + "=== get_fundamentals ===\n" + fundamentals + "\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preflight the staged public-evidence route. No model call.")
    parser.add_argument("--runner", type=Path, required=True, help="Staged run_ta.py, not the live file.")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--session-date", required=True)
    parser.add_argument("--decision-at", required=True)
    parser.add_argument("--expected-currency", default="")
    args = parser.parse_args(argv)
    sys.stdout.write(execute_staged(
        args.runner, args.file, args.symbol, args.session_date, args.decision_at, args.expected_currency,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
