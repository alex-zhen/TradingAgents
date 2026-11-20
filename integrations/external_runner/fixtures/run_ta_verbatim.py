import sys, os, json, re, pathlib
sys.path.insert(0, '/workspace/tradingagents')
import tradingagents.agents.tools as T
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
TICKER = sys.argv[1]; DATE = sys.argv[2] if len(sys.argv)>2 else '2026-11-13'
RUN = pathlib.Path('/workspace/tradingagents-runs')
sent_path=RUN/f'sentiment_digest_{TICKER}_2026-11-15.md'
if not sent_path.exists():
    candidates=sorted(RUN.glob(f'sentiment_digest_{TICKER}_*.md'))
    sent_path=candidates[-1] if candidates else sent_path
sent=sent_path.read_text() if sent_path.exists() else ''
# existing options/xueqiu hooks and cfg remain unchanged
# sent_block built from sent
_orig=T.route_to_vendor
def patched(method,*a,**k):
    out=_orig(method,*a,**k)
    if method=='get_news':out=f'{out}{sent_block}'
    elif method=='get_stock_data':out=f'{out}{opt_block}'
    return out
T.route_to_vendor=patched
# xueqiu wraps T.route_to_vendor after this
# final calls: ta=TradingAgentsGraph(...,config=cfg);state,decision=ta.propagate(TICKER,DATE)
# outdir=RUN/f'{TICKER}_{DATE}' then writes reports
