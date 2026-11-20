# Bulk metrics history (TACUSDT USD-M futures)

Written 2026-11-20 (UTC). Facts and what could not be shown; no rule is changed and no feature or model was built. The rules used to build the normalized file are the user's decisions of 2026-11-21 in docs/bulk_equivalence_report.md.

## Download

- Days processed: 493; verified against the published checksum: **493**; already on disk and checked again against the published checksum (not downloaded again): 493.
- Revisions (an archive file differing from the copy on disk): **0**. Other failures (mismatch, no checksum, 404): **0**.
- Stopped by a refusal: no.
- Pinned manifest `data/static/bulk_metrics_manifest.csv`: 493 rows. LastModified per file comes from the cached listing of the earlier bulk_equivalence run.

Run history (one line per run; the first line was recorded from the console output of the first run):

- 2026-11-20 UTC (first run, recorded afterwards from its console output): days 493, verified 493, reused from earlier downloads 35, newly downloaded 458, revisions 0, failures 0, stopped: no, normalized rows added 141855
- 2026-11-20 19:14:53 UTC: days 493, verified 493, reused from disk 493, revisions 0, failures 0, stopped: no, normalized rows added 0

## Normalized file

- Rows added this run: 0 from 0 days; days already present: 493.
- Bulk labels from 2025-07-15 10:30:00 to 2026-11-19 23:55:00 UTC; total rows 141,855.
- Rules: ts_ours_ms = label + 5 min before 2026-11-16 00:00 UTC, the label from then on; known_at_oi_ms = ts_ours_ms + 10 min from 2026-10-19 on, otherwise the later of UTC day end of the file date + 24 h and LastModified; known_at_other_ms always the later of those two; unverified_era = true before 2026-07-12. Rows between 2026-10-19 00:00 and our first recorder row (17:25) are covered by the 2026-10-19 rule as decided, although the recorder cannot check them.

## Quality checks

- Rows: 141,855 over 493 days; days without exactly 288 rows: 2 (2025-07-15: 162, 2025-08-29: 285).
- Missing 5-minute slots inside the range: 3 (first: 2025-08-29 06:20:00, 2025-08-29 06:25:00, 2025-08-29 06:30:00).
- Duplicate labels: 0. Rows in time order: yes (0 backward steps).
- Open interest at or below zero: 25; not a number: 0.
- One-step open-interest jumps above 50%: 24: 2025-07-21 16:20:00 (-100%); 2025-07-21 17:10:00 (+inf%); 2026-10-15 10:55:00 (-82%); 2026-10-15 11:15:00 (+493%); 2026-10-15 11:20:00 (-81%); 2026-10-15 11:50:00 (+447%); 2026-10-15 11:55:00 (-82%); 2026-10-15 12:30:00 (+460%); 2026-10-15 12:35:00 (-82%); 2026-10-15 12:40:00 (+465%) (jumps after a gap in the labels: 0).
- Symbols: TACUSDT.

| Ratio column | Min | Max | At or below zero | Not a number |
|---|---|---|---|---|
| count_toptrader_long_short_ratio | 0.279782 | 6.50826 | 0 | 41 |
| sum_toptrader_long_short_ratio | 0.372497 | 2.24041 | 0 | 12 |
| count_long_short_ratio | 0.301222 | 6.00257 | 0 | 13 |
| sum_taker_long_short_vol_ratio | 0 | 9166 | 39 | 27 |

### Monthly distributions (median, 5th and 95th percentile)

**sum_open_interest**

| Month | Rows | Median | 5th pct | 95th pct |
|---|---|---|---|---|
| 2025-07 | 4,770 | 2.53401e+08 | 1.8472e+08 | 3.5253e+08 |
| 2025-08 | 8,925 | 2.26484e+08 | 1.53811e+08 | 2.94687e+08 |
| 2025-09 | 8,640 | 1.70634e+08 | 1.59995e+08 | 1.92356e+08 |
| 2025-10 | 8,928 | 2.4507e+08 | 1.94747e+08 | 2.98493e+08 |
| 2025-11 | 8,640 | 3.2147e+08 | 2.92599e+08 | 7.15836e+08 |
| 2025-12 | 8,928 | 3.68614e+08 | 3.01214e+08 | 4.79026e+08 |
| 2026-01 | 8,928 | 2.81197e+08 | 2.5538e+08 | 3.02369e+08 |
| 2026-02 | 8,064 | 3.11017e+08 | 2.8786e+08 | 3.20385e+08 |
| 2026-03 | 8,928 | 3.25962e+08 | 2.87142e+08 | 3.83544e+08 |
| 2026-04 | 8,640 | 3.94144e+08 | 3.79658e+08 | 5.94372e+08 |
| 2026-05 | 8,928 | 3.33674e+08 | 2.43326e+08 | 4.86804e+08 |
| 2026-06 | 8,640 | 2.31779e+08 | 1.98147e+08 | 4.48375e+08 |
| 2026-07 | 8,928 | 9.2142e+08 | 2.71273e+08 | 1.66653e+09 |
| 2026-08 | 8,928 | 8.35836e+08 | 8.13594e+08 | 2.08424e+09 |
| 2026-09 | 8,640 | 1.68485e+09 | 1.4489e+09 | 1.82667e+09 |
| 2026-10 | 8,928 | 1.88753e+09 | 1.792e+09 | 2.02154e+09 |
| 2026-11 | 5,472 | 2.21998e+09 | 2.04845e+09 | 3.48646e+09 |

**count_toptrader_long_short_ratio**

| Month | Rows | Median | 5th pct | 95th pct |
|---|---|---|---|---|
| 2025-07 | 4,731 | 0.922851 | 0.72443 | 1.69986 |
| 2025-08 | 8,925 | 1.51973 | 1.00506 | 1.86977 |
| 2025-09 | 8,639 | 2.27235 | 1.60917 | 2.96429 |
| 2025-10 | 8,928 | 2.92627 | 2.36382 | 3.5485 |
| 2025-11 | 8,640 | 2.06168 | 1.29218 | 3.08747 |
| 2025-12 | 8,928 | 1.57597 | 1.05562 | 2.7582 |
| 2026-01 | 8,928 | 2.87308 | 2.32455 | 3.51213 |
| 2026-02 | 8,064 | 2.57388 | 1.97728 | 3.0373 |
| 2026-03 | 8,927 | 2.83257 | 2.26684 | 3.32992 |
| 2026-04 | 8,640 | 2.71663 | 0.587186 | 3.18527 |
| 2026-05 | 8,928 | 0.687387 | 0.473301 | 1.08624 |
| 2026-06 | 8,640 | 1.28112 | 0.361176 | 1.60229 |
| 2026-07 | 8,928 | 1.73476 | 0.686853 | 2.80932 |
| 2026-08 | 8,928 | 3.5098 | 1.14378 | 4.80087 |
| 2026-09 | 8,640 | 2.87374 | 1.7151 | 5.14124 |
| 2026-10 | 8,928 | 5.16896 | 4.46914 | 6.05088 |
| 2026-11 | 5,472 | 5.21934 | 2.29871 | 6.2163 |

**sum_toptrader_long_short_ratio**

| Month | Rows | Median | 5th pct | 95th pct |
|---|---|---|---|---|
| 2025-07 | 4,760 | 1.50642 | 1.23666 | 2.06326 |
| 2025-08 | 8,925 | 1.00235 | 0.830944 | 1.61748 |
| 2025-09 | 8,639 | 1.03893 | 0.886284 | 1.16463 |
| 2025-10 | 8,928 | 1.1933 | 0.607569 | 1.47292 |
| 2025-11 | 8,640 | 1.11416 | 1.02438 | 1.48416 |
| 2025-12 | 8,928 | 1.47333 | 1.31544 | 1.66698 |
| 2026-01 | 8,928 | 1.46146 | 1.35496 | 1.60207 |
| 2026-02 | 8,064 | 1.52501 | 1.20154 | 1.78517 |
| 2026-03 | 8,927 | 1.69962 | 1.55569 | 1.82402 |
| 2026-04 | 8,640 | 1.7557 | 1.238 | 2.02964 |
| 2026-05 | 8,928 | 1.46503 | 1.29544 | 1.67276 |
| 2026-06 | 8,640 | 1.33755 | 1.18815 | 1.50894 |
| 2026-07 | 8,928 | 1.37724 | 1.08788 | 1.51341 |
| 2026-08 | 8,928 | 1.13674 | 0.956768 | 1.38908 |
| 2026-09 | 8,640 | 1.21875 | 1.03317 | 1.46477 |
| 2026-10 | 8,928 | 1.17012 | 1.13151 | 1.2696 |
| 2026-11 | 5,472 | 1.17206 | 1.11304 | 1.3896 |

**count_long_short_ratio**

| Month | Rows | Median | 5th pct | 95th pct |
|---|---|---|---|---|
| 2025-07 | 4,757 | 1.07836 | 0.833676 | 2.03765 |
| 2025-08 | 8,925 | 1.79839 | 1.18724 | 2.09332 |
| 2025-09 | 8,640 | 2.60014 | 1.77497 | 3.36519 |
| 2025-10 | 8,928 | 3.47677 | 2.89686 | 4.3025 |
| 2025-11 | 8,640 | 2.4474 | 1.37423 | 3.73155 |
| 2025-12 | 8,928 | 1.59054 | 1.01745 | 2.87398 |
| 2026-01 | 8,928 | 3.15884 | 2.59036 | 3.8729 |
| 2026-02 | 8,064 | 2.76871 | 2.09078 | 3.34173 |
| 2026-03 | 8,928 | 3.03097 | 2.50215 | 3.44711 |
| 2026-04 | 8,640 | 2.84519 | 0.679359 | 3.53042 |
| 2026-05 | 8,928 | 0.755786 | 0.454598 | 1.38152 |
| 2026-06 | 8,640 | 1.61069 | 0.399295 | 2.06394 |
| 2026-07 | 8,928 | 1.52384 | 0.733421 | 2.7642 |
| 2026-08 | 8,928 | 3.75808 | 1.22106 | 4.82757 |
| 2026-09 | 8,640 | 2.72061 | 1.66276 | 5.01467 |
| 2026-10 | 8,928 | 5.03933 | 4.40913 | 5.57325 |
| 2026-11 | 5,472 | 5.16262 | 2.47676 | 5.83038 |

**sum_taker_long_short_vol_ratio**

| Month | Rows | Median | 5th pct | 95th pct |
|---|---|---|---|---|
| 2025-07 | 4,770 | 0.945917 | 0.387464 | 2.35643 |
| 2025-08 | 8,924 | 0.965723 | 0.213502 | 4.72709 |
| 2025-09 | 8,638 | 0.976593 | 0.165375 | 5.9995 |
| 2025-10 | 8,926 | 0.965466 | 0.206069 | 4.56212 |
| 2025-11 | 8,640 | 0.953877 | 0.260815 | 3.51196 |
| 2025-12 | 8,928 | 0.969001 | 0.254327 | 4.01203 |
| 2026-01 | 8,926 | 0.925194 | 0.153905 | 5.43239 |
| 2026-02 | 8,056 | 0.885405 | 0.14504 | 5.61489 |
| 2026-03 | 8,920 | 0.996273 | 0.176301 | 6.02294 |
| 2026-04 | 8,639 | 1.02713 | 0.23099 | 4.88493 |
| 2026-05 | 8,928 | 1.06091 | 0.309657 | 3.70525 |
| 2026-06 | 8,638 | 1.00608 | 0.245845 | 3.80079 |
| 2026-07 | 8,928 | 0.979122 | 0.350324 | 2.74459 |
| 2026-08 | 8,928 | 0.986345 | 0.241637 | 4.15504 |
| 2026-09 | 8,640 | 0.953693 | 0.264862 | 3.59691 |
| 2026-10 | 8,927 | 0.974186 | 0.224222 | 4.38912 |
| 2026-11 | 5,472 | 0.962605 | 0.279593 | 3.75973 |

### The 14 days before and after 2026-07-12

| Column | Median before | Median after | 5th-95th pct before | 5th-95th pct after |
|---|---|---|---|---|
| sum_open_interest | 3.75848e+08 | 1.00352e+09 | 2.64148e+08 to 1.84137e+09 | 8.75708e+08 to 1.19713e+09 |
| count_toptrader_long_short_ratio | 0.961758 | 1.75336 | 0.314133 to 2.52512 | 1.62252 to 1.98578 |
| sum_toptrader_long_short_ratio | 1.37745 | 1.46159 | 1.13061 to 1.56197 | 1.27963 to 1.56253 |
| count_long_short_ratio | 0.935686 | 1.52107 | 0.349515 to 2.26681 | 1.38393 to 1.70934 |
| sum_taker_long_short_vol_ratio | 1.00584 | 0.937596 | 0.507722 to 1.98859 | 0.319036 to 2.88636 |

### The 14 days before and after 2026-11-16

| Column | Median before | Median after | 5th-95th pct before | 5th-95th pct after |
|---|---|---|---|---|
| sum_open_interest | 2.1858e+09 | 2.91095e+09 | 2.04318e+09 to 3.37807e+09 | 2.79022e+09 to 3.62982e+09 |
| count_toptrader_long_short_ratio | 5.38692 | 2.91291 | 2.53754 to 6.24228 | 2.06847 to 3.30122 |
| sum_toptrader_long_short_ratio | 1.17371 | 1.1616 | 1.10916 to 1.41681 | 1.12633 to 1.23458 |
| count_long_short_ratio | 5.29954 | 2.93831 | 2.77618 to 5.8525 | 2.29246 to 3.41031 |
| sum_taker_long_short_vol_ratio | 0.968906 | 0.977558 | 0.273627 to 3.9247 | 0.321678 to 2.95691 |

### Label convention recheck against the recorder (decision 5)

Open interest at ts_ours_ms equals our recorder's value in 100.00% of 9,008 compared rows.

## Taker ratio against our 1m klines

Derived ratio = taker_buy_base_volume divided by (volume minus taker_buy_base_volume), summed over the five 1m candles of a 5-minute window (base units); windows with fewer than five candles are dropped.

Which alignment fits best (bulk taker ratio vs the derived ratio, whole history):

| Alignment | Rows | Within 0.1% | Within 1% | Median abs. diff | 95th pct abs. diff |
|---|---|---|---|---|---|
| window ending at ts_ours_ms (starts 5 min before it) | 141,448 | 64.11% | 96.54% | 0.00068 | 0.00912 |
| window starting at ts_ours_ms | 141,420 | 0.08% | 0.77% | 0.66356 | 5.00797 |

**Best fit: window ending at ts_ours_ms (starts 5 min before it).**

Per month, using the best alignment:

| Month | Rows | Within 0.1% | Within 1% | Median abs. diff | 95th pct abs. diff |
|---|---|---|---|---|---|
| 2025-07 | 4,770 | 47.15% | 91.01% | 0.00101 | 0.02479 |
| 2025-08 | 8,924 | 53.64% | 97.10% | 0.00082 | 0.01069 |
| 2025-09 | 8,638 | 53.72% | 97.45% | 0.00083 | 0.01073 |
| 2025-10 | 8,926 | 42.99% | 96.50% | 0.00102 | 0.01328 |
| 2025-11 | 8,640 | 61.54% | 96.34% | 0.00068 | 0.00923 |
| 2025-12 | 8,928 | 78.17% | 96.38% | 0.00042 | 0.00639 |
| 2026-01 | 8,926 | 73.59% | 97.30% | 0.00053 | 0.00730 |
| 2026-02 | 8,056 | 73.63% | 97.27% | 0.00051 | 0.00826 |
| 2026-03 | 8,920 | 80.90% | 97.16% | 0.00050 | 0.00790 |
| 2026-04 | 8,639 | 54.33% | 96.78% | 0.00093 | 0.01064 |
| 2026-05 | 8,928 | 68.72% | 96.31% | 0.00064 | 0.00815 |
| 2026-06 | 8,638 | 73.56% | 96.46% | 0.00052 | 0.00743 |
| 2026-07 | 8,928 | 55.25% | 96.31% | 0.00082 | 0.00861 |
| 2026-08 | 8,928 | 63.88% | 96.66% | 0.00070 | 0.00753 |
| 2026-09 | 8,640 | 66.05% | 96.10% | 0.00067 | 0.00843 |
| 2026-10 | 8,927 | 76.14% | 97.29% | 0.00057 | 0.00620 |
| 2026-11 | 5,092 | 55.64% | 96.03% | 0.00086 | 0.00872 |

By era:

| Era | Rows | Within 0.1% | Within 1% | Median abs. diff | 95th pct abs. diff |
|---|---|---|---|---|---|
| before 2026-07-12 | 104,101 | 63.60% | 96.52% | 0.00068 | 0.00960 |
| 2026-07-12 and later | 37,347 | 65.52% | 96.60% | 0.00068 | 0.00768 |

### Recorder window only: API ratio vs bulk ratio, each against the klines-derived ratio (9,007 common periods)

| Source | Rows | Within 0.1% | Within 1% | Median abs. diff | 95th pct abs. diff |
|---|---|---|---|---|---|
| Our recorder (API ratio, 4 decimals) | 8,627 | 92.49% | 96.59% | 0.00003 | 0.00427 |
| Bulk ratio | 8,627 | 60.61% | 96.56% | 0.00080 | 0.00826 |

**Which agrees better with the klines: the API ratio (our recorder) agrees better with the klines.**

## Anything odd

- 2 day(s) do not have 288 rows: 2025-07-15 (162), 2025-08-29 (285)
- 3 five-minute slot(s) are missing inside the date range.
- 25 rows with open interest at or below zero.
- Zero open interest sits on: 2025-07-21 (10), 2026-10-15 (15).
- 24 one-step open-interest jump(s) above 50%.
- count_toptrader_long_short_ratio: 41 not-a-number and 0 zero-or-negative value(s); range 0.279782 to 6.50826.
- sum_toptrader_long_short_ratio: 12 not-a-number and 0 zero-or-negative value(s); range 0.372497 to 2.24041.
- count_long_short_ratio: 13 not-a-number and 0 zero-or-negative value(s); range 0.301222 to 6.00257.
- sum_taker_long_short_vol_ratio: 27 not-a-number and 39 zero-or-negative value(s); range 0 to 9166.
- Around 2026-07-12 (14 days either side) sum_open_interest: median 3.75848e+08 to 1.00352e+09, 5th-95th percentile range 2.64148e+08-1.84137e+09 to 8.75708e+08-1.19713e+09.
- Around 2026-07-12 (14 days either side) count_toptrader_long_short_ratio: median 0.961758 to 1.75336, 5th-95th percentile range 0.314133-2.52512 to 1.62252-1.98578.
- Around 2026-07-12 (14 days either side) count_long_short_ratio: median 0.935686 to 1.52107, 5th-95th percentile range 0.349515-2.26681 to 1.38393-1.70934.
- Around 2026-11-16 (14 days either side) count_toptrader_long_short_ratio: median 5.38692 to 2.91291, 5th-95th percentile range 2.53754-6.24228 to 2.06847-3.30122.
- Around 2026-11-16 (14 days either side) count_long_short_ratio: median 5.29954 to 2.93831, 5th-95th percentile range 2.77618-5.8525 to 2.29246-3.41031.

## What could not be shown

- Whether bulk values before 2026-10-19 equal what the API showed at the time: our recorder starts then, so only the klines cross-check (taker ratio) reaches earlier.
- Why the bulk and API taker ratios differ slightly where they do; this report gives no cause.
- The exact LastModified of each file: it is rebuilt from the cached publish lag (accurate to the second), not read again from the archive.
- Nothing from this archive has been used as a feature or in any model.

## Decisions

**Decided by the user on 2026-11-21.**

1. The bulk taker ratio is not used as a feature. Taker flow will be derived from our own 1m klines (known at candle close), because over the recorder window the API ratio matches the klines-derived ratio in 92.49 percent of rows within 0.1 percent while the bulk ratio does so in 60.61 percent, and the bulk ratio differs from the klines in both eras.
2. Bad rows are flagged missing by the loader and never filled from neighbours: open interest at or below zero or not-a-number, any ratio at or below zero or not-a-number, and rows inside the 24 open-interest jumps above 50 percent. The raw normalized file stays unchanged.
3. Open interest and the ratio columns are regime-sensitive. Levels shift around 2026-07-12 (this cannot be checked against the recorder, which starts 2026-10-19) and around 2026-11-16 (also present in our recorder's API values, which match the bulk values on both sides, so it is not an archive artifact; the cause is unknown). Phase 2 must test stability per regime before any such feature is used.
4. Nothing from this file has been used as a feature.
