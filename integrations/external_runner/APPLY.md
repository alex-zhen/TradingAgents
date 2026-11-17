# Apply the sentiment-digest patch

The process that runs analyses is the existing `/workspace/tradingagents-runs/run_ta.py`.
Its invocation is positional: `python run_ta.py TICKER DATE`. Do not replace that
file with a different CLI.

The stored conversation did not include that file's import block. The hardcode
described in steering is:

```python
sent_path = RUN / f"sentiment_digest_{TICKER}_2026-11-15.md"
if not sent_path.exists():
    matches = sorted(RUN.glob(f"sentiment_digest_{TICKER}_*.md"))
    sent_path = matches[-1] if matches else sent_path
```

## Files to copy next to the existing runner

Copy `research_ingest.py` into `/workspace/tradingagents-runs/` so the patched
script can import it. Leave `options_digest.py`, `xueqiu_digest.py`, `ta_batch.py`,
model settings, and environment variables where they are.

```bash
python integrations/external_runner/patch_run_ta.py /path/to/run_ta.py --output /tmp/run_ta.patched.py
```

Review the diff. The patch rewrites only the `sent_path` assignment and its
`glob` fallback. It adds `from research_ingest import select_sentiment_digest`.
If the assignment is not in that form, the command exits 2 and writes nothing.

`fixtures/defective_run_ta.py` is a pattern fixture for that assignment. It is
not a copy of the live runner.

## What the patched line does

`select_sentiment_digest(RUN, TICKER, DATE)` returns an object whose `.path` is
the latest digest whose publication, availability, and capture times are at or
before the decision cutoff. The name `sentiment_digest_{TICKER}_2026-11-15.md`
is not preferred, and a later filename is not used when its timestamps are after
the cutoff. `DATE` as `YYYY-MM-DD` means the end of that day in the listing's
market, and not later than the clock. The price date stays the last completed
session and is not the filter for the digest.

Existing digest files are only read. Older run directories are not deleted.

## Official extracts and route_to_vendor

Selecting a file that is already on disk is not a refresh. For a current run,
call `preflight_acquire` and pass the callables the wrapper already uses:

```python
from research_ingest import official_extract_vendor, preflight_acquire, vendor_config

prepared = preflight_acquire(
    symbol=TICKER,
    market=None,
    decision_at=DATE,  # or a timezone-aware timestamp
    mode="current",
    corpus=CORPUS,
    runs_dir=RUNS,
    producers={
        "options_digest": options_digest.refresh,
        "xueqiu_digest": xueqiu_digest.refresh,
        "official_extract": official_extract_writer,
    },
)
```

`official_extract_writer(symbol, decision_at, corpus)` is the local writer that
emits an official IR or HKEX extract with `source_url`, currency, unit, period,
and the three timestamps. This repository does not add a paid client and does
not read account credentials. If that callable is omitted, `automatic_latest`
stays false and `route_to_vendor("get_fundamentals", ...)` returns
`OFFICIAL_EXTRACT_NOT_REFRESHED` instead of an older file.

```python
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.router import route_to_vendor

with official_extract_vendor(prepared), run_config(vendor_config()):
    text = route_to_vendor("get_fundamentals", prepared.canonical, prepared.graph_trade_date)
```

Historical mode does not call producers. It serves the extract that was published
and captured by the cutoff, and records `automatic_latest: false`.

A `full_state.json` written beside a run is not evidence that TradingAgentsGraph
used the extract. The check is the string returned by `route_to_vendor`.
