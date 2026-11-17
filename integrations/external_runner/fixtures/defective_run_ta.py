"""Pattern fixture for the stated hardcode.

The attached runner's import block was not stored in this workspace, so this
file does not pretend to be that script. It keeps the invocation shape a patch
must leave untouched: positional TICKER and DATE, options_digest, xueqiu_digest,
and TradingAgentsGraph.
"""

import sys
from pathlib import Path

import options_digest
import xueqiu_digest

RUN = Path("/workspace/tradingagents-runs")


def load_sentiment(TICKER, DATE):
    sent_path = RUN / f"sentiment_digest_{TICKER}_2026-11-15.md"
    if not sent_path.exists():
        matches = sorted(RUN.glob(f"sentiment_digest_{TICKER}_*.md"))
        sent_path = matches[-1] if matches else sent_path
    return sent_path


def main(argv):
    TICKER, DATE = argv[1], argv[2]
    options_digest.build(TICKER)
    xueqiu_digest.build(TICKER)
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    return load_sentiment(TICKER, DATE), TradingAgentsGraph


if __name__ == "__main__":
    main(sys.argv)
