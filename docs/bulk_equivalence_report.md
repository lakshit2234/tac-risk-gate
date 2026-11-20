# Bulk archive equivalence and backfill cutover (TACUSDT)

Written 2026-11-20 (UTC). Two read-only checks; nothing here changes any rule or builds any feature. Downloads are in `data/raw/bulk_window/` (git-ignored) and every one was checked against its published checksum.

## Check 1: full-window equivalence with our recorder

- Bulk metrics files downloaded: 32 (2026-10-19 to 2026-11-19, the latest day the archive had when checked), 32 verified against their checksum. File URLs were built from the naming pattern; the archive was not listed for this.

### Per-column match with the fixed shift from the earlier report

This is the comparison the earlier report suggested: our timestamp = bulk label + 5 minutes (taker: + 0). Exact = equal at full precision. At our precision = the bulk value rounded to the decimals our file stores equals our value. The low rates here come from the label change described next, not from different values.

| Bulk column | Our column | Shift (min) | Rows compared | Our decimals | Exact | At our precision | Within 0.1% | Within 1% | Largest abs. difference |
|---|---|---|---|---|---|---|---|---|---|
| sum_open_interest | open_interest.sumOpenInterest | 5 | 9,008 | 8 | 87.21% | 87.21% | 95.36% | 99.79% | 2.03938e+08 |
| sum_open_interest_value | open_interest.sumOpenInterestValue | 5 | 9,008 | 8 | 87.21% | 87.21% | 89.46% | 98.19% | 888837 |
| count_long_short_ratio | global_long_short.longShortRatio | 5 | 9,008 | 4 | 0.04% | 2.69% | 89.40% | 98.27% | 0.376448 |
| sum_toptrader_long_short_ratio | top_position_long_short.longShortRatio | 5 | 9,008 | 4 | 0.72% | 87.16% | 93.64% | 99.66% | 0.032845 |
| sum_taker_long_short_vol_ratio | taker_buy_sell.buySellRatio | 0 | 9,008 | 4 | 0.02% | 3.33% | 57.17% | 87.41% | 19.3978 |

`count_toptrader_long_short_ratio` has no counterpart in our recorder files and was not compared.

### Label offset: is the bulk label always exactly 5 minutes before our timestamp?

Share of bulk open-interest rows equal to our open interest at our timestamp = bulk label + shift (9,216 bulk rows, whole window):

| Shift (min) | Rows with a counterpart | Equal |
|---|---|---|
| -10 | 9,005 | 0.00% |
| -5 | 9,006 | 0.00% |
| +0 | 9,007 | 12.80% |
| +5 | 9,008 | 87.21% |
| +10 | 9,009 | 0.01% |

Every bulk label is on a 5-minute boundary: yes.

**Answer: no.** Open interest equals ours at label + 5 minutes for 7,855 rows (up to 2026-11-15 23:55) and at label + 0 for 1,152 rows (from 2026-11-16 00:00); 0 rows that have a counterpart match at neither shift, 1 match at both, and 208 bulk rows have no counterpart in our file (they come before our first recorder row). The split is clean (every +5 row comes before every +0 row). So the bulk label convention changed by 5 minutes at the start of the file for that day. The same change appears in the other columns (the taker ratio moves from shift 0 to shift -5).

Share of rows that match at each shift, by bulk file day (open interest):

| Day | Equal at +5 | Equal at +0 |
|---|---|---|
| 2026-10-19 | 27.78% | 0.00% |
| 2026-10-20 | 100.00% | 0.00% |
| ... | | |
| 2026-11-14 | 100.00% | 0.00% |
| 2026-11-15 | 100.00% | 0.00% |
| 2026-11-16 | 0.00% | 100.00% |
| 2026-11-17 | 0.00% | 100.00% |
| 2026-11-18 | 0.00% | 100.00% |
| 2026-11-19 | 0.00% | 100.00% |

### Per-column match with the label change allowed for

Same comparison, but the shift is 5 minutes smaller from the label-change date on (open interest, long/short: +5 then +0; taker: 0 then -5).

| Bulk column | Our column | Shift (min) | Rows compared | Our decimals | Exact | At our precision | Within 0.1% | Within 1% | Largest abs. difference |
|---|---|---|---|---|---|---|---|---|---|
| sum_open_interest | open_interest.sumOpenInterest | 5 before the label change, 0 from it on | 9,008 | 8 | 100.00% | 100.00% | 100.00% | 100.00% | 0 |
| sum_open_interest_value | open_interest.sumOpenInterestValue | 5 before the label change, 0 from it on | 9,008 | 8 | 100.00% | 100.00% | 100.00% | 100.00% | 0 |
| count_long_short_ratio | global_long_short.longShortRatio | 5 before the label change, 0 from it on | 9,008 | 4 | 0.04% | 3.34% | 100.00% | 100.00% | 0.00235901 |
| sum_toptrader_long_short_ratio | top_position_long_short.longShortRatio | 5 before the label change, 0 from it on | 9,008 | 4 | 0.89% | 99.50% | 100.00% | 100.00% | 5e-05 |
| sum_taker_long_short_vol_ratio | taker_buy_sell.buySellRatio | 0 before the label change, -5 from it on | 9,008 | 4 | 0.02% | 3.89% | 64.28% | 100.00% | 0.059691 |

First 5 mismatches at our precision for `count_long_short_ratio` (our timestamp ms, bulk value, our value):

- 1792430700000 (2026-10-19 17:25): bulk 4.59619687, ours 4.596
- 1792431000000 (2026-10-19 17:30): bulk 4.62767154, ours 4.6275
- 1792431300000 (2026-10-19 17:35): bulk 4.62767154, ours 4.6275
- 1792431600000 (2026-10-19 17:40): bulk 4.62767154, ours 4.6275
- 1792431900000 (2026-10-19 17:45): bulk 4.62654668, ours 4.6275

First 5 mismatches at our precision for `sum_toptrader_long_short_ratio` (our timestamp ms, bulk value, our value):

- 1792461000000 (2026-10-20 01:50): bulk 1.17175, ours 1.1717
- 1792473300000 (2026-10-20 05:15): bulk 1.16705, ours 1.1671
- 1792690500000 (2026-10-22 17:35): bulk 1.18075, ours 1.1807
- 1792752900000 (2026-10-23 10:55): bulk 1.19955, ours 1.1996
- 1792836900000 (2026-10-24 10:15): bulk 1.18655, ours 1.1865

First 5 mismatches at our precision for `sum_taker_long_short_vol_ratio` (our timestamp ms, bulk value, our value):

- 1792430400000 (2026-10-19 17:20): bulk 0.28326, ours 0.2828
- 1792431000000 (2026-10-19 17:30): bulk 4.124412, ours 4.1232
- 1792431300000 (2026-10-19 17:35): bulk 1.231249, ours 1.2307
- 1792431600000 (2026-10-19 17:40): bulk 0.513508, ours 0.5132
- 1792431900000 (2026-10-19 17:45): bulk 1.784667, ours 1.784

### Taker ratio: why only part of the rows match

All tests use the bulk rows aligned to our periods (shift allowed for as above), so shift 0 means the same 5-minute period.

| Explanation tested | Rows | Share equal |
|---|---|---|
| baseline: our ratio, same period, within 0.1% | 9,007 | 64.27% |
| rounding: bulk rounded to 4 decimals equals our buySellRatio | 9,007 | 3.89% |
| rounding: bulk equals our own buyVol / sellVol to 1e-6 | 9,007 | 0.02% |
| volumes: bulk equals our own buyVol / sellVol within 0.1% | 9,007 | 64.49% |
| internal: our buySellRatio equals our own buyVol / sellVol within 0.1% (no bulk data involved) | 9,231 | 99.97% |
| alignment: our ratio -10 min from the aligned period, within 0.1% | 9,005 | 0.04% |
| alignment: our ratio -5 min from the aligned period, within 0.1% | 9,006 | 0.07% |
| alignment: our ratio +5 min from the aligned period, within 0.1% | 9,008 | 0.07% |
| alignment: our ratio +10 min from the aligned period, within 0.1% | 9,009 | 0.04% |
| window: this and the next 5-minute period, within 0.1% | 9,007 | 0.14% |
| window: this and the previous 5-minute period, within 0.1% | 9,006 | 0.20% |

Relative difference between the bulk ratio and our ratio at the aligned period (9,007 rows): median 0.080%, 95th percentile 0.24%, largest 0.97%.

**Result: unexplained: no tested explanation reaches 99% of rows.**

### Live versus backfilled recorder rows

Our rows are called backfilled when fetched_at_ms is more than 15 minutes after the timestamp, otherwise live (the recorder rule). Rates are for the label-change-aware comparison; 'within 0.1%' because our ratios are rounded.

| Bulk column | Live rows | Live: exact | Live: within 0.1% | Backfilled rows | Backfilled: exact | Backfilled: within 0.1% |
|---|---|---|---|---|---|---|
| sum_open_interest | 118 | 100.00% | 100.00% | 8,890 | 100.00% | 100.00% |
| sum_open_interest_value | 118 | 100.00% | 100.00% | 8,890 | 100.00% | 100.00% |
| count_long_short_ratio | 118 | 0.00% | 100.00% | 8,890 | 0.04% | 100.00% |
| sum_toptrader_long_short_ratio | 118 | 1.69% | 100.00% | 8,890 | 0.88% | 100.00% |
| sum_taker_long_short_vol_ratio | 115 | 0.00% | 70.43% | 8,893 | 0.02% | 64.20% |

### bookDepth against our depth snapshot

Our snapshot bands are 0.5, 1 and 2 percent of mid. The bulk file has the levels listed below. Only 1 and 2 percent correspond; the 0.5 percent band has no counterpart and the other bulk levels have none in our snapshot. Our value is a USD depth within the band of our own mid; whether the bulk `notional` uses the same reference price and the same definition is not stated in the file, so this is a plausibility check, not proof.

**2026-11-18**: bulk levels -5, -4, -3, -2, -1, -0.2, 0.2, 1, 2, 3, 4, 5; our snapshot rows matched to a bulk snapshot within 30 s: 9.

| Our column | Rows | Median ours / bulk | 5th pct | 95th pct | Within 10% |
|---|---|---|---|---|---|
| bid_depth_usd_1pct | 9 | 1.009 | 0.938 | 1.246 | 66.67% |
| ask_depth_usd_1pct | 9 | 1.032 | 0.887 | 1.148 | 66.67% |
| bid_depth_usd_2pct | 9 | 0.999 | 0.975 | 1.208 | 88.89% |
| ask_depth_usd_2pct | 9 | 1.011 | 0.943 | 1.084 | 88.89% |

**2026-11-19**: bulk levels -5, -4, -3, -2, -1, -0.2, 0.2, 1, 2, 3, 4, 5; our snapshot rows matched to a bulk snapshot within 30 s: 104.

| Our column | Rows | Median ours / bulk | 5th pct | 95th pct | Within 10% |
|---|---|---|---|---|---|
| bid_depth_usd_1pct | 104 | 1.000 | 0.939 | 1.098 | 92.31% |
| ask_depth_usd_1pct | 104 | 1.000 | 0.929 | 1.094 | 95.19% |
| bid_depth_usd_2pct | 104 | 1.000 | 0.933 | 1.058 | 96.15% |
| ask_depth_usd_2pct | 104 | 1.000 | 0.956 | 1.047 | 100.00% |

## Check 2: backfill cutover

The four check-2 listing requests (metrics, bookDepth, klines 1m, markPriceKlines 1m) were made twice in total: once in a first run whose listing results I did not save, and once more with the results cached. All later runs used the cache and made no listing request.

Lag = hours between the end of the UTC day and the file's LastModified time (from one listing per dataset). Cutover = the earliest date from which the lag is below 48 hours for every later day.

| Dataset | Daily files | Cutover date (strict) | Cutover ignoring isolated re-written files | Files at or above 48 h |
|---|---|---|---|---|
| metrics | 493 | 2026-08-13 | 2026-07-12 | 363 |
| bookDepth | 491 | 2025-07-15 | 2025-07-15 | 0 |
| klines | 493 | 2026-10-29 | 2025-07-15 | 1 |
| markPriceKlines | 493 | 2026-10-30 | 2026-10-30 | 3 |

Strict = the date you asked for: the lag is below 48 hours for every later day. The second date treats a single slow file with fast neighbours on both sides as an isolated re-written file and ignores it. For the other datasets the strict date is decided by one or a few slow recent files, not by a long backfilled era.

Metrics files at or above 48 h since 2026-06-01 (these decide the metrics cutover date):

| Day | Lag |
|---|---|
| 2026-06-01 | 1945.5 h |
| 2026-06-02 | 1921.5 h |
| 2026-06-03 | 1898.1 h |
| 2026-06-04 | 1874.6 h |
| 2026-06-05 | 1851.0 h |
| 2026-06-06 | 1827.4 h |
| 2026-06-07 | 1803.8 h |
| 2026-06-08 | 1780.5 h |
| 2026-06-09 | 1757.0 h |
| 2026-06-10 | 1706.7 h |
| 2026-06-11 | 1646.0 h |
| 2026-06-12 | 1575.2 h |
| 2026-06-13 | 1480.3 h |
| 2026-06-14 | 1420.2 h |
| 2026-06-15 | 1358.7 h |
| 2026-06-16 | 1299.7 h |
| 2026-06-17 | 1206.1 h |
| 2026-06-18 | 1144.9 h |
| 2026-06-19 | 1093.5 h |
| 2026-06-20 | 1038.9 h |
| 2026-06-21 | 954.3 h |
| 2026-06-22 | 906.1 h |
| 2026-06-23 | 872.6 h |
| 2026-06-24 | 822.2 h |
| 2026-06-25 | 772.4 h |
| 2026-06-26 | 727.2 h |
| 2026-06-27 | 701.0 h |
| 2026-06-28 | 2414.9 h |
| 2026-06-29 | 558.9 h |
| 2026-06-30 | 511.9 h |
| 2026-07-01 | 461.6 h |
| 2026-07-02 | 419.6 h |
| 2026-07-03 | 392.6 h |
| 2026-07-04 | 302.9 h |
| 2026-07-05 | 2247.4 h |
| 2026-07-06 | 248.8 h |
| 2026-07-07 | 220.5 h |
| 2026-07-08 | 175.9 h |
| 2026-07-09 | 2151.9 h |
| 2026-07-10 | 125.5 h |
| 2026-07-11 | 88.1 h |
| 2026-08-12 | 776.8 h |

Lag by month, metrics:

| Month | Files | Median lag | Max lag | Files at or above 48 h |
|---|---|---|---|---|
| 2025-07 | 17 | 9037.2 h | 9215.9 h | 17 |
| 2025-08 | 31 | 8483.3 h | 8828.9 h | 31 |
| 2025-09 | 30 | 7779.7 h | 8113.5 h | 30 |
| 2025-10 | 31 | 7081.4 h | 7428.2 h | 31 |
| 2025-11 | 30 | 6418.8 h | 6755.7 h | 30 |
| 2025-12 | 31 | 5724.4 h | 6070.3 h | 31 |
| 2026-01 | 31 | 5014.4 h | 5362.6 h | 31 |
| 2026-02 | 28 | 4342.6 h | 4655.9 h | 28 |
| 2026-03 | 31 | 3709.3 h | 4052.0 h | 31 |
| 2026-04 | 30 | 3024.1 h | 3359.1 h | 30 |
| 2026-05 | 31 | 2318.8 h | 2669.9 h | 31 |
| 2026-06 | 30 | 1389.5 h | 2414.9 h | 30 |
| 2026-07 | 31 | 8.5 h | 2247.4 h | 11 |
| 2026-08 | 31 | 7.0 h | 776.8 h | 1 |
| 2026-09 | 30 | 7.0 h | 8.2 h | 0 |
| 2026-10 | 31 | 6.9 h | 10.2 h | 0 |
| 2026-11 | 19 | 6.8 h | 8.3 h | 0 |

Lag by month, bookDepth:

| Month | Files | Median lag | Max lag | Files at or above 48 h |
|---|---|---|---|---|
| 2025-07 | 17 | 7.2 h | 8.0 h | 0 |
| 2025-08 | 31 | 7.2 h | 8.0 h | 0 |
| 2025-09 | 30 | 7.2 h | 8.3 h | 0 |
| 2025-10 | 31 | 7.3 h | 7.7 h | 0 |
| 2025-11 | 30 | 7.4 h | 8.0 h | 0 |
| 2025-12 | 31 | 7.5 h | 7.9 h | 0 |
| 2026-01 | 30 | 7.4 h | 8.9 h | 0 |
| 2026-02 | 28 | 7.5 h | 8.3 h | 0 |
| 2026-03 | 31 | 7.5 h | 8.2 h | 0 |
| 2026-04 | 30 | 7.6 h | 8.6 h | 0 |
| 2026-05 | 31 | 7.5 h | 8.8 h | 0 |
| 2026-06 | 30 | 7.7 h | 9.4 h | 0 |
| 2026-07 | 31 | 7.9 h | 10.4 h | 0 |
| 2026-08 | 31 | 7.5 h | 9.5 h | 0 |
| 2026-09 | 30 | 7.8 h | 9.5 h | 0 |
| 2026-10 | 30 | 8.0 h | 11.6 h | 0 |
| 2026-11 | 19 | 7.8 h | 10.3 h | 0 |

Lag by month, klines:

| Month | Files | Median lag | Max lag | Files at or above 48 h |
|---|---|---|---|---|
| 2025-07 | 17 | 8.1 h | 9.8 h | 0 |
| 2025-08 | 31 | 8.3 h | 9.1 h | 0 |
| 2025-09 | 30 | 8.3 h | 9.5 h | 0 |
| 2025-10 | 31 | 8.5 h | 39.0 h | 0 |
| 2025-11 | 30 | 8.7 h | 9.8 h | 0 |
| 2025-12 | 31 | 8.8 h | 9.7 h | 0 |
| 2026-01 | 31 | 9.0 h | 11.7 h | 0 |
| 2026-02 | 28 | 9.1 h | 11.0 h | 0 |
| 2026-03 | 31 | 9.0 h | 10.7 h | 0 |
| 2026-04 | 30 | 9.4 h | 10.7 h | 0 |
| 2026-05 | 31 | 9.4 h | 10.4 h | 0 |
| 2026-06 | 30 | 9.7 h | 11.0 h | 0 |
| 2026-07 | 31 | 10.3 h | 13.7 h | 0 |
| 2026-08 | 31 | 9.5 h | 14.5 h | 0 |
| 2026-09 | 30 | 8.5 h | 11.6 h | 0 |
| 2026-10 | 31 | 9.0 h | 317.7 h | 1 |
| 2026-11 | 19 | 8.6 h | 12.8 h | 0 |

Lag by month, markPriceKlines:

| Month | Files | Median lag | Max lag | Files at or above 48 h |
|---|---|---|---|---|
| 2025-07 | 17 | 8.4 h | 10.3 h | 0 |
| 2025-08 | 31 | 8.8 h | 11.0 h | 0 |
| 2025-09 | 30 | 8.8 h | 10.0 h | 0 |
| 2025-10 | 31 | 8.9 h | 10.0 h | 0 |
| 2025-11 | 30 | 9.3 h | 11.6 h | 0 |
| 2025-12 | 31 | 9.3 h | 10.3 h | 0 |
| 2026-01 | 31 | 9.5 h | 12.2 h | 0 |
| 2026-02 | 28 | 9.8 h | 11.9 h | 0 |
| 2026-03 | 31 | 10.0 h | 12.2 h | 0 |
| 2026-04 | 30 | 10.2 h | 12.2 h | 0 |
| 2026-05 | 31 | 10.4 h | 12.1 h | 0 |
| 2026-06 | 30 | 11.4 h | 570.5 h | 1 |
| 2026-07 | 31 | 10.4 h | 14.0 h | 0 |
| 2026-08 | 31 | 9.6 h | 14.3 h | 0 |
| 2026-09 | 30 | 8.6 h | 10.8 h | 0 |
| 2026-10 | 31 | 8.8 h | 279.0 h | 2 |
| 2026-11 | 19 | 8.6 h | 13.0 h | 0 |

### Four metrics files compared

| Item | old file: 2025-08-01 | day before the cutover: 2026-08-12 | cutover day: 2026-08-13 | recent file: 2026-11-10 |
|---|---|---|---|---|
| Rows | 288 | 288 | 288 | 288 |
| Missing 5-minute slots (of 288) | 0 | 0 | 0 | 0 |
| Duplicate labels | 0 | 0 | 0 | 0 |
| Rows sorted by time | yes | NO | NO | NO |
| Label format | datetime text | datetime text | datetime text | datetime text |
| Symbols | TACUSDT | TACUSDT | TACUSDT | TACUSDT |
| Decimals: sum_open_interest | 16 | 16 | 16 | 16 |
| Decimals: sum_open_interest_value | 16 | 16 | 16 | 16 |
| Decimals: count_toptrader_long_short_ratio | 8 | 8 | 8 | 8 |
| Decimals: sum_toptrader_long_short_ratio | 8 | 8 | 8 | 8 |
| Decimals: count_long_short_ratio | 8 | 8 | 8 | 8 |
| Decimals: sum_taker_long_short_vol_ratio | 8 | 8 | 8 | 8 |
| Header | same as the first file | same as the first file | same as the first file | same as the first file |

Compared with the 2025-08-01 file, the others differ in: day before the cutover (2026-08-12): row order; cutover day (2026-08-13): row order; recent file (2026-11-10): row order.

What four files can and cannot show: they show whether the file FORMAT changed between the sampled dates. They cannot show how the VALUES were produced; that can only be tested against another source, and the only one we have (our recorder) starts on 2026-10-19.

Two window files either side of the label change (already downloaded for check 1, no extra request):

| Day | Rows | Missing slots | Sorted | Decimals (OI / ratios) |
|---|---|---|---|---|
| 2026-11-15 | 288 | 0 | NO | 16 / 8 |
| 2026-11-16 | 288 | 0 | NO | 16 / 8 |

- The listing results came from the cache written by the earlier run (no listing request was made this time).

## Recommendation on the known-time rule

**This is a recommendation only. No rule has been adopted.**

The rule used so far for bulk rows is: known at the end of the UTC day plus 24 hours (or the file's LastModified time if later).
- **Files from 2026-08-13 on (publish lag below 48 hours for every day):** the day-end rule is supported by the observed lag and can stay as the default. (Ignoring isolated re-written files, the lag has been below 48 hours since 2026-07-12; the strict date is moved by one slow file.)
- **Files before 2026-08-13:** the file time says only when the archive was filled, not when the data existed, so the day-end rule must stay as the most conservative choice. This check cannot show whether their values were produced the same way, because our recorder only covers 2026-10-19 onward.
- **A tighter rule for open interest is supported only inside our recorder window (2026-10-19 onward).** There, once the label change on 2026-11-16 00:00 is allowed for, the bulk open interest equals our recorder value in 100.00% of 9,008 rows. A rule such as "our API timestamp plus 10 minutes" (the recorder's rule) would then be justified for those rows, expressed in OUR timestamp, because the bulk label is not a stable reference: it sits 5 minutes before our timestamp until the change and equals it afterwards. A rule written as "bulk label plus 10 minutes" would be wrong by 5 minutes on one side of that date.
- For days before 2026-10-19 there is no second source, so the label convention and the equality are not shown; keep the day-end rule there.
- `count_long_short_ratio`: within 0.1% of our value in 100.00% of rows, equal at our 4-decimal precision in 3.34%. Close but not identical, so the tighter rule is justified only if a feature can tolerate differences of that size; otherwise keep the day-end rule.
- `sum_toptrader_long_short_ratio`: within 0.1% of our value in 100.00% of rows, equal at our 4-decimal precision in 99.50%. Close but not identical, so the tighter rule is justified only if a feature can tolerate differences of that size; otherwise keep the day-end rule.
- Taker ratio: within 0.1% of our value in 64.28% of rows; explanation test: unexplained: no tested explanation reaches 99% of rows. Keep the day-end rule until the differences are explained.
- Whatever is decided, the decision belongs to you; this report only lists what the data support.

## Decisions

**Decided by the user on 2026-11-21.** These replace the recommendation above for the points they cover.

1. Bulk metrics are normalized to our timestamp convention: the bulk label plus 5 minutes before 2026-11-16 00:00 UTC, and the bulk label unchanged from that time on.
2. Open interest is known at our timestamp plus 10 minutes only from 2026-10-19 on, because that part was verified against the recorder. Everywhere else the rule is UTC day end plus 24 hours, or the file's LastModified time if that is later.
3. The long/short ratios, the taker ratio and bookDepth use UTC day end plus 24 hours everywhere for now.
4. Metrics values before 2026-07-12 are marked as an unverified era: the archive wrote them months late and our recorder cannot check them.
5. The checksums of downloaded files must be pinned, and the label convention must be rechecked against the recorder on every rerun, because Binance could rewrite old files.
6. Consequence for the backtest: intraday features come from klines, mark, index and premium klines, and funding. Open interest, the ratios, the taker ratio and depth enter with a day lag until proven otherwise.

## Open item

An independent check of the taker ratio over the whole history is still to do: derive buy over sell volume per 5 minutes from our 1m klines (taker_buy_volume) and compare it with the bulk taker ratio, including the backfilled era. Nothing from the bulk archive has been used as a feature.
