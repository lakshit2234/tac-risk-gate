# Cross-exchange klines check: Binance vs Bybit (TACUSDT 1m)

- Binance file: `data\raw\binance_TACUSDT_1m.csv` (read-only)
- Bybit file: `data\raw\bybit_TACUSDT_1m.csv` (read-only)
- Verdict: **PASS** (Part A problems are hard failures; Part B items are flags)

## Hard failures

- none

## Warnings and flags

- Bybit volume: 123561 zero-volume candle(s)
- Compare: 328 minute(s) where close differs by more than 1.0%

## Part A: Bybit data quality

- First candle: 2025-07-15 11:00:00 UTC
- Last candle: 2026-11-18 17:03:00 UTC
- Rows: 707,404 (expected 707,404, missing 0)
- Zero-volume candles: 123,561

### Gaps (0)

none

## Part B: all-time low and high per exchange (whole files, from 1m low/high)

| | Binance | Bybit |
|---|---|---|
| Rows | 707,389 | 707,404 |
| All-time low | 0.000859 at 2026-11-08 21:55:00 UTC | 0.000863 at 2026-11-13 03:53:00 UTC |
| All-time high | 0.0687 at 2026-06-30 14:21:00 UTC | 0.06888 at 2026-06-30 14:21:00 UTC |

### Low prices (1m low below 0.0005; is 0.00031 ever reached?)

- Binance: lowest low 0.000859; lows below 0.0005: 0; lows at or below 0.00031: 0
- Bybit: lowest low 0.000863; lows below 0.0005: 0; lows at or below 0.00031: 0

## Part B: overlap

- Overlapping minutes: 707,359 (2025-07-15 11:00:00 UTC to 2026-11-18 16:18:00 UTC)
- Only in Binance: 30 minute(s) (30 outside the shared time range, 0 inside it, i.e. missing from the other file)
  - first: 2025-07-15 10:30:00 UTC, 2025-07-15 10:31:00 UTC, 2025-07-15 10:32:00 UTC, 2025-07-15 10:33:00 UTC, 2025-07-15 10:34:00 UTC
  - last: 2025-07-15 10:55:00 UTC, 2025-07-15 10:56:00 UTC, 2025-07-15 10:57:00 UTC, 2025-07-15 10:58:00 UTC, 2025-07-15 10:59:00 UTC
- Only in Bybit: 45 minute(s) (45 outside the shared time range, 0 inside it, i.e. missing from the other file)
  - first: 2026-11-18 16:19:00 UTC, 2026-11-18 16:20:00 UTC, 2026-11-18 16:21:00 UTC, 2026-11-18 16:22:00 UTC, 2026-11-18 16:23:00 UTC
  - last: 2026-11-18 16:59:00 UTC, 2026-11-18 17:00:00 UTC, 2026-11-18 17:01:00 UTC, 2026-11-18 17:02:00 UTC, 2026-11-18 17:03:00 UTC

## Part B: close-to-close difference, (Bybit / Binance - 1) in %

- mean -0.0892, median -0.0876, p99 of absolute 0.5296, max absolute 37.4265
- Correlation of 1m close-to-close returns: 0.9059 (over 707,358 consecutive-minute pairs present in both files)

### Top 10 largest differences

| Time (UTC) | Binance close | Bybit close | Diff % | Binance vol | Bybit vol |
|---|---|---|---|---|---|
| 2025-10-10 21:21:00 UTC | 0.00136 | 0.001869 | +37.426 | 1.58733e+07 | 3.36241e+06 |
| 2025-10-10 21:30:00 UTC | 0.00209 | 0.001618 | -22.584 | 3.24988e+07 | 5.11243e+06 |
| 2025-10-10 21:23:00 UTC | 0.00154 | 0.001287 | -16.429 | 1.5325e+07 | 4.1616e+06 |
| 2025-10-10 21:33:00 UTC | 0.00276 | 0.002335 | -15.399 | 5.30926e+06 | 367940 |
| 2026-07-07 15:07:00 UTC | 0.01578 | 0.013432 | -14.880 | 2.86207e+08 | 1.08176e+08 |
| 2025-10-10 21:41:00 UTC | 0.00262 | 0.002277 | -13.092 | 1.82776e+06 | 1.9026e+06 |
| 2025-10-10 21:27:00 UTC | 0.00147 | 0.00131 | -10.884 | 1.0508e+07 | 2.1255e+06 |
| 2025-10-10 21:44:00 UTC | 0.00301 | 0.00269 | -10.631 | 1.04699e+06 | 2.44393e+06 |
| 2025-10-10 21:42:00 UTC | 0.00267 | 0.00239 | -10.487 | 2.05406e+06 | 7.33681e+06 |
| 2025-10-10 21:24:00 UTC | 0.00109 | 0.001198 | +9.908 | 5.17789e+07 | 2.95316e+06 |

### Minutes where close differs by more than 1.0%: 328 (top 20 shown)

| Time (UTC) | Binance close | Bybit close | Diff % | Binance vol | Bybit vol |
|---|---|---|---|---|---|
| 2025-10-10 21:21:00 UTC | 0.00136 | 0.001869 | +37.426 | 1.58733e+07 | 3.36241e+06 |
| 2025-10-10 21:30:00 UTC | 0.00209 | 0.001618 | -22.584 | 3.24988e+07 | 5.11243e+06 |
| 2025-10-10 21:23:00 UTC | 0.00154 | 0.001287 | -16.429 | 1.5325e+07 | 4.1616e+06 |
| 2025-10-10 21:33:00 UTC | 0.00276 | 0.002335 | -15.399 | 5.30926e+06 | 367940 |
| 2026-07-07 15:07:00 UTC | 0.01578 | 0.013432 | -14.880 | 2.86207e+08 | 1.08176e+08 |
| 2025-10-10 21:41:00 UTC | 0.00262 | 0.002277 | -13.092 | 1.82776e+06 | 1.9026e+06 |
| 2025-10-10 21:27:00 UTC | 0.00147 | 0.00131 | -10.884 | 1.0508e+07 | 2.1255e+06 |
| 2025-10-10 21:44:00 UTC | 0.00301 | 0.00269 | -10.631 | 1.04699e+06 | 2.44393e+06 |
| 2025-10-10 21:42:00 UTC | 0.00267 | 0.00239 | -10.487 | 2.05406e+06 | 7.33681e+06 |
| 2025-10-10 21:24:00 UTC | 0.00109 | 0.001198 | +9.908 | 5.17789e+07 | 2.95316e+06 |
| 2025-10-10 21:19:00 UTC | 0.00287 | 0.003151 | +9.791 | 5.70361e+06 | 1.72747e+06 |
| 2025-10-10 21:43:00 UTC | 0.0029 | 0.00266 | -8.276 | 2.78953e+06 | 2.2495e+06 |
| 2026-07-07 15:21:00 UTC | 0.00869 | 0.008048 | -7.388 | 1.07147e+08 | 3.73079e+07 |
| 2025-10-10 21:29:00 UTC | 0.00152 | 0.00141 | -7.237 | 1.67787e+07 | 7.68949e+06 |
| 2026-07-07 15:24:00 UTC | 0.008602 | 0.00799 | -7.115 | 7.29152e+07 | 2.38782e+07 |
| 2025-10-10 21:31:00 UTC | 0.00189 | 0.00202 | +6.878 | 3.07139e+07 | 4.35781e+06 |
| 2025-10-10 21:45:00 UTC | 0.00303 | 0.00283 | -6.601 | 1.31105e+06 | 46480 |
| 2026-07-07 15:23:00 UTC | 0.008769 | 0.008196 | -6.534 | 8.41692e+07 | 3.29184e+07 |
| 2025-11-26 14:06:00 UTC | 0.012513 | 0.011745 | -6.138 | 4.78918e+08 | 1.1286e+08 |
| 2026-07-07 15:28:00 UTC | 0.006531 | 0.006132 | -6.109 | 1.98348e+08 | 7.12158e+07 |
