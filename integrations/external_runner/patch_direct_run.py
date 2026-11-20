"""Harden the attached live runner. The source file is never opened for writing.

The match is the current runner whose sha256 starts with 0b6de641. News,
options, and the xueqiu hook stay. A same-date report and framework log are
copied before the first write. Official fundamentals follow the tool symbol.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import sys
from pathlib import Path

SOURCE_SHA = "0b6de641a9a31697f832529a10db0d504ff340f6af0d30752b277b62f37ef0c1"
MARKER = "def _official_fundamentals_block"
TAIL = Path(__file__).with_name("direct_run_tail.txt").read_text(encoding="utf-8")
if not TAIL.endswith("\n"):
    TAIL += "\n"


class PatchMismatch(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def patch_bytes(data: bytes) -> bytes:
    digest = hashlib.sha256(data).hexdigest()
    if digest != SOURCE_SHA:
        raise PatchMismatch(f"source sha256 {digest} is not the attached live runner")
    text = data.decode()
    start = text.find(MARKER)
    if start < 0 or text.find(MARKER, start + len(MARKER)) != -1:
        raise PatchMismatch("official fundamentals block was not found once")
    if not text.endswith("print(\"DECISION\", TICKER, decision)\n"):
        raise PatchMismatch("runner ending is not the attached live wrapper")
    return (text[:start] + TAIL).encode()


def unified_diff(before: str, after: str, fromfile: str, tofile: str) -> str:
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
    parser = argparse.ArgumentParser(description="Stage direct-run guards onto the attached live runner.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--backup", type=Path, help="Copy the untouched source bytes here")
    args = parser.parse_args(argv)
    source = args.source
    output = args.output if args.output is not None else source.with_name(source.name + ".patched")
    if output.resolve() == source.resolve():
        print("refusing to overwrite the source", file=sys.stderr)
        return 2
    if args.backup is not None and args.backup.resolve() == source.resolve():
        print("refusing to use the source as its own backup", file=sys.stderr)
        return 2
    try:
        original = source.read_bytes()
        updated = patch_bytes(original)
    except PatchMismatch as exc:
        print(exc, file=sys.stderr)
        return 2
    except OSError as exc:
        print(exc, file=sys.stderr)
        return 2
    if args.backup is not None:
        args.backup.parent.mkdir(parents=True, exist_ok=True)
        args.backup.write_bytes(original)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
