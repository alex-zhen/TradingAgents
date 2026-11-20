"""Append official financials to the fundamentals tool route.

The match is the live runner's route wrapper, including the news and options
branches and the xueqiu hook that follows it. Those bytes stay. The source
file is never opened for writing.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

HELPER = '''def _official_fundamentals_block(digest: str, cutoff: str) -> str:
    """Labelled official report for get_fundamentals. Plain markdown is accepted."""
    import datetime as _dt
    import re as _re
    header = "\\n\\n=== OFFICIAL FUNDAMENTALS (labelled; not a vendor value) ===\\n"
    end = "\\n=== END OFFICIAL FUNDAMENTALS ===\\n"

    def declared():
        match = _re.search(r"decision_at:\\s*(\\S+)", digest or "")
        return match.group(1) if match else ""

    def missing(reason):
        as_of = cutoff or declared() or "not declared"
        return header + f"as_of: {as_of}\\ndigest_decision_at: {declared() or 'not declared'}\\nMISSING: {reason} Do not describe vendor output as the current official filing.\\n" + end

    if not digest or digest.startswith("MISSING "):
        return missing("no verified official financial report was loaded for this decision.")
    hk = _re.search(r"HKEX listing datetime[^0-9\\n]{0,80}(\\d{2}/\\d{2}/\\d{4} \\d{2}:\\d{2})", digest)
    if not hk:
        hk = _re.search(r"hkex_listing_datetime:\\s*(\\d{2}/\\d{2}/\\d{4} \\d{2}:\\d{2})", digest)
    if not hk:
        return missing("publication availability time is not in the digest. The report is not treated as current.")
    avail = _dt.datetime.strptime(hk.group(1), "%d/%m/%Y %H:%M").replace(
        tzinfo=_dt.timezone(_dt.timedelta(hours=8))
    )
    used = cutoff or declared()
    if not used:
        return missing("as-of is not declared in the digest and no explicit decision cutoff was supplied.")
    text = used.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        cut = _dt.datetime.fromisoformat(text)
    except ValueError:
        return missing("decision cutoff is not a timezone-aware timestamp.")
    if cut.tzinfo is None:
        return missing("decision cutoff has no timezone. No timestamp was invented.")
    if cut < avail:
        return missing(
            "official report availability " + avail.isoformat()
            + " is after cutoff " + cut.isoformat() + ". The report is not included."
        )
    dateline = _re.search(
        r"(?:publication_dateline:\\s*|Hong Kong,\\s*)(\\d{1,2} [A-Z][a-z]+ \\d{4}|[A-Z][a-z]+ \\d{1,2}, \\d{4})",
        digest,
    )
    period = _re.search(
        r"((?:quarter|nine months|six months|three months|period).{0,40}ended \\d{1,2} [A-Z][a-z]+ \\d{4}|ended [A-Z][a-z]+ \\d{1,2}, \\d{4})",
        digest,
        _re.I,
    )
    urls = _re.findall(r"https://[^\\s)]+", digest)
    source = next((item for item in urls if item.lower().endswith(".pdf")), urls[0] if urls else "")
    body = ""
    for title in ("## 3Q2026 official figures", "## Financial report"):
        if title in digest:
            body = digest.split(title, 1)[1].split("\\n## ", 1)[0].strip()
            break
    if not body:
        lines = [
            line.strip() for line in digest.splitlines()
            if _re.search(r"revenue|attributable|operating profit|source_url", line, _re.I) and _re.search(r"\\d", line)
        ]
        body = "\\n".join(lines[:12])
    if not body or not _re.search(r"\\d", body):
        return missing("the digest has no official financial amounts.")
    return (
        header
        + "as_of: " + (declared() or cut.isoformat()) + "\\n"
        + "digest_decision_at: " + (declared() or "not declared") + "\\n"
        + "availability: " + avail.isoformat() + "\\n"
        + "publication_dateline: " + (dateline.group(1) if dateline else "not stated") + "\\n"
        + "report_period: " + (period.group(1) if period else "not stated") + "\\n"
        + "source_url: " + source + "\\n"
        + "vendor_conflict: the vendor text above is not replaced. If it reports an earlier period, that vendor period is stale relative to this official report. Do not call the vendor period the latest official filing.\\n"
        + "body:\\n" + body + "\\n"
        + end
    )


'''

OLD = (
    "_orig = T.route_to_vendor\n"
    "def patched(method, *a, **k):\n"
    "    out = _orig(method, *a, **k)\n"
    "    if method == \"get_news\":\n"
    "        out = f\"{out}{sent_block}\"\n"
    "    elif method == \"get_stock_data\":\n"
    "        out = f\"{out}{opt_block}\"\n"
    "    return out\n"
    "T.route_to_vendor = patched\n"
)

NEW = HELPER + (
    "_orig = T.route_to_vendor\n"
    "def patched(method, *a, **k):\n"
    "    out = _orig(method, *a, **k)\n"
    "    if method == \"get_news\":\n"
    "        out = f\"{out}{sent_block}\"\n"
    "    elif method == \"get_stock_data\":\n"
    "        out = f\"{out}{opt_block}\"\n"
    "    elif method in {\"get_fundamentals\", \"get_balance_sheet\", \"get_cashflow\", \"get_income_statement\"}:\n"
    "        _cut = \"\"\n"
    "        _declared = __import__(\"re\").search(r\"decision_at:\\s*(\\S+)\", sent or \"\")\n"
    "        if _declared:\n"
    "            _cut = _declared.group(1)\n"
    "        out = f\"{out}{_official_fundamentals_block(sent, _cut)}\"\n"
    "    return out\n"
    "T.route_to_vendor = patched\n"
)


class PatchMismatch(Exception):
    def __init__(self, count: int):
        self.count = count
        super().__init__(f"expected exactly one fundamentals route block, found {count}")


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
    parser = argparse.ArgumentParser(description="Stage the fundamentals route onto the live runner.")
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
