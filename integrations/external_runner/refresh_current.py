"""Preflight for the existing runner. Does not rewrite that runner.

--runner refuses to start unless this acquisition extracted a fresh official
document and that file is the one installed for the runner. Historical mode
does not fetch and does not start the runner. Existing digests, same-date
report directories, and framework logs are copied aside and not deleted.
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


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def archive_existing(root: Path, ticker: str, price_date: str) -> Path:
    """Copy same-date outputs. Never deletes them."""
    backup = root / "backups" / f"{ticker}_{price_date}_{_stamp()}"
    report = root / f"{ticker}_{price_date}"
    if report.exists():
        shutil.copytree(report, backup / "report")
    log = root / "logs" / ticker / "TradingAgentsStrategy_logs" / f"full_states_log_{price_date}.json"
    if log.is_file():
        target = backup / "framework_log"
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(log, target / log.name)
    digest = root / f"sentiment_digest_{ticker}_{price_date}.md"
    if digest.is_file():
        target = backup / "digest"
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(digest, target / digest.name)
    return backup


def install_digest(root: Path, ticker: str, price_date: str, produced: Path) -> Path:
    dest = root / f"sentiment_digest_{ticker}_{price_date}.md"
    if dest.exists():
        archive_existing(root, ticker, price_date)
    shutil.copy2(produced, dest)
    if dest.read_bytes() != produced.read_bytes():
        raise RuntimeError("installed digest does not match this acquisition")
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh current official material, then optionally call run_ta.py.")
    parser.add_argument("ticker")
    parser.add_argument("price_date", help="Price-session DATE, YYYY-MM-DD. Not the decision timestamp.")
    parser.add_argument("--decision-at", required=True)
    parser.add_argument("--mode", choices=("current", "historical"), default="current")
    parser.add_argument("--root", type=Path, default=Path("/workspace/tradingagents-runs"))
    parser.add_argument("--refresh-current", action="store_true")
    parser.add_argument("--install-for-runner", action="store_true")
    parser.add_argument("--runner", type=Path)
    parser.add_argument("--digest", type=Path, help="Must be the file this acquisition just wrote")
    parser.add_argument("--operator-feed", type=Path)
    args = parser.parse_args(argv)
    if args.mode == "historical":
        if args.runner:
            print("refusing historical fetch and refusing to run on an old digest", file=sys.stderr)
            return 4
        result = acquire(
            args.ticker, args.price_date, args.decision_at, "historical", args.root,
            operator_feed=args.operator_feed,
        )
        print(result.run_dir)
        return 0
    refresh = args.refresh_current or os.getenv("REFRESH_CURRENT") == "1"
    if not refresh:
        print("refresh not requested; runner not started", file=sys.stderr)
        return 2
    result = acquire(
        args.ticker, args.price_date, args.decision_at, "current", args.root,
        operator_feed=args.operator_feed,
    )
    print(result.run_dir)
    produced = result.run_dir / f"sentiment_digest_{args.ticker}_{args.price_date}.md"
    if args.runner or args.install_for_runner:
        if not result.fetched or not produced.is_file():
            print("refusing: this acquisition has no fresh official extract", file=sys.stderr)
            return 4
        if args.digest is not None and args.digest.resolve() != produced.resolve() and args.digest.read_bytes() != produced.read_bytes():
            print("refusing: digest is not the file from this acquisition", file=sys.stderr)
            return 4
        install_digest(args.root, args.ticker, args.price_date, produced)
    if args.runner:
        archive_existing(args.root, args.ticker, args.price_date)
        if not args.runner.is_file():
            print(f"runner not found: {args.runner}", file=sys.stderr)
            return 3
        completed = subprocess.run([sys.executable, str(args.runner), args.ticker, args.price_date], check=False)
        return completed.returncode
    return 0 if result.fetched else 1


if __name__ == "__main__":
    raise SystemExit(main())
