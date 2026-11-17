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

The command writes a new directory under `acquisitions/` and does not replace an existing digest. Add `--install-for-runner` only after review; that copies the baseline digest into `backups/` and then places the new file at `sentiment_digest_TICKER_PRICE-DATE.md`. `--refuse-on-failure` exits 4 when no filing text or results excerpt was extracted. Historical mode does not fetch.

Supported acquisition: `BABA`, `LI`, and `0700` / `0700.HK`. Any other ticker returns `NOT_COVERED` and leaves old files in place.

BABA and LI: each current run reads the EDGAR full-text search index and that CIK's submissions index, then keeps filings whose acceptance time is at or before `--decision-at`. `www.sec.gov` filing indexes returned 403 from this environment after the submissions JSON succeeded. A 403 is not retried. `fetched` is true only when filing text or the Tencent results PDF text was extracted. XBRL companyfacts can still be present when the archive is blocked; that run is not marked fetched.

0700.HK: the Tencent investor results page and its first results PDF. The PDF text includes the 12 August 2026 release. HKEX's title-search page did not list documents, so that section stays missing. Options and social posts are not collected. `--operator-feed` copies a parent file and labels it as not fetched here.

Not done: the options fallback pinned to 2026-11-13 (that source text was not in the runner excerpt, so it was not patched), same-day report overwrite inside the runner, and coverage beyond these three companies.
