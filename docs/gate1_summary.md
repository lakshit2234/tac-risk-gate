# Gate 1 summary: data quality for Phase 0

First written 2026-11-20 (UTC) and updated the same day for the Binance bulk archive work (`binance_bulk_availability.md`, `bulk_equivalence_report.md`, `bulk_metrics_history_report.md`). Nothing was fetched or re-checked for this update. Rows, first and last timestamps and days are read-only counts of the files in `data/raw/` and `data/static/` taken at about 19:25 UTC on 2026-11-20 (they agree with the reports wherever a report states the same number). Checks and verdicts come from the report named in each row. "Days" = last minus first timestamp.

## 1. Sources

| Source (file) | Rows | First to last (UTC) | Days | Checks done (report) | Gate 1 verdict | When a row counts as known |
|---|---|---|---|---|---|---|
| Binance perp 1m klines (`binance_TACUSDT_1m.csv`) | 707,389 | 2025-07-15 10:30 to 2026-11-18 16:18 | 491.2 | gaps (0), expected row count, zero-volume candles, min and max price, largest 1-minute returns flagged, not removed (`quality_klines_report.md`: PASS; 5,814 zero-volume candles) | **pass** | at the candle's close (open + 1 minute); the fetcher stores only closed candles (`binance_klines.py`) |
| Bybit perp 1m klines (`bybit_TACUSDT_1m.csv`) | 707,404 | 2025-07-15 11:00 to 2026-11-18 17:03 | 491.3 | gaps (0), zero-volume candles, cross-check against Binance (`crosscheck_klines_report.md`: PASS; 123,561 zero-volume candles; 328 minutes where closes differ by more than 1%) | **pass** (cross-check only) | at the candle's close |
| Binance funding (`binance_TACUSDT_funding.csv`) | 2,947 | 2025-07-15 12:00 to 2026-11-18 16:00 | 491.2 | interval spacing, row count vs a 4 h grid, rate and mark price checks (`quality_funding_report.md`: PASS; one 8 h gap; 181 rates above 0.0005 and 22 below -0.0005, kept) | **pass** | at its fundingTime, never earlier (decided; the file has no fetched_at_ms) |
| **Bulk metrics: open interest columns** (`binance_bulk_metrics_TACUSDT_5m.csv`, built from the Binance bulk archive) | 141,855 | 2025-07-15 10:30 to 2026-11-19 23:55 | 492.6 | all 493 daily files verified against their published checksums and pinned (`data/static/bulk_metrics_manifest.csv`); label convention rechecked against the recorder: open interest equal in 100% of 9,008 rows (`bulk_equivalence_report.md`, `bulk_metrics_history_report.md`); 2 days without 288 rows, 3 missing slots, 25 rows with open interest at or below zero, 24 one-step jumps above 50% (`bulk_metrics_history_report.md`) | **pass with rule** | our timestamp plus 10 minutes only from 2026-10-19 on (our timestamp = bulk label + 5 minutes before 2026-11-16 00:00 UTC, the label itself from then on); everywhere else the later of UTC day end plus 24 h and the file's LastModified. Bad rows are flagged missing by the loader. **104,127 rows (73.4%), all before 2026-07-12, are an unverified era**: the archive wrote them months late and our recorder cannot check them |
| **Bulk metrics: long/short ratio columns** (same file) | 141,855 | same | 492.6 | the global and top-position ratios were within 0.1% of our recorder's values in 100% of the 9,008 overlapping rows, but are not identical (equal at our 4-decimal precision in 99.5% for top-position and 3.3% for global) (`bulk_equivalence_report.md`); not-a-number values 12 to 41 per ratio column (`bulk_metrics_history_report.md`) | **pass with rule** | the later of UTC day end plus 24 h and LastModified, everywhere (decided, for now); same unverified era; bad rows flagged missing |
| **Bulk metrics: taker ratio column** (same file) | 141,855 | same | 492.6 | matches the ratio derived from our 1m klines in 63.6% of rows before 2026-07-12 and 65.5% from then on (within 0.1%); in the recorder window 60.61% against 92.49% for the ratio our recorder stored from the API (`bulk_metrics_history_report.md`) | **not used** (decided) | not applicable; taker flow will be derived from our 1m klines instead, known at candle close |
| Bulk archive `bookDepth` (not downloaded) | none | listed: 491 daily files, 2025-07-15 to 2026-11-19 | n/a | one sample day downloaded and checksum-verified only (`binance_bulk_availability.md`) | **available, not downloaded, not checked** | the later of UTC day end plus 24 h and LastModified (decided, for now) |
| Bulk archive `markPriceKlines`, `indexPriceKlines`, `premiumIndexKlines` (1m; not downloaded) | none | listed: 493 daily files each, 2025-07-15 to 2026-11-19 | n/a | one sample day each downloaded and checksum-verified only (`binance_bulk_availability.md`) | **available, not downloaded, not checked** | no rule decided yet |
| Bulk archive `aggTrades` and `trades` (not downloaded) | none | listed: 493 daily files each, 2025-07-15 to 2026-11-19 | n/a | one sample day each downloaded and checksum-verified only (`binance_bulk_availability.md`) | **available, not downloaded, not checked** | no rule decided yet |
| Recorder open interest (`binance_TACUSDT_open_interest_5m.csv`), forward recording, still running; used to verify the bulk data and for live use | 9,240 | 2026-10-19 17:25 to 2026-11-20 19:20 | 32.1 | schema, gaps (0), look-ahead (0), live vs backfilled (`quality_recorder_report.md`, checked 2026-11-19 15:25: PASS) | **pass with rule** | live rows: fetched_at_ms. Backfilled rows: timestamp + 10 min |
| Recorder global long/short (`..._global_long_short_5m.csv`), same | 9,239 | 2026-10-19 17:25 to 2026-11-20 19:15 | 32.1 | same report: PASS | **pass with rule** | same rule |
| Recorder top-position long/short (`..._top_position_long_short_5m.csv`), same | 9,239 | 2026-10-19 17:25 to 2026-11-20 19:15 | 32.1 | same report: PASS | **pass with rule** | same rule |
| Recorder taker buy/sell (`..._taker_buy_sell_5m.csv`), same | 9,239 | 2026-10-19 17:20 to 2026-11-20 19:10 | 32.1 | same report: PASS; its API ratio agrees with the klines-derived ratio in 92.49% of rows within 0.1% (`bulk_metrics_history_report.md`) | **pass with rule** | same rule (the taker label is the period start) |
| Recorder depth snapshot (`binance_TACUSDT_snapshot.csv`), same | 346 | 2026-11-18 17:26 to 2026-11-20 19:21 | 2.1 | schema, row checks, gaps above 10 min (`quality_recorder_report.md`: PASS; coverage warning) | **pass with rule** (too short to use) | fetched_at_ms (the real fetch time). Gaps are permanent: there is no backfill source |
| CoinGecko daily (`coingecko_TAC_market_chart_daily.csv`) | 364 | 2025-11-21 to 2026-11-19 | 363.0 | schema, gaps (0), look-ahead (0), cross-check vs Binance and DeFiLlama (`quality_daily_external_report.md`: PASS; 73 of 363 days more than 2% from Binance) | **pass with rule** | timestamp + 24 h |
| DeFiLlama chain TVL (`defillama_TAC_chain_tvl_daily.csv`) | 490 | 2025-07-18 to 2026-11-19 | 489.0 | schema, gaps (0), look-ahead (0); 2 days with TVL change above 50% flagged (`quality_daily_external_report.md`: PASS) | **pass with rule** | timestamp + 24 h |
| DeFiLlama price (`defillama_TAC_price_daily.csv`) | 493 | 2025-07-16 to 2026-11-19 | 492.0 | schema, gaps (0), look-ahead (0), cross-check vs Binance (`quality_daily_external_report.md`: PASS; 97.6% of days within 1% of Binance, 3 days above 2%) | **pass with rule** | timestamp + 24 h |
| Static tokenomics (`data/static/tokenomics.csv`) | 18 | no dates (retrieved 2026-11-20) | n/a | validator `static_events.py`: 0 errors; 16 sourced, 2 unverified; the 12 allocation rows sum to 100 | **pass with rule** | static constants: only for time since TGE (2025-07-15) and cliff dates derived from the TGE-relative terms; retrieved_at_utc is not a known time (decided) |
| Static events (`data/static/events.csv`) | 25 | 2025-07-15 to 2026-10-16 (event dates) | n/a | validator: 0 errors; 6 sourced, 19 unverified; 3 rows with empty known_at_utc | **pass with rule** | known_at_utc of each row; empty means never used |

No source fails a hard check. The recorder files are a forward recording that is still running (the newest snapshot row is from 2026-11-20 19:21 UTC); `quality_recorder_report.md` itself was written on 2026-11-19 and has not been regenerated since.

## 2. Rules that are now fixed

- A CoinGecko or DeFiLlama daily price more than 2 percent away from the Binance price is excluded from features. CoinGecko is never used as a price (73 of 363 days off by more than 2%, nearly all in Jan to Mar 2026); it is kept for market cap and volume only.
- A derived supply step counts as an event only if it persists at least 3 days. One-day reversals look like sampling noise.
- Daily external rows (CoinGecko, DeFiLlama TVL, DeFiLlama price) are known at timestamp + 24 h, never earlier.
- Backfilled recorder rows are known at timestamp + 10 minutes. Live recorder rows are known at fetched_at_ms.
- Exploit and all other event labels are not usable before their known_at_utc.
- Rows with an empty known_at_utc are never used (currently the Binance Alpha listing, the 2025-10-10 market-wide crash and the May 2026 bridge exploit).
- Binance funding rates are known at their fundingTime, never earlier.
- The static tokenomics file is treated as static constants. It may be used only to compute time since TGE (2025-07-15) and cliff dates derived from the TGE-relative terms. No other feature may use it, and its retrieved_at_utc is not used as a known time.
- **Bulk metrics are normalized to our timestamp convention** (`bulk_equivalence_report.md`, decisions): the bulk label plus 5 minutes before 2026-11-16 00:00 UTC, and the bulk label unchanged from that time on. The bulk label convention changed by 5 minutes on 2026-11-16, so the label is not a stable reference.
- **Bulk open interest** is known at our timestamp plus 10 minutes only from 2026-10-19 on (verified against the recorder); everywhere else it is known at UTC day end plus 24 hours, or the file's LastModified time if that is later.
- **Bulk long/short ratios, the bulk taker ratio and bulk bookDepth** use UTC day end plus 24 hours (or LastModified if later) everywhere for now.
- **Bulk metrics values before 2026-07-12 are an unverified era**: the archive wrote them months late and our recorder cannot check them.
- **Bad bulk rows are flagged missing by the loader and never filled from neighbours** (`bulk_metrics_history_report.md`, decisions): open interest at or below zero or not-a-number, any ratio at or below zero or not-a-number, and rows inside the 24 open-interest jumps above 50 percent. The raw normalized file stays unchanged.
- **Downloaded archive files are pinned by checksum** (`data/static/bulk_metrics_manifest.csv`), and the label convention is rechecked against the recorder on every rerun, because Binance could rewrite old files.
- **The bulk taker ratio is not used as a feature.** Taker flow will be derived from our own 1m klines (known at candle close).
- **Open interest and the ratio columns are regime-sensitive.** Phase 2 must test their stability per regime before any such feature is used.
- **In the backtest**, intraday features come from klines, mark, index and premium klines, and funding; open interest, the ratios, the taker ratio and depth enter with a day lag until proven otherwise.
- Nothing from the bulk archive has been used as a feature.

## 3. Known gaps

- **Funding:** one 8 h gap, 2026-06-24 00:00 to 08:00 UTC (`quality_funding_report.md`).
- **Depth snapshot:** a gap from 2026-11-18 18:35 to 2026-11-19 15:25 UTC (the recorder log shows the restart at 15:20:25), plus a short one from 17:27 to 18:05 on 2026-11-18. The snapshot cannot be backfilled.
- **CoinGecko:** history before 2025-11-21 is unrecoverable on the free tier, and days not saved before they leave the 365-day window are lost.
- **Bulk metrics, missing data** (`bulk_metrics_history_report.md`): 2025-07-15 has 162 rows and 2025-08-29 has 285 rows instead of 288; 3 five-minute slots are missing, all on 2025-08-29 between 06:20 and 06:30.
- **Bulk metrics, open interest:** 25 rows at or below zero, 10 on 2025-07-21 and 15 on 2026-10-15, and 24 one-step jumps above 50%, all on those two days.
- **Bulk metrics, ratios:** not-a-number values in every ratio column (count_toptrader 41, sum_toptrader 12, count_long_short 13, taker 27), and 39 taker ratios at or below zero, with a maximum of 9,166.
- **Bulk metrics, regime shifts** (14 days either side): around 2026-07-12 the open interest median goes from 3.8e8 to 1.0e9 and the two account-count ratios go from about 0.95 to about 1.6, with much narrower ranges after; around 2026-11-16 the two account-count ratios go from about 5.3 to 2.9. The 2026-11-16 shift is also in our recorder's API values, which match the bulk values on both sides, so it is not an archive artifact (decision in `bulk_metrics_history_report.md`); the cause of either shift is unknown: a real change in positioning and a Binance definition change cannot be told apart from our data. The 2026-07-12 shift also cannot be checked against the recorder.
- **Bulk metrics before 2026-07-12 cannot be checked:** our recorder starts on 2026-10-19, so the values before it (104,127 rows, 73.4% of the file) have no second source for open interest and the ratios (`bulk_equivalence_report.md`).
- **Bulk taker ratio** differs from the ratio derived from our klines in both eras (see section 1), which is why it is not used.
- **Depth:** the only depth history we hold is the 2-day recorder snapshot. The bulk archive lists 491 daily `bookDepth` files, but they are not downloaded or checked (`binance_bulk_availability.md`).
- **No liquidation data:** the bulk archive lists no `liquidationSnapshot` or `bookTicker` files for TACUSDT (`binance_bulk_availability.md`), so this gap stays.
- **Unlock calendar: unknown.** The official post gives terms relative to TGE only, and third-party trackers disagree. Circulating supply history is only available as a derived series.
- **No spot market found:** the Binance spot request for TACUSDT returned HTTP 400, so a spot-versus-perp test could not be run. A missing spot market is likely but unverified (`aug_2026_divergence_report.md`).
- **Recorder lag:** with the 45 s cycle offset only 7 to 31 percent of rows are captured in their first cycle (open interest 20.4, global long/short 30.5, top position 29.8, taker 7.0). No row is lost, because each cycle fetches the latest 2 periods, so a live row's fetched_at_ms can be up to about 6.9 minutes after the period close (`lag_analysis_report.md`).
- **Backfilled recorder rows** have an honest fetched_at_ms (the fetch time, long after the period), but the real publication time is unknown; hence the timestamp + 10 minutes rule.

## 4. Sample size

**Days of history by feature family** (read-only counts, section 1):

| Feature family | Days |
|---|---|
| Klines (Binance, Bybit) and funding | about 491 (from 2025-07-15) |
| Taker flow derived from our 1m klines (decided, not built yet) | about 491 (the klines file has the taker buy volume column) |
| DeFiLlama price and TVL | 492 and 489 (from 2025-07-16 and 2025-07-18) |
| CoinGecko market cap and volume | 363 (from 2025-11-21) |
| Bulk open interest and long/short ratios | about 493 (2025-07-15 to 2026-11-19): 362 days (104,127 rows) are the unverified era before 2026-07-12 and 131 days (37,728 rows) are from 2026-07-12 on; only the last 32 days overlap the recorder, where the values were checked |
| Recorder open interest, long/short, taker (forward recording, still running) | 32.1 (from 2026-10-19), of which 351 open-interest rows (about 1.2 days) were captured live; the rest were backfilled |
| Depth | 2.1 days of our own snapshot (from 2026-11-18); bulk `bookDepth` is listed but not downloaded, so none usable yet |

**Big events in `data/static/events.csv`, by type:** price_crash 3 (2025-10-10, 2026-07-07, 2026-08-22), price_spike 3 (2025-11-26, 2026-06-29, 2026-08-26), exploit 2 (2026-05-11, 2026-08-22), market_wide 1 (2025-10-10). Also 13 supply steps, 2 listings and 1 launch row, which are not risk events. These are not independent: 2025-10-10 appears as both a market-wide and a TAC crash, and 2026-08-22 as both an exploit and a crash, with a spike four days later. Grouped by day that is 7 episodes (2025-10-10, 2025-11-26, 2026-05-11, 2026-06-29, 2026-07-07, 2026-08-22, 2026-08-26), and in every episode the cause of the TAC price move is unverified (the exploit facts themselves are sourced).

**More days do not add independent episodes.** The bulk archive gives open interest and the ratios about 493 days instead of 32, but the count of big events is unchanged: about 7 episodes. The longer history adds ordinary days and regime changes (see the regime shifts in section 3), not more crashes or exploits, and 73.4% of it is the unverified era.

What this means: with this few events, a backtest cannot prove that the gate works. It can show whether the gate would have said "stay out" or "caution" around those few episodes, but a handful of cases cannot separate skill from luck, and any rule tuned on them will fit them by construction. Walk-forward testing and paper trading (CLAUDE.md, Phase 5, 8+ weeks) must carry the weight. No statistical power figure is given here.

## 5. Open items before Phase 2

- Rerun the CoinGecko fetcher weekly (at least every few weeks): its 365-day window moves forward every day.
- The recorder must keep running. Every gap in the recorder files and the snapshot is permanent once the 30-day history window has passed. It also keeps verifying the bulk data on the days after 2026-10-19.
- India: the legality and tax treatment of crypto futures is unresolved. This is a non-code item and was not researched here.
- Every web-sourced fact in `data/static/` and every source in `literature_scan.md` was read by Claude Code and has not been independently checked by you.
- The downloads and checks of the bulk `bookDepth`, `markPriceKlines`, `indexPriceKlines` and `premiumIndexKlines` files are still to do (and `aggTrades` and `trades`, if wanted).
- Phase 2 must test the stability of the regime-sensitive columns (open interest and the ratios) per regime, around 2026-07-12 and 2026-11-16, before any such feature is used; the taker flow derived from klines is still to be built.
- The recorder quality report should be regenerated before it is cited as current.

## 6. Verdict

Per feature family (Gate 1 here means the data is clean enough to start Phase 2 on, under the fixed rules above):

- **Binance and Bybit 1m klines:** passed.
- **Binance funding:** passed.
- **DeFiLlama price and TVL:** passed with rules (the 2% exclusion for price, known at timestamp + 24 h).
- **CoinGecko:** passed for market cap and volume only, with rules; never as a price.
- **Static files (events and tokenomics):** passed with rules (known_at_utc per row; tokenomics as static constants only).
- **Bulk open interest:** passed with rules, as a candidate for Phase 2 testing only: normalized timestamps, bad rows flagged missing, known at our timestamp + 10 minutes only from 2026-10-19 and at day end + 24 hours elsewhere, the era before 2026-07-12 marked unverified, regime-sensitive (stability test needed first).
- **Bulk long/short ratios:** passed with rules, known at day end + 24 hours everywhere, close to but not identical with the recorder's values, same unverified era and regime sensitivity.
- **Bulk taker ratio:** not used (taker flow comes from the 1m klines).
- **Bulk depth (`bookDepth`):** not checked yet; it is not downloaded.
- **Recorder files:** passed with rules as a forward recording that is still running; they verified the bulk open interest and ratios and serve live use, but at 32 days (about 1.2 days live) they are too short to be a history on their own; the depth snapshot (2.1 days) is too short to use.

Nothing may be called validated until walk-forward and paper trading.

Gate 1 passing means the data is clean enough to start Phase 2, not that any edge exists.
