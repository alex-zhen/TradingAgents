"""Patch a local run_ta.py that still pins the BABA 2026-11-15 digest.

The parent's runner is not in this repository. This rewriter only accepts the
recognized defect: an assignment of that digest path and a ``load_research``
that returns it for every symbol. Any other file is refused so a partial edit
cannot look applied.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MARKER = "BABA_2026-11-15"

_PATTERN = re.compile(
    r"RESEARCH_DIGEST\s*=\s*Path\(\s*(?P<q>[\"'])[^\"']*BABA_2026-11-15\.md(?P=q)\s*\)\s*"
    r"def load_research\(symbol,\s*as_of\):\n"
    r"(?:[ \t]+.*\n)*?"
    r"[ \t]+return RESEARCH_DIGEST\.read_text\([^\n]*\)\n?",
    re.M,
)

_REPLACEMENT = '''def load_research(symbol, as_of, mode="current", corpus=None, runs_dir=None):
    """Select corpus files published and captured by ``as_of``.

    ``as_of`` is a timezone-aware ISO-8601 timestamp. The filename is not used.
    ``mode="historical"`` keeps the same strict cutoff; it does not mean "now".
    """
    prepared = prepare_run(
        symbol=symbol,
        market=None,
        decision_at=as_of,
        mode=mode,
        corpus=corpus if corpus is not None else RUNS / "research_corpus",
        runs_dir=runs_dir if runs_dir is not None else RUNS / "runs",
        config_path=CONFIG,
    )
    return prepared.analyst_text
'''


class PatchError(RuntimeError):
    pass


def patch_source(text: str) -> str:
    if MARKER not in text:
        raise PatchError(
            "refusing to patch: hardcoded BABA_2026-11-15 digest marker not found. "
            "Install integrations/external_runner/run_ta.py instead of editing in place."
        )
    updated, count = _PATTERN.subn(_REPLACEMENT, text, count=1)
    if count != 1 or MARKER in updated:
        raise PatchError(
            "refusing to patch: the digest marker is present but not the recognized "
            "RESEARCH_DIGEST / load_research pattern. Install the maintained run_ta.py."
        )
    if "from research_ingest import prepare_run" not in updated:
        updated = updated.replace(
            "from pathlib import Path\n",
            "from pathlib import Path\n\nfrom research_ingest import prepare_run\n",
            1,
        )
    if "prepare_run(" not in updated:
        raise PatchError("patch did not call prepare_run")
    return updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replace a hardcoded BABA digest loader.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--output", type=Path)
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
