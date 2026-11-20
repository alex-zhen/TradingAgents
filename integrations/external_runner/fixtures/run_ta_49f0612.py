"""Run TradingAgents with extra context injected.
Injection method: wrap tradingagents.agents.tools.route_to_vendor so that
- every get_news result for the ticker is followed by the X + Chinese news digest
  (reaches News Analyst via its tool and Sentiment Analyst via its pre-fetch);
- every get_stock_data result is followed by the trading-volume & options digest
  (reaches Market/Technical Analyst).
"""
import sys, os, json, re, pathlib
sys.path.insert(0, "/workspace/tradingagents")
import tradingagents.agents.tools as T
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

TICKER = sys.argv[1]; DATE = sys.argv[2] if len(sys.argv) > 2 else "2026-11-13"
RUN = pathlib.Path("/workspace/tradingagents-runs")
sent_path = RUN / f"sentiment_digest_{TICKER}_{DATE}.md"
sent = sent_path.read_text() if sent_path.exists() else (
    f"MISSING sentiment_digest_{TICKER}_{DATE}.md in {RUN}. "
    "No older file was substituted. This run did not fetch a replacement."
)

def _load_options_digest(ticker: str, as_of: str) -> str:
    """Prefer the OpenBB per-ticker digest; build it if missing. No LLM calls."""
    target = RUN / f"options_digest_{ticker}_{as_of}.md"
    if not target.exists():
        script = RUN / "options_digest.py"
        py = pathlib.Path("/workspace/openbb-venv/bin/python")
        if script.exists() and py.exists():
            import subprocess
            try:
                subprocess.run(
                    [str(py), str(script), ticker, "--as-of", as_of, "--out-dir", str(RUN)],
                    check=False,
                    timeout=60,
                )
            except subprocess.TimeoutExpired:
                pass
    if target.exists():
        return target.read_text()
    legacy = RUN / f"options_digest_{as_of}.md"
    if legacy.exists():
        blocks = [b for b in legacy.read_text().split("## ") if b.startswith(ticker + " ")]
        if blocks:
            return "## " + blocks[0]
    return f"(no options digest found for {ticker} as of {as_of})"

opt = _load_options_digest(TICKER, DATE)
opt_block = (
    "\n\n=== EXTRA CONTEXT: trading volume & options data "
    "(OpenBB: Cboe preferred, yfinance fallback) ===\n"
    + (opt if opt.lstrip().startswith("##") else "## " + opt)
    + "\n=== END EXTRA CONTEXT ===\n"
)
sent_block = "\n\n=== EXTRA CONTEXT: X (Twitter) posts + Chinese & English finance news digest (gathered by operator) ===\n" + sent + "\n=== END EXTRA CONTEXT ===\n"

def _norm_listing(value: str) -> str:
    text = (value or "").strip().upper().replace(" ", "").replace("_", "")
    match = __import__("re").fullmatch(r"(?:HK\.?)?0*(\d{3,5})(?:\.HK)?", text)
    if match:
        return "HK" + str(int(match.group(1)))
    return text


def _same_listing(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return _norm_listing(left) == _norm_listing(right)


def _requested_symbol(args, kwargs) -> str:
    for key in ("ticker", "symbol", "company"):
        if kwargs.get(key):
            return str(kwargs[key])
    if args:
        return str(args[0])
    return ""


def _period_fields(digest: str) -> str:
    import re as _re
    explicit = [" ".join(item.split()) for item in _re.findall(r"(?m)^document_coverage:\s*(.+)$", digest or "")]
    found = []
    for item in explicit:
        if item and item not in found:
            found.append(item)
    if not found:
        pattern = _re.compile(
            r"((?:fiscal years|fiscal year|three and nine months|three and six months|nine months|six months|three months|quarter|period)"
            r"[^\n]{0,80}?ended[^\n]{0,40}?\d{4})",
            _re.I,
        )
        for match in pattern.finditer(digest or ""):
            raw = " ".join(match.group(1).split())
            if raw not in found:
                found.append(raw)
    if not found:
        return "document_coverage: not stated\nmetric_period: unknown\n"
    coverage = " | ".join(found)
    low = coverage.lower()
    short = ("three months" in low) or ("quarter" in low)
    long = ("six months" in low) or ("nine months" in low) or ("fiscal year" in low)
    if len(found) == 1 and not (short and long):
        metric = found[0]
    else:
        metric = "unknown"
    return "document_coverage: " + coverage + "\nmetric_period: " + metric + "\n"


def _strip_urls(text: str) -> str:
    import re as _re
    return _re.sub(r"https?://\S+", " ", text or "")


def _dates_in_segment(segment: str):
    """Dates in a label's tail. Period-end dates are not publication dates."""
    import datetime as _dt
    import re as _re
    segment = _strip_urls(segment)
    found = []
    patterns = (
        (r"\d{4}-\d{2}-\d{2}", None),
        (r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s+20\d{2}", "mdy"),
        (r"\d{1,2}\s+[A-Z][a-z]+\s+20\d{2}", "dmy"),
        (r"20\d{2}年\d{1,2}月\d{1,2}日", "cjk"),
    )
    occupied = []
    for pattern, kind in patterns:
        for match in _re.finditer(pattern, segment, _re.I):
            span = match.span()
            if any(span[0] < end and span[1] > start for start, end in occupied):
                continue
            window = segment[max(0, span[0] - 24):span[0]].lower()
            if "ended" in window or "ending" in window or "截至" in window:
                continue
            raw = " ".join(match.group(0).split())
            parsed = None
            if kind is None:
                parsed = _dt.date.fromisoformat(raw)
            elif kind == "mdy":
                cleaned = raw.replace(".", "")
                for fmt in ("%b %d, %Y", "%B %d, %Y"):
                    try:
                        parsed = _dt.datetime.strptime(cleaned, fmt).date()
                        break
                    except ValueError:
                        continue
            elif kind == "dmy":
                try:
                    parsed = _dt.datetime.strptime(raw, "%d %B %Y").date()
                except ValueError:
                    parsed = None
            else:
                parts = _re.match(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", raw)
                if parts:
                    parsed = _dt.date(int(parts.group(1)), int(parts.group(2)), int(parts.group(3)))
            if parsed is not None:
                found.append((parsed, raw))
                occupied.append(span)
    return found


def _labeled_availability(digest: str):
    """Publication time or date bound to an explicit label. No clock is invented."""
    import datetime as _dt
    import re as _re
    text = digest or ""
    stamps = []
    for match in _re.finditer(r"HKEX listing datetime", text, _re.I):
        line_end = text.find("\n", match.end())
        if line_end < 0:
            line_end = len(text)
        tail = _strip_urls(text[match.end():line_end])
        clock = _re.search(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}", tail)
        if not clock:
            continue
        raw = clock.group(0)
        moment = _dt.datetime.strptime(raw, "%d/%m/%Y %H:%M").replace(
            tzinfo=_dt.timezone(_dt.timedelta(hours=8))
        )
        stamps.append((moment, raw))
    unique_stamps = []
    for item in stamps:
        if item[0] not in [have[0] for have in unique_stamps]:
            unique_stamps.append(item)
    if len(unique_stamps) > 1:
        return ("ambiguous", None, "", "")
    labeled = []
    label = _re.compile(r"publication_dateline|dateline|filed/accepted|\bfiled\b|公告日期|刊登日期", _re.I)
    for line in text.splitlines():
        if _re.search(r"do not treat|not the current|not published|不是本期|尚未刊", line, _re.I):
            continue
        cursor = 0
        while True:
            found = label.search(line, cursor)
            if not found:
                break
            nxt = label.search(line, found.end())
            stop = nxt.start() if nxt else len(line)
            for parsed, raw in _dates_in_segment(line[found.end():stop]):
                labeled.append((parsed, raw, found.group(0).lower()))
            cursor = found.end()
    unique_dates = []
    for parsed, raw, kind in labeled:
        if parsed not in [have[0] for have in unique_dates]:
            unique_dates.append((parsed, raw, kind))
    if len(unique_stamps) == 1:
        moment, raw = unique_stamps[0]
        if any(item[0] != moment.date() for item in unique_dates):
            return ("ambiguous", None, "", "")
        return ("timestamp", moment, "hkex", raw)
    if len(unique_dates) > 1:
        return ("ambiguous", None, "", "")
    if len(unique_dates) == 1:
        parsed, raw, kind = unique_dates[0]
        source = "filed" if "filed" in kind else ("announcement" if kind in {"公告日期", "刊登日期"} else "dateline")
        return ("date", parsed, source, raw)
    return ("missing", None, "", "")


def _discovery_lines(digest: str) -> str:
    import re as _re
    match = _re.search(r"latest_discovery_verified:\s*(true|false)", digest or "", _re.I)
    stated = match.group(1).lower() if match else "not stated"
    return (
        "digest_latest_discovery_verified: " + stated + "\n"
        "latest_discovery_verified: not established by this hook\n"
    )


def _official_fundamentals_block(digest: str, cutoff: str) -> str:
    """Labelled official report for get_fundamentals. Plain markdown is accepted."""
    import datetime as _dt
    import re as _re
    header = "\n\n=== OFFICIAL FUNDAMENTALS (labelled; not a vendor value) ===\n"
    end = "\n=== END OFFICIAL FUNDAMENTALS ===\n"

    def declared():
        match = _re.search(r"decision_at:\s*(\S+)", digest or "")
        return match.group(1) if match else ""

    def missing(reason):
        as_of = cutoff or declared() or "not declared"
        return (
            header
            + f"as_of: {as_of}\ndigest_decision_at: {declared() or 'not declared'}\n"
            + _discovery_lines(digest)
            + "MISSING: " + reason + " Do not describe vendor output as the current official filing.\n"
            + end
        )

    if not digest or digest.startswith("MISSING "):
        return missing("no verified official financial report was loaded for this decision.")
    kind, avail, source_kind, raw = _labeled_availability(digest)
    if kind == "ambiguous":
        return missing("more than one publication date is labeled and they disagree. None was selected.")
    if kind == "missing":
        return missing("publication availability is not stated. No period-end, URL, or retrieval time was used.")
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
    if kind == "timestamp":
        if cut < avail:
            return missing(
                "official report availability " + avail.isoformat()
                + " is after cutoff " + cut.isoformat() + ". The report is not included."
            )
        availability = (
            "availability: " + avail.isoformat() + "\n"
            "availability_precision: timestamp\n"
            "availability_source: " + source_kind + "\n"
            "publication_dateline: " + raw + "\n"
        )
    else:
        if cut.date() <= avail:
            return missing(
                "publication date " + avail.isoformat()
                + " is not before the cutoff date and no clock was stated. The report is not included."
            )
        availability = (
            "availability: " + avail.isoformat() + "\n"
            "availability_precision: date\n"
            "availability_clock: not stated\n"
            "availability_source: " + source_kind + "\n"
            "publication_dateline: " + raw + "\n"
        )
    urls = _re.findall(r"https://[^\s)]+", digest)
    source = next((item for item in urls if item.lower().endswith(".pdf") or "/Archives/" in item), urls[0] if urls else "")
    body = ""
    for title in ("## 3Q2026 official figures", "## Financial report"):
        if title in digest:
            body = digest.split(title, 1)[1].split("\n## ", 1)[0].strip()
            break
    if not body:
        lines = [
            line.strip() for line in digest.splitlines()
            if _re.search(r"revenue|attributable|operating profit|net sales|source_url", line, _re.I) and _re.search(r"\d", line)
        ]
        body = "\n".join(lines[:12])
    if not body or not _re.search(r"\d", body):
        return missing("the digest has no official financial amounts.")
    return (
        header
        + "as_of: " + (declared() or cut.isoformat()) + "\n"
        + "digest_decision_at: " + (declared() or "not declared") + "\n"
        + availability
        + _period_fields(digest)
        + _discovery_lines(digest)
        + "source_url: " + source + "\n"
        + "vendor_conflict: the vendor text above is not replaced. If it reports an earlier period, that vendor period is stale relative to this official report. Do not call the vendor period the latest official filing.\n"
        + "body:\n" + body + "\n"
        + end
    )


def _official_not_applicable(requested: str) -> str:
    shown = requested or "not provided"
    return (
        "\n\n=== OFFICIAL FUNDAMENTALS (labelled; not a vendor value) ===\n"
        "MISSING: official digest is not applicable to the requested symbol "
        + shown
        + ". No official fields were attached.\n"
        "=== END OFFICIAL FUNDAMENTALS ===\n"
    )


_orig = T.route_to_vendor
def patched(method, *a, **k):
    out = _orig(method, *a, **k)
    if method == "get_news":
        out = f"{out}{sent_block}"
    elif method == "get_stock_data":
        out = f"{out}{opt_block}"
    elif method in {"get_fundamentals", "get_balance_sheet", "get_cashflow", "get_income_statement"}:
        requested = _requested_symbol(a, k)
        if not _same_listing(requested, TICKER):
            out = f"{out}{_official_not_applicable(requested)}"
        else:
            _cut = ""
            _declared = __import__("re").search(r"decision_at:\s*(\S+)", sent or "")
            if _declared:
                _cut = _declared.group(1)
            out = f"{out}{_official_fundamentals_block(sent, _cut)}"
    return out
T.route_to_vendor = patched

# === XUEQIU HOOK START =====================================================
# Appends 雪球 Chinese-retail heat/sentiment after get_news.
# Implementation lives in /workspace/tradingagents-runs/xueqiu_digest.py.
# Do not fold this into the OpenBB/options block above. No-op if missing.
try:
    if "/workspace/tradingagents-runs" not in sys.path:
        sys.path.insert(0, "/workspace/tradingagents-runs")
    from xueqiu_digest import get_digest_block as _xq_get_digest_block
    _xq_prev = T.route_to_vendor
    def _xq_patched(method, *a, **k):
        out = _xq_prev(method, *a, **k)
        if method == "get_news":
            _blk = _xq_get_digest_block(TICKER)
            if _blk:
                out = f"{out}{_blk}"
        return out
    T.route_to_vendor = _xq_patched
except Exception as _xq_exc:
    print("xueqiu hook skipped:", _xq_exc)
# === XUEQIU HOOK END =======================================================

def _archive_same_date(root, ticker, price_date):
    """Copy this ticker's same-date report and framework log. Do not delete them."""
    import datetime as _dt
    import os as _os
    import shutil as _shutil
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + str(_os.getpid())
    backup = root / "backups" / f"{ticker}_{price_date}_{stamp}"
    partial = root / "backups" / f".{ticker}_{price_date}_{stamp}.partial"
    report = root / f"{ticker}_{price_date}"
    log = root / "logs" / ticker / "TradingAgentsStrategy_logs" / f"full_states_log_{price_date}.json"
    if not report.exists() and not log.is_file():
        return backup
    try:
        if report.exists():
            _shutil.copytree(report, partial / "report")
        if log.is_file():
            target = partial / "framework_log"
            target.mkdir(parents=True, exist_ok=True)
            _shutil.copy2(log, target / log.name)
        partial.rename(backup)
    except Exception:
        if partial.exists():
            _shutil.rmtree(partial)
        raise
    return backup


# RUN_BODY
cfg = DEFAULT_CONFIG.copy()
cfg.update(llm_provider="deepseek", deep_think_llm="deepseek-v4-pro", quick_think_llm="deepseek-flash",
           max_debate_rounds=1, max_risk_discuss_rounds=1, output_language="Chinese",
           results_dir=str(RUN / "logs"), max_tokens=8000, llm_max_retries=4)
ta = TradingAgentsGraph(selected_analysts=["market", "social", "news", "fundamentals"], debug=False, config=cfg)
_archive_same_date(RUN, TICKER, DATE)
state, decision = ta.propagate(TICKER, DATE)
outdir = RUN / f"{TICKER}_{DATE}"; outdir.mkdir(exist_ok=True)
keys = ["market_report","sentiment_report","news_report","fundamentals_report","investment_plan","trader_investment_plan","final_trade_decision"]
for kk in keys:
    v = state.get(kk)
    if v: (outdir / f"{kk}.md").write_text(str(v))
for kk in ["investment_debate_state","risk_debate_state"]:
    v = state.get(kk)
    if v: (outdir / f"{kk}.json").write_text(json.dumps(v, ensure_ascii=False, indent=2, default=str))
(outdir / "decision.txt").write_text(str(decision))
def _placeholder(value):
    text = str(value or "").strip().strip("`").strip().strip('"').strip("'")
    compact = "".join(text.split())
    return compact in {"", "...", "…", ".", ".."}
_final = state.get("final_trade_decision")
_plan = "\n".join(str(state.get(key) or "") for key in ("investment_plan", "trader_investment_plan"))
if _placeholder(decision) or _placeholder(_final):
    (outdir / "output_status.txt").write_text(
        "incomplete: final output is a placeholder. "
        + ("A substantive plan is present. " if len(_plan.strip()) >= 40 and not _placeholder(_plan) else "")
        + "No result was invented.\n",
        encoding="utf-8",
    )
    print("INCOMPLETE", TICKER, "placeholder final output; no result was invented")
    raise SystemExit(3)
print("DECISION", TICKER, decision)
