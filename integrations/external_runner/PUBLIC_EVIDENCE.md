# Public market evidence file

This is not a live feed. It reads one JSON file that an operator already saved. It does not call a broker or an account.

Schema `tradingagents.public_market_evidence.v1`:

- `underlying`: listing code. `HK.00700` and `0700.HK` match. A different ticker does not.
- `currency`: required. Compared with `--expected-currency` when that flag is set.
- `session_date`: `YYYY-MM-DD`. Must equal the session being analyzed. A 2026-11-17 file is not current for 2026-11-20.
- `options.observed_at` and `social.observed_at`: timezone-aware, not after `--decision-at`, and on `session_date`.
- `options.source`, `social.source`, and `delay_seconds` (>= 0) are required.
- `options.entitlement`: `public` or `none`. `none` means this provider grant is absent. It does not mean the market has no options.
- A validated contract needs finite `iv` (`decimal` 0–5 or `percent` 0–500), `delta`, `gamma`, `theta`, `vega`, `volume`, `open_interest`, and an `orderbook` of `[price, size]` levels.
- Missing Greeks or book is `partial_field_coverage`, not a validated chain and not an entitlement failure.
- No file is `evidence_absent`.
- `social.posts[].text` is copied as untrusted public text. It is not an official figure and it is not executed.

Entry:

```bash
python integrations/external_runner/public_market_evidence.py \
  --file integrations/external_runner/fixtures/synthetic_public_0700.json \
  --symbol 0700.HK --session-date 2026-11-18 \
  --decision-at 2026-11-18T16:10:00+08:00 \
  --expected-currency HKD --method get_stock_data
```

`get_stock_data` receives the options block. `get_news` receives the social block. Other tools are left unchanged. When the chain validates, the options block says not to claim that listed options are unavailable. A partial chain does not say that.

The staged runner reads `decision_at:` from the digest text. It does not take the cutoff from `DATE` or from `TRADINGAGENTS_DECISION_AT`. The session compared with the JSON is the runner `DATE`. The patcher accepts only source sha256 `49f0612df01d86d5c651cd92749a3053b55d9374df381894ebed2d55a7fa0c14`.

Preflight runs the staged tool route with a stub vendor and does not load a model. Replace the JSON path with a real public snapshot when one exists. `PARENT_COPY` is the directory where this archive was unpacked:

```bash
python3 PARENT_COPY/preflight_public_evidence.py \
  --runner PARENT_COPY/run_ta.py.staged \
  --file PARENT_COPY/fixtures/synthetic_public_0700.json \
  --symbol 0700.HK --session-date 2026-11-18 \
  --decision-at 2026-11-18T16:10:00+08:00 \
  --expected-currency HKD
```

Local check:

```bash
python -m pytest integrations/external_runner/test_public_market_evidence.py -q -p no:cacheprovider
```

A real public snapshot is a later acceptance step. These fixtures are synthetic.
