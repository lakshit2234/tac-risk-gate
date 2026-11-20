# Recorder lag analysis

Data directory: `data\raw`. Rows with fetched_at_ms >= 1795104000000 (2026-11-19 16:00:00 UTC). Cycle offset in force: 45 s after each 5-minute boundary.

Read-only: each file read once, partial last line ignored, no network.

Lag after close = fetched_at_ms - timestamp; for the taker file (label = period start) minus a further 300 s. Rows with lag above 15 minutes are backfilled and skipped. Buckets: first-cycle < 120 s, second-cycle 120-420 s, later > 420 s.

## Verdicts

- open_interest: offset 45 s sufficient: 20.4% first-cycle
- global_long_short: offset 45 s sufficient: 30.5% first-cycle
- top_position_long_short: offset 45 s sufficient: 29.8% first-cycle
- taker_buy_sell: offset 45 s sufficient: 7.0% first-cycle

## open_interest

Rows in file: 9195. Before cutoff (fetched_at_ms < since-ms): 8910. Skipped as backfilled (lag > 15 min): 0. Malformed: 0. Negative lag (excluded): 0. **Live rows analysed: 285.**

| Capture | Rows | Share |
|---|---|---|
| first-cycle | 58 | 20.4% |
| second-cycle | 227 | 79.6% |
| later | 0 | 0.0% |

Lag after close: p50 345.2 s, p90 345.5 s, p95 347.2 s, p99 368.1 s, max 414.7 s.

### Rows not captured in the first cycle (227 in total)

Showing the 20 most recent of 227.

| Timestamp (UTC) | Lag | Lag after close | Bucket |
|---|---|---|---|
| 2026-11-20 13:25:00 | 356.1 s | 356.1 s | second |
| 2026-11-20 13:30:00 | 348.2 s | 348.2 s | second |
| 2026-11-20 13:40:00 | 345.3 s | 345.3 s | second |
| 2026-11-20 13:45:00 | 345.7 s | 345.7 s | second |
| 2026-11-20 13:55:00 | 345.3 s | 345.3 s | second |
| 2026-11-20 14:00:00 | 345.3 s | 345.3 s | second |
| 2026-11-20 14:10:00 | 345.3 s | 345.3 s | second |
| 2026-11-20 14:15:00 | 345.9 s | 345.9 s | second |
| 2026-11-20 14:25:00 | 345.2 s | 345.2 s | second |
| 2026-11-20 14:30:00 | 345.2 s | 345.2 s | second |
| 2026-11-20 14:35:00 | 345.2 s | 345.2 s | second |
| 2026-11-20 14:40:00 | 346.3 s | 346.3 s | second |
| 2026-11-20 14:45:00 | 345.2 s | 345.2 s | second |
| 2026-11-20 14:50:00 | 345.2 s | 345.2 s | second |
| 2026-11-20 14:55:00 | 345.3 s | 345.3 s | second |
| 2026-11-20 15:05:00 | 345.7 s | 345.7 s | second |
| 2026-11-20 15:10:00 | 345.6 s | 345.6 s | second |
| 2026-11-20 15:20:00 | 414.7 s | 414.7 s | second |
| 2026-11-20 15:25:00 | 368.0 s | 368.0 s | second |
| 2026-11-20 15:35:00 | 367.9 s | 367.9 s | second |

### First-cycle share by UTC hour (hour of the period close)

| Hour | First-cycle | Live rows | Share |
|---|---|---|---|
| 00 | 4 | 12 | 33.3% |
| 01 | 2 | 12 | 16.7% |
| 02 | 2 | 12 | 16.7% |
| 03 | 1 | 12 | 8.3% |
| 04 | 2 | 12 | 16.7% |
| 05 | 3 | 12 | 25.0% |
| 06 | 4 | 12 | 33.3% |
| 07 | 0 | 12 | 0.0% |
| 08 | 2 | 12 | 16.7% |
| 09 | 1 | 12 | 8.3% |
| 10 | 3 | 12 | 25.0% |
| 11 | 2 | 12 | 16.7% |
| 12 | 2 | 12 | 16.7% |
| 13 | 2 | 12 | 16.7% |
| 14 | 2 | 12 | 16.7% |
| 15 | 3 | 9 | 33.3% |
| 16 | 4 | 12 | 33.3% |
| 17 | 3 | 12 | 25.0% |
| 18 | 4 | 12 | 33.3% |
| 19 | 2 | 12 | 16.7% |
| 20 | 4 | 12 | 33.3% |
| 21 | 2 | 12 | 16.7% |
| 22 | 2 | 12 | 16.7% |
| 23 | 2 | 12 | 16.7% |

## global_long_short

Rows in file: 9195. Before cutoff (fetched_at_ms < since-ms): 8910. Skipped as backfilled (lag > 15 min): 0. Malformed: 0. Negative lag (excluded): 0. **Live rows analysed: 285.**

| Capture | Rows | Share |
|---|---|---|
| first-cycle | 87 | 30.5% |
| second-cycle | 198 | 69.5% |
| later | 0 | 0.0% |

Lag after close: p50 345.7 s, p90 345.9 s, p95 346.6 s, p99 368.6 s, max 415.3 s.

### Rows not captured in the first cycle (198 in total)

Showing the 20 most recent of 198.

| Timestamp (UTC) | Lag | Lag after close | Bucket |
|---|---|---|---|
| 2026-11-20 13:15:00 | 345.9 s | 345.9 s | second |
| 2026-11-20 13:20:00 | 346.6 s | 346.6 s | second |
| 2026-11-20 13:30:00 | 348.7 s | 348.7 s | second |
| 2026-11-20 13:40:00 | 345.8 s | 345.8 s | second |
| 2026-11-20 13:45:00 | 346.2 s | 346.2 s | second |
| 2026-11-20 13:55:00 | 345.7 s | 345.7 s | second |
| 2026-11-20 14:00:00 | 345.7 s | 345.7 s | second |
| 2026-11-20 14:10:00 | 345.7 s | 345.7 s | second |
| 2026-11-20 14:15:00 | 346.5 s | 346.5 s | second |
| 2026-11-20 14:25:00 | 345.7 s | 345.7 s | second |
| 2026-11-20 14:30:00 | 345.7 s | 345.7 s | second |
| 2026-11-20 14:35:00 | 345.8 s | 345.8 s | second |
| 2026-11-20 14:40:00 | 346.9 s | 346.9 s | second |
| 2026-11-20 14:50:00 | 345.7 s | 345.7 s | second |
| 2026-11-20 14:55:00 | 345.8 s | 345.8 s | second |
| 2026-11-20 15:05:00 | 346.8 s | 346.8 s | second |
| 2026-11-20 15:10:00 | 346.1 s | 346.1 s | second |
| 2026-11-20 15:20:00 | 415.3 s | 415.3 s | second |
| 2026-11-20 15:25:00 | 368.6 s | 368.6 s | second |
| 2026-11-20 15:35:00 | 368.4 s | 368.4 s | second |

### First-cycle share by UTC hour (hour of the period close)

| Hour | First-cycle | Live rows | Share |
|---|---|---|---|
| 00 | 2 | 12 | 16.7% |
| 01 | 4 | 12 | 33.3% |
| 02 | 4 | 12 | 33.3% |
| 03 | 3 | 12 | 25.0% |
| 04 | 3 | 12 | 25.0% |
| 05 | 4 | 12 | 33.3% |
| 06 | 3 | 12 | 25.0% |
| 07 | 3 | 12 | 25.0% |
| 08 | 4 | 12 | 33.3% |
| 09 | 4 | 12 | 33.3% |
| 10 | 5 | 12 | 41.7% |
| 11 | 3 | 12 | 25.0% |
| 12 | 3 | 12 | 25.0% |
| 13 | 4 | 12 | 33.3% |
| 14 | 3 | 12 | 25.0% |
| 15 | 3 | 9 | 33.3% |
| 16 | 5 | 12 | 41.7% |
| 17 | 4 | 12 | 33.3% |
| 18 | 4 | 12 | 33.3% |
| 19 | 3 | 12 | 25.0% |
| 20 | 5 | 12 | 41.7% |
| 21 | 4 | 12 | 33.3% |
| 22 | 4 | 12 | 33.3% |
| 23 | 3 | 12 | 25.0% |

## top_position_long_short

Rows in file: 9195. Before cutoff (fetched_at_ms < since-ms): 8910. Skipped as backfilled (lag > 15 min): 0. Malformed: 0. Negative lag (excluded): 0. **Live rows analysed: 285.**

| Capture | Rows | Share |
|---|---|---|
| first-cycle | 85 | 29.8% |
| second-cycle | 200 | 70.2% |
| later | 0 | 0.0% |

Lag after close: p50 346.2 s, p90 346.8 s, p95 348.3 s, p99 369.2 s, max 415.9 s.

### Rows not captured in the first cycle (200 in total)

Showing the 20 most recent of 200.

| Timestamp (UTC) | Lag | Lag after close | Bucket |
|---|---|---|---|
| 2026-11-20 13:25:00 | 357.3 s | 357.3 s | second |
| 2026-11-20 13:30:00 | 349.3 s | 349.3 s | second |
| 2026-11-20 13:35:00 | 346.8 s | 346.8 s | second |
| 2026-11-20 13:45:00 | 346.7 s | 346.7 s | second |
| 2026-11-20 13:50:00 | 346.2 s | 346.2 s | second |
| 2026-11-20 14:00:00 | 346.2 s | 346.2 s | second |
| 2026-11-20 14:05:00 | 346.3 s | 346.3 s | second |
| 2026-11-20 14:10:00 | 346.2 s | 346.2 s | second |
| 2026-11-20 14:15:00 | 346.9 s | 346.9 s | second |
| 2026-11-20 14:25:00 | 346.2 s | 346.2 s | second |
| 2026-11-20 14:30:00 | 346.2 s | 346.2 s | second |
| 2026-11-20 14:40:00 | 347.9 s | 347.9 s | second |
| 2026-11-20 14:45:00 | 346.2 s | 346.2 s | second |
| 2026-11-20 14:55:00 | 346.3 s | 346.3 s | second |
| 2026-11-20 15:00:00 | 349.8 s | 349.8 s | second |
| 2026-11-20 15:05:00 | 347.8 s | 347.8 s | second |
| 2026-11-20 15:10:00 | 346.6 s | 346.6 s | second |
| 2026-11-20 15:20:00 | 415.9 s | 415.9 s | second |
| 2026-11-20 15:25:00 | 369.2 s | 369.2 s | second |
| 2026-11-20 15:35:00 | 368.9 s | 368.9 s | second |

### First-cycle share by UTC hour (hour of the period close)

| Hour | First-cycle | Live rows | Share |
|---|---|---|---|
| 00 | 4 | 12 | 33.3% |
| 01 | 3 | 12 | 25.0% |
| 02 | 4 | 12 | 33.3% |
| 03 | 4 | 12 | 33.3% |
| 04 | 4 | 12 | 33.3% |
| 05 | 3 | 12 | 25.0% |
| 06 | 3 | 12 | 25.0% |
| 07 | 3 | 12 | 25.0% |
| 08 | 4 | 12 | 33.3% |
| 09 | 4 | 12 | 33.3% |
| 10 | 5 | 12 | 41.7% |
| 11 | 3 | 12 | 25.0% |
| 12 | 4 | 12 | 33.3% |
| 13 | 3 | 12 | 25.0% |
| 14 | 3 | 12 | 25.0% |
| 15 | 2 | 9 | 22.2% |
| 16 | 6 | 12 | 50.0% |
| 17 | 3 | 12 | 25.0% |
| 18 | 3 | 12 | 25.0% |
| 19 | 3 | 12 | 25.0% |
| 20 | 5 | 12 | 41.7% |
| 21 | 3 | 12 | 25.0% |
| 22 | 3 | 12 | 25.0% |
| 23 | 3 | 12 | 25.0% |

## taker_buy_sell

Rows in file: 9195. Before cutoff (fetched_at_ms < since-ms): 8910. Skipped as backfilled (lag > 15 min): 0. Malformed: 0. Negative lag (excluded): 0. **Live rows analysed: 285.**

| Capture | Rows | Share |
|---|---|---|
| first-cycle | 20 | 7.0% |
| second-cycle | 265 | 93.0% |
| later | 0 | 0.0% |

Lag after close: p50 346.7 s, p90 347.7 s, p95 350.7 s, p99 369.8 s, max 416.4 s.
(Raw lag is this plus 300 s.)

### Rows not captured in the first cycle (265 in total)

Showing the 20 most recent of 265.

| Timestamp (UTC) | Lag | Lag after close | Bucket |
|---|---|---|---|
| 2026-11-20 13:50:00 | 646.7 s | 346.7 s | second |
| 2026-11-20 13:55:00 | 646.7 s | 346.7 s | second |
| 2026-11-20 14:00:00 | 646.7 s | 346.7 s | second |
| 2026-11-20 14:05:00 | 646.7 s | 346.7 s | second |
| 2026-11-20 14:10:00 | 647.4 s | 347.4 s | second |
| 2026-11-20 14:15:00 | 668.2 s | 368.2 s | second |
| 2026-11-20 14:20:00 | 646.7 s | 346.7 s | second |
| 2026-11-20 14:25:00 | 646.6 s | 346.6 s | second |
| 2026-11-20 14:30:00 | 646.7 s | 346.7 s | second |
| 2026-11-20 14:35:00 | 648.6 s | 348.6 s | second |
| 2026-11-20 14:40:00 | 646.6 s | 346.6 s | second |
| 2026-11-20 14:45:00 | 646.7 s | 346.7 s | second |
| 2026-11-20 14:50:00 | 646.8 s | 346.8 s | second |
| 2026-11-20 14:55:00 | 650.8 s | 350.8 s | second |
| 2026-11-20 15:00:00 | 648.3 s | 348.3 s | second |
| 2026-11-20 15:05:00 | 647.1 s | 347.1 s | second |
| 2026-11-20 15:10:00 | 647.0 s | 347.0 s | second |
| 2026-11-20 15:15:00 | 716.4 s | 416.4 s | second |
| 2026-11-20 15:20:00 | 669.7 s | 369.7 s | second |
| 2026-11-20 15:30:00 | 669.4 s | 369.4 s | second |

### First-cycle share by UTC hour (hour of the period close)

| Hour | First-cycle | Live rows | Share |
|---|---|---|---|
| 00 | 0 | 12 | 0.0% |
| 01 | 2 | 12 | 16.7% |
| 02 | 1 | 12 | 8.3% |
| 03 | 2 | 12 | 16.7% |
| 04 | 2 | 12 | 16.7% |
| 05 | 0 | 12 | 0.0% |
| 06 | 1 | 12 | 8.3% |
| 07 | 3 | 12 | 25.0% |
| 08 | 0 | 12 | 0.0% |
| 09 | 1 | 12 | 8.3% |
| 10 | 1 | 12 | 8.3% |
| 11 | 1 | 12 | 8.3% |
| 12 | 0 | 12 | 0.0% |
| 13 | 0 | 12 | 0.0% |
| 14 | 0 | 12 | 0.0% |
| 15 | 1 | 9 | 11.1% |
| 16 | 1 | 12 | 8.3% |
| 17 | 0 | 12 | 0.0% |
| 18 | 0 | 12 | 0.0% |
| 19 | 0 | 12 | 0.0% |
| 20 | 0 | 12 | 0.0% |
| 21 | 1 | 12 | 8.3% |
| 22 | 1 | 12 | 8.3% |
| 23 | 2 | 12 | 16.7% |

## Do the files agree?

Timestamps live in all of open_interest, global_long_short, top_position_long_short: 285.

- all three first-cycle: 8 (2.8%)
- all three NOT first-cycle: 122 (42.8%)
- mixed (one file late while another was on time, same timestamp): 155 (54.4%)

In mixed cases, the late file was: open_interest 105x, global_long_short 76x, top_position_long_short 78x.

| Timestamp (UTC) | open_interest | global_long_short | top_position_long_short |
|---|---|---|---|
| 2026-11-19 16:05:00 | second | second | first |
| 2026-11-19 16:10:00 | second | first | second |
| 2026-11-19 16:15:00 | first | second | first |
| 2026-11-19 16:25:00 | second | first | second |
| 2026-11-19 16:30:00 | first | second | first |
| 2026-11-19 16:35:00 | second | first | second |
| 2026-11-19 16:40:00 | second | second | first |
| 2026-11-19 16:45:00 | first | second | second |
| 2026-11-19 16:50:00 | second | first | second |
| 2026-11-19 16:55:00 | second | second | first |
| 2026-11-19 17:00:00 | first | first | second |
| 2026-11-19 17:15:00 | first | first | second |
| 2026-11-19 17:20:00 | second | second | first |
| 2026-11-19 17:30:00 | first | first | second |
| 2026-11-19 17:35:00 | second | second | first |
| 2026-11-19 17:50:00 | second | second | first |
| 2026-11-19 17:55:00 | second | first | second |
| 2026-11-19 18:10:00 | first | first | second |
| 2026-11-19 18:15:00 | second | second | first |
| 2026-11-19 18:25:00 | first | first | second |
| 2026-11-19 18:35:00 | second | first | second |
| 2026-11-19 18:40:00 | first | second | first |
| 2026-11-19 18:50:00 | second | first | second |
| 2026-11-19 18:55:00 | first | second | first |
| 2026-11-19 19:05:00 | second | first | second |
| 2026-11-19 19:10:00 | first | second | first |
| 2026-11-19 19:20:00 | second | second | first |
| 2026-11-19 19:25:00 | first | second | second |
| 2026-11-19 19:30:00 | second | first | second |
| 2026-11-19 19:35:00 | second | second | first |
| 2026-11-19 19:45:00 | second | first | second |
| 2026-11-19 20:00:00 | second | first | first |
| 2026-11-19 20:05:00 | first | second | second |
| 2026-11-19 20:10:00 | second | first | second |
| 2026-11-19 20:15:00 | second | second | first |
| 2026-11-19 20:20:00 | first | second | second |
| 2026-11-19 20:25:00 | second | first | second |
| 2026-11-19 20:30:00 | second | second | first |
| 2026-11-19 20:35:00 | first | second | second |
| 2026-11-19 20:40:00 | second | first | first |
| 2026-11-19 20:50:00 | first | second | second |
| 2026-11-19 20:55:00 | second | first | first |
| 2026-11-19 21:05:00 | first | first | second |
| 2026-11-19 21:10:00 | second | second | first |
| 2026-11-19 21:20:00 | first | first | second |
| 2026-11-19 21:35:00 | second | first | first |
| 2026-11-19 21:50:00 | second | first | first |
| 2026-11-19 22:05:00 | second | second | first |
| 2026-11-19 22:15:00 | second | first | second |
| 2026-11-19 22:40:00 | second | first | second |
| 2026-11-19 22:45:00 | first | second | first |
| 2026-11-19 22:55:00 | second | first | second |
| 2026-11-19 23:00:00 | first | second | second |
| 2026-11-19 23:10:00 | second | first | first |
| 2026-11-19 23:15:00 | first | second | second |
| 2026-11-19 23:25:00 | second | first | first |
| 2026-11-19 23:50:00 | second | first | first |
| 2026-11-20 00:05:00 | second | first | first |
| 2026-11-20 00:10:00 | first | second | second |
| 2026-11-20 00:15:00 | second | second | first |
| 2026-11-20 00:20:00 | second | first | second |
| 2026-11-20 00:25:00 | first | second | second |
| 2026-11-20 00:30:00 | second | second | first |
| 2026-11-20 00:40:00 | first | second | second |
| 2026-11-20 00:45:00 | second | second | first |
| 2026-11-20 00:55:00 | first | second | second |
| 2026-11-20 01:00:00 | second | first | first |
| 2026-11-20 01:10:00 | first | second | second |
| 2026-11-20 01:15:00 | second | first | second |
| 2026-11-20 01:25:00 | first | second | first |
| 2026-11-20 01:30:00 | second | first | second |
| 2026-11-20 01:40:00 | second | second | first |
| 2026-11-20 01:55:00 | second | first | second |
| 2026-11-20 02:05:00 | second | second | first |
| 2026-11-20 02:10:00 | second | first | second |
| 2026-11-20 02:20:00 | second | second | first |
| 2026-11-20 02:25:00 | second | first | second |
| 2026-11-20 02:35:00 | first | second | first |
| 2026-11-20 02:40:00 | second | first | second |
| 2026-11-20 02:45:00 | second | second | first |
| 2026-11-20 02:50:00 | first | second | second |
| 2026-11-20 02:55:00 | second | first | second |
| 2026-11-20 03:00:00 | second | second | first |
| 2026-11-20 03:05:00 | first | second | second |
| 2026-11-20 03:15:00 | second | second | first |
| 2026-11-20 03:20:00 | second | first | second |
| 2026-11-20 03:35:00 | second | first | second |
| 2026-11-20 03:40:00 | second | second | first |
| 2026-11-20 03:50:00 | second | first | second |
| 2026-11-20 03:55:00 | second | second | first |
| 2026-11-20 04:10:00 | second | second | first |
| 2026-11-20 04:15:00 | second | first | second |
| 2026-11-20 04:25:00 | second | second | first |
| 2026-11-20 04:30:00 | first | first | second |
| 2026-11-20 04:35:00 | second | second | first |
| 2026-11-20 04:45:00 | first | first | second |
| 2026-11-20 04:50:00 | second | second | first |
| 2026-11-20 05:00:00 | first | first | second |
| 2026-11-20 05:05:00 | second | second | first |
| 2026-11-20 05:15:00 | first | second | second |
| 2026-11-20 05:25:00 | second | first | second |
| 2026-11-20 05:30:00 | first | second | first |
| 2026-11-20 05:40:00 | second | first | second |
| 2026-11-20 05:45:00 | second | second | first |
| 2026-11-20 05:55:00 | second | first | second |
| 2026-11-20 06:25:00 | first | second | first |
| 2026-11-20 06:35:00 | second | first | second |
| 2026-11-20 06:40:00 | first | second | first |
| 2026-11-20 06:50:00 | second | first | second |
| 2026-11-20 06:55:00 | first | second | second |
| 2026-11-20 07:05:00 | second | first | first |
| 2026-11-20 07:20:00 | second | second | first |
| 2026-11-20 07:30:00 | second | first | second |
| 2026-11-20 07:45:00 | second | first | first |
| 2026-11-20 08:00:00 | second | first | first |
| 2026-11-20 08:15:00 | second | second | first |
| 2026-11-20 08:20:00 | first | second | second |
| 2026-11-20 08:25:00 | second | first | second |
| 2026-11-20 08:35:00 | first | second | second |
| 2026-11-20 08:40:00 | second | first | first |
| 2026-11-20 08:55:00 | second | first | first |
| 2026-11-20 09:10:00 | second | first | first |
| 2026-11-20 09:20:00 | second | first | first |
| 2026-11-20 09:35:00 | second | first | first |
| 2026-11-20 09:45:00 | first | first | second |
| 2026-11-20 09:50:00 | second | second | first |
| 2026-11-20 10:00:00 | first | first | second |
| 2026-11-20 10:05:00 | second | second | first |
| 2026-11-20 10:40:00 | second | first | first |
| 2026-11-20 10:55:00 | second | first | first |
| 2026-11-20 11:10:00 | second | first | first |
| 2026-11-20 11:35:00 | second | first | first |
| 2026-11-20 11:40:00 | first | second | second |
| 2026-11-20 11:50:00 | second | first | first |
| 2026-11-20 11:55:00 | first | second | second |
| 2026-11-20 12:05:00 | second | second | first |
| 2026-11-20 12:10:00 | first | second | second |
| 2026-11-20 12:15:00 | second | first | second |
| 2026-11-20 12:20:00 | second | second | first |
| 2026-11-20 12:25:00 | first | second | second |
| 2026-11-20 12:30:00 | second | first | second |
| 2026-11-20 12:35:00 | second | second | first |
| 2026-11-20 12:45:00 | second | first | first |
| 2026-11-20 13:00:00 | second | second | first |
| 2026-11-20 13:10:00 | second | first | second |
| 2026-11-20 13:25:00 | second | first | second |
| 2026-11-20 13:35:00 | first | first | second |
| 2026-11-20 13:40:00 | second | second | first |
| 2026-11-20 13:50:00 | first | first | second |
| 2026-11-20 13:55:00 | second | second | first |
| 2026-11-20 14:05:00 | first | first | second |
| 2026-11-20 14:35:00 | second | second | first |
| 2026-11-20 14:45:00 | second | first | second |
| 2026-11-20 14:50:00 | second | second | first |
| 2026-11-20 15:00:00 | first | first | second |
