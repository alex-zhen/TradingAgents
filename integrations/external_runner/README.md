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

`--runner path/to/run_ta.py` starts that script only when this run's `content_validated` and `latest_discovery_verified` are both true, and the installed file is the one just written. `fetch_succeeded` only means a public page came back. A disclaimer snippet, a file-less card, or an unknown HKEX listing does not install and does not start the runner. Historical mode does not fetch and does not start the runner. An existing same-date report directory and `logs/{TICKER}/TradingAgentsStrategy_logs/full_states_log_{DATE}.json` are copied under `backups/` first and are not deleted.

SEC filing HTML that returns 403 is not retried. BABA then reads the Alibaba results listing. A results-card date, an event date, a press-release dateline, and an SEC acceptance time stay separate fields. A card with no file is not a report. LI follows at most six same-origin results or news links, including HTML; a 403 is disclosed and not retried. 0700.HK keeps the results-release dateline separate from the HKEX listing time. If the HKEX title search is not fetched, the filing time is unknown.

Inventory before any graph launch, with no model call:

```
python integrations/external_runner/accept_inventory.py --price-date 2026-11-16 --decision-at 2026-11-17T21:00:00Z --root /tmp/acquire-accept
```

The options block patch, separate from the sentiment loader patch:

```bash
python integrations/external_runner/patch_options_block.py \
  /workspace/tradingagents-runs/run_ta.py \
  --output /tmp/run_ta.patched.py
```

It removes `options_digest_2026-11-13.md`. A same-date combined file returns only that ticker's `## ` block. The header does not say HK options are unavailable.
