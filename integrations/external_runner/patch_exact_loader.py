"""Replace one exact sentiment-loader block. Every other byte stays.

The match is the live text, including spaces and double quotes. Zero or
several matches exit 2 and write nothing. The source file is never opened
for writing. Output goes to --output, or to SOURCE.patched when omitted.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

OLD = (
    'sent_path = RUN / f"sentiment_digest_{TICKER}_2026-11-15.md"\n'
    "if not sent_path.exists():\n"
    "    # fall back to any digest for this ticker\n"
    '    candidates = sorted(RUN.glob(f"sentiment_digest_{TICKER}_*.md"))\n'
    "    sent_path = candidates[-1] if candidates else sent_path\n"
    'sent = sent_path.read_text() if sent_path.exists() else ""\n'
)

NEW = (
    'sent_path = RUN / f"sentiment_digest_{TICKER}_{DATE}.md"\n'
    "sent = sent_path.read_text() if sent_path.exists() else (\n"
    '    f"MISSING sentiment_digest_{TICKER}_{DATE}.md in {RUN}. "\n'
    '    "No older file was substituted. This run did not fetch a replacement."\n'
    ")\n"
)


class PatchMismatch(Exception):
    def __init__(self, count: int):
        self.count = count
        super().__init__(f"expected exactly one loader block, found {count}")


def patch_bytes(data: bytes) -> bytes:
    old, new = OLD.encode(), NEW.encode()
    count = data.count(old)
    if count != 1:
        raise PatchMismatch(count)
    return data.replace(old, new, 1)


def unified_diff(before: str, after: str, fromfile: str, tofile: str) -> str:
    """A git-applyable diff. Headers come from difflib, not a handwritten hunk."""
    # readlines()-style inputs already end with newline; lineterm is only
    # for the --- / +++ / @@ lines. Stripping newlines and letting difflib
    # add them is not what this Python does.
    text = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
            lineterm="\n",
        )
    )
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replace the pinned 2026-11-15 sentiment loader.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    source = args.source
    output = args.output if args.output is not None else source.with_name(source.name + ".patched")
    if output.resolve() == source.resolve():
        print("refusing to overwrite the source", file=sys.stderr)
        return 2
    try:
        updated = patch_bytes(source.read_bytes())
    except PatchMismatch as exc:
        print(exc, file=sys.stderr)
        return 2
    except OSError as exc:
        print(exc, file=sys.stderr)
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
