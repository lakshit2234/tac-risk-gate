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

## Bybit klines fetcher (cross-exchange price check)

| Date | What was tried | Result |
|------|----------------|--------|
| 2026-11-18 | Built `bybit_klines.py` (public `GET /v5/market/kline`, category=linear, TACUSDT, interval 1, limit 1000 max per docs "Get Kline"). Bybit returns newest first; rows are sorted ascending and de-duplicated. Fixed windows of 1000 minutes, so empty or short pages never end the download. Only closed candles saved (the close of an open candle is just the last traded price per docs). 403 raises immediately (docs: 403 = "access too frequent", wait at least 10 minutes; also used for region blocks). First kline detected from instruments-info launchTime: Bybit's first TACUSDT 1m kline is 2025-07-15 11:00:00 UTC (Binance starts 10:30 UTC, so the two files do not start together). Live test of 1 hour (2026-11-18 10:00-10:59 UTC, 60 rows) written to a scratch file, not data/raw; re-run added 0 rows. Full download NOT run yet. | OK |

## Cross-exchange klines check: Binance vs Bybit

| Date | What was tried | Result |
|------|----------------|--------|
| 2026-11-18 | `python -m tacgate.data.crosscheck_klines` (read-only on both CSVs; hashes identical before and after). Part A: Bybit quality. Part B: compare on shared timestamps. | PASS (Part A clean, Part B flags only). Bybit: 707,404 rows, 2025-07-15 11:00 to 2026-11-18 17:03 UTC, 0 gaps, 123,561 zero-volume candles (about 17%, vs 5,814 on Binance). Overlap 707,359 minutes; Binance-only 30 (before Bybit starts) and Bybit-only 45 (Binance download ends earlier), none inside the shared range. All-time low: Binance 0.000859 (2026-11-08 21:55 UTC), Bybit 0.000863 (2026-11-13 03:53 UTC); all-time high 0.0687 vs 0.06888, both 2026-06-30 14:21 UTC. No low below 0.0005 in either file, so 0.00031 never appears. Close diff (Bybit/Binance-1): mean -0.089%, median -0.088%, p99 of absolute 0.53%, max absolute 37.4% (2025-10-10 21:21 UTC). 328 minutes differ by more than 1%, concentrated on 2025-10-10 (90), 2025-11-26 (82) and 2026-07-07 (77). Correlation of 1m close-to-close returns 0.906. Report: docs/crosscheck_klines_report.md |
