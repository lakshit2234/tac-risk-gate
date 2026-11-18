# Experiment Log

| Date | What was tried | Result |
|------|----------------|--------|

## Known data limits

Checked 2026-11-18 against the Binance USDⓈ-M Futures docs, page "Market Data - Futures (USDⓈ-M) REST API | Binance Developer Docs" (developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/...). Exact wording quoted from the docs.

| Data | Endpoint | What the docs say | Status |
|------|----------|-------------------|--------|
| Open interest history | `/futures/data/openInterestHist` (page: Open Interest Statistics) | "Only the data of the latest 1 month is available." `limit` max 500 | Verified |
| Long/short ratio (global accounts) | `/futures/data/globalLongShortAccountRatio` (page: Long/Short Ratio) | "Only the data of the latest 30 days is available." `limit` max 500 | Verified |
| Top trader long/short account and position ratios | pages "Top Trader Long/Short Account Ratio" and "Top Trader Long/Short Position Ratio" | Listed in the docs navigation; the text was cut off in my fetch, so the history limit was not read | **Unverified** |
| Liquidations | only "User's Force Orders (USER_DATA)" (Trade section) appears in the navigation | Description not readable in my fetch, so its history limit and whether any public liquidation history endpoint exists are not confirmed. A USER_DATA endpoint is for authenticated account data, so it is not public market data | **Unverified** |

Consequence for planning: open interest and long/short ratio history from the public REST API reaches back only about 1 month, so it cannot be backfilled to 2025-07-15. Any feature using them must be collected forward in time (start recording now) or taken from another source. Liquidation data should be treated as unavailable until verified. Do not design Phase 2 features around these until then.

Other limits seen on the same page, for reference: `/fapi/v1/aggTrades` "only trade histories within the past 48 hours (counted from now) can be queried"; `/fapi/v1/historicalTrades` "Only supports data from within the last one month."

## Gate 1: klines quality check

| Date | What was tried | Result |
|------|----------------|--------|
| 2026-11-18 | `python -m tacgate.data.quality_klines` on data/raw/binance_TACUSDT_1m.csv (read-only; CSV hash identical before and after) | PASS. 707,389 rows, 2025-07-15 10:30 to 2026-11-18 16:18 UTC, 0 gaps, 0 missing, 5,814 zero-volume candles (warning). Report: docs/quality_klines_report.md |

## Gate 1: funding quality check

| Date | What was tried | Result |
|------|----------------|--------|
| 2026-11-18 | `python -m tacgate.data.quality_funding` on data/raw/binance_TACUSDT_funding.csv (read-only; CSV hash identical before and after) | PASS. 2,947 rows, 2025-07-15 12:00 to 2026-11-18 16:00 UTC. Intervals: 2,945 x 4h (2,156 of them off by milliseconds, within -24..+26 ms) and 1 x 8h at 2026-06-24 00:00 -> 08:00 UTC, so one funding record (04:00 UTC) is missing. This explains 2,947 rows vs 2,948 on a 4h grid. 181 rates above 0.0005 and 22 below -0.0005 flagged and kept (max +0.00521896 on 2025-11-26 16:00 UTC). 0 blank/zero markPrice. Report: docs/quality_funding_report.md |
