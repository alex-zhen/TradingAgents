"""Fetch public official material for BABA, LI, and 0700.HK.

This file is the acquisition command. It does not read account data, does not
call Reddit or StockTwits, and does not invent an SEC contact email. Set
SEC_EDGAR_USER_AGENT to a name and email you control. If it is unset, requests
identify the program and say that no contact email is configured.

DATE passed by the runner is the price-session date. --decision-at is a
separate timezone-aware timestamp. A filing is eligible only when EDGAR's
acceptance time is at or before that timestamp.

Historical mode performs no HTTP. An unsupported ticker is not covered and
does not raise. A failed fetch is reported and is not replaced with an older
digest.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

ALLOW = {
    "data.sec.gov",
    "efts.sec.gov",
    "www.sec.gov",
    "www.hkexnews.hk",
    "www1.hkexnews.hk",
    "www.tencent.com",
    "static.www.tencent.com",
    "www.alibabagroup.com",
    "data.alibabagroup.com",
    "ali-home-data.oss-cn-hangzhou.aliyuncs.com",
    "ir.lixiang.com",
}
TIMEOUT = 20
RETRIES = 2
FINANCIAL_FORMS = {"6-K", "20-F", "10-K", "10-Q"}
TAG = re.compile(r"(?is)<(script|style).*?>.*?</\1>")
BREAK = re.compile(r"(?i)<br\s*/?>|</p>|</tr>|</h\d>")
STRIP = re.compile(r"(?s)<[^>]+>")
HREF = re.compile(r'(?is)<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>')
logging.getLogger("pypdf").setLevel(logging.ERROR)


def user_agent() -> str:
    configured = os.getenv("SEC_EDGAR_USER_AGENT", "").strip()
    if configured:
        return configured
    return "TradingAgents acquisition (no contact email configured)"


def parse_decision(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("decision-at must include a timezone offset")
    return parsed.astimezone(UTC)


@dataclass
class Fetch:
    url: str
    status: int | None
    body: bytes
    captured_at: str
    error: str = ""

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


@dataclass
class Result:
    ticker: str
    canonical: str | None
    price_date: str
    decision_at: str
    ok: bool
    fetched: bool
    status: str
    markdown: str
    run_dir: Path | None = None
    fetches: list[Fetch] = field(default_factory=list)
    covered: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def target_for(ticker: str) -> str | None:
    key = ticker.strip().upper().replace(" ", "")
    if key == "BABA":
        return "BABA"
    if key == "LI":
        return "LI"
    if key in {"0700", "0700.HK", "00700.HK"}:
        return "0700.HK"
    return None


class Client:
    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.calls: list[str] = []

    def get(self, url: str) -> Fetch:
        host = urlparse(url).hostname or ""
        captured = datetime.now(UTC).isoformat()
        if host not in ALLOW:
            return Fetch(url, None, b"", captured, f"host {host} is not allowlisted")
        headers = {"User-Agent": user_agent(), "Accept": "application/json,text/html,application/pdf"}
        last_error = "no attempt"
        for attempt in range(RETRIES + 1):
            self.calls.append(url)
            try:
                response = self.session.get(url, headers=headers, timeout=TIMEOUT)
            except requests.RequestException as exc:
                last_error = type(exc).__name__
                if attempt < RETRIES:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                return Fetch(url, None, b"", captured, last_error)
            if response.status_code == 403:
                return Fetch(url, 403, response.content, captured, "403")
            if response.status_code in {429, 500, 502, 503, 504} and attempt < RETRIES:
                time.sleep(0.5 * (attempt + 1))
                continue
            if response.status_code != 200:
                return Fetch(url, response.status_code, response.content, captured, f"HTTP {response.status_code}")
            return Fetch(url, response.status_code, response.content, captured)
        return Fetch(url, None, b"", captured, last_error)


def _text(raw: str, limit: int = 3500) -> str:
    cleaned = TAG.sub(" ", raw)
    cleaned = BREAK.sub("\n", cleaned)
    cleaned = html.unescape(STRIP.sub(" ", cleaned))
    lines = [" ".join(line.split()) for line in cleaned.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)[:limit]


def _save(run: Path, fetch: Fetch) -> None:
    raw = run / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    digest = fetch.sha256 or "empty"
    (raw / f"{digest}.bin").write_bytes(fetch.body)
    (raw / f"{digest}.json").write_text(json.dumps({
        "url": fetch.url, "status": fetch.status, "captured_at": fetch.captured_at,
        "sha256": fetch.sha256, "error": fetch.error, "nbytes": len(fetch.body),
    }, indent=2), encoding="utf-8")


def _archive(cik: str, accession: str, name: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{name}"


def _rows(submissions: dict) -> list[dict]:
    recent = submissions["filings"]["recent"]
    count = len(recent["form"])
    rows = []
    for i in range(count):
        rows.append({key: recent[key][i] for key in recent})
    return rows


def _listed(name: str, ticker: str) -> bool:
    symbols = []
    for group in re.findall(r"\(([^)]*)\)", name):
        symbols.extend(part.strip().upper() for part in group.split(","))
    return ticker.upper() in symbols


def _discover_cik(client: Client, ticker: str, query: str, decision: datetime) -> tuple[str | None, Fetch]:
    end = decision.date().isoformat()
    url = (
        "https://efts.sec.gov/LATEST/search-index?q="
        + quote(query)
        + f"&dateRange=custom&startdt=2024-01-01&enddt={end}&forms=6-K"
    )
    fetch = client.get(url)
    if fetch.status != 200:
        return None, fetch
    try:
        hits = json.loads(fetch.body)["hits"]["hits"]
    except (ValueError, KeyError):
        fetch.error = "unreadable search index"
        return None, fetch
    for hit in hits:
        source = hit.get("_source") or {}
        names = source.get("display_names") or []
        if not any(_listed(name, ticker) for name in names):
            continue
        ciks = source.get("ciks") or []
        if ciks:
            return f"{int(ciks[0]):010d}", fetch
    fetch.error = f"search index had no filing whose listed symbol is {ticker}"
    return None, fetch


def _eligible(rows: list[dict], decision: datetime, forms: set[str]) -> list[dict]:
    chosen = []
    for row in rows:
        if row.get("form") not in forms:
            continue
        accepted = row.get("acceptanceDateTime") or ""
        if not accepted:
            continue
        stamp = parse_decision(accepted.replace("Z", "+00:00") if accepted.endswith("Z") else accepted)
        if stamp <= decision:
            row = dict(row)
            row["_accepted"] = stamp
            chosen.append(row)
    chosen.sort(key=lambda row: row["_accepted"], reverse=True)
    return chosen


def _excerpt_from_index(client: Client, cik: str, row: dict) -> tuple[str, str, list[Fetch]]:
    accession = row["accessionNumber"]
    index_url = _archive(cik, accession, f"{accession}-index.html")
    fetches = [client.get(index_url)]
    index = fetches[0]
    if index.status != 200:
        return "", "", fetches
    exhibits = []
    for href, label in HREF.findall(index.body.decode("utf-8", "replace")):
        name = href.rsplit("/", 1)[-1]
        blob = f"{name} {label}".lower()
        if "ex99" in blob or "ex-99" in blob or name.lower().endswith(".htm"):
            exhibits.append(name)
    # Prefer an earnings exhibit over the 6-K cover. Dedup while keeping order.
    ordered = []
    for name in exhibits:
        if name not in ordered:
            ordered.append(name)
    ordered.sort(key=lambda name: (0 if "ex99" in name.lower() or "ex-99" in name.lower() else 1, name))
    excerpt, url = "", ""
    for name in ordered[:3]:
        url = _archive(cik, accession, name)
        fetched = client.get(url)
        fetches.append(fetched)
        if fetched.status != 200:
            continue
        text = _text(fetched.body.decode("utf-8", "replace"))
        if text:
            excerpt = text
            if re.search(r"revenue|results of operations|net income", text, re.I):
                break
    return excerpt, url, fetches


def _facts_excerpt(facts: dict, decision: datetime) -> str:
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    tags = (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "NetIncomeLoss",
        "EarningsPerShareDiluted",
    )
    lines = []
    for tag in tags:
        node = gaap.get(tag)
        if not node:
            continue
        best = None
        for unit, points in (node.get("units") or {}).items():
            for point in points:
                filed = point.get("filed")
                if not filed or filed > decision.date().isoformat():
                    continue
                end = point.get("end") or ""
                if best is None or end > (best.get("end") or "") or (
                    end == (best.get("end") or "") and filed > best["filed"]
                ):
                    best = dict(point)
                    best["unit"] = unit
                    best["tag"] = tag
        if best:
            lines.append(
                f"{tag} {best.get('val')} {best['unit']} period_end={best.get('end')} "
                f"filed={best.get('filed')} form={best.get('form')} accn={best.get('accn')}"
            )
    return "\n".join(lines)


def _issuer_ir(client: Client, ticker: str, decision: datetime):
    if ticker == "BABA":
        return acquire_alibaba_ir(client, decision)
    if ticker == "LI":
        return acquire_li_ir(client, decision)
    return "", [], [], []


def _issuer_after_sec(client, ticker, decision, financial, covered, missing, fetches):
    ir_text, ir_covered, ir_missing, ir_fetches = _issuer_ir(client, ticker, decision)
    fetches = list(fetches) + list(ir_fetches)
    covered = list(covered) + list(ir_covered)
    missing = list(missing) + list(ir_missing)
    if ir_text:
        financial = (financial + "\n" if financial else "") + "issuer_ir_after_sec_403:\n" + ir_text
    return financial, covered, missing, fetches


def acquire_sec(client: Client, ticker: str, decision: datetime) -> tuple[str, list[str], list[str], list[Fetch]]:
    if not _sec_ua_configured():
        note = (
            "sec_skipped: no compliant User-Agent configured; SEC was not queried. "
            "Filing coverage is unknown."
        )
        return _issuer_after_sec(
            client, ticker, decision, note, [], ["sec_skipped_no_user_agent"], [],
        )
    query = "BABA" if ticker == "BABA" else '"Li Auto"'
    cik, search = _discover_cik(client, ticker, query, decision)
    fetches = [search]
    missing, covered = [], []
    if not cik:
        missing.append("sec_cik_discovery")
        return _issuer_after_sec(client, ticker, decision, "", covered, missing, fetches)
    submissions_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    submissions = client.get(submissions_url)
    fetches.append(submissions)
    if submissions.status != 200:
        missing.append("sec_submissions_index")
        return _issuer_after_sec(client, ticker, decision, "", covered, missing, fetches)
    try:
        payload = json.loads(submissions.body)
        rows = _rows(payload)
    except (ValueError, KeyError):
        missing.append("sec_submissions_index")
        return "", covered, missing, fetches
    covered.append("sec_submissions_index")
    parts_name = payload.get("name") or payload.get("entityName") or ""
    tickers = [str(item).upper() for item in (payload.get("tickers") or [])]
    if ticker not in tickers:
        missing.append("sec_ticker_mismatch")
        return f"CIK {cik} submissions tickers {tickers} do not include {ticker}.", covered, missing, fetches
    financial = _eligible(rows, decision, FINANCIAL_FORMS)
    recent_cut = decision.timestamp() - 48 * 3600
    recent = [row for row in financial if row["_accepted"].timestamp() >= recent_cut]
    parts = [f"entity: {parts_name}", f"CIK: {cik}", f"submissions_index: {submissions_url}"]
    if not financial:
        missing.append("financial_filing")
    else:
        excerpt, url, row = "", "", None
        blocked = False
        for candidate in financial[:12]:
            text, doc_url, extra = _excerpt_from_index(client, cik, candidate)
            fetches.extend(extra)
            if any(item.status == 403 for item in extra):
                blocked = True
                break
            if text and re.search(r"revenue|net income|results of operations", text, re.I):
                excerpt, url, row = text, doc_url, candidate
                break
            if row is None and text:
                excerpt, url, row = text, doc_url, candidate
        if blocked:
            missing.append("sec_archive_403")
            ir_text, ir_covered, ir_missing, ir_fetches = _issuer_ir(client, ticker, decision)
            fetches.extend(ir_fetches)
            covered.extend(ir_covered)
            missing.extend(ir_missing)
            if ir_text:
                parts.append("issuer_ir_after_sec_403:\n" + ir_text)
            unread = financial[0]
            parts.append(
                "sec_filing: archive returned 403 before a filing document was read\n"
                "newest_unread_form: " + str(unread.get("form"))
                + "\nnewest_unread_acceptance: " + str(unread.get("acceptanceDateTime") or "")
                + "\nnote: an unread submissions row is not a press-release dateline and is not a confirmed results filing"
            )
            missing.append("financial_excerpt")
        else:
            row = row or financial[0]
            parts.append(
                "form: " + str(row.get("form"))
                + "\nsec_acceptance: " + row.get("acceptanceDateTime", "")
                + "\nsec_report_period_end: " + str(row.get("reportDate") or "")
                + "\naccession: " + row.get("accessionNumber", "")
                + "\nsource_url: " + url
            )
            if excerpt and quality_gate(excerpt)[0]:
                covered.append("financial_excerpt")
                parts.extend(evidence_lines(excerpt))
            elif excerpt and re.search(r"revenue|net income|results of operations", excerpt, re.I):
                missing.append("financial_excerpt")
                parts.extend(evidence_lines(excerpt))
            else:
                missing.append("financial_excerpt")
                if excerpt:
                    parts.append("non_earnings_filing_text:\n" + excerpt)
    if recent:
        covered.append("recent_official_filings")
        parts.append("recent_filings_within_48h:")
        for row in recent[:8]:
            parts.append(
                f"- {row.get('form')} accepted {row.get('acceptanceDateTime')} "
                f"{row.get('accessionNumber')} {row.get('primaryDocDescription') or row.get('primaryDocument')}"
            )
    else:
        missing.append("recent_48h_filings")
        parts.append("recent_filings_within_48h: none accepted in the 48 hours before decision_at")
    facts = client.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    fetches.append(facts)
    if facts.status == 200:
        try:
            fact_text = _facts_excerpt(json.loads(facts.body), decision)
        except ValueError:
            fact_text = ""
        if fact_text:
            covered.append("companyfacts")
            parts.append("companyfacts filed by decision_at:\n" + fact_text)
        else:
            missing.append("companyfacts")
    else:
        missing.append("companyfacts")
    parts.append(
        "earnings_schedule: FUTURE_NOT_REPORTED. EDGAR lists filings already accepted, not a future earnings date."
    )
    missing.append("future_earnings_date")
    return "\n".join(parts), covered, missing, fetches


PERIOD = re.compile(
    r"(?:quarter|six months|three months|year|period) ended "
    r"(?:[A-Z][a-z]+ \d{1,2}, 20\d{2}|\d{1,2} [A-Z][a-z]+ 20\d{2})",
    re.I,
)
AMOUNT = re.compile(
    r"(?:RMB|CNY|HKD|HK\$|US\$|USD)\s*[0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?"
    r"|[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?\s*(?:million|billion)",
    re.I,
)
STATEMENT = re.compile(
    r"revenue|income from operations|net income|operating activities|free cash flow",
    re.I,
)


def quality_gate(text: str) -> tuple[bool, list[str]]:
    """Issuer, period, currency, and an income or cash-flow amount. A disclaimer fails."""
    issuer = bool(re.search(r"Alibaba Group|Li Auto|Tencent Holdings|Tencent Announces", text, re.I))
    period = PERIOD.search(text)
    currency = bool(AMOUNT.search(text))
    lines = []
    for line in text.splitlines():
        compact = " ".join(line.split())
        if STATEMENT.search(compact) and AMOUNT.search(compact):
            lines.append(compact)
    return bool(issuer and period and currency and lines), lines[:12]


def evidence_lines(text: str) -> list[str]:
    ok, lines = quality_gate(text)
    notes = []
    issuer = re.search(r"Alibaba Group|Li Auto|Tencent Holdings|Tencent Announces", text, re.I)
    period = PERIOD.search(text)
    if issuer:
        notes.append("issuer: " + issuer.group(0))
    if period:
        notes.append("report_period: " + period.group(0))
    notes.append("useful_lines:\n" + ("\n".join(lines) if lines else "none"))
    notes.append("content_gate: " + ("passed" if ok else "failed"))
    return notes


def _us_date(text: str):
    try:
        return datetime.strptime(text, "%B %d, %Y").date()
    except ValueError:
        return None


def _stated_date(text: str):
    """A release dateline. A period end such as '30 June 2026' is not a dateline."""
    patterns = (
        (r"Hong Kong(?:,\s*[A-Za-z]+)*,\s*([A-Z][a-z]+ \d{1,2}, 20\d{2})", "%B %d, %Y"),
        (r"Hong Kong,\s*(\d{1,2} [A-Z][a-z]+ 20\d{2})", "%d %B %Y"),
    )
    for pattern, fmt in patterns:
        dateline = re.search(pattern, text)
        if not dateline:
            continue
        try:
            return datetime.strptime(dateline.group(1), fmt).date(), dateline.group(1)
        except ValueError:
            continue
    for match in re.finditer(r"([A-Z][a-z]+ \d{1,2}, 20\d{2})", text[:800]):
        parsed = _us_date(match.group(1))
        if parsed:
            return parsed, match.group(1)
    return None, ""


def _alibaba_cards(page: str) -> list[dict]:
    """Quarterly cards. Card date, event date, and press-release id stay separate."""
    cards = []
    for match in re.finditer(r'"documentTitle":"((?:September|June|March|December) Quarter[^"]*Results)"', page):
        before = page[max(0, match.start() - 900):match.start()]
        after = page[match.end():match.end() + 1800]
        nxt = re.search(r'"documentTitle":', after)
        if nxt:
            after = after[:nxt.start()]
        events = re.findall(r'"eventDateLocal":"([^"]*)"', before)
        published = re.findall(r'"documentPublishTimeLocal":"([^"]*)"', before)
        press = re.search(r'"pressRelease":"(\d+)"', after)
        presentation = re.search(r'"presentationUrl":"(https:[^"]+)"', after)
        cards.append({
            "title": match.group(1),
            "event_date": events[-1] if events else "",
            "card_date": published[-1] if published else "",
            "press_release_id": press.group(1) if press else "",
            "presentation_url": presentation.group(1) if presentation else "",
        })
    return cards


def acquire_alibaba_ir(client: Client, decision: datetime) -> tuple[str, list[str], list[str], list[Fetch]]:
    cards_url = "https://www.alibabagroup.com/en-US/ir-financial-reports-quarterly-results"
    news_url = "https://www.alibabagroup.com/en-US/ir-news-filings"
    cards = client.get(cards_url)
    news = client.get(news_url)
    fetches = [cards, news]
    if cards.status == 403:
        return "issuer_ir: 403 on Alibaba results listing, not retried", [], ["issuer_ir_403"], fetches
    if cards.status != 200:
        return "issuer_ir: Alibaba listing was not readable", [], ["issuer_ir_listing"], fetches
    card_html = cards.body.decode("utf-8", "replace")
    found = _alibaba_cards(card_html)
    lines = [
        f"results_listing: {cards_url}",
        "date_fields: results_card_date, event_date, publication_dateline, and sec_acceptance are separate",
    ]
    if news.status == 200:
        lines.append(f"news_listing: {news_url}")
        for title in re.findall(r'"documentTitle":"([^"]*Will Announce[^"]*)"', news.body.decode("utf-8", "replace")):
            lines.append("news_title: " + title)
    elif news.status == 403:
        lines.append(f"news_listing: 403 {news_url} not retried")
    else:
        lines.append(f"news_listing: HTTP {news.status}")
    conflicts = []
    eligible = []
    for card in found:
        event = _us_date(card["event_date"]) if card["event_date"] else None
        has_file = bool(card["press_release_id"] or card["presentation_url"])
        lines.append(
            f"card: {card['title']}\n"
            f"results_card_date: {card['card_date'] or 'not stated'}\n"
            f"event_date: {card['event_date'] or 'not stated'}\n"
            f"press_release_id: {card['press_release_id'] or 'none'}"
        )
        if card["presentation_url"]:
            lines.append(f"presentation_not_selected: {card['presentation_url']}")
        if event and event > decision.date():
            lines.append(
                f"FUTURE_NOT_REPORTED: {card['title']} event_date {card['event_date']} "
                "is after decision_at. A card with no file is not a report."
            )
            continue
        if not has_file:
            conflicts.append(
                f"conflict: {card['title']} card date {card['card_date']} has no file and no later "
                "issuer schedule was on the card; unverified, not a report"
            )
            continue
        if card["press_release_id"] and event and event <= decision.date():
            eligible.append((event, card))
    for item in conflicts:
        lines.append(item)
    covered = ["issuer_ir_listing"]
    missing = list(conflicts)
    if not eligible:
        missing.append("issuer_ir_excerpt")
        return "\n".join(lines), covered, missing, fetches
    _event, chosen = max(eligible, key=lambda item: item[0])
    doc_url = f"https://www.alibabagroup.com/en-US/document-{chosen['press_release_id']}"
    page = client.get(doc_url)
    fetches.append(page)
    lines.append(
        f"selected_title: {chosen['title']}\n"
        f"results_card_date: {chosen['card_date']}\n"
        f"event_date: {chosen['event_date']}\n"
        f"document_page: {doc_url}"
    )
    if page.status != 200:
        missing.append("issuer_ir_document")
        lines.append("press_release_pdf: document page not fetched; presentation deck was not substituted")
        return "\n".join(lines), covered, missing, fetches
    html_text = page.body.decode("utf-8", "replace")
    pdfs = re.findall(r'href="(https://data\.alibabagroup\.com/[^"]+\.pdf)"', html_text)
    if not pdfs:
        missing.append("issuer_ir_excerpt")
        lines.append("press_release_pdf: not linked on the document page; presentation deck was not substituted")
        return "\n".join(lines), covered, missing, fetches
    pdf_url = pdfs[0]
    pdf = client.get(pdf_url)
    fetches.append(pdf)
    lines.append(f"source_url: {pdf_url}")
    if pdf.status == 403:
        missing.append("issuer_ir_pdf_403")
        lines.append("pdf: 403 not retried")
        return "\n".join(lines), covered, missing, fetches
    if pdf.status != 200:
        missing.append("issuer_ir_pdf")
        return "\n".join(lines), covered, missing, fetches
    full = _pdf_parts(pdf.body)[1]
    _when, printed = _stated_date(full)
    lines.append("publication_dateline: " + (printed or "not stated in the press-release text"))
    if printed and chosen["card_date"] and printed != chosen["card_date"]:
        lines.append(
            "date_note: results_card_date and publication_dateline differ. "
            "The dateline is the document date. The card date is not the publication date."
        )
    if printed and chosen["event_date"] and printed != chosen["event_date"]:
        lines.append("date_note: event_date and publication_dateline differ; both are kept.")
    lines.extend(evidence_lines(full))
    if quality_gate(full)[0]:
        covered.append("issuer_ir_excerpt")
    else:
        missing.append("issuer_ir_excerpt")
    return "\n".join(lines), covered, missing, fetches


def _same_origin(page_url: str, href: str) -> str | None:
    if href.startswith("//"):
        return None
    if href.startswith("/"):
        host = urlparse(page_url).hostname or ""
        return f"https://{host}{href.split('#')[0]}"
    parsed = urlparse(href)
    if parsed.hostname and parsed.hostname == urlparse(page_url).hostname and parsed.scheme in {"http", "https"}:
        return href.split("#")[0]
    return None


def acquire_li_ir(client: Client, decision: datetime) -> tuple[str, list[str], list[str], list[Fetch]]:
    """Homepage plus at most six same-origin results/news pages. HTML is accepted."""
    page_url = "https://ir.lixiang.com/"
    page = client.get(page_url)
    if page.status == 403:
        return f"issuer_ir: 403 {page_url} not retried", [], ["issuer_ir_403"], [page]
    if page.status != 200:
        return f"issuer_ir: HTTP {page.status} {page_url}", [], ["issuer_ir_listing"], [page]
    html_text = page.body.decode("utf-8", "replace")
    links = []
    for href, label in HREF.findall(html_text):
        blob = f"{href} {label}".lower()
        if not re.search(r"result|earning|press|news|financial|announce", blob):
            continue
        absolute = _same_origin(page_url, href)
        if absolute and absolute not in links and absolute != page_url:
            links.append(absolute)
        if len(links) >= 6:
            break
    fetches = [page]
    lines = [f"listing: {page_url}", f"same_origin_links: {len(links)}", "discovery: homepage links fetched this run, HTML allowed"]
    covered, missing = ["issuer_ir_listing"], []
    if not links:
        missing.append("issuer_ir_documents")
        lines.append("No results or news links on the homepage.")
        return "\n".join(lines), covered, missing, fetches
    validated = False
    for link in links:
        fetched = client.get(link)
        fetches.append(fetched)
        if fetched.status == 403:
            missing.append("issuer_ir_403")
            lines.append(f"403 not retried: {link}")
            break
        if fetched.status != 200:
            continue
        body = fetched.body
        text = _pdf_parts(body)[1] if body[:4] == b"%PDF" else _text(body.decode("utf-8", "replace"), 20000)
        ok, _useful = quality_gate(text)
        dateline = _stated_date(text)
        lines.append(f"source_url: {link}")
        lines.append("publication_dateline: " + (dateline[1] or "not stated"))
        lines.extend(evidence_lines(text))
        if ok and dateline[0] and dateline[0] <= decision.date():
            covered.append("issuer_ir_excerpt")
            validated = True
            break
    if not validated:
        missing.append("issuer_ir_excerpt")
    return "\n".join(lines), covered, missing, fetches


def _pdf_text(body: bytes) -> str:
    excerpt, _haystack = _pdf_parts(body)
    return excerpt


def _pdf_parts(body: bytes) -> tuple[str, str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return "", ""
    import io
    try:
        reader = PdfReader(io.BytesIO(body))
    except Exception:
        return "", ""
    pages = []
    for index, page in enumerate(reader.pages):
        if index >= 40:
            break
        pages.append(page.extract_text() or "")
    full = "\n".join(pages)
    return full, full


def _tencent_documents(page: str, source: str) -> list[dict]:
    found = []
    seen = set()
    for match in re.finditer(r'href="(https://[^"]+\.pdf)"[^>]*>(.*?)</a>', page, re.I | re.S):
        url = match.group(1)
        label = " ".join(re.sub(r"<[^>]+>", " ", match.group(2)).split())
        pre = page[max(0, match.start() - 700):match.start()]
        heads = re.findall(r"<h2[^>]*>(.*?)</h2>", pre, re.I | re.S)
        title = " ".join(re.sub(r"<[^>]+>", " ", heads[-1]).split()) if heads else label
        if re.fullmatch(r"20\d{2}", title or ""):
            title = label or title
        if url in seen:
            continue
        blob = f"{title} {label}".lower()
        if source == "results" and "announces" in blob and "results" in blob:
            kind = "results_announcement"
        elif source == "financial_reports" and ("interim report" in blob or "annual report" in blob):
            kind = "periodic_report"
        else:
            continue
        seen.add(url)
        found.append({"url": url, "title": title or label, "kind": kind})
    return found


def acquire_hkex(client: Client, decision: datetime) -> tuple[str, list[str], list[Fetch]]:
    prefix_url = "https://www.hkexnews.hk/search/prefix.do?callback=cb&lang=EN&type=A&name=00700&market=SEHK"
    prefix = client.get(prefix_url)
    if prefix.status != 200:
        return "hkex_filing: unknown", ["hkex_filing_unknown"], [prefix]
    raw = prefix.body.decode("utf-8", "replace")
    matched = None
    for stock in re.finditer(r'"stockId":(\d+)', raw):
        window = raw[max(0, stock.start() - 120):stock.end() + 120]
        if '"code":"00700"' in window:
            matched = stock
            break
    if not matched:
        return "hkex_filing: unknown", ["hkex_filing_unknown"], [prefix]
    end = decision.strftime("%Y%m%d")
    url = (
        "https://www1.hkexnews.hk/search/titleSearchServlet.do?sortDir=0&sortByOptions=DateTime"
        f"&category=0&market=SEHK&stockId={matched.group(1)}&documentType=-1&fromDate=20260101&toDate={end}"
        "&title=&searchType=0&t1code=-2&t2Gcode=-2&t2code=-2&rowRange=100&lang=E"
    )
    listing = client.get(url)
    fetches = [prefix, listing]
    if listing.status != 200:
        return "hkex_filing: unknown", ["hkex_filing_unknown"], fetches
    try:
        payload = json.loads(listing.body.decode("utf-8"))
        result = payload["result"]
        rows = json.loads(result) if isinstance(result, str) else result
    except (ValueError, KeyError, TypeError):
        return "hkex_filing: unknown", ["hkex_filing_unknown"], fetches
    lines = ["hkex_listing: title search for 00700 fetched this run", "hkex_listing_datetime is not a press-release dateline"]
    kept = 0
    for row in rows:
        title = html.unescape(re.sub(r"<[^>]+>", " ", row.get("TITLE") or ""))
        if not re.search(r"interim report|results for the three|announce", title, re.I):
            continue
        lines.append(
            f"hkex_title: {' '.join(title.split())}\n"
            f"hkex_listing_datetime: {row.get('DATE_TIME')}\n"
            f"hkex_file: {row.get('FILE_LINK')}"
        )
        kept += 1
        if kept >= 4:
            break
    if kept == 0:
        return "hkex_filing: unknown", ["hkex_filing_unknown"], fetches
    return "\n".join(lines), [], fetches


def acquire_tencent(client: Client, decision: datetime) -> tuple[str, list[str], list[str], list[Fetch]]:
    page_url = "https://www.tencent.com/investors/results/"
    page = client.get(page_url)
    fetches = [page]
    missing, covered = [], []
    if page.status != 200:
        missing.append("tencent_ir_results")
        return "", covered, missing, fetches
    covered.append("tencent_ir_results_page")
    html_text = page.body.decode("utf-8", "replace")
    reports = client.get("https://www.tencent.com/investors/financial-reports/")
    fetches.append(reports)
    documents = _tencent_documents(html_text, "results")
    if reports.status == 200:
        covered.append("tencent_financial_reports_page")
        documents.extend(_tencent_documents(reports.body.decode("utf-8", "replace"), "financial_reports"))
    else:
        missing.append("tencent_financial_reports")
    # One announcement and one periodic report, in the order each listing returned them.
    selected = []
    for kind in ("results_announcement", "periodic_report"):
        for doc in documents:
            if doc["kind"] == kind:
                selected.append(doc)
                break
    if not selected:
        missing.append("tencent_results_pdf")
        return f"results_page: {page_url}\nNo results or periodic-report PDF in the fetched listings.", covered, missing, fetches
    described = []
    for doc in selected:
        pdf = client.get(doc["url"])
        fetches.append(pdf)
        excerpt, haystack = _pdf_parts(pdf.body) if pdf.status == 200 else ("", "")
        published, printed = _stated_date(haystack) if haystack else (None, "")
        ok, useful = quality_gate(haystack) if haystack else (False, [])
        described.append({
            **doc, "text": excerpt, "haystack": haystack, "published": published, "printed": printed,
            "status": pdf.status, "useful": useful, "ok": ok,
        })
    dated = [doc for doc in described if doc["published"] and doc["published"] <= decision.date()]
    later = [doc for doc in described if doc["published"] and doc["published"] > decision.date()]
    latest = None
    if dated:
        top = max(doc["published"] for doc in dated)
        winners = [doc for doc in dated if doc["published"] == top]
        latest = winners[0] if len(winners) == 1 else None
    parts = [
        f"results_page: {page_url}",
        "financial_reports_page: https://www.tencent.com/investors/financial-reports/",
        "discovery: documents taken from the listings fetched this run, not from a stored filename",
        "later_than_decision: " + (", ".join(doc["title"] for doc in later) or "none"),
        "dateline_order: " + (
            latest["title"] if latest else "datelines do not identify a single later document"
        ),
        "effective_publication: not taken from a dateline alone; hkex_listing_datetime is a separate field",
        "currency: excerpts are quoted from the PDFs; this collector does not convert units",
    ]
    for doc in described:
        mark = " later_dateline" if latest and doc["url"] == latest["url"] else ""
        parts.append(
            f"document: {doc['title']}\nkind: {doc['kind']}{mark}\nsource_url: {doc['url']}\n"
            f"publication_dateline: {doc['printed'] or 'not stated in the extracted pages'}\n"
            "note: a dateline is not an HKEX filing time\n"
            f"http_status: {doc['status']}"
        )
        if doc["status"] == 200 and doc.get("haystack"):
            parts.extend(evidence_lines(doc["haystack"]))
        elif doc["status"] == 403:
            missing.append("tencent_pdf_403")
            parts.append("useful_lines: 403 not retried")
        else:
            missing.append("tencent_pdf_text")
    if any(doc["ok"] for doc in described):
        covered.append("tencent_results_excerpt")
    else:
        missing.append("tencent_results_pdf")
    # Recent IR news is a separate section. Dates are recorded only when the page states them.
    news = client.get("https://www.tencent.com/investors/investor-news/")
    fetches.append(news)
    if news.status != 200:
        missing.append("tencent_recent_news")
    else:
        covered.append("tencent_investor_news_page")
        dates = re.findall(r"20\d{2}-\d{2}-\d{2}", news.body.decode("utf-8", "replace"))
        start = (decision.timestamp() - 48 * 3600)
        fresh = []
        for stamp in dict.fromkeys(dates):
            try:
                moment = datetime.fromisoformat(stamp + "T00:00:00+00:00")
            except ValueError:
                continue
            if start <= moment.timestamp() <= decision.timestamp():
                fresh.append(stamp)
        if fresh:
            covered.append("recent_48h_news")
            parts.append("investor_news dates within 48h: " + ", ".join(fresh))
        else:
            missing.append("recent_48h_news")
            parts.append("investor_news: page fetched; no YYYY-MM-DD in the 48 hours before decision_at was found")
    hkex_text, hkex_missing, hkex_fetches = acquire_hkex(client, decision)
    fetches.extend(hkex_fetches)
    parts.append(hkex_text)
    if hkex_missing:
        missing.extend(hkex_missing)
    else:
        covered.append("hkex_listing")
    return "\n".join(parts), covered, missing, fetches


def _markdown(result_bits: dict) -> str:
    lines = [
        "# Official material",
        f"ticker: {result_bits['ticker']}",
        f"price_session_date: {result_bits['price_date']}",
        f"decision_at: {result_bits['decision_at']}",
        f"fetch_succeeded: {str(result_bits['fetch_succeeded']).lower()}",
        f"content_validated: {str(result_bits['content_validated']).lower()}",
        f"latest_discovery_verified: {str(result_bits['latest_discovery_verified']).lower()}",
        f"install_allowed: {str(result_bits['install_allowed']).lower()}",
        "This file is collector output for the price-session filename the runner opens.",
        "decision_at is not the price-session date.",
        "",
        "## Financial report",
        result_bits["financial"] or "MISSING",
        "",
        "## Coverage",
        "covered: " + (", ".join(result_bits["covered"]) or "none"),
        "missing: " + (", ".join(result_bits["missing"]) or "none"),
        "",
        "## Options and social",
        result_bits["operator"],
    ]
    return "\n".join(lines).rstrip() + "\n"


def _sec_ua_configured() -> bool:
    """A configured contact string. This does not invent an email."""
    return "@" in os.getenv("SEC_EDGAR_USER_AGENT", "")


def _newer_unread_filing(financial: str) -> str:
    if "sec_skipped:" in financial:
        return "conflict: SEC was not queried; filing coverage is unknown"
    if "sec_filing: archive returned 403" not in financial and "sec_archive_403" not in financial:
        return ""
    unread = re.search(r"newest_unread_acceptance: (\d{4}-\d{2}-\d{2})", financial)
    if unread:
        return (
            "conflict: SEC filing text was not read; newest unread acceptance "
            f"{unread.group(1)}; filing coverage is unresolved"
        )
    return "conflict: SEC archive was not read; filing coverage is unresolved"


def acquire(
    ticker: str,
    price_date: str,
    decision_at: str,
    mode: str,
    root: Path,
    session: requests.Session | None = None,
    operator_feed: Path | None = None,
) -> Result:
    decision = parse_decision(decision_at)
    datetime.strptime(price_date, "%Y-%m-%d")
    canonical = target_for(ticker)
    run = root / "acquisitions" / f"{ticker}_{price_date}_{uuid.uuid4().hex[:8]}"
    run.mkdir(parents=True)
    operator = "operator_feed: not provided. This collector did not fetch options or social posts."
    if operator_feed is not None:
        operator = (
            "operator_feed: supplied by the parent, not fetched by this collector.\n"
            f"path: {operator_feed}\n"
            + operator_feed.read_text(encoding="utf-8")
        )
    if canonical is None:
        text = _markdown({
            "ticker": ticker, "price_date": price_date, "decision_at": decision.isoformat(),
            "fetch_succeeded": False, "content_validated": False, "latest_discovery_verified": False,
            "install_allowed": False, "financial": f"NOT_COVERED: {ticker} has no acquisition source in this pilot.",
            "covered": [], "missing": ["acquisition"], "operator": operator,
        })
        _finish(run, ticker, price_date, decision, False, "not_covered", text, [])
        return Result(ticker, None, price_date, decision.isoformat(), False, False, "not_covered", text, run)
    if mode == "historical":
        text = _markdown({
            "ticker": ticker, "price_date": price_date, "decision_at": decision.isoformat(),
            "fetch_succeeded": False, "content_validated": False, "latest_discovery_verified": False,
            "install_allowed": False,
            "financial": "MISSING: historical mode does not fetch and does not open an older digest.",
            "covered": [], "missing": ["historical_no_fetch"], "operator": operator,
        })
        _finish(run, ticker, price_date, decision, False, "historical_no_fetch", text, [])
        return Result(ticker, canonical, price_date, decision.isoformat(), False, False, "historical_no_fetch", text, run)
    client = Client(session)
    if canonical == "0700.HK":
        financial, covered, missing, fetches = acquire_tencent(client, decision)
    else:
        financial, covered, missing, fetches = acquire_sec(client, canonical, decision)
    for fetch in fetches:
        _save(run, fetch)
    _write_extracts(run, fetches)
    if "FUTURE_NOT_REPORTED" in financial:
        missing = [item for item in missing if item != "future_earnings_date"]
    newer = _newer_unread_filing(financial)
    if newer:
        missing.append(newer)
        financial = financial + "\n" + newer
    conflicts = [item for item in missing if str(item).startswith("conflict:")]
    content_validated, _lines = quality_gate(financial)
    fetch_succeeded = any(item.status == 200 and len(item.body) > 200 for item in fetches)
    sec_unknown = any(
        item in missing
        for item in (
            "sec_skipped_no_user_agent",
            "sec_archive_403",
            "sec_cik_discovery",
            "sec_submissions_index",
        )
    )
    unresolved = bool(conflicts) or "hkex_filing_unknown" in missing or "issuer_ir_403" in missing or sec_unknown
    latest_ok = content_validated and not unresolved
    text = _markdown({
        "ticker": ticker, "price_date": price_date, "decision_at": decision.isoformat(),
        "fetch_succeeded": fetch_succeeded,
        "content_validated": content_validated,
        "latest_discovery_verified": latest_ok,
        "install_allowed": latest_ok,
        "financial": financial, "covered": covered, "missing": missing,
        "operator": operator,
    })
    status = "validated" if latest_ok else "partial_or_failed"
    fetched = latest_ok
    digest_name = f"sentiment_digest_{ticker}_{price_date}.md"
    (run / digest_name).write_text(text, encoding="utf-8")
    _finish(
        run, ticker, price_date, decision, fetched, status, text, fetches, covered, missing,
        fetch_succeeded=fetch_succeeded, content_validated=content_validated,
        latest_discovery_verified=latest_ok,
    )
    return Result(ticker, canonical, price_date, decision.isoformat(), fetched, fetched, status, text, run, fetches, covered, missing)


def _write_extracts(run: Path, fetches: list[Fetch]) -> None:
    chunks = []
    for item in fetches:
        if not item.body.startswith(b"%PDF-"):
            continue
        _excerpt, full = _pdf_parts(item.body)
        if full.strip():
            chunks.append(f"SOURCE {item.url}\n{full}")
    if chunks:
        (run / "extracted_full.txt").write_text("\n\n".join(chunks), encoding="utf-8")


def _finish(
    run, ticker, price_date, decision, fetched, status, text, fetches, covered=None, missing=None,
    fetch_succeeded=False, content_validated=False, latest_discovery_verified=False,
):
    manifest = {
        "ticker": ticker,
        "price_session_date": price_date,
        "decision_at": decision.isoformat(),
        "fetch_succeeded": fetch_succeeded,
        "content_validated": content_validated,
        "latest_discovery_verified": latest_discovery_verified,
        "install_allowed": fetched,
        "status": status,
        "covered": covered or [],
        "missing": missing or [],
        "sources": [
            {"url": item.url, "status": item.status, "sha256": item.sha256, "captured_at": item.captured_at, "error": item.error}
            for item in fetches
        ],
    }
    (run / "audit_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    digest = run / f"sentiment_digest_{ticker}_{price_date}.md"
    if not digest.exists():
        digest.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Acquire public official material for BABA, LI, or 0700.HK.")
    parser.add_argument("ticker")
    parser.add_argument("--price-date", required=True, help="YYYY-MM-DD price-session date used in the digest filename")
    parser.add_argument("--decision-at", required=True, help="Timezone-aware decision timestamp")
    parser.add_argument("--mode", choices=("current", "historical"), default="current")
    parser.add_argument("--root", type=Path, default=Path("/workspace/tradingagents-runs"))
    parser.add_argument("--operator-feed", type=Path)
    args = parser.parse_args(argv)
    result = acquire(
        args.ticker, args.price_date, args.decision_at, args.mode, args.root, operator_feed=args.operator_feed,
    )
    print(result.run_dir)
    print(result.status)
    return 0 if result.status in {"validated", "not_covered", "historical_no_fetch"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
