"""Live source inventory before any graph launch.

Prints typed dates, the first useful financial lines, missing items and
conflicts, and the three collector booleans. It does not start the runner
and it does not call a model.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from acquire_sentiment import acquire

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print a live official-source inventory. Does not start the graph.")
    parser.add_argument("--price-date", required=True)
    parser.add_argument("--decision-at", required=True)
    parser.add_argument("--root", type=Path, default=Path("/tmp/acquire-accept"))
    parser.add_argument("--tickers", nargs="+", default=["BABA", "LI", "0700.HK"])
    args = parser.parse_args(argv)
    for ticker in args.tickers:
        result = acquire(ticker, args.price_date, args.decision_at, "current", args.root)
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
