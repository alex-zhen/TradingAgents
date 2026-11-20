"""Show get_stock_data and get_news evidence blocks. No graph and no model.

DATE is the session date. --decision-at is the cutoff. They are separate.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from public_market_evidence import attach_public_evidence

VENDOR = "VENDOR. Hong Kong listed options are not available from the free OpenBB providers."


def render(path: Path, symbol: str, session_date: str, decision_at: str, currency: str) -> str:
    prices = attach_public_evidence(
        VENDOR, "get_stock_data",
        requested_symbol=symbol, session_date=session_date, decision_at=decision_at,
        path=path, expected_currency=currency or None,
    )
    news = attach_public_evidence(
        "VENDOR NEWS", "get_news",
        requested_symbol=symbol, session_date=session_date, decision_at=decision_at,
        path=path, expected_currency=currency or None,
    )
    fundamentals = attach_public_evidence(
        "VENDOR FUNDAMENTALS", "get_fundamentals",
        requested_symbol=symbol, session_date=session_date, decision_at=decision_at,
        path=path, expected_currency=currency or None,
    )
    return (
        "=== get_stock_data ===\n" + prices + "\n"
        + "=== get_news ===\n" + news + "\n"
        + "=== get_fundamentals ===\n" + fundamentals + "\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preflight public evidence for the two tool routes. No model call.")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--session-date", required=True, help="Trade date DATE. Not the decision cutoff.")
    parser.add_argument("--decision-at", required=True, help="Timezone-aware decision cutoff.")
    parser.add_argument("--expected-currency", default="")
    args = parser.parse_args(argv)
    sys.stdout.write(render(args.file, args.symbol, args.session_date, args.decision_at, args.expected_currency))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
