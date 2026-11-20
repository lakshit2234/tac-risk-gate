# Gate 1 summary: data quality for Phase 0

Written 2026-11-20 (UTC). Nothing was fetched or re-checked for this page. Rows, first and last timestamps and days are read-only counts of the files in `data/raw/` and `data/static/` taken at about 17:02 UTC on 2026-11-20 (they agree with the reports wherever a report states the same number). Checks and verdicts come from the report named in each row. "Days" = last minus first timestamp.

## 1. Sources

| Source (file) | Rows | First to last (UTC) | Days | Checks done (report) | Gate 1 verdict | When a row counts as known |
|---|---|---|---|---|---|---|
| Binance perp 1m klines (`binance_TACUSDT_1m.csv`) | 707,389 | 2025-07-15 10:30 to 2026-11-18 16:18 | 491.2 | gaps (0), expected row count, zero-volume candles, min and max price, largest 1-minute returns flagged, not removed (`quality_klines_report.md`: PASS; 5,814 zero-volume candles) | **pass** | at the candle's close (open + 1 minute); the fetcher stores only closed candles (`binance_klines.py`) |
| Bybit perp 1m klines (`bybit_TACUSDT_1m.csv`) | 707,404 | 2025-07-15 11:00 to 2026-11-18 17:03 | 491.3 | gaps (0), zero-volume candles, cross-check against Binance (`crosscheck_klines_report.md`: PASS; 123,561 zero-volume candles; 328 minutes where closes differ by more than 1%) | **pass** (cross-check only) | at the candle's close |
| Binance funding (`binance_TACUSDT_funding.csv`) | 2,947 | 2025-07-15 12:00 to 2026-11-18 16:00 | 491.2 | interval spacing, row count vs a 4 h grid, rate and mark price checks (`quality_funding_report.md`: PASS; one 8 h gap; 181 rates above 0.0005 and 22 below -0.0005, kept) | **pass** | at its fundingTime, never earlier (decided; the file has no fetched_at_ms) |
| Recorder open interest (`binance_TACUSDT_open_interest_5m.csv`) | 9,211 | 2026-10-19 17:25 to 2026-11-20 16:55 | 32.0 | schema, gaps (0), look-ahead (0), live vs backfilled (`quality_recorder_report.md`, checked 2026-11-19 15:25: PASS) | **pass with rule** | live rows: fetched_at_ms. Backfilled rows: timestamp + 10 min |
| Recorder global long/short (`..._global_long_short_5m.csv`) | 9,211 | 2026-10-19 17:25 to 2026-11-20 16:55 | 32.0 | same report: PASS | **pass with rule** | same rule |
| Recorder top-position long/short (`..._top_position_long_short_5m.csv`) | 9,211 | 2026-10-19 17:25 to 2026-11-20 16:55 | 32.0 | same report: PASS | **pass with rule** | same rule |
| Recorder taker buy/sell (`..._taker_buy_sell_5m.csv`) | 9,212 | 2026-10-19 17:20 to 2026-11-20 16:55 | 32.0 | same report: PASS | **pass with rule** | same rule (the taker label is the period start) |
| Recorder depth snapshot (`binance_TACUSDT_snapshot.csv`) | 318 | 2026-11-18 17:26 to 2026-11-20 17:01 | 2.0 | schema, row checks, gaps above 10 min (`quality_recorder_report.md`: PASS; coverage warning) | **pass with rule** (too short to use) | fetched_at_ms (the real fetch time). Gaps are permanent: there is no backfill source |
| CoinGecko daily (`coingecko_TAC_market_chart_daily.csv`) | 364 | 2025-11-21 to 2026-11-19 | 363.0 | schema, gaps (0), look-ahead (0), cross-check vs Binance and DeFiLlama (`quality_daily_external_report.md`: PASS; 73 of 363 days more than 2% from Binance) | **pass with rule** | timestamp + 24 h |
| DeFiLlama chain TVL (`defillama_TAC_chain_tvl_daily.csv`) | 490 | 2025-07-18 to 2026-11-19 | 489.0 | schema, gaps (0), look-ahead (0); 2 days with TVL change above 50% flagged (`quality_daily_external_report.md`: PASS) | **pass with rule** | timestamp + 24 h |
| DeFiLlama price (`defillama_TAC_price_daily.csv`) | 493 | 2025-07-16 to 2026-11-19 | 492.0 | schema, gaps (0), look-ahead (0), cross-check vs Binance (`quality_daily_external_report.md`: PASS; 97.6% of days within 1% of Binance, 3 days above 2%) | **pass with rule** | timestamp + 24 h |
| Static tokenomics (`data/static/tokenomics.csv`) | 18 | no dates (retrieved 2026-11-20) | n/a | validator `static_events.py`: 0 errors; 16 sourced, 2 unverified; the 12 allocation rows sum to 100 | **pass with rule** | static constants: only for time since TGE (2025-07-15) and cliff dates derived from the TGE-relative terms; retrieved_at_utc is not a known time (decided) |
| Static events (`data/static/events.csv`) | 25 | 2025-07-15 to 2026-10-16 (event dates) | n/a | validator: 0 errors; 6 sourced, 19 unverified; 3 rows with empty known_at_utc | **pass with rule** | known_at_utc of each row; empty means never used |

No source fails a hard check. The recorder rows are counted today; `quality_recorder_report.md` itself was written on 2026-11-19 and has not been regenerated since.

## 2. Rules that are now fixed

- A CoinGecko or DeFiLlama daily price more than 2 percent away from the Binance price is excluded from features. CoinGecko is never used as a price (73 of 363 days off by more than 2%, nearly all in Jan to Mar 2026); it is kept for market cap and volume only.
- A derived supply step counts as an event only if it persists at least 3 days. One-day reversals look like sampling noise.
- Daily external rows (CoinGecko, DeFiLlama TVL, DeFiLlama price) are known at timestamp + 24 h, never earlier.
- Backfilled recorder rows are known at timestamp + 10 minutes. Live recorder rows are known at fetched_at_ms.
- Exploit and all other event labels are not usable before their known_at_utc.
- Rows with an empty known_at_utc are never used (currently the Binance Alpha listing, the 2025-10-10 market-wide crash and the May 2026 bridge exploit).
- Binance funding rates are known at their fundingTime, never earlier.
- The static tokenomics file is treated as static constants. It may be used only to compute time since TGE (2025-07-15) and cliff dates derived from the TGE-relative terms. No other feature may use it, and its retrieved_at_utc is not used as a known time.

## 3. Known gaps

- **Funding:** one 8 h gap, 2026-06-24 00:00 to 08:00 UTC (`quality_funding_report.md`).
- **Depth snapshot:** a gap from 2026-11-18 18:35 to 2026-11-19 15:25 UTC (the recorder log shows the restart at 15:20:25), plus a short one from 17:27 to 18:05 on 2026-11-18. The snapshot cannot be backfilled.
- **CoinGecko:** history before 2025-11-21 is unrecoverable on the free tier, and days not saved before they leave the 365-day window are lost.
- **No depth history** before 2026-11-18, and **no liquidation data** (skipped by decision).
- **Unlock calendar: unknown.** The official post gives terms relative to TGE only, and third-party trackers disagree. Circulating supply history is only available as a derived series.
- **No spot market found:** the Binance spot request for TACUSDT returned HTTP 400, so a spot-versus-perp test could not be run. A missing spot market is likely but unverified (`aug_2026_divergence_report.md`).
- **Recorder lag:** with the 45 s cycle offset only 7 to 31 percent of rows are captured in their first cycle (open interest 20.4, global long/short 30.5, top position 29.8, taker 7.0). No row is lost, because each cycle fetches the latest 2 periods, so a live row's fetched_at_ms can be up to about 6.9 minutes after the period close (`lag_analysis_report.md`).
- **Backfilled recorder rows** have an honest fetched_at_ms (the fetch time, long after the period), but the real publication time is unknown; hence the timestamp + 10 minutes rule.

## 4. Sample size

**Days of history by feature family** (read-only counts, section 1):

| Feature family | Days |
|---|---|
| Klines (Binance, Bybit) and funding | about 491 (from 2025-07-15) |
| DeFiLlama price and TVL | 492 and 489 (from 2025-07-16 and 2025-07-18) |
| CoinGecko market cap and volume | 363 (from 2025-11-21) |
| Recorder open interest, long/short, taker | 32 (from 2026-10-19), of which 322 rows (about 1.1 days) were captured live; the rest were backfilled |
| Depth snapshot | 2 (from 2026-11-18) |

**Big events in `data/static/events.csv`, by type:** price_crash 3 (2025-10-10, 2026-07-07, 2026-08-22), price_spike 3 (2025-11-26, 2026-06-29, 2026-08-26), exploit 2 (2026-05-11, 2026-08-22), market_wide 1 (2025-10-10). Also 13 supply steps, 2 listings and 1 launch row, which are not risk events. These are not independent: 2025-10-10 appears as both a market-wide and a TAC crash, and 2026-08-22 as both an exploit and a crash, with a spike four days later. Grouped by day that is 7 episodes (2025-10-10, 2025-11-26, 2026-05-11, 2026-06-29, 2026-07-07, 2026-08-22, 2026-08-26), and in every episode the cause of the TAC price move is unverified (the exploit facts themselves are sourced).

What this means: with this few events, a backtest cannot prove that the gate works. It can show whether the gate would have said "stay out" or "caution" around those few episodes, but a handful of cases cannot separate skill from luck, and any rule tuned on them will fit them by construction. Walk-forward testing and paper trading (CLAUDE.md, Phase 5, 8+ weeks) must carry the weight. No statistical power figure is given here.

## 5. Open items before Phase 2

- Rerun the CoinGecko fetcher weekly (at least every few weeks): its 365-day window moves forward every day.
- The recorder must keep running. Every gap in the recorder files and the snapshot is permanent once the 30-day history window has passed.
- India: the legality and tax treatment of crypto futures is unresolved. This is a non-code item and was not researched here.
- Every web-sourced fact in `data/static/` was read by Claude Code and has not been independently checked by you.
- The recorder quality report should be regenerated before it is cited as current.

## 6. Verdict

**Gate 1 is passed for Phase 2 to start on Binance and Bybit 1m klines, Binance funding, DeFiLlama price and TVL, and CoinGecko market cap and volume (with the fixed rules above), plus the static events and tokenomics (with known_at rules); it is NOT passed for anything built on the recorder files (32 days, about 1 day live) or the depth snapshot (2 days), which are too thin to support a claim, and nothing may be called validated until walk-forward and paper trading.**

Gate 1 passing means the data is clean enough to start Phase 2, not that any edge exists.
