"""Replace the exact options-digest block. Every other byte stays.

The pinned 2026-11-13 file is removed. A same-date combined digest returns
only the block for that ticker. The source file is never opened for writing.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

OLD = (
    "def _load_options_digest(ticker: str, as_of: str) -> str:\n"
    '    """Prefer the OpenBB per-ticker digest; build it if missing. No LLM calls."""\n'
    '    target = RUN / f"options_digest_{ticker}_{as_of}.md"\n'
    "    if not target.exists():\n"
    '        script = RUN / "options_digest.py"\n'
    '        py = pathlib.Path("/workspace/openbb-venv/bin/python")\n'
    "        if script.exists() and py.exists():\n"
    "            import subprocess\n"
    "            subprocess.run(\n"
    '                [str(py), str(script), ticker, "--as-of", as_of, "--out-dir", str(RUN)],\n'
    "                check=False,\n"
    "            )\n"
    "    if target.exists():\n"
    "        return target.read_text()\n"
    "    # Legacy combined yfinance digest\n"
    '    legacy = RUN / f"options_digest_{as_of}.md"\n'
    "    if not legacy.exists():\n"
    '        legacy = RUN / "options_digest_2026-11-13.md"\n'
    "    if legacy.exists():\n"
    '        blocks = [b for b in legacy.read_text().split("## ") if b.startswith(ticker + " ")]\n'
    '        return ("## " + blocks[0]) if blocks else legacy.read_text()\n'
    '    return f"(no options digest found for {ticker} as of {as_of})"\n'
    "\n"
    "opt = _load_options_digest(TICKER, DATE)\n"
    "opt_block = (\n"
    '    "\\n\\n=== EXTRA CONTEXT: trading volume & options data "\n'
    '    "(OpenBB: Cboe preferred, yfinance fallback; HK options unavailable) ===\\n"\n'
    '    + (opt if opt.lstrip().startswith("##") else "## " + opt)\n'
    '    + "\\n=== END EXTRA CONTEXT ===\\n"\n'
    ")\n"
)

NEW = (
    "def _load_options_digest(ticker: str, as_of: str) -> str:\n"
    '    """Prefer the OpenBB per-ticker digest; build it if missing. No LLM calls."""\n'
    '    target = RUN / f"options_digest_{ticker}_{as_of}.md"\n'
    "    if not target.exists():\n"
    '        script = RUN / "options_digest.py"\n'
    '        py = pathlib.Path("/workspace/openbb-venv/bin/python")\n'
    "        if script.exists() and py.exists():\n"
    "            import subprocess\n"
    "            try:\n"
    "                subprocess.run(\n"
    '                    [str(py), str(script), ticker, "--as-of", as_of, "--out-dir", str(RUN)],\n'
    "                    check=False,\n"
    "                    timeout=60,\n"
    "                )\n"
    "            except subprocess.TimeoutExpired:\n"
    "                pass\n"
    "    if target.exists():\n"
    "        return target.read_text()\n"
    '    legacy = RUN / f"options_digest_{as_of}.md"\n'
    "    if legacy.exists():\n"
    '        blocks = [b for b in legacy.read_text().split("## ") if b.startswith(ticker + " ")]\n'
    "        if blocks:\n"
    '            return "## " + blocks[0]\n'
    '    return f"(no options digest found for {ticker} as of {as_of})"\n'
    "\n"
    "opt = _load_options_digest(TICKER, DATE)\n"
    "opt_block = (\n"
    '    "\\n\\n=== EXTRA CONTEXT: trading volume & options data "\n'
    '    "(OpenBB: Cboe preferred, yfinance fallback) ===\\n"\n'
    '    + (opt if opt.lstrip().startswith("##") else "## " + opt)\n'
    '    + "\\n=== END EXTRA CONTEXT ===\\n"\n'
    ")\n"
)


class PatchMismatch(Exception):
    def __init__(self, count: int):
        self.count = count
        super().__init__(f"expected exactly one options block, found {count}")


def patch_bytes(data: bytes) -> bytes:
    old, new = OLD.encode(), NEW.encode()
    count = data.count(old)
    if count != 1:
        raise PatchMismatch(count)
    return data.replace(old, new, 1)


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
    parser = argparse.ArgumentParser(description="Remove the pinned 2026-11-13 options fallback.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    output = args.output if args.output is not None else args.source.with_name(args.source.name + ".patched")
    if output.resolve() == args.source.resolve():
        print("refusing to overwrite the source", file=sys.stderr)
        return 2
    try:
        updated = patch_bytes(args.source.read_bytes())
    except (PatchMismatch, OSError) as exc:
        print(exc, file=sys.stderr)
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
