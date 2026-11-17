"""Optional preflight. Runs acquire_sentiment, then can call an existing runner.

The 101-line runner is not rewritten here. Pass --runner only when that file
is the parent's script. Baseline digest files are copied aside before a new
file is placed where the runner reads it.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from acquire_sentiment import acquire


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh current official material, then optionally call run_ta.py.")
    parser.add_argument("ticker")
    parser.add_argument("price_date", help="Positional price-session DATE, YYYY-MM-DD")
    parser.add_argument("--decision-at", required=True)
    parser.add_argument("--mode", choices=("current", "historical"), default="current")
    parser.add_argument("--root", type=Path, default=Path("/workspace/tradingagents-runs"))
    parser.add_argument("--refresh-current", action="store_true")
    parser.add_argument("--install-for-runner", action="store_true")
    parser.add_argument("--refuse-on-failure", action="store_true")
    parser.add_argument("--runner", type=Path)
    parser.add_argument("--operator-feed", type=Path)
    args = parser.parse_args(argv)
    refresh = args.refresh_current or os.getenv("REFRESH_CURRENT") == "1"
    if args.mode == "current" and not refresh:
        print("refresh not requested; no fetch", file=sys.stderr)
        return 2
    result = acquire(
        args.ticker, args.price_date, args.decision_at, args.mode, args.root,
        operator_feed=args.operator_feed,
    )
    print(result.run_dir)
    if args.install_for_runner and result.fetched:
        digest_name = f"sentiment_digest_{args.ticker}_{args.price_date}.md"
        source = result.run_dir / digest_name
        dest = args.root / digest_name
        if dest.exists():
            backup = args.root / "backups" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            backup.mkdir(parents=True)
            shutil.copy2(dest, backup / digest_name)
        shutil.copy2(source, dest)
    if not result.fetched and args.refuse_on_failure:
        print(result.status, file=sys.stderr)
        return 4
    if args.runner:
        if not args.runner.is_file():
            print(f"runner not found: {args.runner}", file=sys.stderr)
            return 3
        completed = subprocess.run([sys.executable, str(args.runner), args.ticker, args.price_date], check=False)
        return completed.returncode
    return 0 if result.status != "partial_or_failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
