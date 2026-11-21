# Phase 2 loaders: check against the documented numbers

Generated 2026-11-21 18:03 UTC by `python -m tacgate.phase2.loaders --check`. The loaders read the real files read-only (nothing is written to data/ and the recorder is not touched). The recorder files keep growing, so their numbers are information, not pass or fail.

Result: 34 match, 0 mismatch, 7 information only.

| Check | Loader value | Documented value | Source doc | Match |
|---|---|---|---|---|
| Binance 1m klines: rows | 707,389 | 707,389 | quality_klines_report.md | yes |
| Binance 1m klines: first open | 2025-07-15 10:30 | 2025-07-15 10:30 | quality_klines_report.md | yes |
| Binance 1m klines: last open | 2026-11-18 16:18 | 2026-11-18 16:18 | quality_klines_report.md | yes |
| Binance 1m klines: zero-volume candles | 5,814 | 5,814 | quality_klines_report.md | yes |
| Bybit 1m klines: rows | 707,404 | 707,404 | crosscheck_klines_report.md | yes |
| Bybit 1m klines: first open | 2025-07-15 11:00 | 2025-07-15 11:00 | crosscheck_klines_report.md | yes |
| Bybit 1m klines: last open | 2026-11-18 17:03 | 2026-11-18 17:03 | crosscheck_klines_report.md | yes |
| Bybit 1m klines: zero-volume candles | 123,561 | 123,561 | crosscheck_klines_report.md | yes |
| Funding: rows | 2,947 | 2,947 | quality_funding_report.md | yes |
| Funding: first fundingTime | 2025-07-15 12:00 | 2025-07-15 12:00 | quality_funding_report.md | yes |
| Funding: last fundingTime | 2026-11-18 16:00 | 2026-11-18 16:00 | quality_funding_report.md | yes |
| CoinGecko: rows | 364 | 364 | quality_daily_external_report.md | yes |
| CoinGecko: days compared with Binance | 363 | 363 | quality_daily_external_report.md | yes |
| CoinGecko: days more than 2% off Binance | 73 | 73 | quality_daily_external_report.md | yes |
| DeFiLlama price: rows | 493 | 493 | quality_daily_external_report.md | yes |
| DeFiLlama price: days compared with Binance | 491 | 491 | quality_daily_external_report.md | yes |
| DeFiLlama price: share within 1% of Binance | 97.6% | 97.6% | quality_daily_external_report.md | yes |
| DeFiLlama price: days more than 2% off Binance | 3 | 3 | quality_daily_external_report.md | yes |
| DeFiLlama TVL: rows | 490 | 490 | quality_daily_external_report.md | yes |
| Bulk metrics normalized: rows | 141,855 | 141,855 | bulk_metrics_history_report.md | yes |
| Bulk metrics: first bulk label | 2025-07-15 10:30 | 2025-07-15 10:30 | bulk_metrics_history_report.md | yes |
| Bulk metrics: last bulk label | 2026-11-19 23:55 | 2026-11-19 23:55 | bulk_metrics_history_report.md | yes |
| Bulk metrics: missing 5-minute slots | 3 | 3 | bulk_metrics_history_report.md | yes |
| Bulk metrics: open interest at or below zero (rows) | 25 | 25 | bulk_metrics_history_report.md | yes |
| Bulk metrics: one-step open-interest jumps above 50% | 24 | 24 | bulk_metrics_history_report.md | yes |
| Bulk metrics: rows inside the jump excursions (the rule defined in this module) | 43 | no documented value | loaders.py docstring | info |
| Bulk metrics: not-a-number count_toptrader_long_short_ratio | 41 | 41 | bulk_metrics_history_report.md | yes |
| Bulk metrics: not-a-number sum_toptrader_long_short_ratio | 12 | 12 | bulk_metrics_history_report.md | yes |
| Bulk metrics: not-a-number count_long_short_ratio | 13 | 13 | bulk_metrics_history_report.md | yes |
| Bulk metrics: not-a-number sum_taker_long_short_vol_ratio (column dropped by the loader) | 27 | 27 | bulk_metrics_history_report.md | yes |
| Bulk metrics: unverified-era rows (before 2026-07-12) | 104,127 | 104,127 | gate1_summary.md | yes |
| Bulk metrics: taker column absent from the loader output (decided: not used) | yes | yes | bulk_metrics_history_report.md | yes |
| Static events: rows | 25 | 25 | gate1_summary.md | yes |
| Static events: sourced rows | 6 | 6 | gate1_summary.md | yes |
| Static events: rows with an empty known_at_utc (never usable) | 3 | 3 | gate1_summary.md | yes |
| Static tokenomics: cliff date derived from the TGE-relative terms | 2026-07-15 00:00 | 2026-07-15 (TGE + 12 months) | tokenomics.csv terms; phase2_plan.md | info |
| Recorder open_interest: rows (live / backfilled), first, last | 9,511 (361 / 9,150), 2026-10-19 17:25 to 2026-11-21 17:55 | grows while the recorder runs | quality_recorder_report.md (2026-11-19) | info |
| Recorder global_long_short: rows (live / backfilled), first, last | 9,512 (362 / 9,150), 2026-10-19 17:25 to 2026-11-21 18:00 | grows while the recorder runs | quality_recorder_report.md (2026-11-19) | info |
| Recorder top_position_long_short: rows (live / backfilled), first, last | 9,512 (362 / 9,150), 2026-10-19 17:25 to 2026-11-21 18:00 | grows while the recorder runs | quality_recorder_report.md (2026-11-19) | info |
| Recorder taker_buy_sell: rows (live / backfilled), first, last | 9,511 (356 / 9,155), 2026-10-19 17:20 to 2026-11-21 17:50 | grows while the recorder runs | quality_recorder_report.md (2026-11-19) | info |
| Recorder snapshot: rows, first, last | 354, 2026-11-18 17:26 to 2026-11-21 18:00 | grows while the recorder runs | quality_recorder_report.md (2026-11-19) | info |

## Mismatches

None.

## Rules applied

- Klines known at open + 60 s; funding at fundingTime; CoinGecko, DeFiLlama price and TVL at timestamp + 24 h; prices flagged when more than 2% from the Binance 1m open at the nearest minute.
- Bulk metrics: open interest at known_at_oi_ms, ratios at known_at_other_ms, taker dropped, unverified era carried; bad rows flagged (open interest at or below zero or not a number, ratios at or below zero or not a number, the excursion rows of the 24 one-step open-interest jumps above 50%), never filled.
- Recorder: live rows at fetched_at_ms, backfilled rows (fetched more than 15 minutes after the timestamp) at timestamp + 10 minutes. Static events: known_at_utc, never when empty.

## Decisions

**Decided by the user on 2026-11-21.**

1. The open-interest jump rule is accepted as implemented. A jump is a one-step change in open interest of more than 50 percent between two rows whose labels are 5 minutes apart. The rows inside a jump are the whole excursion, from the row of a down jump up to, but not including, the row of the next up jump.
2. The rule applies only to the bulk archive file, never to the live recorder. A real fall of more than 50 percent in open interest during a liquidation cascade must not be masked as a data glitch.
