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
        return header + f"as_of: {as_of}\ndigest_decision_at: {declared() or 'not declared'}\nMISSING: {reason} Do not describe vendor output as the current official filing.\n" + end

    if not digest or digest.startswith("MISSING "):
        return missing("no verified official financial report was loaded for this decision.")
    hk = _re.search(r"HKEX listing datetime[^0-9\n]{0,80}(\d{2}/\d{2}/\d{4} \d{2}:\d{2})", digest)
    if not hk:
        hk = _re.search(r"hkex_listing_datetime:\s*(\d{2}/\d{2}/\d{4} \d{2}:\d{2})", digest)
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
        r"(?:publication_dateline:\s*|Hong Kong,\s*)(\d{1,2} [A-Z][a-z]+ \d{4}|[A-Z][a-z]+ \d{1,2}, \d{4})",
        digest,
    )
    period = _re.search(
        r"((?:quarter|nine months|six months|three months|period).{0,40}ended \d{1,2} [A-Z][a-z]+ \d{4}|ended [A-Z][a-z]+ \d{1,2}, \d{4})",
        digest,
        _re.I,
    )
    urls = _re.findall(r"https://[^\s)]+", digest)
    source = next((item for item in urls if item.lower().endswith(".pdf")), urls[0] if urls else "")
    body = ""
    for title in ("## 3Q2026 official figures", "## Financial report"):
        if title in digest:
            body = digest.split(title, 1)[1].split("\n## ", 1)[0].strip()
            break
    if not body:
        lines = [
            line.strip() for line in digest.splitlines()
            if _re.search(r"revenue|attributable|operating profit|source_url", line, _re.I) and _re.search(r"\d", line)
        ]
        body = "\n".join(lines[:12])
    if not body or not _re.search(r"\d", body):
        return missing("the digest has no official financial amounts.")
    return (
        header
        + "as_of: " + (declared() or cut.isoformat()) + "\n"
        + "digest_decision_at: " + (declared() or "not declared") + "\n"
        + "availability: " + avail.isoformat() + "\n"
        + "publication_dateline: " + (dateline.group(1) if dateline else "not stated") + "\n"
        + "report_period: " + (period.group(1) if period else "not stated") + "\n"
        + "source_url: " + source + "\n"
        + "vendor_conflict: the vendor text above is not replaced. If it reports an earlier period, that vendor period is stale relative to this official report. Do not call the vendor period the latest official filing.\n"
        + "body:\n" + body + "\n"
        + end
    )


_orig = T.route_to_vendor
def patched(method, *a, **k):
    out = _orig(method, *a, **k)
    if method == "get_news":
        out = f"{out}{sent_block}"
    elif method == "get_stock_data":
        out = f"{out}{opt_block}"
    elif method in {"get_fundamentals", "get_balance_sheet", "get_cashflow", "get_income_statement"}:
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

cfg = DEFAULT_CONFIG.copy()
cfg.update(llm_provider="deepseek", deep_think_llm="deepseek-v4-pro", quick_think_llm="deepseek-flash",
           max_debate_rounds=1, max_risk_discuss_rounds=1, output_language="Chinese",
           results_dir=str(RUN / "logs"), max_tokens=8000, llm_max_retries=4)
ta = TradingAgentsGraph(selected_analysts=["market", "social", "news", "fundamentals"], debug=False, config=cfg)
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
print("DECISION", TICKER, decision)
