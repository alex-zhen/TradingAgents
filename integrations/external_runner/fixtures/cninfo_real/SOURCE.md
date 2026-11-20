# SOURCE.md — provenance for CNINFO publication-compat fixtures

Packaged at 2026-11-20 15:17:04 Asia/Shanghai (UTC+8).
No new public fetch was made in this pass. Required official fields already existed in the 2026-11-19 packages. No private account or collector was used. HTTP response `Set-Cookie` values were redacted in the copied header files; JSON bodies are unmodified.

Times below that originated as HTTP `Date` headers (GMT) are also shown converted to Asia/Shanghai.

## 300750.SZ / announcementId 1225613175

Original official package (do not overwrite):

- `/workspace/tradingagents-data-audit/2026-11-19/catl-hook-preflight/`
- Official date lookup notes: `OFFICIAL_DATE_LOOKUP.md` (lookup documented 2026-11-19 11:39 Asia/Shanghai)
- Evening closeout notes: `/workspace/investment-analysis-history/2026-11-19-evening-closeout/01-official-dates.md` and `official/catl/`

Official CNINFO detail API (verbatim `bulletin_detail.json` copied into `fixtures/300750.SZ/raw/`):

- POST `https://www.cninfo.com.cn/new/announcement/bulletin_detail?announceId=1225613175&flag=true`
- HTTP `Date: Thu, 19 Nov 2026 03:38:39 GMT` = 2026-11-19 11:38:39 Asia/Shanghai
- Detail page used by the Vue shell: `https://www.cninfo.com.cn/new/disclosure/detail?plate=szse&stockCode=300750&announcementId=1225613175`

Official CNINFO list API (full query JSON plus the isolated 1225613175 object):

- POST `https://www.cninfo.com.cn/new/hisAnnouncement/query` (`stock=300750`, `orgId=GD165627`, `searchkey=三季度报告`)
- HTTP `Date: Thu, 19 Nov 2026 03:39:17 GMT` = 2026-11-19 11:39:17 Asia/Shanghai
- List-page template column: `https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search&startsWithLetter=&tabName=fulltext&stockCode=300750`
- Template excerpt (unmodified): `<el-table-column width="150" align="left" prop="announcementTime" sortable="custom" label="公告时间">`

Official PDF corresponding to `fileUrl` `http://static.cninfo.com.cn/finalpage/2026-10-21/1225613175.PDF`:

- Reused file: `/workspace/tradingagents-data-audit/2026-11-18/priority7-ta/official/catl-300750-2026q3-cninfo.pdf`
- sha256 `476611fe240b90088319c852de4e89d8ab1537b858d2ffbca573af5f8c5419b3` (588,939 bytes)
- Extracted text (reused, then copied): same directory `catl-300750-2026q3-cninfo.txt`; PDF body has `证券代码：300750`, title `2026 年第三季度报告`, period-end wording `2026 年 9 月 30 日`, and an unlabeled board dateline `2026 年 10 月 20 日`
- Do not substitute the company IR PDF `q3_ir.pdf` sha256 `48c8e2717dbfd08f0afdb87b1ddb99c5c2230236d6e20a522559f2643137c3a1` (1,044,973 bytes); it is a different file

The 11/19 closeout already recorded that the SZSE announcement page was a site shell without a usable labelled date, and that CATL IR GET was 403. Those negative findings are not re-fetched here.

## 600519.SH / announcementId 1225649896

Original official package (do not overwrite):

- `/workspace/tradingagents-data-audit/2026-11-19/maotai-600519-preflight/`
- Official date lookup notes: `OFFICIAL_DATE_LOOKUP.md` (lookup documented 2026-11-19 14:18:27 Asia/Shanghai)
- Evening closeout notes: `/workspace/investment-analysis-history/2026-11-19-evening-closeout/01-official-dates.md` and `official/moutai/`

Official CNINFO detail API (verbatim `bulletin_detail.json` copied into `fixtures/600519.SH/raw/`):

- POST `https://www.cninfo.com.cn/new/announcement/bulletin_detail?announceId=1225649896&flag=true`
- HTTP `Date: Thu, 19 Nov 2026 06:16:33 GMT` = 2026-11-19 14:16:33 Asia/Shanghai
- Detail page: `https://www.cninfo.com.cn/new/disclosure/detail?plate=sse&stockCode=600519&announcementId=1225649896`

Official CNINFO list API:

- POST `https://www.cninfo.com.cn/new/hisAnnouncement/query` (`stock=600519`, `orgId=gssh0600519`, `searchkey=三季度报告`)
- HTTP `Date: Thu, 19 Nov 2026 06:16:45 GMT` = 2026-11-19 14:16:45 Asia/Shanghai
- List-page template column: `https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search&startsWithLetter=&tabName=fulltext&stockCode=600519`
- Same official column label `公告时间` / `prop="announcementTime"`

Official PDF corresponding to `fileUrl` `http://static.cninfo.com.cn/finalpage/2026-10-31/1225649896.PDF`:

- Reused file: `/workspace/investment-analysis-history/research-closeout/2026-11-18-supplement-9/official/moutai-600519-2026q3-cninfo.pdf`
- sha256 `96ba51ebf414f841bce79b3ba019927df2f795142392e12e96a9d559e96ebb9b` (193,430 bytes)
- This matches the 11/19 preflight backup and the closeout company-site PDF
- Extracted text has `证券代码：600519`, title `2026 年第三季度报告`, period-end wording `2026 年 9 月 30 日`, and an unlabeled board dateline `2026 年 10 月 29 日`

The 11/19 preflight already recorded that SSE company-announcement static pages were shells and that `query.sse.com.cn` list queries returned empty results. Those negative findings are not re-fetched here.

## Why 00:00 is treated as date-only

- Both 2026 Q3 `announcementTime` values are millisecond epochs that land on exact Asia/Shanghai midnight (remainder 0).
- The official list column and JSON field remain `公告时间` / `announcementTime`; they are not rewritten.
- `storageTime` is a separate field and, for both filings, carries a real non-midnight clock on the previous calendar evening. It is not a publication label and must not be used to invent a publication clock or to admit an earlier DATE.
- In the reused hisAnnouncement series, every CATL 2018–2026 Q3 row is midnight. For Moutai, 2013–2026 Q3 rows are midnight, while 2002–2012 rows still have non-midnight clocks (often 05:xx or 06:30). That contrast is evidence that later CNINFO values are date placeholders, not a reason to assign a clock to the 2026 filings.

## Current runner baseline

- Live runner `/workspace/tradingagents-runs/run_ta.py` sha256 `4dac0876f434b93b666b8663171317f0e3ef89f32ed60ea77a5d00411a4f5f4b` (matches the expected non-repo hash)
- Check time: 2026-11-20 15:17:04 Asia/Shanghai
- Method: executed official-fundamentals functions already contained in the live runner; did not start `run_ta.py` RUN_BODY or a model; did not change code, caches, or the existing CATL digest
- Result: MISSING for constructed `公告时间` digests of both names, and MISSING for the existing frozen digest `/workspace/tradingagents-runs/sentiment_digest_300750.SZ_2026-11-18.md` (sha256 `00417ae133bbec9495611549d86f7d6c586cd96299c18c3611321787cb0c5433`, left unchanged). No 2026-11-18 Moutai frozen digest exists.
