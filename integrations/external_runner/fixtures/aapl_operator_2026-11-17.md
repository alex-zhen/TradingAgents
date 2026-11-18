# Official material (operator-verified) — AAPL
ticker: AAPL
price_session_date: 2026-11-17
price_session: US regular official close 2026-11-17 16:00 US/Eastern = 2026-11-18 05:00 Asia/Shanghai
decision_at: 2026-11-18T22:51:20.416057+08:00
compile_time: 2026-11-18 22:51:20 Asia/Shanghai (UTC+8)
operator-verified: true
latest_discovery_verified: false
SEC_EDGAR_USER_AGENT: unset
This file was compiled by the operator from an already-verified official Form 10-K on disk and a fresh public Futu quote. It is not a live auto-install of the collector, and it is not a collector self-fetch. SEC EDGAR was not accessed in this compile (no compliant user-agent session). No contact email was invented. latest_discovery_verified is false because auto-fresh discovery was not run and SEC was skipped.

Official figures are taken from the local 10-K already retrieved earlier tonight and not re-downloaded:
- form: 10-K, fiscal year ended 26 September 2026, filed/accepted 2026-11-03 (date from the already-verified research package sources.json; an SEC accepted clock time was not extracted from the local HTML header and is not invented)
- source_url: https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm
- local: /workspace/investment-analysis-history/research-closeout/2026-11-18-supplement-9/official/aapl-20260926-10k.htm
- sha256: a57a9acaf658191789ccc31102d9e86d97dab038ae65b7efcd5a8fb1c5feafdc
- currency: USD; amounts in millions of dollars unless noted

The live runner official-fundamentals gate requires an HKEX listing datetime. AAPL is a US-only listing and has no genuine HKEX listing datetime. That field is intentionally omitted and is not invented. Official amounts below are still provided so they can reach the model through the get_news extra-context path. If the official fundamentals block is marked MISSING, that is expected for this ticker with the current unchanged runner.

## How dates are kept separate
- TradingAgents DATE / price_session: 2026-11-17, the last completed official US regular close. Official last 351.91 USD (Futu prev_close / official last for 2026-11-17 16:00 US/Eastern = 2026-11-18 05:00 Asia/Shanghai).
- decision_at: 2026-11-18T22:51:20.416057+08:00. This is the compile/decision clock in Asia/Shanghai, not the price session.
- Mid-session indicative print at the pre-launch public refresh: 355.11 USD at 2026-11-18 22:51:06 Asia/Shanghai (UTC+8) = 2026-11-18 09:51:06 US/Eastern, Futu market_state=AFTERNOON, data_date=2026-11-18, open 352.05, high 355.87, low 351.87, volume 5,001,661 (incomplete session). This print is NOT the official close and must not be written as today's official last.
- The 22:19 Asia/Shanghai PRE_MARKET package (pre_market about 351.00) is historical and must not be used as the current price.
- Do not mix this US official close with Hong Kong or Shanghai session dates.

## Financial report
Latest disclosed official annual results — Form 10-K for the fiscal year ended 26 September 2026, compared with the fiscal years ended 2025 and 2024 (USD millions except per-share data):

Fiscal year ended 26 September 2026 versus fiscal year 2025 versus fiscal year 2024:
- net sales 478,834 / 416,161 / 391,035 (2026 versus 2025 +15%)
- product net sales 355,533; services net sales 123,301 (+13%)
- iPhone 254,098 (+21%); Mac 37,929 (+13%); iPad 27,929 (flat); Wearables, Home and Accessories 35,577 (flat); Services 123,301
- Americas 198,083 (+11%); Europe 127,604 (+15%); Greater China 82,378 (+28%); Japan 30,908 (+8%); Rest of Asia Pacific 39,861 (+18%)
- gross margin 48.8% (prior year 46.9%); product gross margin 39.3%; services gross margin 76.2%
- research and development 45,765 (+32%); selling, general and administrative 29,774 (+8%)
- operating income 158,063
- net income 132,175; diluted EPS 8.98 (prior year 7.46); effective tax rate 17.0%
- operating cash flow 145,097; payments for acquisition of property, plant and equipment 9,041; repurchases of common stock 86,390; dividends and dividend equivalents 15,721
- in April 2026 the company announced a new repurchase authorization of up to 100,000; the quarterly dividend was raised from 0.26 to 0.27 per share

As of 26 September 2026:
- cash and cash equivalents 36,305; current marketable securities 20,417; non-current marketable securities 80,213; combined about 136,935 (consistent with the liquidity discussion)
- term debt carrying amounts: current 9,906 plus non-current 68,208; commercial paper 1,997; notes principal 78,700, of which 10,000 matures within 12 months
- inventories 14,541 (prior year 5,718); this increase should be tracked and not ignored
- diluted shares about 14.532 billion

The 10-K discusses fiscal 2026 launches (including iPhone Duo / 18 Pro and Siri AI / system updates), tightness and cost pressure in advanced semiconductors and memory, and import tariffs affecting multiple countries from the second quarter of 2025. These are company disclosures, not third-party news confirmation.

document_coverage: fiscal year ended 26 September 2026
This 10-K is an annual report, not a quarterly 10-Q. Do not label these figures as a September 2026 quarter only. Vendor quarterly statements, if earlier than this 10-K, are stale relative to this official report and must not be called the latest official filing.

source_url: https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl-20260926.htm

## Other constraints for this run
- Do not invent a target price.
- Do not read or assume private account, margin, or position data.
- The 2026-11-13 TradingAgents report and any page historical DATA row are not this run's conclusion.
- This digest is only for AAPL. Do not attach it to any other ticker.
