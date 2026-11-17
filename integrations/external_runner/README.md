# Official acquisition pilot

Collector coverage is BABA, LI, and 0700.HK only. Other symbols, including Realty Income `O`, stay on the existing runner and are `NOT_COVERED` here. This is not a 29-symbol collector.

```bash
pip install -r integrations/external_runner/requirements.txt
export SEC_EDGAR_USER_AGENT="Name and email you control"
python integrations/external_runner/refresh_current.py BABA 2026-11-16 \
  --decision-at 2026-11-17T09:00:00-05:00 \
  --refresh-current \
  --root /workspace/tradingagents-runs
```

`--price` is the positional price-session date. `--decision-at` is the decision time and must include a timezone. The command writes a new directory under `acquisitions/` and does not delete prior reports or logs.

`--runner path/to/run_ta.py` starts that script only after this run extracted official text and installed that file. A failed fetch does not start the runner. Historical mode does not fetch and does not start the runner. An existing same-date report directory and `logs/{TICKER}/TradingAgentsStrategy_logs/full_states_log_{DATE}.json` are copied under `backups/` first and are not deleted.

SEC filing HTML that returns 403 is not retried. BABA then uses the Alibaba IR quarterly-results listing fetched on that run. LI uses `https://ir.lixiang.com/`; a 403 there is a failure, not an older digest. 0700.HK reads Tencent's current results and financial-reports pages and keeps the quarterly release and the interim report as separate documents.

The options block patch, separate from the sentiment loader patch:

```bash
python integrations/external_runner/patch_options_block.py \
  /workspace/tradingagents-runs/run_ta.py \
  --output /tmp/run_ta.patched.py
```

It removes `options_digest_2026-11-13.md`. A same-date combined file returns only that ticker's `## ` block. The header does not say HK options are unavailable.
