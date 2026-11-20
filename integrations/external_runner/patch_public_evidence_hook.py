"""Insert the public-evidence hook after the xueqiu hook.

The source file is never written. The official-fundamentals function is not
edited. The input must be the live runner sha256 6d269117.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

SOURCE_SHA = "6d2691173afd287dd9b69fcd0f77b4518089c81cd56e8eb595f21f51f6d7842a"
ANCHOR = "# === XUEQIU HOOK END =======================================================\n"
HOOK = Path(__file__).with_name("public_evidence_hook.txt").read_text(encoding="utf-8")
if not HOOK.endswith("\n"):
    HOOK += "\n"


class PatchMismatch(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def patch_bytes(data: bytes) -> bytes:
    digest = hashlib.sha256(data).hexdigest()
    if digest != SOURCE_SHA:
        raise PatchMismatch(f"source sha256 {digest} is not the known live runner")
    text = data.decode()
    if text.count(ANCHOR) != 1:
        raise PatchMismatch("xueqiu hook end was not found once")
    if "PUBLIC EVIDENCE HOOK" in text:
        raise PatchMismatch("public evidence hook is already present")
    official = text.split("def _official_fundamentals_block", 1)[1].split("def _official_not_applicable", 1)[0]
    updated = text.replace(ANCHOR, ANCHOR + "\n" + HOOK, 1)
    updated_official = updated.split("def _official_fundamentals_block", 1)[1].split("def _official_not_applicable", 1)[0]
    if official != updated_official:
        raise PatchMismatch("official fundamentals block changed")
    return updated.encode()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage the public-evidence hook onto a copy of the live runner.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.resolve() == args.source.resolve() or args.backup.resolve() == args.source.resolve():
        print("refusing to write the source path", file=sys.stderr)
        return 2
    try:
        original = args.source.read_bytes()
        updated = patch_bytes(original)
    except (PatchMismatch, OSError) as exc:
        print(exc, file=sys.stderr)
        return 2
    args.backup.parent.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.backup.write_bytes(original)
    args.output.write_bytes(updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
