# Binance bulk archive (data.binance.vision): availability check for TACUSDT USD-M futures

Checked on 2026-11-20 (UTC). This is a listing and sample check, not a history download. The archive's file listing is a public S3 listing; a file that is not listed is treated as not existing. Samples are in `data/raw/bulk_sample/` (git-ignored).

## 1. What exists

| Dataset | Daily files | First to last (daily) | Monthly files | First to last (monthly) | Checksum files (daily) |
|---|---|---|---|---|---|
| klines 1m (daily and monthly) | 493 | 2025-07-15 to 2026-11-19 | 16 | 2025-07 to 2026-10 | 493 |
| metrics (daily only) | 493 | 2025-07-15 to 2026-11-19 | 0 | - to - | 493 |
| bookDepth (daily only) | 491 | 2025-07-15 to 2026-11-19 | 0 | - to - | 491 |
| markPriceKlines 1m (daily and monthly) | 493 | 2025-07-15 to 2026-11-19 | 16 | 2025-07 to 2026-10 | 493 |
| indexPriceKlines 1m (daily and monthly) | 493 | 2025-07-15 to 2026-11-19 | 16 | 2025-07 to 2026-10 | 493 |
| premiumIndexKlines 1m (daily and monthly) | 493 | 2025-07-15 to 2026-11-19 | 16 | 2025-07 to 2026-10 | 493 |
| fundingRate (monthly only) | 0 | - to - | 16 | 2025-07 to 2026-10 | 0 |
| aggTrades (daily and monthly) | 493 | 2025-07-15 to 2026-11-19 | 16 | 2025-07 to 2026-10 | 493 |
| trades (daily and monthly) | 493 | 2025-07-15 to 2026-11-19 | 16 | 2025-07 to 2026-10 | 493 |
| bookTicker (none) | 0 | - to - | 0 | - to - | 0 |
| liquidationSnapshot (none) | 0 | - to - | 0 | - to - | 0 |

## 2. Sample files and formats

### klines

- File: `data/futures/um/daily/klines/TACUSDT/1m/TACUSDT-1m-2026-11-10.zip` (daily, 2026-11-10), 47,737 bytes
- Checksum: verified (sha256 e5c21c7b69727639...)
- Header row: yes; data rows: 1,440; time column open_time: epoch milliseconds (13 digits)
- Rows in time order: yes; distinct time values: 1,440
- Columns: open_time, open, high, low, close, volume, close_time, quote_volume, count, taker_buy_volume, taker_buy_quote_volume, ignore

```
open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore
1794268800000,0.0009370,0.0009370,0.0009360,0.0009360,283372,1794268859999,265.4801900,15,64401,60.3437370,0
1794268860000,0.0009370,0.0009380,0.0009370,0.0009380,814428,1794268919999,763.5361990,35,481561,451.4886400,0
1794268920000,0.0009380,0.0009380,0.0009370,0.0009380,710180,1794268979999,665.9134060,27,226940,212.8697200,0
```

### metrics

- File: `data/futures/um/daily/metrics/TACUSDT/TACUSDT-metrics-2026-11-10.zip` (daily, 2026-11-10), 11,189 bytes
- Checksum: verified (sha256 ee43fb32c55adc61...)
- Header row: yes; data rows: 288; time column create_time: datetime text, UTC assumed (not stated in the file)
- Rows in time order: **NO, the rows are not sorted by time (sort before use)**; distinct time values: 288
- Columns: create_time, symbol, sum_open_interest, sum_open_interest_value, count_toptrader_long_short_ratio, sum_toptrader_long_short_ratio, count_long_short_ratio, sum_taker_long_short_vol_ratio

```
create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio
2026-11-10 02:40:00,TACUSDT,2240532026.0000000000000000,2053492.4124695200000000,5.17708333,1.18227500,5.16496018,0.73839800
2026-11-10 02:45:00,TACUSDT,2240027329.0000000000000000,2057644.3038728200000000,5.15224913,1.18230800,5.14172336,2.86126500
2026-11-10 07:00:00,TACUSDT,2231647877.0000000000000000,2126760.4267810000000000,5.13769363,1.15310200,5.15575621,0.43379600
```

### bookDepth

- File: `data/futures/um/daily/bookDepth/TACUSDT/TACUSDT-bookDepth-2026-11-10.zip` (daily, 2026-11-10), 541,269 bytes
- Checksum: verified (sha256 aaa1e2d88f5d4d6a...)
- Header row: yes; data rows: 34,560; time column timestamp: datetime text, UTC assumed (not stated in the file)
- Rows in time order: yes; distinct time values: 2,880
- Columns: timestamp, percentage, depth, notional

```
timestamp,percentage,depth,notional
2026-11-10 00:00:01,-5.00,107642336.00000000,98491.64286400
2026-11-10 00:00:01,-4.00,94073949.00000000,86338.63657900
2026-11-10 00:00:01,-3.00,75967283.00000000,69956.42730100
```

### markPriceKlines

- File: `data/futures/um/daily/markPriceKlines/TACUSDT/1m/TACUSDT-1m-2026-11-10.zip` (daily, 2026-11-10), 20,009 bytes
- Checksum: verified (sha256 c0ef139b3e8f28bc...)
- Header row: yes; data rows: 1,440; time column open_time: epoch milliseconds (13 digits)
- Rows in time order: yes; distinct time values: 1,440
- Columns: open_time, open, high, low, close, volume, close_time, quote_volume, count, taker_buy_volume, taker_buy_quote_volume, ignore

```
open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore
1794268800000,0.00093700,0.00093700,0.00093587,0.00093600,0,1794268859999,0,60,0,0,0
1794268860000,0.00093600,0.00093791,0.00093600,0.00093791,0,1794268919999,0,60,0,0,0
1794268920000,0.00093780,0.00093800,0.00093697,0.00093774,0,1794268979999,0,60,0,0,0
```

### indexPriceKlines

- File: `data/futures/um/daily/indexPriceKlines/TACUSDT/1m/TACUSDT-1m-2026-11-10.zip` (daily, 2026-11-10), 21,464 bytes
- Checksum: verified (sha256 d0714771b8e583e1...)
- Header row: yes; data rows: 1,440; time column open_time: epoch milliseconds (13 digits)
- Rows in time order: yes; distinct time values: 1,440
- Columns: open_time, open, high, low, close, volume, close_time, quote_volume, count, taker_buy_volume, taker_buy_quote_volume, ignore

```
open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore
1794268800000,0.00093425,0.00093425,0.00093349,0.00093349,0,1794268859999,0,60,0,0,0
1794268860000,0.00093336,0.00093444,0.00093336,0.00093444,0,1794268919999,0,60,0,0,0
1794268920000,0.00093444,0.00093569,0.00093444,0.00093519,0,1794268979999,0,60,0,0,0
```

### premiumIndexKlines

- File: `data/futures/um/daily/premiumIndexKlines/TACUSDT/1m/TACUSDT-1m-2026-11-10.zip` (daily, 2026-11-10), 22,560 bytes
- Checksum: verified (sha256 471086a61a61e5c0...)
- Header row: yes; data rows: 1,440; time column open_time: epoch milliseconds (13 digits)
- Rows in time order: yes; distinct time values: 1,440
- Columns: open_time, open, high, low, close, volume, close_time, quote_volume, count, taker_buy_volume, taker_buy_quote_volume, ignore

```
open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore
1794268800000,0.00141380,0.00172027,0.00079476,0.00172027,0,1794268859999,0,12,0,0,0
1794268860000,0.00174850,0.00234352,0.00132980,0.00132980,0,1794268919999,0,12,0,0,0
1794268920000,0.00120612,0.00136642,0.00000000,0.00081676,0,1794268979999,0,12,0,0,0
```

### fundingRate

- File: `data/futures/um/monthly/fundingRate/TACUSDT/TACUSDT-fundingRate-2026-10.zip` (monthly, 2026-10), 1,456 bytes
- Checksum: verified (sha256 38fde7c2bb51d3ee...)
- Header row: yes; data rows: 186; time column calc_time: epoch milliseconds (13 digits)
- Rows in time order: yes; distinct time values: 186
- Columns: calc_time, funding_interval_hours, last_funding_rate

```
calc_time,funding_interval_hours,last_funding_rate
1790812800001,4,0.00037011
1790827200002,4,0.00033889
1790841600005,4,0.00026154
```

### aggTrades

- File: `data/futures/um/daily/aggTrades/TACUSDT/TACUSDT-aggTrades-2026-11-10.zip` (daily, 2026-11-10), 279,821 bytes
- Checksum: verified (sha256 52b30572c001887b...)
- Header row: yes; data rows: 17,332; time column transact_time: epoch milliseconds (13 digits)
- Rows in time order: yes; distinct time values: 16,560
- Columns: agg_trade_id, price, quantity, first_trade_id, last_trade_id, transact_time, is_buyer_maker

```
agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker
62692077,9.37E-4,179597.0,119234780,119234785,1794268800097,true
62692078,9.36E-4,10730.0,119234786,119234786,1794268800132,true
62692079,9.37E-4,6404.0,119234787,119234787,1794268800309,false
```

### trades

- File: `data/futures/um/daily/trades/TACUSDT/TACUSDT-trades-2026-11-10.zip` (daily, 2026-11-10), 519,710 bytes
- Checksum: verified (sha256 8bf15b5db683e8a6...)
- Header row: yes; data rows: 40,242; time column time: epoch milliseconds (13 digits)
- Rows in time order: yes; distinct time values: 19,602
- Columns: id, price, qty, quote_qty, time, is_buyer_maker

```
id,price,qty,quote_qty,time,is_buyer_maker
119234780,9.37E-4,6010.0,5.63137,1794268800097,true
119234781,9.37E-4,35813.0,33.556781,1794268800097,true
119234782,9.37E-4,27985.0,26.221945,1794268800097,true
```

Units are not stated inside the files. Where a unit matters it is taken from the comparison with our own files below, or marked unknown.

## 3. Publish lag (hours after the end of the UTC day or month, from the object's LastModified time in the listing)

| Dataset | Area | Latest file | Its LastModified (UTC) | Lag of latest | Median | 95th pct | Max | Max (latest 90) | Files |
|---|---|---|---|---|---|---|---|---|---|
| klines | daily | 2026-11-19 | 2026-11-20 08:30 | 8.5 h | 8.9 h | 10.9 h | 317.7 h | 317.7 h | 493 |
| klines | monthly | 2026-10 | 2026-11-11 10:51 | 250.9 h | 33.9 h | 250.9 h | 250.9 h | 250.9 h | 16 |
| metrics | daily | 2026-11-19 | 2026-11-20 06:55 | 6.9 h | 3663.8 h | 8670.1 h | 9215.9 h | 10.2 h | 493 |
| bookDepth | daily | 2026-11-19 | 2026-11-20 07:37 | 7.6 h | 7.5 h | 8.6 h | 11.6 h | 11.6 h | 491 |
| markPriceKlines | daily | 2026-11-19 | 2026-11-20 08:13 | 8.2 h | 9.5 h | 11.9 h | 570.5 h | 279.0 h | 493 |
| markPriceKlines | monthly | 2026-10 | 2026-11-09 19:00 | 211.0 h | 33.9 h | 211.0 h | 211.0 h | 211.0 h | 16 |
| indexPriceKlines | daily | 2026-11-19 | 2026-11-20 07:47 | 7.8 h | 9.3 h | 11.9 h | 570.0 h | 278.7 h | 493 |
| indexPriceKlines | monthly | 2026-10 | 2026-11-09 18:52 | 210.9 h | 33.9 h | 210.9 h | 210.9 h | 210.9 h | 16 |
| premiumIndexKlines | daily | 2026-11-19 | 2026-11-20 07:51 | 7.9 h | 9.3 h | 11.5 h | 570.3 h | 278.7 h | 493 |
| premiumIndexKlines | monthly | 2026-10 | 2026-11-09 18:48 | 210.8 h | 33.7 h | 210.8 h | 210.8 h | 210.8 h | 16 |
| fundingRate | monthly | 2026-10 | 2026-11-01 08:26 | 8.4 h | 8.2 h | 9.7 h | 9.7 h | 9.7 h | 16 |
| aggTrades | daily | 2026-11-19 | 2026-11-20 07:08 | 7.1 h | 7.1 h | 8.3 h | 319.7 h | 319.7 h | 493 |
| aggTrades | monthly | 2026-10 | 2026-11-11 15:42 | 255.7 h | 8.9 h | 255.7 h | 255.7 h | 255.7 h | 16 |
| trades | daily | 2026-11-19 | 2026-11-20 07:01 | 7.0 h | 7.3 h | 112.2 h | 9753.9 h | 424.8 h | 493 |
| trades | monthly | 2026-10 | 2026-11-18 03:34 | 411.6 h | 10.6 h | 411.6 h | 411.6 h | 411.6 h | 16 |

LastModified is when the object was last written. A file that was rewritten later would look slower than it first appeared, which only makes the lag estimate more conservative.

## 4. Overlap with our own files on 2026-11-10

### Bulk 1m klines vs our Binance 1m file

- Rows: bulk 1,440, ours 1,440, in both 1,440; only in bulk 0, only in ours 0
- Rows with any differing value: **0**

### Bulk metrics vs our recorder history files

For each numeric bulk column, the recorder column whose values match best, at which time shift between the bulk row time and our timestamp (a shift of +5 means our timestamp is the bulk row time plus 5 minutes), and the share of rows that match (close = within 0.1%, exact = equal; our ratios are rounded to 4 decimals, so exact is not expected for them). A share well below 100% means the mapping is unclear.

| Bulk column | Best match in our files | Shift (min) | Rows compared | Close | Exact | Largest relative difference |
|---|---|---|---|---|---|---|
| sum_open_interest | open_interest.sumOpenInterest | 5 | 288 | 100.0% | 100.0% | 0.00% |
| sum_open_interest_value | open_interest.sumOpenInterestValue | 5 | 288 | 100.0% | 100.0% | 0.00% |
| count_toptrader_long_short_ratio | global_long_short.longShortRatio | 5 | 288 | 9.0% | 0.0% | 2.40% |
| sum_toptrader_long_short_ratio | top_position_long_short.longShortRatio | 5 | 288 | 100.0% | 0.0% | 0.00% |
| count_long_short_ratio | global_long_short.longShortRatio | 5 | 288 | 100.0% | 0.0% | 0.04% |
| sum_taker_long_short_vol_ratio | taker_buy_sell.buySellRatio | 0 | 288 | 75.0% | 0.0% | 0.34% |

Mapping unclear or partial for: count_toptrader_long_short_ratio, sum_taker_long_short_vol_ratio.

- `count_toptrader_long_short_ratio` matched `global_long_short.longShortRatio` in only 9% of rows (largest relative difference 2.40%), so it is a near match at best; the cause of the differences is not known.
- `count_toptrader_long_short_ratio` has no clear counterpart in our recorder files. By its name it may be a top-trader account ratio, which our recorder does not fetch; that is a reading of the name, the data do not show it.
- `sum_taker_long_short_vol_ratio` matched `taker_buy_sell.buySellRatio` in only 75% of rows (largest relative difference 0.34%), so it is a near match at best; the cause of the differences is not known.

## 5. Proposed known-time rules

Two facts from section 3 shape these rules. First, recent day files appear a few hours after their UTC day ends. Second, many OLD files appear to have been written long after their day (for metrics the median lag over all files is far larger than the latest ones), so for historical rows the file's LastModified time says when the archive was filled, not when the data first existed. The overlap above shows the same values were already public through the API on that day (open interest matched exactly on the sample day). Because of that, and to stay conservative, the proposed rule treats every bulk row like our daily external rows: known no earlier than the end of its UTC day plus 24 h. That rule gives up intraday timing for bulk history, which is the price of not trusting the file time. The equality with the API was checked on one sample day only.

- **klines (daily)**: a row counts as known at the end of its UTC day plus 24 h, never at the row's own time. Why: the latest file appeared 8.5 h after the UTC day ended, but among the latest 90 one took 317.7 h, so a live system must also check the file's own LastModified time and use whichever is later.
- **klines (monthly)**: a row counts as known at the end of its UTC month plus 11 days, never at the row's own time. Why: monthly files are a later consolidated copy; the 16 listed ones appeared between 33.0 h and 250.9 h after the month ended, so the largest observed lag, rounded up, is used. Where daily files exist for the same data they are earlier and should be used instead.
- **metrics (daily)**: a row counts as known at the end of its UTC day plus 24 h, never at the row's own time. Why: the latest file appeared 6.9 h after the UTC day ended and none of the latest 90 took longer than 10.2 h, so 24 h leaves more than a 2x margin.
- **bookDepth (daily)**: a row counts as known at the end of its UTC day plus 24 h, never at the row's own time. Why: the latest file appeared 7.6 h after the UTC day ended and none of the latest 90 took longer than 11.6 h, so 24 h leaves more than a 2x margin.
- **markPriceKlines (daily)**: a row counts as known at the end of its UTC day plus 24 h, never at the row's own time. Why: the latest file appeared 8.2 h after the UTC day ended, but among the latest 90 one took 279.0 h, so a live system must also check the file's own LastModified time and use whichever is later.
- **markPriceKlines (monthly)**: a row counts as known at the end of its UTC month plus 9 days, never at the row's own time. Why: monthly files are a later consolidated copy; the 16 listed ones appeared between 33.0 h and 211.0 h after the month ended, so the largest observed lag, rounded up, is used. Where daily files exist for the same data they are earlier and should be used instead.
- **indexPriceKlines (daily)**: a row counts as known at the end of its UTC day plus 24 h, never at the row's own time. Why: the latest file appeared 7.8 h after the UTC day ended, but among the latest 90 one took 278.7 h, so a live system must also check the file's own LastModified time and use whichever is later.
- **indexPriceKlines (monthly)**: a row counts as known at the end of its UTC month plus 9 days, never at the row's own time. Why: monthly files are a later consolidated copy; the 16 listed ones appeared between 33.0 h and 210.9 h after the month ended, so the largest observed lag, rounded up, is used. Where daily files exist for the same data they are earlier and should be used instead.
- **premiumIndexKlines (daily)**: a row counts as known at the end of its UTC day plus 24 h, never at the row's own time. Why: the latest file appeared 7.9 h after the UTC day ended, but among the latest 90 one took 278.7 h, so a live system must also check the file's own LastModified time and use whichever is later.
- **premiumIndexKlines (monthly)**: a row counts as known at the end of its UTC month plus 9 days, never at the row's own time. Why: monthly files are a later consolidated copy; the 16 listed ones appeared between 33.0 h and 210.8 h after the month ended, so the largest observed lag, rounded up, is used. Where daily files exist for the same data they are earlier and should be used instead.
- **fundingRate (monthly)**: a row counts as known at the end of its UTC month plus 1 days, never at the row's own time. Why: monthly files are a later consolidated copy; the 16 listed ones appeared between 7.7 h and 9.7 h after the month ended, so the largest observed lag, rounded up, is used. Where daily files exist for the same data they are earlier and should be used instead.
- **aggTrades (daily)**: a row counts as known at the end of its UTC day plus 24 h, never at the row's own time. Why: the latest file appeared 7.1 h after the UTC day ended, but among the latest 90 one took 319.7 h, so a live system must also check the file's own LastModified time and use whichever is later.
- **aggTrades (monthly)**: a row counts as known at the end of its UTC month plus 11 days, never at the row's own time. Why: monthly files are a later consolidated copy; the 16 listed ones appeared between 8.3 h and 255.7 h after the month ended, so the largest observed lag, rounded up, is used. Where daily files exist for the same data they are earlier and should be used instead.
- **trades (daily)**: a row counts as known at the end of its UTC day plus 24 h, never at the row's own time. Why: the latest file appeared 7.0 h after the UTC day ended, but among the latest 90 one took 424.8 h, so a live system must also check the file's own LastModified time and use whichever is later.
- **trades (monthly)**: a row counts as known at the end of its UTC month plus 18 days, never at the row's own time. Why: monthly files are a later consolidated copy; the 16 listed ones appeared between 9.4 h and 411.6 h after the month ended, so the largest observed lag, rounded up, is used. Where daily files exist for the same data they are earlier and should be used instead.

## 6. What this changes for Gate 1

- `metrics`: the listing shows daily files for TACUSDT from 2025-07-15 to 2026-11-19 (493 files, a span of 493 days). Our recorder history has 32 days. On the sample day the open interest, the top-position ratio and the global ratio matched our recorder columns (see section 4), so open interest and the two long/short ratios could have about 493 days of history instead of 32. The taker ratio matched only approximately, and one bulk column has no counterpart in our files. Only one day was compared; no history was downloaded.
- `bookDepth`: 491 daily files from 2025-07-15 to 2026-11-19, so the 'no depth history' gap in Gate 1 could shrink to banded depth only (not the full book, not trade-size slippage). The sample day has 2,880 snapshots (median spacing 30 s) at the percentage levels -5, -4, -3, -2, -1, -0.2, 0.2, 1, 2, 3, 4, 5; each row gives a depth and a notional value. Whether `depth` is in tokens and `notional` in USD is not stated in the file.
- Daily 1m klines are listed from 2025-07-15 to 2026-11-19 (493 files). On the sample day they matched our Binance 1m file (section 4), so they add no new information for klines, only a second source.
- `markPriceKlines`: 493 daily files (2025-07-15 to 2026-11-19), 16 monthly files (2025-07 to 2026-10). New data for us (not compared with anything of ours).
- `indexPriceKlines`: 493 daily files (2025-07-15 to 2026-11-19), 16 monthly files (2025-07 to 2026-10). New data for us (not compared with anything of ours).
- `premiumIndexKlines`: 493 daily files (2025-07-15 to 2026-11-19), 16 monthly files (2025-07 to 2026-10). New data for us (not compared with anything of ours).
- `aggTrades`: 493 daily files (2025-07-15 to 2026-11-19), 16 monthly files (2025-07 to 2026-10). New data for us (not compared with anything of ours).
- `trades`: 493 daily files (2025-07-15 to 2026-11-19), 16 monthly files (2025-07 to 2026-10). New data for us (not compared with anything of ours).
- `fundingRate`: no daily files, 16 monthly files (2025-07 to 2026-10). New data for us (not compared with anything of ours) except funding, which our funding file already covers.
- `bookTicker`: no files are listed for TACUSDT (daily or monthly), so it does not exist in this archive. 
- `liquidationSnapshot`: no files are listed for TACUSDT (daily or monthly), so it does not exist in this archive. The 'no liquidation data' gap stays.

## 7. Open items

1. The equivalence with our recorder was checked on one day only (2026-11-10). A check over the full recorder window (2026-10-19 to the latest day) is still needed for open interest, the long/short ratios and the taker ratio, together with an explanation of the taker differences (75% of rows within 0.1%, largest difference 0.34%).
2. Many old metrics files were written months after their day. The date where the file lag changes from months to hours (the backfilled era versus the live era) must be found, and values before that date may have been produced differently.
3. The proposed known-time rule (end of the UTC day plus 24 hours, or the file's LastModified time if later) is provisional. A tighter rule (label time plus 10 minutes, as for the recorder) may be justified only if item 1 shows exact equality.
4. Units are not stated in the files. `count_toptrader_long_short_ratio` has no counterpart in our files. The bookDepth bands differ from our snapshot bands.

No feature was built from any of this data.
