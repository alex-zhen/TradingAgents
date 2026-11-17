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


def acquire_sec(client: Client, ticker: str, decision: datetime) -> tuple[str, list[str], list[str], list[Fetch]]:
    query = "BABA" if ticker == "BABA" else '"Li Auto"'
    cik, search = _discover_cik(client, ticker, query, decision)
    fetches = [search]
    missing, covered = [], []
    if not cik:
        missing.append("sec_cik_discovery")
        return "", covered, missing, fetches
    submissions_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    submissions = client.get(submissions_url)
    fetches.append(submissions)
    if submissions.status != 200:
        missing.append("sec_submissions_index")
        return "", covered, missing, fetches
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
            ir_text, ir_covered, ir_missing, ir_fetches = (
                acquire_alibaba_ir(client, decision) if ticker == "BABA" else acquire_li_ir(client, decision)
            )
            fetches.extend(ir_fetches)
            covered.extend(ir_covered)
            missing.extend(ir_missing)
            if ir_text:
                parts.append("issuer_ir_after_sec_403:\n" + ir_text)
        row = row or financial[0]
        parts.append(
            "form: " + str(row.get("form"))
            + "\naccepted: " + row.get("acceptanceDateTime", "")
            + "\nreport_date: " + str(row.get("reportDate") or "")
            + "\naccession: " + row.get("accessionNumber", "")
            + "\nsource_url: " + url
        )
        if excerpt and re.search(r"revenue|net income|results of operations", excerpt, re.I):
            covered.append("financial_excerpt")
            parts.append("excerpt:\n" + excerpt)
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


def _us_date(text: str):
    try:
        return datetime.strptime(text, "%B %d, %Y").date()
    except ValueError:
        return None


def _stated_date(text: str):
    """A release dateline, not a period-end such as '30 June 2026'."""
    dateline = re.search(r"Hong Kong,\s*(\d{1,2}\s+[A-Z][a-z]+\s+20\d{2})", text)
    if dateline:
        try:
            parsed = datetime.strptime(dateline.group(1), "%d %B %Y").date()
        except ValueError:
            parsed = None
        if parsed:
            return parsed, dateline.group(1)
    for match in re.finditer(r"([A-Z][a-z]+ \d{1,2}, 20\d{2})", text):
        parsed = _us_date(match.group(1))
        if parsed:
            return parsed, match.group(1)
    return None, ""


def _alibaba_documents(page: str) -> list[dict]:
    documents = []
    for part in page.split('"documentPublishTimeLocal":"')[1:]:
        published = part.split('"', 1)[0]
        chunk = part.split('"documentPublishTimeLocal":"', 1)[0]
        title_match = re.search(r'"documentTitle":"([^"]+)"', chunk)
        if not title_match:
            continue
        urls = []
        for url in re.findall(
            r"https://(?:data\.alibabagroup\.com|ali-home-data\.oss-cn-hangzhou\.aliyuncs\.com)/[^\"\\ ]+\.pdf",
            chunk,
        ):
            if url not in urls:
                urls.append(url)
        documents.append({
            "published": published,
            "date": _us_date(published),
            "title": title_match.group(1),
            "urls": urls,
        })
    return documents


def _choose_pdf(urls: list[str]) -> str:
    return sorted(urls, key=lambda url: (0 if url.lower().endswith("results.pdf") else 1, url))[0]


def acquire_alibaba_ir(client: Client, decision: datetime) -> tuple[str, list[str], list[str], list[Fetch]]:
    page_url = "https://www.alibabagroup.com/en-US/ir-financial-reports-quarterly-results"
    page = client.get(page_url)
    fetches = [page]
    if page.status == 403:
        return f"issuer_ir: 403 {page_url} not retried", [], ["issuer_ir_403"], fetches
    if page.status != 200:
        return f"issuer_ir: HTTP {page.status} {page_url}", [], ["issuer_ir_listing"], fetches
    html_text = page.body.decode("utf-8", "replace")
    documents = _alibaba_documents(html_text)
    if not documents:
        return f"listing: {page_url}\nNo dated results records in the page.", ["issuer_ir_listing"], ["issuer_ir_documents"], fetches
    eligible = [doc for doc in documents if doc["date"] and doc["date"] <= decision.date() and doc["urls"]]
    undated_or_empty = [doc for doc in documents if doc["date"] and doc["date"] <= decision.date() and not doc["urls"]]
    future = [doc for doc in documents if doc["date"] and doc["date"] > decision.date()]
    lines = [f"listing: {page_url}", "discovery: records parsed from the IR page fetched this run"]
    for doc in undated_or_empty:
        lines.append(f"no_file: {doc['title']} published {doc['published']}")
    for doc in future:
        lines.append(f"FUTURE_NOT_REPORTED: {doc['title']} dated {doc['published']}")
    if not eligible:
        return "\n".join(lines), ["issuer_ir_listing"], ["issuer_ir_excerpt"], fetches
    chosen = max(eligible, key=lambda doc: doc["date"])
    url = _choose_pdf(chosen["urls"])
    pdf = client.get(url)
    fetches.append(pdf)
    lines.append(
        f"title: {chosen['title']}\npublished: {chosen['published']}\nsource_url: {url}\n"
        "identity: issuer results document selected as the latest listing entry with a file "
        "on or before decision_at"
    )
    covered = ["issuer_ir_listing"]
    missing = []
    if pdf.status == 403:
        missing.append("issuer_ir_pdf_403")
        lines.append("pdf: 403 not retried")
    elif pdf.status == 200:
        text = _pdf_text(pdf.body)
        if text:
            covered.append("issuer_ir_excerpt")
            lines.append("excerpt:\n" + text)
        else:
            missing.append("issuer_ir_pdf_text")
    else:
        missing.append("issuer_ir_pdf")
    return "\n".join(lines), covered, missing, fetches


def acquire_li_ir(client: Client, decision: datetime) -> tuple[str, list[str], list[str], list[Fetch]]:
    del decision
    page_url = "https://ir.lixiang.com/"
    page = client.get(page_url)
    if page.status == 403:
        return f"issuer_ir: 403 {page_url} not retried", [], ["issuer_ir_403"], [page]
    if page.status != 200:
        return f"issuer_ir: HTTP {page.status} {page_url}", [], ["issuer_ir_listing"], [page]
    html_text = page.body.decode("utf-8", "replace")
    urls = []
    for url in re.findall(r'href="([^"]+\.pdf)"', html_text, re.I):
        if url.startswith("/"):
            url = "https://ir.lixiang.com" + url
        if url not in urls:
            urls.append(url)
    if not urls:
        return f"listing: {page_url}\nNo PDF links in the fetched IR HTML.", ["issuer_ir_listing"], ["issuer_ir_documents"], [page]
    # The listing order is the order the issuer page returned. Do not substitute a remembered filename.
    chosen = urls[0]
    pdf = client.get(chosen)
    lines = [f"listing: {page_url}", f"source_url: {chosen}", "discovery: first PDF href on the IR page fetched this run"]
    covered, missing = ["issuer_ir_listing"], []
    if pdf.status == 200 and _pdf_text(pdf.body):
        covered.append("issuer_ir_excerpt")
        lines.append("excerpt:\n" + _pdf_text(pdf.body))
    elif pdf.status == 403:
        missing.append("issuer_ir_pdf_403")
    else:
        missing.append("issuer_ir_excerpt")
    return "\n".join(lines), covered, missing, [page, pdf]


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
    pages = [page.extract_text() or "" for page in reader.pages[:8]]
    full = "\n".join(pages)
    return full[:1500], full


def _tencent_documents(page: str, source: str) -> list[dict]:
    found = []
    seen = set()
    for match in re.finditer(r'href="(https://[^"]+\.pdf)"[^>]*>(.*?)</a>', page, re.I | re.S):
        url = match.group(1)
        label = " ".join(re.sub(r"<[^>]+>", " ", match.group(2)).split())
        pre = page[max(0, match.start() - 700):match.start()]
        heads = re.findall(r"<h2[^>]*>(.*?)</h2>", pre, re.I | re.S)
        title = " ".join(re.sub(r"<[^>]+>", " ", heads[-1]).split()) if heads else label
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
        described.append({**doc, "text": excerpt, "published": published, "printed": printed, "status": pdf.status})
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
        "latest_by_publication: " + (
            latest["title"] if latest else "not a single later document; identities are listed separately"
        ),
        "currency: excerpts are quoted from the PDFs; this collector does not convert units",
    ]
    for doc in described:
        mark = " latest_by_publication" if latest and doc["url"] == latest["url"] else ""
        parts.append(
            f"document: {doc['title']}\nkind: {doc['kind']}{mark}\nsource_url: {doc['url']}\n"
            f"publication: {doc['printed'] or 'not stated in the first pages'}\n"
            f"http_status: {doc['status']}"
        )
        if doc["text"]:
            parts.append("excerpt:\n" + doc["text"][:1200])
        elif doc["status"] == 403:
            missing.append("tencent_pdf_403")
            parts.append("excerpt: 403 not retried")
        else:
            missing.append("tencent_pdf_text")
    if any(doc["text"] for doc in described):
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
    parts.append(
        "earnings_schedule: FUTURE_NOT_REPORTED unless a later dated event is printed below. "
        "HKEX title search was not used; its HTML shell did not list documents."
    )
    missing.append("hkex_document_index")
    return "\n".join(parts), covered, missing, fetches


def _markdown(result_bits: dict) -> str:
    lines = [
        "# Official material",
        f"ticker: {result_bits['ticker']}",
        f"price_session_date: {result_bits['price_date']}",
        f"decision_at: {result_bits['decision_at']}",
        f"fetched: {str(result_bits['fetched']).lower()}",
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
            "fetched": False, "financial": f"NOT_COVERED: {ticker} has no acquisition source in this pilot.",
            "covered": [], "missing": ["acquisition"], "operator": operator,
        })
        _finish(run, ticker, price_date, decision, False, "not_covered", text, [])
        return Result(ticker, None, price_date, decision.isoformat(), False, False, "not_covered", text, run)
    if mode == "historical":
        text = _markdown({
            "ticker": ticker, "price_date": price_date, "decision_at": decision.isoformat(),
            "fetched": False,
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
    fetched = bool({"financial_excerpt", "tencent_results_excerpt", "issuer_ir_excerpt"} & set(covered))
    text = _markdown({
        "ticker": ticker, "price_date": price_date, "decision_at": decision.isoformat(),
        "fetched": fetched, "financial": financial, "covered": covered, "missing": missing,
        "operator": operator,
    })
    status = "fetched" if fetched else "partial_or_failed"
    digest_name = f"sentiment_digest_{ticker}_{price_date}.md"
    (run / digest_name).write_text(text, encoding="utf-8")
    _finish(run, ticker, price_date, decision, fetched, status, text, fetches, covered, missing)
    return Result(ticker, canonical, price_date, decision.isoformat(), fetched, fetched, status, text, run, fetches, covered, missing)


def _finish(run, ticker, price_date, decision, fetched, status, text, fetches, covered=None, missing=None):
    manifest = {
        "ticker": ticker,
        "price_session_date": price_date,
        "decision_at": decision.isoformat(),
        "fetched": fetched,
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
    return 0 if result.status in {"fetched", "not_covered", "historical_no_fetch"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
