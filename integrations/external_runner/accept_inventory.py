"""Live source inventory before any graph launch.

Prints typed dates, the first useful financial lines, missing items and
conflicts, and the three collector booleans. It does not start the runner
and it does not call a model.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from acquire_sentiment import acquire, parse_decision

KEEP_PREFIXES = (
    "results_card_date:",
    "event_date:",
    "publication_dateline:",
    "sec_acceptance:",
    "sec_report_period_end:",
    "newest_unread_acceptance:",
    "sec_filing:",
    "hkex_listing_datetime:",
    "hkex_title:",
    "hkex_filing:",
    "source_url:",
    "card:",
    "conflict:",
    "FUTURE_NOT_REPORTED:",
    "issuer:",
    "report_period:",
    "content_gate:",
    "date_note:",
    "presentation_not_selected:",
    "unverified",
)


def _inventory(markdown: str) -> str:
    lines = markdown.splitlines()
    kept = []
    capture = False
    for line in lines:
        if line.startswith("useful_lines:"):
            kept.append(line)
            capture = True
            continue
        if capture:
            if not line.strip() or line.startswith(("content_gate:", "document:", "card:", "##")):
                capture = False
            else:
                kept.append(line)
                continue
        if line.startswith(KEEP_PREFIXES) or line.startswith("conflict:"):
            kept.append(line)
    return "\n".join(kept)


def _price_map(tickers: list[str], price_date: str, price_dates: str) -> dict[str, str] | str:
    mapping: dict[str, str] = {}
    if price_dates:
        for part in price_dates.split(","):
            if "=" not in part:
                return "price-dates entries must be TICKER=YYYY-MM-DD"
            ticker, day = part.split("=", 1)
            mapping[ticker.strip()] = day.strip()
    if len(tickers) > 1 and price_date and not price_dates:
        return "one --price-date cannot cover multiple listings; pass --price-dates TICKER=YYYY-MM-DD,..."
    if len(tickers) == 1 and price_date and not mapping:
        mapping[tickers[0]] = price_date
    missing = [ticker for ticker in tickers if ticker not in mapping]
    if missing:
        return "missing listing price date for " + ", ".join(missing)
    return mapping


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print a live official-source inventory. Does not start the graph.")
    parser.add_argument("--price-date", default="", help="Only with a single ticker")
    parser.add_argument("--price-dates", default="", help="TICKER=YYYY-MM-DD,TICKER=YYYY-MM-DD")
    parser.add_argument("--decision-at", required=True)
    parser.add_argument("--root", type=Path, default=Path("/tmp/acquire-accept"))
    parser.add_argument("--tickers", nargs="+", default=["BABA", "LI", "0700.HK"])
    args = parser.parse_args(argv)
    try:
        decision = parse_decision(args.decision_at)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if decision > datetime.now(UTC):
        print("refusing: decision-at is in the future", file=sys.stderr)
        return 2
    mapped = _price_map(args.tickers, args.price_date, args.price_dates)
    if isinstance(mapped, str):
        print(mapped, file=sys.stderr)
        return 2
    for ticker in args.tickers:
        result = acquire(ticker, mapped[ticker], args.decision_at, "current", args.root)
        manifest_path = result.run_dir / "audit_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(f"ticker: {ticker}")
        print(f"run_dir: {result.run_dir}")
        print(f"fetch_succeeded: {str(manifest.get('fetch_succeeded')).lower()}")
        print(f"content_validated: {str(manifest.get('content_validated')).lower()}")
        print(f"latest_discovery_verified: {str(manifest.get('latest_discovery_verified')).lower()}")
        print(f"install_allowed: {str(manifest.get('install_allowed')).lower()}")
        print(_inventory(result.markdown))
        print("missing: " + ", ".join(manifest.get("missing") or []))
        print("runner_started: false")
        print("---")
    print("graph_launched: false", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
