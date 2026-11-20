"""Patch the live runner's frozen sentiment digest, and leave the rest alone.

The recognized lines are::

    sent_path = RUN / f"sentiment_digest_{TICKER}_2026-11-15.md"
    if not sent_path.exists():
        ... RUN.glob(... sentiment_digest_ ...)

Positional ``TICKER`` / ``DATE``, options_digest, xueqiu_digest, and
TradingAgentsGraph calls are not rewritten. A file without that assignment
is refused.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MARKER = "sentiment_digest_{TICKER}_2026-11-15.md"

_BLOCK = re.compile(
    r"(?P<indent>[ \t]*)sent_path\s*=\s*RUN\s*/\s*f(?P<q>['\"])"
    r"sentiment_digest_\{TICKER\}_2026-11-15\.md(?P=q)\s*\n"
    r"(?:(?P=indent)if not sent_path\.exists\(\):\s*\n"
    r"(?:(?P=indent)[ \t]+[^\n]*\n){1,8})?",
    re.M,
)


class PatchError(RuntimeError):
    pass


def patch_source(text: str) -> str:
    if MARKER not in text:
        raise PatchError(
            "refusing to patch: sent_path assignment of "
            "sentiment_digest_{TICKER}_2026-11-15.md was not found"
        )
    match = _BLOCK.search(text)
    if match is None:
        raise PatchError(
            "refusing to patch: the 2026-11-15 digest is mentioned but not in the "
            "sent_path = RUN / f'...' form"
        )
    indent = match.group("indent")
    replacement = (
        f"{indent}_sentiment = select_sentiment_digest(RUN, TICKER, DATE)\n"
        f"{indent}sent_path = _sentiment.path\n"
    )
    updated = text[:match.start()] + replacement + text[match.end():]
    if MARKER in updated or ".glob(" in updated and "sentiment_digest_" in updated:
        raise PatchError("patch left a sentiment_digest filename fallback in place")
    if "from research_ingest import select_sentiment_digest" not in updated:
        found = re.search(r"^(?:import |from )", updated, re.M)
        line = "from research_ingest import select_sentiment_digest\n"
        if found:
            updated = updated[:found.start()] + line + updated[found.start():]
        else:
            updated = line + updated
    return updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replace the frozen sentiment_digest_2026-11-15 assignment.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--in-place", action="store_true")
    args = parser.parse_args(argv)
    updated = patch_source(args.path.read_text(encoding="utf-8"))
    if args.in_place:
        args.path.write_text(updated, encoding="utf-8")
    elif args.output:
        args.output.write_text(updated, encoding="utf-8")
    else:
        sys.stdout.write(updated)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PatchError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(2) from exc
