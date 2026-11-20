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

from sse_2026_calendar import classify_session, coverage_line

SCHEMA = "tradingagents.cninfo_listing_evidence.v1"
FUNDAMENTAL_METHODS = {"get_fundamentals", "get_balance_sheet", "get_cashflow", "get_income_statement"}
SOURCE_LABELS = {"公告时间", "announcementTime"}
OFFICIAL_HOSTS = {
    "cninfo": {"static.cninfo.com.cn", "www.cninfo.com.cn"},
    "sse": {"www.sse.com.cn", "static.sse.com.cn"},
    "szse": {"www.szse.cn", "disc.szse.cn", "disc.static.szse.cn"},
}
ANNOUNCEMENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{3,128}")
CN_DATE = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
ISO_DATE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


@dataclass
class ListingView:
    status: str
    reasons: list[str] = field(default_factory=list)
    text: str = ""
    codes: list[str] = field(default_factory=list)


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


def _share_code(value: str) -> str:
    text = (value or "").strip().upper().replace(" ", "")
    match = re.fullmatch(r"(\d{6})(?:\.(?:SZ|SH|SS|BJ))?", text)
    return match.group(1) if match else ""


def _parsed_period(value: str) -> date | None:
    text = (value or "").strip()
    as_date = _date_value(text)
    if as_date is not None:
        return as_date
    match = CN_DATE.fullmatch(text)
    if match:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return None


def _body_has_date(body: str, target: date) -> bool:
    """Match a date after removing spaces. 09 and 9 stay the same calendar day."""
    for match in CN_DATE.finditer(body or ""):
        found = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if found == target:
            return True
    for match in ISO_DATE.finditer(body or ""):
        found = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if found == target:
            return True
    return False


def _body_has_security(body: str, security: str) -> bool:
    code = _share_code(security)
    if not code:
        return bool(security) and security in (body or "")
    return re.search(rf"证券代码\s*[：:]\s*{code}(?!\d)", body or "") is not None


def _cutoff(value: str):
    text = (value or "").strip()
    if not text:
        return "decision_at_missing", None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return "decision_at_invalid", None
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        return "decision_at_naive", None
    return "", parsed


def _view(status: str, reasons: list[str], codes: list[str], text: str = "") -> ListingView:
    return ListingView(status, reasons, text, codes)


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
        return _view("rejected", ["listing evidence is not readable json"], ["listing_unreadable"])
    if not isinstance(payload, dict):
        return _view("rejected", ["listing evidence is not an object"], ["listing_unreadable"])
    reasons: list[str] = []
    codes: list[str] = []

    def fail(code: str, reason: str) -> None:
        codes.append(code)
        reasons.append(reason)

    if payload.get("schema") != SCHEMA:
        fail("schema_invalid", "schema is not an official listing record")
    source = str(payload.get("source") or "")
    if source not in OFFICIAL_HOSTS:
        fail("source_not_official", "source is not an official cninfo or exchange listing")
    label = payload.get("source_label")
    if label not in SOURCE_LABELS:
        fail("source_label_invalid", "source_label must remain 公告时间 or announcementTime")
    announcement_id = str(payload.get("announcement_id") or "")
    if ANNOUNCEMENT_ID.fullmatch(announcement_id) is None:
        fail("announcement_id_invalid", "announcement_id is missing or not a platform listing id")
    security = str(payload.get("security_code") or "")
    if not same_security(requested_symbol, security):
        fail("security_mismatch", "security_code does not match the requested symbol")
    period = str(payload.get("report_period") or "")
    period_date = _parsed_period(period)
    if period_date is None:
        fail("report_period_invalid", "report_period is missing or not a period date")
    pdf_url = str(payload.get("pdf_url") or "")
    parsed_url = urlparse(pdf_url)
    host = parsed_url.hostname or ""
    if parsed_url.scheme not in {"http", "https"} or host not in OFFICIAL_HOSTS.get(source, set()):
        fail("pdf_url_not_official", "pdf_url is not on the official host for the declared source")
    elif announcement_id and announcement_id not in pdf_url:
        fail("announcement_id_not_in_url", "pdf_url does not contain the platform announcement_id")
    adjunct = str(payload.get("adjunctUrl") or "")
    if adjunct and announcement_id and announcement_id not in adjunct:
        fail("announcement_id_not_in_url", "adjunctUrl does not contain the platform announcement_id")
    body = payload.get("body")
    if not isinstance(body, str) or not body.strip():
        fail("body_missing", "body is missing")
        body = ""
    declared_hash = str(payload.get("content_sha256") or "").lower()
    actual_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", declared_hash) or declared_hash != actual_hash:
        fail("content_hash_mismatch", "content_sha256 does not match the body")
    pdf_declared = str(payload.get("pdf_file_sha256") or "").lower()
    pdf_side = Path(path).parent / "pdf" / f"{announcement_id}.PDF"
    if pdf_side.is_file():
        pdf_actual = hashlib.sha256(pdf_side.read_bytes()).hexdigest()
        if pdf_declared != pdf_actual:
            fail("pdf_hash_mismatch", "pdf_file_sha256 does not match the PDF bytes")
    if body and not _body_has_security(body, security):
        fail("security_not_in_body", "body does not contain the security code")
    company = str(payload.get("secName") or payload.get("company_name") or "")
    if not company:
        fail("company_missing", "company name is missing")
    elif body and company not in body:
        fail("company_not_in_body", "body does not contain the company name")
    if body and period_date is not None and not _body_has_date(body, period_date):
        fail("report_period_not_in_body", "report_period is not in the body")
    publication = payload.get("publication")
    if not isinstance(publication, dict):
        fail("publication_missing", "publication is missing")
        publication = {}
    raw = str(publication.get("raw") or "")
    if raw and not any(token in raw for token in ("公告时间", "announcementTime")):
        fail("publication_raw_unlabelled", "publication raw text is not an 公告时间 or announcementTime label")
    elif any(token in raw for token in ("落款", "截至", "period ended", "period end")):
        fail("publication_raw_not_listing_time", "publication raw text is a board signature or period end")
    kind, published_date, published_at = _publication(str(publication.get("value") or ""))
    if kind == "invalid":
        fail("publication_invalid", "publication value is not a date or timestamp")
    elif kind == "naive":
        fail("publication_naive", "publication timestamp has no timezone")
    board = _date_value(str(payload.get("board_signature_date") or ""))
    period_end = _date_value(str(payload.get("period_end") or ""))
    if period_date is not None and period_end is not None and period_date != period_end:
        fail("report_period_mismatch", "report_period does not match period_end")
    if published_date is not None and board is not None and published_date == board:
        fail("board_signature_used", "board signature date is not the publication time")
    if published_date is not None and period_end is not None and published_date == period_end:
        fail("period_end_used", "period end is not the publication time")
    storage_text = str(payload.get("storageTime_asia_shanghai") or "")
    storage_at = _aware(storage_text) if storage_text else None
    if published_at is not None and storage_at is not None and published_at == storage_at:
        fail("storage_time_used", "storageTime is not the publication time")
    cutoff_code, cutoff = _cutoff(decision_at)
    if cutoff_code == "decision_at_missing":
        fail("decision_at_missing", "decision_at is missing. DATE was not used as the decision cutoff.")
    elif cutoff_code == "decision_at_naive":
        fail("decision_at_naive", "decision_at has no timezone. DATE was not used as the decision cutoff.")
    elif cutoff_code:
        fail("decision_at_invalid", "decision_at is not a timestamp. DATE was not used as the decision cutoff.")
    if reasons or published_date is None or cutoff is None:
        return _view("rejected", reasons, codes)
    midnight = kind == "date" and published_at is not None
    if kind == "timestamp" and published_at is not None:
        if cutoff < published_at:
            return _view(
                "withheld",
                ["official publication time is after the decision cutoff"],
                ["cutoff_before_publication"],
            )
        precision = "timestamp"
        shown = published_at.isoformat()
        session_note = ""
    else:
        if cutoff.date() < published_date:
            return _view(
                "withheld",
                ["decision cutoff is before the date-only publication"],
                ["cutoff_before_publication"],
            )
        if cutoff.date() == published_date:
            return _view(
                "withheld",
                ["date-only publication is not used for a same-day decision"],
                ["date_only_same_day"],
            )
        status, detail = classify_session(cutoff.date())
        if status == "holiday":
            return _view("withheld", [detail], ["holiday"])
        if status == "weekend":
            return _view("withheld", [detail], ["not_trading_session"])
        if status != "open":
            return _view("withheld", [detail], ["calendar_unknown"])
        precision = "date"
        shown = published_date.isoformat()
        session_note = "trading_session: open\n" + coverage_line()
    notice = re.search(r"公告编号\s*[：:]\s*([0-9]{4}-[0-9]{3})", body)
    in_body = announcement_id in body
    lines = [
        "status: admitted",
        f"source: {source}",
        f"source_label: {label}",
        f"platform_announcement_id: {announcement_id}",
        "platform_announcement_id_bound_by: official metadata and pdf_url",
        f"platform_announcement_id_in_pdf_body: {str(in_body).lower()}",
        f"security_code: {security}",
        f"company_name: {company}",
        f"report_period: {period}",
        f"pdf_url: {pdf_url}",
        f"content_sha256: {actual_hash}",
        f"availability: {shown}",
        f"availability_precision: {precision}",
        "storage_time_used: false",
        f"publication_raw: {raw}",
        "latest_discovery_verified: not established by this evidence",
        "coverage: the report period is recorded. Latest disclosure discovery is not proven by this evidence.",
        "body:",
        body.strip(),
    ]
    if notice:
        lines.insert(6, f"issuer_notice_number: {notice.group(1)}")
        lines.insert(7, "issuer_notice_number_is_not_the_platform_id: true")
    if midnight:
        lines.insert(12, "midnight_placeholder: true")
    if session_note:
        lines.insert(13, session_note)
    return _view("admitted", [], [], "\n".join(lines))


def _reason_block(view: ListingView) -> str:
    lines = [f"reason_code: {code}" for code in view.codes]
    lines.extend(view.reasons)
    return "\n".join(lines)


def render_listing(view: ListingView) -> str:
    title = "CNINFO LISTING EVIDENCE"
    if view.status == "admitted":
        return f"\n\n=== {title} ===\n{view.text}\n=== END {title} ===\n"
    if view.status == "absent":
        return (
            f"\n\n=== {title} ===\nstatus: evidence_absent\n"
            + _reason_block(view)
            + "\nlatest_discovery_verified: not established by this evidence\n"
            + f"=== END {title} ===\n"
        )
    return (
        f"\n\n=== {title} ===\nstatus: {view.status}\n"
        + _reason_block(view)
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
