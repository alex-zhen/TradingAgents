# Current-material acquisition

The loader patch is unchanged. This does not rewrite `run_ta.py`.

`DATE` on the runner command is the price-session date. `--decision-at` is separate and must include a timezone. A current run on 2026-11-17 can use price date 2026-11-16.

```bash
python integrations/external_runner/refresh_current.py BABA 2026-11-16 \
  --decision-at 2026-11-17T09:00:00-05:00 \
  --refresh-current \
  --root /workspace/tradingagents-runs
```

Set `SEC_EDGAR_USER_AGENT` to your own name and email before SEC calls. If unset, the header says that no contact email is configured. It does not invent one.

The command writes a new directory under `acquisitions/`. `--install-for-runner` and `--runner` install that file only when `content_validated` and `latest_discovery_verified` are true. Otherwise they exit 4 and leave the previous digest in place. Historical mode does not fetch and does not start the runner.

Supported acquisition: `BABA`, `LI`, and `0700` / `0700.HK`. Any other ticker returns `NOT_COVERED` and leaves old files in place. This is not 29-symbol coverage.

`fetch_succeeded` means a public response was stored. `content_validated` means the text has an issuer, a report period, a currency, and an income or cash-flow amount. `latest_discovery_verified` is false while a discovery conflict is unresolved, the SEC archive is blocked and no issuer excerpt was validated, the issuer site returned 403, or the HKEX filing list was not fetched. A 403 is not retried.

BABA keeps the results-card date, the event date, the press-release dateline, and the SEC acceptance time as different fields. The press-release document is selected. The presentation deck is recorded and not substituted when the press release is missing. A card with no file is not a report. If its event date is still after `decision_at`, it is `FUTURE_NOT_REPORTED`.

LI reads the IR homepage and at most six same-origin results or news links. HTML pages count. A 403 is disclosed.

0700.HK reads the current Tencent results and financial-reports pages. The PDF dateline and the HKEX listing time are both printed when the title search returns them. A dateline alone is not an HKEX filing time. Options and social posts are not collected. `--operator-feed` copies a parent file and labels it as not collected here.

Before a graph launch, print the inventory with no model call:

```bash
python integrations/external_runner/accept_inventory.py \
  --price-date 2026-11-16 --decision-at 2026-11-17T21:00:00Z \
  --root /tmp/acquire-accept
```

The sentiment-loader patch and the options-block patch are separate and are not changed by this collector. Same-day report overwrite inside the untouched runner is still not done; the launcher only copies the existing report directory and framework log aside.
