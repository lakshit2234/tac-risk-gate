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

## Forward recorder (data Binance does not keep long)

Verified 2026-11-18 against the Binance USDⓈ-M docs page "Market Data - Futures (USDⓈ-M) REST API" plus live read-only checks.

| Dataset | Endpoint | Docs | Live check |
|---|---|---|---|
| Open interest | `/futures/data/openInterestHist` | period 5m listed; `limit` default 30, max 500; "Only the data of the latest 1 month is available."; weight 0, 1000 req / 5 min / IP; fields symbol, sumOpenInterest, sumOpenInterestValue, CMCCirculatingSupply, timestamp; periods with no trades are omitted | as documented |
| Global long/short account ratio | `/futures/data/globalLongShortAccountRatio` | same period/limit; "Only the data of the latest 30 days is available."; fields symbol, longShortRatio, longAccount, shortAccount, timestamp | as documented |
| Top trader long/short position ratio | `/futures/data/topLongShortPositionRatio` | **docs text not readable in my fetch (page truncated)**; history limit unverified in docs | works; same fields as global ratio (symbol, longShortRatio, longAccount, shortAccount, timestamp); same ~30 day startTime limit |
| Taker buy/sell volume | `/futures/data/takerlongshortRatio` | **docs text not readable in my fetch**; history limit unverified in docs | works; fields buySellRatio, buyVol, sellVol, timestamp (**no symbol field**); same ~30 day startTime limit |
| Mark price / funding | `/fapi/v1/premiumIndex` | weight 1 with symbol; fields symbol, markPrice, indexPrice, estimatedSettlePrice, lastFundingRate, interestRate, nextFundingTime, time | as documented |
| Order book | `/fapi/v1/depth` | limit values 5, 10, 20, 50, 100, 500, 1000; weight 5 at limit 100; fields lastUpdateId, E, T, bids, asks | as documented |

Differences between the docs and the live API that shaped the design:
- `limit` max is 500 in the docs, but the live API also accepted 501 and 1000. Not relied on; the recorder uses 500.
- A `startTime` older than about 31 days returns HTTP 400 code -1130 (30.5 days was accepted). Backfill starts at now minus 30 days.
- With `startTime` but no `endTime`, the API returns the LATEST `limit` rows, not rows going forward from `startTime`. Backfill therefore always sends both and walks forward in windows of 500 periods.
- An unsupported period such as 1m returns an empty list, not an error.
- Timestamp meaning (inferred from live fetch times, not documented): open interest and the two long/short ratios already had a row labelled at the 5-minute boundary about 20 seconds after it, while taker volume had only the previous label, so taker rows look labelled by period START (known about 5 minutes after the label) and the others by sample time. Until confirmed, use `fetched_at_ms` as the earliest time a recorded row was known, and treat backfilled rows as known no earlier than their `fetched_at_ms`.

| Date | What was tried | Result |
|------|----------------|--------|
| 2026-11-18 | Built `recorder.py` (`backfill`, `run`). Every row carries `fetched_at_ms` (local UTC clock when the response arrived; for backfill it is the fetch time, not the period time). Snapshot file adds premium index plus depth (100 levels) metrics: spread, depth within 0.5/1/2% of mid, and slippage vs mid for market buy/sell of 1000 and 5000 USD, blank plus `filled_ok=0` when the book is too thin. Errors and gaps go to data/raw/recorder_errors.log; stops only on HTTP 418 or 10 consecutive failed cycles. All data/raw files are git-ignored (checked with `git check-ignore`). | Live: backfill added 8,641 rows to each of the 4 history files (30 days, no omitted periods, 0 duplicates); `run --interval 60` for 2 cycles wrote 2 snapshot rows (spread 8.4 bps, ask/bid depth within 2% about 45-52k USD, slippage 7-25 bps, filled_ok=1). The 100-level book reached about 8-9% from mid, so the 2% bands were not truncated at that time. The 2 cycles added no new 5-minute history rows because no new period had closed yet. No errors logged. |

## Gate 1: recorder quality check

| Date | What was tried | Result |
|------|----------------|--------|
| 2026-11-19 | `python -m tacgate.data.quality_recorder` on data/raw (4 history files, snapshot file, recorder_errors.log), read-only (hashes identical before and after; recorder was not running, but the checker reads each file once and ignores a partial last line, so it is safe while the recorder appends). Backfilled = fetched_at_ms - timestamp > 15 min, otherwise live. | PASS, with warnings. History: 8,654 rows each, 2026-10-19 17:25 to 2026-11-18 18:30 UTC (taker ends 18:25), 100% slot coverage, 0 gaps, 0 look-ahead violations, 0 consistency flags. Live rows: 12 (taker 10) of 8,654; live coverage 75% to the last row (66.7% taker) and about 4.5% to now. The recorder was last seen 2026-11-18 18:35 UTC, about 1,244 min before the check, so it was STOPPED; there is no overnight gap inside the files because nothing was written overnight, the data simply ends. The 17:30-18:00 slots (the 34 min restart gap logged at 18:01) are present only because a second backfill at 18:01 filled them (fetched_at_ms 18:01, lag 6-37 min), which is why coverage is 100% but live coverage is 75%. Snapshot: 9 rows, 1.15 h span, 0.52 h covered, 1 gap above 10 min (17:27 to 18:05), filled_ok 100%, median spread 8.4 bps, no flags. Report: docs/quality_recorder_report.md |

Findings from the data (not fixed here):
- Live fetch lag is one full cycle too long: with the 5 s cycle offset, the history row labelled at a boundary is not published yet, so each cycle stores the previous label. Open interest and long/short rows have a median fetched_at_ms - timestamp of 5.1 min; taker rows 10.1 min (period-start label plus one cycle). The newest period is therefore always one cycle behind, and the final period before a stop is never captured. Possible fix, to be tested: a larger CYCLE_OFFSET_MS (the label appeared within 21 s in the 17:25 backfill, not within 5 s).
- Taker volume label looks like the period START (confirmed by the 10.1 min live lag: a period closes 5 min after its label).
- The first and last 3 or so rows of a backfill count as "live" under the 15-minute rule (their lag is under 15 min), so live row counts include a few backfill rows.

## Fix: recorder cycle offset 5 s -> 45 s

| Date | What was tried | Result |
|------|----------------|--------|
| 2026-11-19 | **Problem:** `run` fired 5 s after each 5-minute boundary, but Binance had not published the history row labelled at that boundary yet, so every live cycle stored the previous label. **Evidence** (Gate 1 recorder check, docs/quality_recorder_report.md): live open interest and long/short rows had a median fetched_at_ms - timestamp of 5.1 min (an exact one-label lag), taker rows 10.1 min, and the last period before a stop was never captured (the log of the 18:00-18:35 UTC run shows rows labelled 18:05..18:30 fetched at 18:10..18:35, never the newest label). In the 17:25 backfill the open-interest row labelled 17:25:00 was already present at 17:25:21, so publication takes somewhere between 5 and 21 s. **Fix:** `CYCLE_OFFSET_MS` 5_000 -> 45_000 (named constant with a comment), roughly twice the observed delay. Unchanged: latest 2 periods per cycle with dedupe (a late row is still caught next cycle), snapshot taken in the same cycle with its real fetched_at_ms, file formats, columns, dedupe logic, backfill. Tests (mocked, with a fake API that publishes rows 21 s late) cover: next cycle = next boundary + 45 s; waiting at 44 s; a boundary-labelled row stored in that cycle; the old 5 s offset storing the previous label (regression); a late row caught one cycle later with no duplicates. | Tests pass (203). **Not yet verified on real data**: the running recorder keeps the old offset until it is restarted. **Expected after restart** (new live rows only): fetched_at_ms - timestamp about 45 s for open interest and long/short, and about 5 min 45 s for taker (its label is the period start, so a period closes 5 min after its label). If live open interest rows still show a lag near 5 min, 45 s is not enough and the real publication delay must be measured. |

## Recorder lag analysis (is a 45 s cycle offset enough?)

| Date | What was tried | Result |
|------|----------------|--------|
| 2026-11-20 | `python -m tacgate.data.lag_analysis` (read-only, no network; each file read once, partial last line ignored; recorder not started or stopped). Rows with fetched_at_ms >= 1795104000000 (2026-11-19 16:00 UTC, restart with the 45 s offset); lag = fetched_at_ms - timestamp, taker minus a further 300 s (label = period start); lag above 15 min skipped as backfilled. Buckets by lag after close: first-cycle < 120 s, second 120-420 s, later > 420 s. Report: docs/lag_analysis_report.md. Tests: synthetic CSVs only. | 284 live rows per file, 0 backfilled in the window. **First-cycle capture: open interest 20.4%, global long/short 30.5%, top-position long/short 29.8%, taker 7.0%.** The rest were second-cycle (lag after close p50 about 345 s, max about 416 s); **none "later"**. So with the 45 s offset the row labelled at a boundary is usually NOT yet published, and is picked up by the next cycle (5 min later, when the cycle fetches the latest 2). No clustering by UTC hour or by position in the quarter hour. The three non-taker files disagree on the same timestamp: all first-cycle 2.8%, all not first-cycle 42.6%, mixed 54.6% (publication is per endpoint, not per period). Resolution is limited: with 5-minute cycles a late row can only show as about 45 s or about 345 s, so this cannot say how long publication really takes (somewhere between 45 s and 345 s). No offset recommended here; that needs a finer measurement. |

**Conclusion (lag analysis):**
- The 45 s offset is not enough to catch a period's row in the first cycle: only 7 to 31 percent of rows are captured there (open interest 20.4%, global long/short 30.5%, top-position long/short 29.8%, taker 7.0%).
- No row is lost. Each cycle fetches the latest 2 periods, so a row missed in its first cycle is picked up in the next one. No row was later than the second cycle.
- `fetched_at_ms` stays the known-by time for live rows.
- For backfilled rows the true known time is unknown, so Phase 2 features must use timestamp + 10 minutes as the known-by time.
- The offset is left unchanged (recorder.py not touched). It is revisited only if live freshness is needed.
- The report docs/lag_analysis_report.md lists only the 20 most recent late rows per file; the total count of late rows is still shown.

## CoinGecko market_chart fetcher (market cap and volume, daily)

| Date | What was tried | Result |
|------|----------------|--------|
| 2026-11-20 | Built `src/tacgate/data/coingecko_market_chart.py` as approved in docs/phase0_sources.md. One request per run to `GET https://api.coingecko.com/api/v3/coins/tac/market_chart?vs_currency=usd&days=365&interval=daily` (coin id `tac`, no key; re-verified live before coding). Saves RAW fields only (`timestamp_ms, price, market_cap, total_volume, fetched_at_ms`) to `data/raw/coingecko_TAC_market_chart_daily.csv`. Points on the current UTC day are skipped (the last point CoinGecko returns is a live partial day). Append-only with dedupe by `timestamp_ms`; partial last line repaired; shape change, 401/403 (incl. error 10012) raise at once; 429 and 5xx retried with backoff and Retry-After. Revision check: stored days are only compared with the new values, never overwritten; the report (count, largest relative change in price/market_cap/volume, up to 10 changed days) is printed, logged, and appended to `<out>_revisions.log` when anything changed. Tests: 45 mocked, no network (268 total pass). **Live run, once:** 364 rows added, 2025-11-21 to 2026-11-19, 0 missing days inside the range, 2 points skipped on the current day, 0 revisions (nothing was stored before). | CoinGecko's price is NOT to be used as a price (it differed from Binance by more than 2% on 73 of 363 days); this file is for market cap and volume, with mismatch days excluded. Revision question (does CoinGecko change past days?) is open until the next run. **Operational note: this run must be repeated at least every few weeks.** The free tier only serves the last 365 days and the window moves forward daily, so days before the first stored date (2025-11-21) are unrecoverable on the free tier, and any day not captured before it leaves the window is lost for good. The newest stored row is the previous midnight (a point stamped D 00:00 UTC is the value at that instant). |

## DeFiLlama fetchers (chain TVL and coin price, daily)

| Date | What was tried | Result |
|------|----------------|--------|
| 2026-11-20 | Built `src/tacgate/data/defillama.py` with two subcommands, same rules as the CoinGecko fetcher (raw fields only, `fetched_at_ms` on every row, append-only, dedupe by `timestamp_ms`, revision check that logs but never overwrites, partial last line repaired, current UTC day skipped, missing days reported and not filled). `tvl`: `GET https://api.llama.fi/v2/historicalChainTvl/TAC` -> `timestamp_ms, tvl, fetched_at_ms` (API gives unix SECONDS, stored x 1000). `price`: `GET https://coins.llama.fi/chart/coingecko:tac?start=1752537600&span=<n>&period=1d` -> `timestamp_ms, price, confidence, fetched_at_ms` (confidence is one value per chart, 0.99, stored on every row). 401/402/403 raise at once; 429/5xx retried with Retry-After. Both endpoints re-verified live before coding. Tests: 62 mocked (330 total pass). **Live run, once each:** tvl 490 rows, 2025-07-18 to 2026-11-19, 0 missing days, 1 current-day point skipped; price 493 rows, 2025-07-16 to 2026-11-19, 0 missing days, 0 skipped; 0 revisions on both (first run). | Price timestamps are NOT midnight aligned (they sit seconds either side of a UTC midnight, e.g. 23:59:42 or 00:00:23) and are stored exactly as returned. Days are therefore assigned to the NEAREST midnight when counting gaps. **Correction to docs/phase0_sources.md:** it listed missing price days (2025-07-17, 07-22, 07-27, 07-31, 2026-04-30 and 2026-07-07). Those came from assigning days by floor() in my ad-hoc check and are artifacts: with nearest-midnight assignment there are 0 missing days in 493 points (consecutive points are 23.2 to 24.8 hours apart). The point nearest the 2026-07-07 crash is 2026-07-06 23:59:36 (0.03224, before the drop) and the next is 2026-07-08 00:00:01 (0.004489). **Open:** whether DeFiLlama revises history is unknown until the next run. The TVL file ends the day before today because today's midnight point is a live, still-changing value. |

## Gate 1: daily external data quality check

| Date | What was tried | Result |
|------|----------------|--------|
| 2026-11-20 | `python -m tacgate.data.quality_daily_external` on data/raw (CoinGecko market chart, DeFiLlama chain TVL, DeFiLlama price, plus the Binance 1m klines and the recorder open-interest file for cross-checks). Read-only (md5 of the three daily CSVs identical before and after), no network. Part A per file: schema, numeric, strictly increasing, positive (tvl >= 0), spacing vs 24 h with 1 h tolerance, no row on the current UTC day, fetched_at_ms >= timestamp_ms; rule stated in the report: every daily row is known at timestamp + 24 h. Part B: each price vs the Binance 1m open at the nearest minute, CoinGecko vs DeFiLlama, derived supply (market_cap / price) with steps above 1% (all labelled "cause unverified"), and derived supply vs the recorder CMCCirculatingSupply at 00:00 UTC. Tests: 26 synthetic (356 total pass). Report: docs/quality_daily_external_report.md | PASS, 0 hard failures. All three files: 0 gaps, 0 duplicates, 0 current-day rows, 0 look-ahead violations (CoinGecko 364 rows 2025-11-21 to 2026-11-19; TVL 490 rows from 2025-07-18; price 493 rows from 2025-07-16). **CoinGecko vs Binance: 73 of 363 days above 2% (all 73 also above 5%), matching the earlier research; median 0.35%, within 1% on 79.1%; 72 of the 73 are in Jan to Mar 2026 (Jan 21, Feb 26, Mar 25 days), the 73rd is 2026-08.** 72 of the 73 have CoinGecko ABOVE Binance (up to +93%, 2026-02-23: 0.00787 vs 0.00407); the one below is 2026-08-23 (CoinGecko 0.00102 vs Binance 0.00164, -38%). **DeFiLlama vs Binance: 97.6% within 1% (earlier estimate 96.5%; this uses 491 days and the nearest minute); 3 days above 2%, the largest -37.8% on 2026-08-23 (0.00102 vs 0.00164), the day after the August chain exploit was disclosed (cause unverified).** CoinGecko vs DeFiLlama: 74 days above 2%, the same Jan to Mar 2026 stretch, so DeFiLlama agrees with Binance and CoinGecko is the outlier. **Derived supply:** 2.61B on 2025-11-21 to 6.49B on 2026-11-19, 19 step candidates above 1% (all cause unverified); several come in +/- pairs that reverse the next day (2026-07-07/08: +8.3% then -7.7%; 2026-07-29/30: +6.4% then -6.0%), which looks like price and market cap sampled at different moments, not real supply changes (unverified). The step on 2026-11-19 (+329M) matches the recorder's CMCCirculatingSupply jump. **Supply vs recorder: 30 of 31 overlapping days within 0.1%;** the one mismatch is 2026-11-19 (derived 6,485,265,581 vs Binance 6,156,312,240, -5.07%), the day CoinGecko's 00:00 point already reflected an update that Binance published at 02:35 UTC. Warnings only (exit code 0): TVL changed more than 50% on 2 days (2025-07-19 +382%, 2025-08-06 +176%, both early after launch). |

**Decisions and open item (daily external checker):**
- Any CoinGecko row more than 2 percent away from the Binance price is excluded from features.
- A derived supply step counts as an event only if it persists for at least 3 days. One-day reversals look like sampling noise.
- On 2026-08-23 both CoinGecko and DeFiLlama are about 38 percent below Binance, while Bybit agrees with Binance (00:00 UTC 1m open: Binance 0.001648, Bybit 0.001647; CoinGecko 0.00102, DeFiLlama 0.00102). Hypothesis: the spot or aggregator price diverged from the perpetuals after the exploit. This is unverified and to be investigated.

## Aug 2026 price divergence (correction of an earlier hypothesis)

| Date | What was tried | Result |
|------|----------------|--------|
| 2026-11-20 | `python -m tacgate.data.divergence_check` (read-only on local files, plus ONE Binance spot request, `--fetch-spot`) for 2026-08-20 to 2026-08-26 UTC. Report: docs/aug_2026_divergence_report.md. Tests: 24 synthetic (380 total pass). | **Correction: the earlier hypothesis that the spot or aggregator price crashed while the perps held is rejected.** Both the Binance and the Bybit perps fell from about 0.0025 to about 0.00104 on 2026-08-22 at 20:20 UTC (Binance low 0.00104, Bybit low 0.001051) and recovered within hours, so the perps did not hold. The Binance spot TACUSDT request returned HTTP 400, so the spot test could not be run; the verdict is "cannot tell". A missing Binance spot market is likely but unverified (the response body was not kept, and I did not retry). On 2026-08-23 both CoinGecko and DeFiLlama show about 0.00102, which is near the perp crash low (2% below it) and 38% below the perp at 00:00 UTC (0.001648); the value is stamped 3.7 hours after the low, when the perp was already near 0.00165. Cause unverified. |

**Rule extended:** any daily external price (CoinGecko or DeFiLlama) more than 2 percent away from the Binance price is excluded from features.

**Risk note:** this coin has had a minus 40 percent day (Binance perp 2026-08-22, 0.002755 to 0.00165) and a minus 62 percent intraday wick (the same day, low 0.00104 against the day's open of 0.002755). The gate must therefore use the intraday range, not only the daily close.
