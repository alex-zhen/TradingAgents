# Official material (operator-verified) — 0700.HK
ticker: 0700.HK
price_session_date: 2026-11-18
decision_at: 2026-11-18T19:34:57.536861+08:00
compile_time: 2026-11-18 19:34:57 Asia/Shanghai (UTC+8)
OFFICIAL_Q3_20261118_HKEX_1630
This file was compiled by the operator from official issuer and HKEX documents for this decision. It is not a live auto-install of the collector, and it is not a collector self-fetch of options or social posts.

## How dates are kept separate
- Price session (HK regular close used as DATE): 2026-11-18. Close 372.80 HKD. Exchange time 2026-11-18 16:07:58 Asia/Shanghai (UTC+8). Source: Futu public quote, cross-checked with the OpenBB/yfinance equity digest close 372.80.
- Official results dateline in the press release: Hong Kong, 18 November 2026.
- HKEX listing datetime for the results announcement: 18/11/2026 16:30 (title: ANNOUNCEMENT OF THE RESULTS FOR THE THREE AND NINE MONTHS ENDED 30 SEPTEMBER 2026). This is not the press-release dateline and not the 20:00 Asia/Shanghai webcast time on the IR calendar.
- Report period: unaudited results for the quarter (and nine months) ended 30 September 2026. This replaces H1 / Q2 2026 as the latest disclosed official results. Do not treat the 2026 Interim Report (dateline 12 August 2026; HKEX listing 25/08/2026 16:53) as the current quarter.
- Fetch/compile time of this digest: 2026-11-18 19:34:57 Asia/Shanghai (UTC+8).

## Official sources used
1) Issuer press release PDF: https://www.tencent.com/wp-content/uploads/2026/11/Tencent-Announces-2026-Third-Quarter-Results.pdf
   sha256 1e80791b9c53c8b2bb128de36b6792623a951fd531c3157239f41329ddad82ba
   Tencent IR news item dated November 18, 2026: “Tencent Announces 2026 Third Quarter Results”.
2) HKEX-listed announcement (byte-identical to the issuer E700_3Qresults.pdf):
   https://www1.hkexnews.hk/listedco/listconews/sehk/2026/1118/2026111800448.pdf
   sha256 cc70d57e4a3677f0ac9bb28085b8a9f1c2c83e49cbdae3a0d916cd82624d9614
3) Isolated collector run at 2026-11-18 19:34:04 Asia/Shanghai (UTC+8), price date 2026-11-18, also selected this Q3 announcement (publication_dateline 18 November 2026; HKEX 18/11/2026 16:30) and passed its content gate. That isolated output was not installed over any live digest.

## 3Q2026 official figures (RMB)
From the issuer press release and the HKEX announcement (RMB in millions unless the press release states billions):
- Revenues 207,336 million (press release: RMB207.3 billion), +8% YoY; vs 2Q2026 revenues 204,785 million, +1% QoQ.
- Gross profit 115,911 million (RMB115.9 billion), +7% YoY.
- IFRS operating profit 59,147 million (RMB59.1 billion), -7% YoY.
- IFRS profit for the period 65,139 million (RMB65.1 billion), +0.3% YoY.
- IFRS profit attributable to equity holders 63,612 million (RMB63.6 billion), +0.8% YoY.
- IFRS basic EPS RMB7.059; diluted RMB6.947.
- Non-IFRS operating profit 68,073 million (RMB68.1 billion), -6% YoY. Operating profit excluding New AI Products RMB83.3 billion, +8% YoY.
- Non-IFRS net profit RMB68.4 billion, -6% YoY; attributable RMB66.5 billion, -6% YoY; basic EPS RMB7.382.
- Capital expenditure payments RMB65.1 billion, +225% YoY.
- Free cash flow RMB-69.1 billion (operating cash inflow RMB2.6 billion less capex 65.1, media content 4.6, lease 2.0). Excluding compute-procurement prepayments, the company stated FCF would have been +RMB16.9 billion.
- Total cash RMB525.7 billion; net debt RMB13.7 billion.
- Segment revenues 3Q2026: VAS RMB98.3 billion (+3% YoY); Marketing Services RMB43.0 billion (+19% YoY); FinTech and Business Services RMB63.7 billion (+9% YoY). Cloud revenue in Business Services +35% YoY.
Currency is RMB as printed. No unit conversion was performed.

## Current price (not a fundamental figure)
HK.00700 regular-session close 372.80 HKD on 2026-11-18 (prev close 376.00). This is the price-session input, not the 3Q report date.

## Options and social — what is and is not in this run
- A same-date equity/options digest was built at 2026-11-18 19:33 Asia/Shanghai (UTC+8) into options_digest_0700.HK_2026-11-18.md. Close 372.80; last-day volume 21.3M = 0.80x 20d average; 20d realized vol 39.7%. Hong Kong listed options are not available from the free OpenBB providers; do not treat equity volume as an options chain, and do not fall back to the 2026-11-13 options file.
- 2026-11-18 X / Twitter posts were not freshly collected for this run. The 2026-11-17 public gapfill remains in /workspace/tencent-data-gap-backfill/2026-11-17/ta_feed/ and is prior-session material; it was not pasted here so that stale 11/17 social or prices would not be mistaken for today.
- This collector did not auto-fetch options or social posts. Xueqiu, if attached, comes only from the runner’s existing hook.

## What this run is not
- Not a rerun that still uses only H1 / Q2 2026 results.
- Not an automatic live install of acquire_sentiment.py / refresh_current.py (BABA SEC-skip discovery gap is still open; those scripts stay out of the live runs directory).
- Not a 29-name batch. Only 0700.HK is being run if this file is used.
