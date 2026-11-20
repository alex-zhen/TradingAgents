"""Official CNINFO or exchange listing publication evidence.

This does not rename 公告时间 to 公告日期. A digest line that only says
公告时间 stays outside the existing text gate. This module admits a separate
listing record when the announcement id, security code, report period, PDF
link, content hash, and official source all correspond.

A date, or a midnight placeholder, is not used for a same-day decision.
A timezone-aware clock other than midnight can be used once the decision
cutoff is at or after that clock. The session date is not a cutoff.
Reading a body does not mark latest discovery as verified.

Entry point:
  python integrations/external_runner/cninfo_listing_evidence.py \
    --file listing.json --symbol 300750.SZ \
    --decision-at 2026-10-21T10:00:00+08:00
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

SCHEMA = "tradingagents.cninfo_listing_evidence.v1"
FUNDAMENTAL_METHODS = {"get_fundamentals", "get_balance_sheet", "get_cashflow", "get_income_statement"}
SOURCE_LABELS = {"公告时间", "announcementTime"}
OFFICIAL_HOSTS = {
    "cninfo": {"static.cninfo.com.cn", "www.cninfo.com.cn"},
    "sse": {"www.sse.com.cn", "static.sse.com.cn"},
    "szse": {"www.szse.cn", "disc.szse.cn", "disc.static.szse.cn"},
}
PERIOD = re.compile(r"\d{4}-\d{2}-\d{2}|20\d{2}年\d{1,2}月\d{1,2}日")
ANNOUNCEMENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{3,128}")


@dataclass
class ListingView:
    status: str
    reasons: list[str] = field(default_factory=list)
    text: str = ""


def same_security(left: str, right: str) -> bool:
    """Match one listing. A 6-digit A-share code keeps its identity."""

    def norm(value: str) -> str:
        text = (value or "").strip().upper().replace(" ", "").replace("_", "")
        share = re.fullmatch(r"(\d{6})(?:\.(?:SZ|SH|SS|BJ))?", text)
        if share:
            return "CN" + share.group(1)
        hong_kong = re.fullmatch(r"(?:HK\.?)?0*(\d{3,5})(?:\.HK)?", text)
        if hong_kong:
            return "HK" + str(int(hong_kong.group(1)))
        return text

    if not left or not right:
        return False
    return norm(left) == norm(right)


def _aware(value: str) -> datetime | None:
    text = (value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        return None
    return parsed


def _date_value(value: str) -> date | None:
    text = (value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return date.fromisoformat(text)
    parts = re.fullmatch(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", text)
    if parts:
        return date(int(parts.group(1)), int(parts.group(2)), int(parts.group(3)))
    return None


def _publication(value: str):
    text = (value or "").strip()
    as_date = _date_value(text)
    if as_date is not None and "T" not in text:
        return "date", as_date, None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return "invalid", None, None
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        return "naive", None, None
    midnight = parsed.hour == 0 and parsed.minute == 0 and parsed.second == 0 and parsed.microsecond == 0
    if midnight:
        return "date", parsed.date(), parsed
    return "timestamp", parsed.date(), parsed


def _reject(reasons: list[str]) -> ListingView:
    return ListingView("rejected", reasons)


def load_cninfo_listing_evidence(
    path: Path | None,
    *,
    requested_symbol: str,
    decision_at: str,
) -> ListingView:
    """Validate one listing file. The body is copied only after every check."""
    if path is None or not Path(path).is_file():
        return ListingView("absent", ["listing evidence file is absent"])
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _reject(["listing evidence is not readable json"])
    if not isinstance(payload, dict):
        return _reject(["listing evidence is not an object"])
    reasons: list[str] = []
    if payload.get("schema") != SCHEMA:
        reasons.append("schema is not an official listing record")
    source = str(payload.get("source") or "")
    if source not in OFFICIAL_HOSTS:
        reasons.append("source is not an official cninfo or exchange listing")
    label = payload.get("source_label")
    if label not in SOURCE_LABELS:
        reasons.append("source_label must remain 公告时间 or announcementTime")
    announcement_id = str(payload.get("announcement_id") or "")
    if ANNOUNCEMENT_ID.fullmatch(announcement_id) is None:
        reasons.append("announcement_id is missing or not a listing id")
    security = str(payload.get("security_code") or "")
    if not same_security(requested_symbol, security):
        reasons.append("security_code does not match the requested symbol")
    period = str(payload.get("report_period") or "")
    if PERIOD.fullmatch(period) is None:
        reasons.append("report_period is missing or not a period date")
    pdf_url = str(payload.get("pdf_url") or "")
    parsed_url = urlparse(pdf_url)
    host = parsed_url.hostname or ""
    if parsed_url.scheme not in {"http", "https"} or host not in OFFICIAL_HOSTS.get(source, set()):
        reasons.append("pdf_url is not on the official host for the declared source")
    elif announcement_id and announcement_id not in pdf_url:
        reasons.append("pdf_url does not contain the announcement_id")
    body = payload.get("body")
    if not isinstance(body, str) or not body.strip():
        reasons.append("body is missing")
        body = ""
    declared_hash = str(payload.get("content_sha256") or "").lower()
    actual_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", declared_hash) or declared_hash != actual_hash:
        reasons.append("content_sha256 does not match the body")
    if body and announcement_id and announcement_id not in body:
        reasons.append("body does not contain the announcement_id")
    if body and security and security not in body:
        reasons.append("body does not contain the security_code")
    if body and period and period not in body:
        reasons.append("body does not contain the report_period")
    publication = payload.get("publication")
    if not isinstance(publication, dict):
        reasons.append("publication is missing")
        publication = {}
    raw = str(publication.get("raw") or "")
    if any(token in raw for token in ("落款", "截至", "period ended", "period end")):
        reasons.append("publication raw text is a board signature or period end")
    kind, published_date, published_at = _publication(str(publication.get("value") or ""))
    if kind == "invalid":
        reasons.append("publication value is not a date or timestamp")
    elif kind == "naive":
        reasons.append("publication timestamp has no timezone")
    board = _date_value(str(payload.get("board_signature_date") or ""))
    period_end = _date_value(str(payload.get("period_end") or ""))
    if published_date is not None and board is not None and published_date == board:
        reasons.append("board signature date is not the publication time")
    if published_date is not None and period_end is not None and published_date == period_end:
        reasons.append("period end is not the publication time")
    cutoff = _aware(decision_at)
    if cutoff is None:
        reasons.append("decision_at is missing or not timezone-aware. DATE was not used as the decision cutoff.")
    if reasons or published_date is None or cutoff is None:
        return _reject(reasons or ["listing evidence is incomplete"])
    midnight = kind == "date" and published_at is not None
    if kind == "timestamp" and published_at is not None:
        if cutoff < published_at:
            return ListingView("withheld", ["official publication time is after the decision cutoff"])
        precision = "timestamp"
        shown = published_at.isoformat()
    else:
        if cutoff.date() <= published_date:
            reason = "date-only publication is not used for a same-day decision"
            if midnight:
                reason = "midnight placeholder is date-only and is not a precise publication time"
            return ListingView("withheld", [reason])
        precision = "date"
        shown = published_date.isoformat()
    lines = [
        "status: admitted",
        f"source: {source}",
        f"source_label: {label}",
        f"announcement_id: {announcement_id}",
        f"security_code: {security}",
        f"report_period: {period}",
        f"pdf_url: {pdf_url}",
        f"content_sha256: {actual_hash}",
        f"availability: {shown}",
        f"availability_precision: {precision}",
        f"publication_raw: {raw}",
        "latest_discovery_verified: not established by this evidence",
        "coverage: the report period is recorded. Latest disclosure discovery is not proven by this evidence.",
        "body:",
        body.strip(),
    ]
    if midnight:
        lines.insert(10, "midnight_placeholder: true")
    return ListingView("admitted", [], "\n".join(lines))


def render_listing(view: ListingView) -> str:
    title = "CNINFO LISTING EVIDENCE"
    if view.status == "admitted":
        return f"\n\n=== {title} ===\n{view.text}\n=== END {title} ===\n"
    if view.status == "absent":
        return (
            f"\n\n=== {title} ===\nstatus: evidence_absent\n"
            + "\n".join(view.reasons)
            + "\nlatest_discovery_verified: not established by this evidence\n"
            + f"=== END {title} ===\n"
        )
    return (
        f"\n\n=== {title} ===\nstatus: {view.status}\n"
        + "\n".join(view.reasons)
        + "\nlatest_discovery_verified: not established by this evidence\n"
        + f"=== END {title} ===\n"
    )


def attach_cninfo_listing(
    vendor_text: str,
    method: str,
    *,
    requested_symbol: str,
    decision_at: str,
    path: Path | None,
) -> str:
    """Append listing evidence to a fundamentals tool. Other methods stay unchanged."""
    if method not in FUNDAMENTAL_METHODS:
        return vendor_text
    view = load_cninfo_listing_evidence(path, requested_symbol=requested_symbol, decision_at=decision_at)
    return f"{vendor_text}{render_listing(view)}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read one official listing evidence file. No network.")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--decision-at", required=True)
    args = parser.parse_args(argv)
    view = load_cninfo_listing_evidence(args.file, requested_symbol=args.symbol, decision_at=args.decision_at)
    print(render_listing(view).strip())
    return 0 if view.status == "admitted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
