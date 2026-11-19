# Recorder data quality report (Gate 1)

- Directory: `data\raw` (read-only; each file read once; a partial last line is ignored)
- Checked at: 2026-11-19 15:25:18 UTC
- Verdict: **PASS**

## Is the recorder running?

- Newest snapshot row: 2026-11-19 15:25:08 UTC (0.2 min ago). Looks running.
- recorder_errors.log: 3 line(s) {'GAP': 3}
  - `2026-11-18 18:01:27 UTC | GAP | restart: snapshot: last row 2026-11-18 17:27:07 UTC, now 2026-11-18 18:01:27 UTC (34 min). Gap is NOT filled.`
  - `2026-11-19 15:20:25 UTC | GAP | restart: taker_buy_sell: last saved period 2026-11-19 15:10:00 UTC, now 2026-11-19 15:20:25 UTC (10 min). Gap is NOT filled.`
  - `2026-11-19 15:20:25 UTC | GAP | restart: snapshot: last row 2026-11-18 18:35:08 UTC, now 2026-11-19 15:20:25 UTC (1245 min). Gap is NOT filled.`

## Hard failures

- none

## Warnings and flags

- snapshot: 2 gap(s) above 10 min; coverage 3.8% of 5-min slots (10 rows; rows from a shorter test interval raise this)

## History: open_interest

- Rows: 8,904; first 2026-10-19 17:25:00 UTC, last 2026-11-19 15:20:00 UTC
- Expected slots at 5 min: 8,904; coverage 100.00%; missing slots 0
- BACKFILLED (fetched_at_ms - timestamp > 15 min): 8,889 rows, 2026-10-19 17:25:00 UTC to 2026-11-19 15:05:00 UTC
- LIVE: 15 rows, 2026-11-18 17:15:00 UTC to 2026-11-19 15:20:00 UTC
- Live coverage since the first live row: 5.64% (to the last row), 5.62% (to now)
- Median fetched_at_ms - timestamp: live 5.10 min, all rows 20942.8 min
- Look-ahead violations (fetched before the timestamp): 0

Spacing distribution (minutes between consecutive timestamps):

| Minutes | Count |
|---|---|
| 5 | 8,903 |

Gaps above 5 min (0):

none

Consistency (flag only): where sumOpenInterest is not > 0: 0

`sumOpenInterest`: min 1877429743.0, max 4051958750.0, median 2117991096.0

Top 5 furthest from the median (flagged, not clipped):

| Time (UTC) | Value |
|---|---|
| 2026-11-16 03:35:00 UTC | 4051958750.0 |
| 2026-11-16 03:40:00 UTC | 4013922982.0 |
| 2026-11-16 03:30:00 UTC | 3970093135.0 |
| 2026-11-16 03:25:00 UTC | 3887320312.0 |
| 2026-11-16 03:20:00 UTC | 3856429282.0 |

## History: global_long_short

- Rows: 8,904; first 2026-10-19 17:25:00 UTC, last 2026-11-19 15:20:00 UTC
- Expected slots at 5 min: 8,904; coverage 100.00%; missing slots 0
- BACKFILLED (fetched_at_ms - timestamp > 15 min): 8,889 rows, 2026-10-19 17:25:00 UTC to 2026-11-19 15:05:00 UTC
- LIVE: 15 rows, 2026-11-18 17:15:00 UTC to 2026-11-19 15:20:00 UTC
- Live coverage since the first live row: 5.64% (to the last row), 5.62% (to now)
- Median fetched_at_ms - timestamp: live 5.10 min, all rows 20942.9 min
- Look-ahead violations (fetched before the timestamp): 0

Spacing distribution (minutes between consecutive timestamps):

| Minutes | Count |
|---|---|
| 5 | 8,903 |

Gaps above 5 min (0):

none

Consistency (flag only): where longAccount + shortAccount is not within 0.001 of 1: 0; where longShortRatio differs from longAccount / shortAccount: 0

`longShortRatio`: min 2.0969, max 6.0028, median 4.988

Top 5 furthest from the median (flagged, not clipped):

| Time (UTC) | Value |
|---|---|
| 2026-11-16 14:00:00 UTC | 2.0969 |
| 2026-11-16 14:10:00 UTC | 2.1309 |
| 2026-11-16 14:05:00 UTC | 2.1466 |
| 2026-11-16 14:15:00 UTC | 2.1506 |
| 2026-11-16 14:20:00 UTC | 2.1686 |

## History: top_position_long_short

- Rows: 8,904; first 2026-10-19 17:25:00 UTC, last 2026-11-19 15:20:00 UTC
- Expected slots at 5 min: 8,904; coverage 100.00%; missing slots 0
- BACKFILLED (fetched_at_ms - timestamp > 15 min): 8,889 rows, 2026-10-19 17:25:00 UTC to 2026-11-19 15:05:00 UTC
- LIVE: 15 rows, 2026-11-18 17:15:00 UTC to 2026-11-19 15:20:00 UTC
- Live coverage since the first live row: 5.64% (to the last row), 5.62% (to now)
- Median fetched_at_ms - timestamp: live 5.11 min, all rows 20943.1 min
- Look-ahead violations (fetched before the timestamp): 0

Spacing distribution (minutes between consecutive timestamps):

| Minutes | Count |
|---|---|
| 5 | 8,903 |

Gaps above 5 min (0):

none

Consistency (flag only): where longAccount + shortAccount is not within 0.001 of 1: 0; where longShortRatio differs from longAccount / shortAccount: 0

`longShortRatio`: min 1.0805, max 1.5699, median 1.179

Top 5 furthest from the median (flagged, not clipped):

| Time (UTC) | Value |
|---|---|
| 2026-11-14 11:55:00 UTC | 1.5699 |
| 2026-11-14 12:10:00 UTC | 1.5692 |
| 2026-11-14 11:50:00 UTC | 1.5688 |
| 2026-11-14 12:05:00 UTC | 1.5644 |
| 2026-11-14 11:05:00 UTC | 1.5624 |

## History: taker_buy_sell

- Rows: 8,904; first 2026-10-19 17:20:00 UTC, last 2026-11-19 15:15:00 UTC
- Expected slots at 5 min: 8,904; coverage 100.00%; missing slots 0
- BACKFILLED (fetched_at_ms - timestamp > 15 min): 8,892 rows, 2026-10-19 17:20:00 UTC to 2026-11-19 15:05:00 UTC
- LIVE: 12 rows, 2026-11-18 17:15:00 UTC to 2026-11-19 15:15:00 UTC
- Live coverage since the first live row: 4.53% (to the last row), 4.49% (to now)
- Median fetched_at_ms - timestamp: live 10.12 min, all rows 20948.3 min
- Look-ahead violations (fetched before the timestamp): 0

Spacing distribution (minutes between consecutive timestamps):

| Minutes | Count |
|---|---|
| 5 | 8,903 |

Gaps above 5 min (0):

none

Consistency (flag only): where buySellRatio differs from buyVol / sellVol: 0

`buySellRatio`: min 0.0132, max 34.5387, median 0.97355

Top 5 furthest from the median (flagged, not clipped):

| Time (UTC) | Value |
|---|---|
| 2026-11-12 22:45:00 UTC | 34.5387 |
| 2026-11-11 05:45:00 UTC | 26.7535 |
| 2026-10-29 12:25:00 UTC | 26.0559 |
| 2026-11-02 19:10:00 UTC | 25.8581 |
| 2026-10-27 05:35:00 UTC | 24.5034 |

## Snapshot

- Rows: 10; first 2026-11-18 17:26:08 UTC, last 2026-11-19 15:25:08 UTC
- Span 21.98 h; hours actually covered (steps of 10 min or less): 0.52 h
- Coverage vs 5-min slots: 3.8% (10 of 264)
- filled_ok share: 100.0%; blank slippage cells: 0; median spread 8.41 bps

Spacing distribution (seconds between rows):

| Seconds | Count |
|---|---|
| 59 | 1 |
| 299 | 1 |
| 300 | 5 |
| 2281 | 1 |
| 74999 | 1 |

Gaps above 10 min (2):

| From (UTC) | To (UTC) |
|---|---|
| 2026-11-18 17:27:07 UTC | 2026-11-18 18:05:09 UTC |
| 2026-11-18 18:35:08 UTC | 2026-11-19 15:25:08 UTC |

Row checks (flag only): with spread_bps <= 0: 0; with a negative depth value: 0; where buy slippage for 5000 is below 1000: 0; where sell slippage for 5000 is below 1000: 0; where mark and index differ by more than 5%: 0; where nextFundingTime is not after fetched_at_ms: 0; where the local clock is more than 2s behind server_time_ms: 0
