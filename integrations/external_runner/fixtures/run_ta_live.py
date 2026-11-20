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

_orig = T.route_to_vendor
def patched(method, *a, **k):
    out = _orig(method, *a, **k)
    if method == "get_news":
        out = f"{out}{sent_block}"
    elif method == "get_stock_data":
        out = f"{out}{opt_block}"
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
