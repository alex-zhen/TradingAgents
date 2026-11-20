# Independent no-LLM acceptance — CNINFO listing package

Checked at 2026-11-20 15:21:37 Asia/Shanghai (UTC+8).

This pass did not start a model, did not edit Page, repository, collector, or live runner code, and did not deploy.

## Cloud archive

- Path: `/cursor/stores/user/grok-bot/agents/6f69acb4-6a9a-4ed5-ada7-8f2f2673e541/assets/01M7VX2GQ908BC74XTZZHXGXVR.gz`
- sha256: `402ee2494cc714f1a3a1a12fbb47cf2b7d07dfc60dd513fbf691db51a8dabcde` (verified)
- Safe extract (no absolute paths, no `..`, no links): `/workspace/tradingagents-data-audit/2026-11-20/cninfo-listing-on-4dac0876-extract/cninfo-listing-on-4dac0876/`
- SHA256SUMS: all listed files matched
- `run_ta.py.backup` sha256 `4dac0876f434b93b666b8663171317f0e3ef89f32ed60ea77a5d00411a4f5f4b` equals the current live runner
- `run_ta.py.staged` sha256 `d6f9097650dcc39018d360b532244086e61252004a4d0c2ae9b305d20b2548c1` (matches the stated staged hash)
- `public_market_evidence.py` sha256 `7b0e6cb07f2de4c30432fcfc29bac15b70c5940819aa8babe8c39ae664ce3ab8` equals the already-deployed live module

## Isolated test suite (independent)

Command, from the extract directory:

`PYTHONPATH=/tmp/pytest-isolated PYTHONNOUSERSITE=1 python3 -m pytest test_cninfo_listing_evidence.py test_public_market_evidence.py test_us_official.py -v -p no:cacheprovider --noconftest --rootdir=<extract>`

Result: **19 passed in 0.22s**. Cloud's count is independently confirmed. The log is `acceptance/isolated_pytest.log`.

The package stub `tradingagents/agents/tools.py` was used only inside that isolated run (tests insert the extract directory). It is not in site-packages and was not placed on the production PYTHONPATH. Production `tools.py` remains `/workspace/tradingagents/tradingagents/agents/tools.py`.

The official text gate on the staged official functions still returns MISSING for a digest that only has `公告时间` / `announcementTime` (not rewritten as `公告日期`). Tencent public-evidence tests and the HKEX earlier-cutoff test are among the 19 that passed. `public_market_evidence.py` is byte-identical to the live module.

## Real CATL / Moutai fixtures (truthful, not schema-filled)

Self-contained official evidence package:

`/workspace/tradingagents-data-audit/2026-11-20/cninfo-publication-compat/`

Truthful listing records (exact official PDF extracted text as `body`, original field name `announcementTime` / label `公告时间` kept, midnight recorded as a date-only placeholder, PDF file sha256 retained separately):

- `fixtures/300750.SZ/listing_v1_truthful.json` — announcementId `1225613175`, code `300750`, PDF `http://static.cninfo.com.cn/finalpage/2026-10-21/1225613175.PDF`, PDF sha256 `476611fe240b90088319c852de4e89d8ab1537b858d2ffbca573af5f8c5419b3`, `announcementTime` 1792512000000 = 2026-10-21 00:00:00 Asia/Shanghai
- `fixtures/600519.SH/listing_v1_truthful.json` — announcementId `1225649896`, code `600519`, PDF `http://static.cninfo.com.cn/finalpage/2026-10-31/1225649896.PDF`, PDF sha256 `96ba51ebf414f841bce79b3ba019927df2f795142392e12e96a9d559e96ebb9b`, `announcementTime` 1793376000000 = 2026-10-31 00:00:00 Asia/Shanghai

The PDF bodies were not rewritten to insert the CNINFO announcement id or a compact period string. The announcement ids are absent even from the raw PDF bytes. The extracted texts contain `证券代码：300750` / `证券代码：600519` and `2026 年 9 月 30 日` (spaces around 年/月/日), not `2026年9月30日`.

## Date granularity and admission results

Intended conservative date-only rule (still correct, and implemented in the staged module for synthetic data):

- A midnight `announcementTime` is date-only, not a verified 00:00:00 clock
- CATL calendar date 2026-10-21 (Wednesday): same day and earlier, including the board dateline 2026-10-20, must stay blocked; first conservative session is 2026-10-22
- Moutai calendar date 2026-10-31 (Saturday): 2026-10-31, 2026-11-01, board dateline 2026-10-29, and storageTime calendar date 2026-10-30 must stay blocked; first conservative weekday is 2026-11-02
- `storageTime` is not a publication label
- Missing or naive `decision_at` must be refused; `DATE` is not a substitute

What actually happened on the truthful real listings, using the staged module unchanged:

| Case | decision_at (Asia/Shanghai) | Expected | Actual |
| --- | --- | --- | --- |
| CATL next session | 2026-10-22T15:00:00+08:00 | admitted, precision=date | **rejected** |
| CATL later digest cutoff | 2026-11-18T22:41:08.989419+08:00 | admitted, precision=date | **rejected** |
| Moutai next weekday | 2026-11-02T15:00:00+08:00 | admitted, precision=date | **rejected** |
| Moutai later cutoff | 2026-11-18T23:59:59+08:00 | admitted, precision=date | **rejected** |
| CATL same day | 2026-10-21T18:00:00+08:00 | withheld (date-only) | rejected (identity first; date rule not reached) |
| CATL board-dateline day | 2026-10-20T18:00:00+08:00 | withheld | rejected (identity first) |
| Moutai Saturday / Sunday / board / storageTime dates | 2026-10-31, 2026-11-01, 2026-10-29, 2026-10-30 | withheld | rejected (identity first) |
| Missing or naive decision_at | empty / no timezone | rejected | rejected (also includes the identity reasons) |
| Wrong content hash / id / code / period / pdf_url | later cutoff | rejected | rejected |

Staged runner preflight with the synthetic fixture admitted (exit 0). Staged preflight with the truthful CATL listing rejected (exit 2) for the same two body-match reasons. The official text gate in that preflight stayed MISSING; the listing path is separate and did not rewrite `公告时间` as `公告日期`.

## Mismatch to send back to cloud (do not patch locally)

The staged matcher requires the JSON `body` to contain the exact `announcement_id` string and the exact `report_period` string, and `report_period` must full-match `YYYY-MM-DD` or `20xx年x月x日` with no spaces.

Real official filings do not satisfy that as written:

1. CNINFO `announcementId` (`1225613175`, `1225649896`) appears in the official list/detail JSON and in the PDF URL / filename, but **not in the PDF bytes or extracted text**. CATL's in-body number is `公告编号：2026-097`, which is a different identifier. Moutai's PDF has no announcement number at all.
2. The extracted period-end wording is `2026 年 9 月 30 日` (spaces). The compact form `2026年9月30日` and the ISO form `2026-09-30` are not in the body.

A truthful listing record that keeps the real PDF text therefore cannot be admitted. Inventing a schema-shaped body that copies the id and a compact period into the text would make the tests go green, but it would not be source-authentic PDF correspondence, so it was not done.

Suggested cloud fix, without renaming `公告时间` and without cancelling look-ahead:

- Prove `announcement_id` by official CNINFO/exchange metadata plus the corresponding PDF URL, and optionally require the PDF file sha256, not a substring in the PDF body
- Accept the official Chinese period-end form with optional spaces (`2026 年 9 月 30 日`) when matching body text
- Keep rejecting mismatched code, id, URL, period, or hash, and keep date-only midnight on next session or later only

## Deploy status

**Not deployed.** The live non-repo runner is unchanged:

`/workspace/tradingagents-runs/run_ta.py` sha256 `4dac0876f434b93b666b8663171317f0e3ef89f32ed60ea77a5d00411a4f5f4b`

Reason: the 19 isolated tests passed, but the two real-name positive cases did not admit, and the real date-only negative path could not be exercised past the body-match rejection. The deployment rule required both the 19 tests and the real positive and negative cases to pass.

No model was run. No rollback copy was applied because the live file was not replaced.

## Attachable paths for cloud

- Real fixtures + manifest: `/workspace/tradingagents-data-audit/2026-11-20/cninfo-publication-compat/`
- Index: `fixtures/index.json`
- Truthful listings: `fixtures/300750.SZ/listing_v1_truthful.json`, `fixtures/600519.SH/listing_v1_truthful.json`
- This report: `acceptance/ACCEPTANCE.md`
- Real preflight JSON: `acceptance/real_listing_preflight.json`
- Isolated test log: `acceptance/isolated_pytest.log`
- Staged preflight logs: `acceptance/staged_synthetic_preflight.log`, `acceptance/staged_real_catl_preflight.log`
- Cloud extract: `/workspace/tradingagents-data-audit/2026-11-20/cninfo-listing-on-4dac0876-extract/cninfo-listing-on-4dac0876/`
