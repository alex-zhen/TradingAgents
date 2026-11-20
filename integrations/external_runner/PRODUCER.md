# Acquisition is not in this patch

`acquire_sentiment.py` does not exist. This repository does not fetch filings or news.

The loader opens `sentiment_digest_{TICKER}_{DATE}.md` only. `DATE` is the second CLI argument. In the current runs that argument is the US price-session date, for example `2026-11-16`, while the decision time is `2026-11-17`. The BABA file with that price-session name was compiled on 2026-11-17 and states its own cutoff. The filename is not the decision timestamp.

If that file is absent, the loader returns a MISSING string and does not open an older digest. A parent-owned writer has to put the file in place before `run_ta.py`. No command for that writer is defined here.

Still open after this loader change: the options fallback pinned to `2026-11-13`, overwriting the same day's report directory, and a real public-source refresh.
