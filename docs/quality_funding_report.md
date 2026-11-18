# Funding rate quality report (Gate 1)

- File: `data\raw\binance_TACUSDT_funding.csv` (read-only; never modified)
- Verdict: **PASS**

## Hard failures

- none

## Warnings

- Interval: 1 gap(s) that are not 4h (listed in report)
- Rate: 181 rate(s) > 0.0005 and 22 < -0.0005 (flagged, kept)

## Summary

- First fundingTime: 2025-07-15 12:00:00 UTC
- Last fundingTime: 2026-11-18 16:00:00 UTC
- Rows: 2,947
- Expected rows if fixed 4h: 2,948 (difference +1)
- rateType counts: {'Regular': 2947}
- markPrice blank/non-numeric: 0, zero or negative: 0

## Interval distribution (gap between consecutive fundingTime, in hours)

| Gap (h) | Count |
|---|---|
| 4.00 | 2,945 |
| 8.00 | 1 |

Gaps are bucketed to 0.01h. Of the 4h gaps, 789 are exactly 14,400,000 ms and 2,156 are off by milliseconds (range -24 to 26 ms). Gaps within +-60s of 4h count as 4h; every other gap is listed below.

## Gaps that are not 4h (1)

| From (UTC) | To (UTC) | Gap (h) | Severity |
|---|---|---|---|
| 2026-06-24 00:00:00 UTC | 2026-06-24 08:00:00 UTC | 8.00 | warning |

## Row count vs a fixed 4h grid

- Rows: 2,947. Expected if every interval were exactly 4h: 2,948 = round((last - first) / 4h) + 1. Difference: +1.
- 2,946 intervals separate 2,947 rows. The span holds 2,947 four-hour slots, so each interval of g hours accounts for (g / 4 - 1) slots more than one row.
- 2026-06-24 00:00:00 UTC -> 2026-06-24 08:00:00 UTC: interval of 8.00h = +1.00 slot(s) vs a 4h step.
- Sum over the non-4h intervals: +1.00 slot(s) (millisecond jitter on the other intervals adds up to well under one slot). This matches the difference of +1: rows are fewer than a pure-4h grid by exactly the slots those intervals skip.

## Funding rate sanity (flagged, never removed)

- min -0.00215101, max 0.00521896, mean 0.00014418, median 0.00005000
- above 0.0005: 181; below -0.0005: 22

Top 10 by absolute rate:

| Time (UTC) | fundingRate | markPrice | rateType |
|---|---|---|---|
| 2025-11-26 16:00:00 UTC | +0.00521896 | 0.006493 | Regular |
| 2025-07-15 12:00:00 UTC | -0.00215101 | 0.02103583 | Regular |
| 2025-11-08 00:00:00 UTC | +0.00209709 | 0.005729 | Regular |
| 2025-08-23 12:00:00 UTC | -0.00207773 | 0.01446 | Regular |
| 2026-11-14 04:00:00 UTC | -0.00190149 | 0.001159 | Regular |
| 2026-08-27 08:00:00 UTC | -0.00174854 | 0.00721726 | Regular |
| 2025-11-07 20:00:00 UTC | +0.00164924 | 0.005866 | Regular |
| 2025-10-09 08:00:00 UTC | +0.00152460 | 0.00660496 | Regular |
| 2026-11-14 08:00:00 UTC | -0.00151111 | 0.00117729 | Regular |
| 2025-07-17 16:00:00 UTC | +0.00138551 | 0.01423058 | Regular |
