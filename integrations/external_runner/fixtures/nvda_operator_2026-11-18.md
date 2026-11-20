# Official material (operator-verified) — NVDA
ticker: NVDA
price_session_date: 2026-11-18
decision_at: 2026-11-18T22:41:08.989419+08:00
compile_time: 2026-11-18 22:41:08 Asia/Shanghai (UTC+8)
OFFICIAL_Q3_FY27_20261117_ISSUER_PR
This digest was compiled by the operator from official issuer documents already read in full (or official exchange PDFs). It is not a live auto-install of acquire_sentiment.py / refresh_current.py, and it does not enable the blocked SEC collector. SEC EDGAR was not queried (no compliant User-Agent). No clock was invented where the official text only gives a date.

## How dates are kept separate
- Price session (DATE for the runner): 2026-11-18. This is the **US regular session in progress**, not the official 2026-11-18 close. Futu public quote last 156.05 USD at exchange time 2026-11-18 09:36:40 America/New_York / 2026-11-18 22:36:40 Asia/Shanghai (UTC+8). Previous official regular close was 155.46 USD on 2026-11-17. After-hours 2026-11-17 last 162.95 USD and 2026-11-18 pre-market 159.20 USD are different sessions; do not treat any of them as today's official close or as each other.
- Official results dateline in the issuer press release: SANTA CLARA, Calif., Nov. 17, 2026 (GLOBE NEWSWIRE). No clock is stated in the release body; none was invented. The 2:00 p.m. PT conference call announced earlier is a call time, not used here as a filing clock.
- Report period: third quarter of fiscal 2027 ended October 25, 2026 (Q3 FY27). This replaces earlier FY27 periods and the July 2026 10-Q as the latest disclosed official quarterly results. Do not treat the 2026-11-13 TradingAgents Sell, or the 2026-11-15 digest, as a post-results view.
- Compile time of this digest: 2026-11-18 22:41:08 Asia/Shanghai (UTC+8).

## Official sources used
1) Issuer newsroom press release: https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-third-quarter-fiscal-2027
   Local official PDF: official/nvda-q3-fy27-ir.pdf sha256 9a18609509e46dd846f7e1f9bc18445807f332314ff28c1d27b329082dab3813
   Local previously saved HTML used as a cross-check: /workspace/investment-analysis-history/market-updates/2026-11-18/web/nvidia-q3-fy27-pr.html sha256 af68faccd7740180ef24188d504c37d8ca5caedd31c275cf23e33faff6d0f5d3
   Figures below were read from the official PDF body (and the matching income-statement tables). Currency is USD. Statement tables are in millions; highlights also use billions. No unit conversion was performed beyond stating both where the issuer did.

## Financial report
Latest official quarterly results — quarter ended October 25, 2026 (unaudited; USD):

Issuer highlights (billions except per share):
- Revenue $115.8 billion, +20% quarter-over-quarter, +103% year-over-year (vs Q2 FY27 $96.2 and Q3 FY26 $57.0).
- GAAP gross margin 74.8%; non-GAAP 74.9%.
- GAAP operating expenses $9.2 billion; operating income $77.5 billion (+22% q/q, +115% y/y); net income $65.3 billion (+9% q/q, +105% y/y); diluted EPS $2.70.
- Non-GAAP operating expenses $8.8 billion; operating income $77.9 billion; net income $64.9 billion; diluted EPS $2.68. Non-GAAP diluted EPS is slightly below GAAP diluted EPS in this official table; do not “correct” that.
- Data Center revenue $107.6 billion, +21% q/q, +110% y/y.
- Edge Computing revenue $8.2 billion, +14% q/q, +42% y/y.

Condensed statements (USD millions), quarter ended October 25, 2026 vs year-ago quarter:
- Revenue 115,844 vs 57,006.
- Cost of revenue (GAAP) 29,168 vs 15,157; GAAP gross profit 86,676; GAAP gross margin 74.8%.
- GAAP operating income 77,520 vs 36,010.
- GAAP net income 65,287 vs 31,910.
- Basic EPS $2.71; diluted EPS $2.70 (diluted weighted-average shares 24,186 million).
- Nine months ended October 25, 2026 (do not treat as the current quarter): revenue 293,681; GAAP operating income 194,791; GAAP net income 183,297; diluted EPS $7.55. Keep this cumulative period separate from the quarter.

Cash and balance sheet (USD millions):
- Q3 net cash provided by operating activities 48,253; issuer free cash flow 43,777.
- Cash and cash equivalents at end of Q3 29,089; total assets 372,188.
- During Q3 FY27 the company returned $28.1 billion to shareholders (repurchases and cash dividends). Remaining repurchase authorization about $227.3 billion after a $150 billion authorization increase in September 2026, without expiration.
- Next quarterly cash dividend $0.25 per share, payable December 23, 2026, to holders of record December 2, 2026.

Outlook (forward-looking, not historical results; Q4 FY27 includes an additional week):
- Revenue expected $130.0 billion plus or minus 3%. The company is not assuming any Data Center compute revenue from China in this outlook.
- GAAP and non-GAAP gross margins expected between 71.0% and 72.0%.
- GAAP / non-GAAP operating expenses expected approximately $11.0 billion and $10.7 billion.
- Full-year FY27 GAAP and non-GAAP tax rates expected 16.0%–18.0%, excluding discrete items and material tax-environment changes.

Other official events in the same release (not financial-statement line items): Vera Rubin NVL72 has begun shipping; the company announced an agreement to acquire Hugging Face (an announced agreement, not treated here as a closed deal unless a later official close notice is read). Colette Kress is identified in the release as interim CEO and EVP and CFO.

## Current price (not a fundamental figure)
US.NVDA regular-session **intraday** last 156.05 USD at 2026-11-18 09:36:40 America/New_York / 22:36:40 Asia/Shanghai (UTC+8), prev official close 155.46 USD (2026-11-17). Not an official close. Source: Futu public quote_stock_quote only; no account data was read.

## Options and social
A same-date options digest may be built by the existing runner hook into options_digest_NVDA_2026-11-18.md. Do not fall back to options_digest_NVDA_2026-11-13.md. This compile did not collect X/Twitter or other social posts. Xueqiu, if attached, comes only from the runner’s existing hook.

## What this run is not
- Not a reuse of the 2026-11-13 Sell or of pre-Q3 FY27 financials as if they were current.
- Not an automatic collector install.
- Official fundamentals-hook availability time: the issuer dateline has a date only. No HKEX listing clock exists for this US listing, and none was invented. Official figures in this digest are still intended to enter analysis via the news/sentiment injection path.
