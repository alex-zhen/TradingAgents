"""Insert the CNINFO listing hook after the public-evidence hook.

The source file is never written. Official date-gate functions and the
public-evidence hook are not edited. The input must be runner sha256 4dac0876.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

SOURCE_SHA = "4dac0876f434b93b666b8663171317f0e3ef89f32ed60ea77a5d00411a4f5f4b"
ANCHOR = "# === PUBLIC EVIDENCE HOOK END =================================================\n"
HOOK = Path(__file__).with_name("cninfo_listing_hook.txt").read_text(encoding="utf-8")
if not HOOK.endswith("\n"):
    HOOK += "\n"


class PatchMismatch(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def patch_bytes(data: bytes) -> bytes:
    digest = hashlib.sha256(data).hexdigest()
    if digest != SOURCE_SHA:
        raise PatchMismatch(f"source sha256 {digest} is not the guarded runner")
    text = data.decode()
    if text.count(ANCHOR) != 1:
        raise PatchMismatch("public evidence hook end was not found once")
    if "CNINFO LISTING HOOK" in text:
        raise PatchMismatch("cninfo listing hook is already present")
    official = text.split("def _labeled_availability", 1)[1].split("def _official_not_applicable", 1)[0]
    public = text.split("# === PUBLIC EVIDENCE HOOK START", 1)[1].split("# === PUBLIC EVIDENCE HOOK END", 1)[0]
    updated = text.replace(ANCHOR, ANCHOR + "\n" + HOOK, 1)
    updated_official = updated.split("def _labeled_availability", 1)[1].split("def _official_not_applicable", 1)[0]
    updated_public = updated.split("# === PUBLIC EVIDENCE HOOK START", 1)[1].split("# === PUBLIC EVIDENCE HOOK END", 1)[0]
    if official != updated_official:
        raise PatchMismatch("official date gate changed")
    if public != updated_public:
        raise PatchMismatch("public evidence hook changed")
    return updated.encode()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage the CNINFO listing hook onto a copy of the guarded runner.")
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
