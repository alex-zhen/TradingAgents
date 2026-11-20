# CNINFO and exchange listing evidence

This file is a separate official listing record. It does not change the text gate. A digest line `公告时间` is still not read as `公告日期`. The record keeps `source_label` as `公告时间` or `announcementTime`.

The record is admitted only when all of these correspond:

- `schema` is `tradingagents.cninfo_listing_evidence.v1`
- `source` is `cninfo`, `sse`, or `szse`, and `pdf_url` is on that source's official host
- `announcement_id` is the CNINFO platform id. It is bound by the official record and the PDF URL. It is not required in the PDF body, and an issuer `公告编号` is not that id.
- `security_code` matches the requested symbol, and the body contains `证券代码` for that code
- `secName` appears in the body
- `report_period` is the same calendar day as a date in the body. Spaces in `2026 年 9 月 30 日` are ignored. The day and month numbers are not otherwise rewritten.
- `content_sha256` is the SHA-256 of the body bytes. A sibling `pdf/<id>.PDF`, when present, must match `pdf_file_sha256`.
- `publication.value` is the listing time, not a board signature, period end, `storageTime`, or URL date

A calendar date, and a timestamp at 00:00:00 in any timezone, is date-only. It is included only on a later SSE/SZSE cash session. Saturday and Sunday are not cash sessions, so the next calendar day is not enough when that day is a weekend. A timezone-aware clock other than midnight is included when the decision cutoff is at or after that clock. A missing or naive `decision_at` is refused. The runner `DATE` is not a substitute.

`latest_discovery_verified` stays `not established by this evidence` when a body is shown.

Entry, with no network:

```bash
python integrations/external_runner/cninfo_listing_evidence.py \
  --file integrations/external_runner/fixtures/synthetic_cninfo_300750.json \
  --symbol 300750.SZ \
  --decision-at 2026-10-21T10:00:00+08:00
```

The runner reads `TRADINGAGENTS_CNINFO_LISTING` as the JSON path and `TRADINGAGENTS_CNINFO_LISTING_DIR` as the directory that contains this module. `decision_at:` is read from the digest. The synthetic fixture is not a CATL or Moutai filing.

Staged preflight, from an unpacked archive, with `PARENT_COPY` replaced by that directory:

```bash
python3 PARENT_COPY/preflight_cninfo_listing.py \
  --runner PARENT_COPY/run_ta.py.staged \
  --file PARENT_COPY/fixtures/synthetic_cninfo_300750.json \
  --symbol 300750.SZ \
  --session-date 2026-10-20 \
  --decision-at 2026-10-21T10:00:00+08:00
```

Clean suite:

```bash
cd PARENT_COPY
PYTHONPATH= python3 -m pytest test_cninfo_listing_evidence.py test_public_market_evidence.py test_us_official.py -q -p no:cacheprovider --noconftest --rootdir=PARENT_COPY
```
