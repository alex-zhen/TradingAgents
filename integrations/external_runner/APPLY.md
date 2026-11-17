# Install the research-input runner

The process that analyzes a symbol is `run_ta.py` on the machine that already
has `/workspace/tradingagents-runs/`. Replacing files inside the TradingAgents
checkout does not change that process. Do not merge this pull request to deploy
it, and do not copy it over the framework package.

## What was and was not in this workspace

`run_ta.py`, `ta_batch.py`, `options_digest.py`, and `xueqiu_digest.py` were
not in the repository or the agent workspace. The maintained `run_ta.py` here
is the file to install in their place for the research-input step. It keeps
the default root `/workspace/tradingagents-runs`, the config path
`/workspace/tradingagents-runs/config.json`, and the corpus
`/workspace/tradingagents-runs/research_corpus`. Symbol, market, cutoff, and
mode are arguments.

`patch_run_ta.py` only rewrites a file that still contains the recognized
`BABA_2026-11-15` digest assignment. If your file does not match that pattern,
it exits 2 and changes nothing. Use the maintained `run_ta.py` in that case.

## Files to copy

Copy these two files into `/workspace/tradingagents-runs/` (the same directory
the current `run_ta.py` occupies):

- `integrations/external_runner/run_ta.py`
- `integrations/external_runner/research_ingest.py`

Leave `ta_batch.py`, `options_digest.py`, and `xueqiu_digest.py` as they are.
They are the producers. This runner only reads files they have already written.
If they have not written an official extract that was published and captured by
the cutoff, the manifest says that category is missing and sets
`freshness_prerequisite.fetches_latest` to false. The run does not download a
replacement and does not reuse `digests/BABA_2026-11-15.md`.

Generated Xueqiu or options summaries stay labeled as generated summaries. Their
`original_urls` are kept. The summary file is not recorded as the official source.

## Corpus records

Put one JSON object, or a markdown file with a `<!-- research-record` header,
under the corpus. Required fields: `symbol`, `kind`, `unit`, `currency`,
`published_at`, `available_at`, `captured_at`, `source_url`, `provenance`.
Timestamps must include a timezone offset. `kind` is one of `financial_extract`,
`news`, `sentiment`, `official_ir`, `hkex_summary`.

`statement_scope: group` and `unit: group` may be shared by BABA and 9988.HK,
or by LI and 2015.HK, when `company` is `alibaba` or `li_auto`. Per-share ADS
records stay on BABA or LI. Per-share ordinary records stay on 9988.HK,
2015.HK, or 0700.HK. Aliases `700.HK` and `09988` resolve to those listings and
do not change the unit.

An optional `producer_status.json` may contain `last_success_at`. The runner
does not update it.

## Command

```bash
python /workspace/tradingagents-runs/run_ta.py \
  --symbol BABA \
  --market US \
  --decision-at 2026-11-17T09:00:00-05:00 \
  --mode current \
  --prepare-only
```

`--mode historical` uses that same timestamp as a strict cutoff. It does not
mean "latest on disk" and it does not mean the wall clock. In both modes the
price date is the listing's last completed session, and news published after
that session is kept when it was available by `--decision-at`.

Each invocation creates a new directory under
`/workspace/tradingagents-runs/runs/`. It does not replace an older run or the
corpus. The analyst-facing text is inside `full_state.json` `messages`, not
only in the manifest.

`--execute` imports the installed TradingAgents package and injects the same
text through `create_run_state`. Omit it when you only want the manifest.
The fixture tests do not call live data services.

## In-place patch, when the marker matches

```bash
python integrations/external_runner/patch_run_ta.py /path/to/run_ta.py --output /tmp/run_ta.patched.py
```

Review the diff before replacing the live file. `research_ingest.py` must sit
on the import path next to the patched script.
