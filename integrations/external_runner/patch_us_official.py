"""Let US and issuer filings reach get_fundamentals without an HKEX clock.

The match is the live runner sha256 6d269117. News, options, the xueqiu hook,
the symbol check, and the same-date archive stay. The source is not overwritten.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import sys
from pathlib import Path

SOURCE_SHA = "6d2691173afd287dd9b69fcd0f77b4518089c81cd56e8eb595f21f51f6d7842a"
FUNCS = Path(__file__).with_name("us_official_funcs.txt").read_text(encoding="utf-8")
if not FUNCS.endswith("\n"):
    FUNCS += "\n"
OLD_END = '(outdir / "decision.txt").write_text(str(decision))\nprint("DECISION", TICKER, decision)\n'
NEW_END = '''(outdir / "decision.txt").write_text(str(decision))
def _placeholder(value):
    text = str(value or "").strip().strip("`").strip().strip('"').strip("'")
    compact = "".join(text.split())
    return compact in {"", "...", "…", ".", ".."}
_final = state.get("final_trade_decision")
_plan = "\\n".join(str(state.get(key) or "") for key in ("investment_plan", "trader_investment_plan"))
if _placeholder(decision) or _placeholder(_final):
    (outdir / "output_status.txt").write_text(
        "incomplete: final output is a placeholder. "
        + ("A substantive plan is present. " if len(_plan.strip()) >= 40 and not _placeholder(_plan) else "")
        + "No result was invented.\\n",
        encoding="utf-8",
    )
    print("INCOMPLETE", TICKER, "placeholder final output; no result was invented")
    raise SystemExit(3)
print("DECISION", TICKER, decision)
'''


class PatchMismatch(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def patch_bytes(data: bytes) -> bytes:
    digest = hashlib.sha256(data).hexdigest()
    if digest != SOURCE_SHA:
        raise PatchMismatch(f"source sha256 {digest} is not the attached live runner")
    text = data.decode()
    start = text.find("def _period_fields")
    end = text.find("def _official_not_applicable")
    if start < 0 or end < 0 or start >= end:
        raise PatchMismatch("official period block was not found")
    if text.count(OLD_END) != 1:
        raise PatchMismatch("decision write was not found once")
    text = text[:start] + FUNCS + text[end:]
    text = text.replace(OLD_END, NEW_END, 1)
    return text.encode()


def unified_diff(before: str, after: str, fromfile: str, tofile: str) -> str:
    body = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
            lineterm="\n",
        )
    )
    if body and not body.endswith("\n"):
        body += "\n"
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage US/issuer official fundamentals onto the attached live runner.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--backup", type=Path)
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
    except (PatchMismatch, OSError) as exc:
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
