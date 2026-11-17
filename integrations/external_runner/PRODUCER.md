# Path B: who writes the dated digest

`run_ta.py` does not fetch filings, news, or quotes. `fetched` in
`digest_manifest.json` is false. Empty producer callbacks are not a refresh.

Before a current run, the parent writes the operator summary for the decision
date. The file is plain markdown. Official URLs and date disclosures stay as
the operator wrote them. The runner does not parse or replace them.

```bash
# parent-owned command, not implemented here and not called by run_ta.py
python /workspace/tradingagents-runs/acquire_sentiment.py TICKER DATE
# must create, and must not replace a different date's file:
# /workspace/tradingagents-runs/sentiment_digest_TICKER_DATE.md
python /workspace/tradingagents-runs/run_ta.py TICKER DATE
```

`DATE` is the decision date (`YYYY-MM-DD`). It is the same value passed to
`TradingAgentsGraph.propagate`. It is not the price last-completed-session
date. A historical date uses only `sentiment_digest_TICKER_DATE.md` for that
date. If that file is absent, the news tool receives a MISSING string and no
older digest is opened.

This repository cannot perform that acquisition without a live source
connector. The parent runs `acquire_sentiment.py` (or an equivalent writer)
first. If the dated file is not there, the run is not fresh.
