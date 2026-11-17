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


def _pdf_text(body: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    import io
    try:
        reader = PdfReader(io.BytesIO(body))
    except Exception:
        return ""
    pages = []
    for page in reader.pages[:2]:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)[:3500]


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
    match = re.search(r'href="(https://www\.tencent\.com/[^"]+\.pdf)"', html_text)
    if not match:
        missing.append("tencent_results_pdf")
        return f"results_page: {page_url}\nNo results PDF link in the fetched HTML.", covered, missing, fetches
    pdf_url = match.group(1)
    pdf = client.get(pdf_url)
    fetches.append(pdf)
    month = re.search(r"/(\d{4})/(\d{2})/", pdf_url)
    published = f"{month.group(1)}-{month.group(2)}" if month else "not stated"
    parts = [
        f"results_page: {page_url}",
        f"source_url: {pdf_url}",
        f"publication: URL path month {published}; the results card did not state a calendar day",
        "currency: the excerpt is quoted from the PDF; this collector does not convert units",
    ]
    if pdf.status == 200:
        text = _pdf_text(pdf.body)
        if text:
            covered.append("tencent_results_excerpt")
            parts.append("excerpt:\n" + text)
        else:
            missing.append("tencent_pdf_text")
            parts.append("excerpt: PDF bytes were fetched but text was not extracted")
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
    fetched = bool({"financial_excerpt", "tencent_results_excerpt"} & set(covered))
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
