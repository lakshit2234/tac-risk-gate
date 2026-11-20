# Daily external data quality report (Gate 1)

- Directory: `data\raw` (read-only; each file read once; a partial last line is ignored; no network)
- Checked at: 2026-11-20 16:35:36 UTC
- Verdict: **PASS**
- Timing rule: every daily row from these three files is treated as **known at timestamp + 24 h**, never earlier. `fetched_at_ms` is only checked for look-ahead (it must be at or after the timestamp), it is not the known-at time.

## Hard failures

- none

## Warnings and flags

- defillama_tvl: 2 day(s) with TVL change above 50% vs the previous day
- coingecko price differs from the Binance 1m open by more than 2% on 73 of 363 days
- defillama_price price differs from the Binance 1m open by more than 2% on 3 of 491 days
- coingecko vs defillama price differ by more than 2% on 74 of 364 days
- derived supply vs recorder CMCCirculatingSupply: 1 of 31 overlapping day(s) differ by more than 0.1%

# Part A: each file on its own

## coingecko

- Rows: 364; first 2025-11-21 00:00:00 UTC, last 2026-11-19 00:00:00 UTC
- Duplicates: 0; out-of-order steps: 0; rows on the current UTC day: 0; look-ahead violations: 0
- Rows fetched before timestamp + 24 h (allowed; known-at is still timestamp + 24 h): 0
- Largest deviation of a step from 24 h: 0 s (tolerance 3,600 s)

Spacing distribution (hours between consecutive timestamps, rounded):

| Hours | Count |
|---|---|
| 24 | 363 |

Gaps above 25 h (0; 0 missing day(s); listed, not failures):

none

Main values (flagged, never clipped):

| Column | Min | Min date | Max | Max date | Median |
|---|---|---|---|---|---|
| price | 0.00089950414 | 2026-11-09 | 0.06242189 | 2026-07-01 | 0.0045036009 |
| market_cap | 4897907.8 | 2026-08-23 | 2.9138299e+08 | 2026-07-01 | 15196464 |
| total_volume | 151495.68 | 2026-08-23 | 66055363 | 2026-06-30 | 924715.99 |

## defillama_tvl

- Rows: 490; first 2025-07-18 00:00:00 UTC, last 2026-11-19 00:00:00 UTC
- Duplicates: 0; out-of-order steps: 0; rows on the current UTC day: 0; look-ahead violations: 0
- Rows fetched before timestamp + 24 h (allowed; known-at is still timestamp + 24 h): 0
- Largest deviation of a step from 24 h: 0 s (tolerance 3,600 s)

Spacing distribution (hours between consecutive timestamps, rounded):

| Hours | Count |
|---|---|
| 24 | 489 |

Gaps above 25 h (0; 0 missing day(s); listed, not failures):

none

Main values (flagged, never clipped):

| Column | Min | Min date | Max | Max date | Median |
|---|---|---|---|---|---|
| tvl | 217954 | 2026-11-19 | 2.1440767e+08 | 2025-08-23 | 2728313 |

Days where TVL changed by more than 50% vs the previous day (2):

| Date (UTC) | Previous TVL | TVL | Change |
|---|---|---|---|
| 2025-07-19 | 9,095,944 | 43,839,344 | +381.97% |
| 2025-08-06 | 42,856,215 | 118,124,206 | +175.63% |

## defillama_price

- Rows: 493; first 2025-07-16 00:00:01 UTC, last 2026-11-19 23:59:42 UTC
- Duplicates: 0; out-of-order steps: 0; rows on the current UTC day: 0; look-ahead violations: 0
- Rows fetched before timestamp + 24 h (allowed; known-at is still timestamp + 24 h): 1
- Largest deviation of a step from 24 h: 2,711 s (tolerance 3,600 s)

Spacing distribution (hours between consecutive timestamps, rounded):

| Hours | Count |
|---|---|
| 23 | 1 |
| 24 | 490 |
| 25 | 1 |

Gaps above 25 h (0; 0 missing day(s); listed, not failures):

none

Main values (flagged, never clipped):

| Column | Min | Min date | Max | Max date | Median |
|---|---|---|---|---|---|
| price | 0.0008989065 | 2026-11-09 | 0.062448969 | 2026-07-01 | 0.004426291 |
| confidence | 0.99 | 2025-07-16 | 0.99 | 2025-07-16 | 0.99 |

# Part B: cross-checks

### CoinGecko price vs Binance 1m open (nearest minute)

- Days compared: 363 (1 external days had no Binance minute)
- Absolute difference: mean 13.217%, median 0.350%, p99 87.30%, max 93.36%
- Days above 1%: 76 (20.9%)
- Days above 2%: 73 (20.1%)
- Days above 5%: 73 (20.1%)
- Share within 1%: 79.1%

Days above 2%, by month (days above 2% / days compared that month):

| Month | Above 2% | Compared |
|---|---|---|
| 2026-01 | 21 | 31 |
| 2026-02 | 26 | 28 |
| 2026-03 | 25 | 31 |
| 2026-08 | 1 | 31 |

The 20 largest differences (date = nearest UTC midnight; coingecko vs binance):

| Date | coingecko | binance | Difference |
|---|---|---|---|
| 2026-02-23 | 0.0078715462 | 0.004071 | +93.36% |
| 2026-02-25 | 0.0076953682 | 0.004014 | +91.71% |
| 2026-02-18 | 0.0077977297 | 0.004133 | +88.67% |
| 2026-03-07 | 0.0072271997 | 0.003844 | +88.01% |
| 2026-03-06 | 0.0072318242 | 0.00387 | +86.87% |
| 2026-02-17 | 0.0074861627 | 0.004117 | +81.84% |
| 2026-03-27 | 0.0071860484 | 0.003964 | +81.28% |
| 2026-02-21 | 0.0074489866 | 0.004116 | +80.98% |
| 2026-02-22 | 0.0074124768 | 0.0041 | +80.79% |
| 2026-03-26 | 0.0074382955 | 0.004127 | +80.23% |
| 2026-02-19 | 0.0072435068 | 0.004034 | +79.56% |
| 2026-02-27 | 0.0072731418 | 0.004111 | +76.92% |
| 2026-02-26 | 0.0073011721 | 0.004127 | +76.91% |
| 2026-03-09 | 0.0068909635 | 0.003905 | +76.47% |
| 2026-01-12 | 0.0075961719 | 0.004313 | +76.12% |
| 2026-02-08 | 0.0074579503 | 0.004277 | +74.37% |
| 2026-02-16 | 0.0072535542 | 0.004176 | +73.70% |
| 2026-02-09 | 0.0072012575 | 0.004155 | +73.32% |
| 2026-02-24 | 0.0070042146 | 0.004051 | +72.90% |
| 2026-03-19 | 0.0069030261 | 0.004009 | +72.19% |

### DeFiLlama price vs Binance 1m open (nearest minute)

- Days compared: 491 (2 external days had no Binance minute)
- Absolute difference: mean 0.427%, median 0.308%, p99 1.55%, max 37.84%
- Days above 1%: 12 (2.4%)
- Days above 2%: 3 (0.6%)
- Days above 5%: 1 (0.2%)
- Share within 1%: 97.6%

Days above 2%, by month (days above 2% / days compared that month):

| Month | Above 2% | Compared |
|---|---|---|
| 2025-08 | 1 | 31 |
| 2026-07 | 1 | 31 |
| 2026-08 | 1 | 31 |

The 20 largest differences (date = nearest UTC midnight; defillama vs binance):

| Date | defillama | binance | Difference |
|---|---|---|---|
| 2026-08-23 | 0.0010193536 | 0.00164 | -37.84% |
| 2025-08-18 | 0.01489046 | 0.01438 | +3.55% |
| 2026-07-10 | 0.004655542 | 0.00476 | -2.19% |
| 2026-11-15 | 0.0010284238 | 0.001045 | -1.59% |
| 2026-04-08 | 0.0036385017 | 0.003696 | -1.56% |
| 2026-09-04 | 0.0022958191 | 0.002332 | -1.55% |
| 2025-10-11 | 0.0042069154 | 0.00427 | -1.48% |
| 2025-08-14 | 0.0141444 | 0.01394 | +1.47% |
| 2026-06-26 | 0.022335226 | 0.022653 | -1.40% |
| 2026-04-21 | 0.00552705 | 0.005605 | -1.39% |
| 2025-11-14 | 0.0052707042 | 0.005336 | -1.22% |
| 2025-11-08 | 0.0056719087 | 0.005734 | -1.08% |
| 2026-10-23 | 0.0011668524 | 0.001178 | -0.95% |
| 2025-11-07 | 0.0048942759 | 0.004941 | -0.95% |
| 2025-12-09 | 0.0045195167 | 0.004562 | -0.93% |
| 2026-08-06 | 0.0032920775 | 0.003323 | -0.93% |
| 2026-04-30 | 0.015407259 | 0.015269 | +0.91% |
| 2025-10-09 | 0.006827802 | 0.00689 | -0.90% |
| 2026-03-01 | 0.0040838039 | 0.004121 | -0.90% |
| 2026-02-04 | 0.0043016863 | 0.00434 | -0.88% |

### CoinGecko price vs DeFiLlama price (same nearest-midnight day)

- Days compared: 364
- Absolute difference: mean 13.159%, median 0.185%, p99 87.76%, max 94.37%
- Days above 1%: 83 (22.8%)
- Days above 2%: 74 (20.3%)
- Days above 5%: 72 (19.8%)
- Share within 1%: 77.2%

Days above 2%, by month (days above 2% / days compared that month):

| Month | Above 2% | Compared |
|---|---|---|
| 2026-01 | 21 | 31 |
| 2026-02 | 26 | 28 |
| 2026-03 | 25 | 31 |
| 2026-07 | 1 | 31 |
| 2026-09 | 1 | 30 |

The 20 largest differences (date = nearest UTC midnight; coingecko vs defillama):

| Date | coingecko | defillama | Difference |
|---|---|---|---|
| 2026-02-23 | 0.0078715462 | 0.0040497699 | +94.37% |
| 2026-02-25 | 0.0076953682 | 0.0039916444 | +92.79% |
| 2026-02-18 | 0.0077977297 | 0.0041014237 | +90.12% |
| 2026-03-07 | 0.0072271997 | 0.0038329293 | +88.56% |
| 2026-03-06 | 0.0072318242 | 0.0038612873 | +87.29% |
| 2026-02-17 | 0.0074861627 | 0.0041054948 | +82.34% |
| 2026-02-22 | 0.0074124768 | 0.0040697805 | +82.13% |
| 2026-03-27 | 0.0071860484 | 0.0039483167 | +82.00% |
| 2026-02-21 | 0.0074489866 | 0.0041011082 | +81.63% |
| 2026-02-19 | 0.0072435068 | 0.0040014383 | +81.02% |
| 2026-03-26 | 0.0074382955 | 0.0041099712 | +80.98% |
| 2026-02-26 | 0.0073011721 | 0.004104876 | +77.87% |
| 2026-02-27 | 0.0072731418 | 0.0041029864 | +77.26% |
| 2026-01-12 | 0.0075961719 | 0.0042987206 | +76.71% |
| 2026-03-09 | 0.0068909635 | 0.0039041147 | +76.51% |
| 2026-02-08 | 0.0074579503 | 0.0042656851 | +74.84% |
| 2026-02-16 | 0.0072535542 | 0.0041561062 | +74.53% |
| 2026-02-09 | 0.0072012575 | 0.0041302682 | +74.35% |
| 2026-02-24 | 0.0070042146 | 0.0040382343 | +73.45% |
| 2026-03-19 | 0.0069030261 | 0.0039969846 | +72.71% |

### Derived circulating supply from CoinGecko (market_cap / price)

- Days: 364
- First: 2,608,522,465 (2025-11-21); last: 6,485,265,581 (2026-11-19)
- Min: 2,608,522,465 (2025-11-21); max: 6,485,265,581 (2026-11-19)

Supply step candidates (change above 1% vs the previous stored day): 19

| Date (UTC) | Change (tokens) | Change | Cause |
|---|---|---|---|
| 2025-11-29 | +37,856,080 | +1.45% | cause unverified |
| 2026-03-30 | +151,449,373 | +5.48% | cause unverified |
| 2026-05-04 | +96,359,518 | +3.24% | cause unverified |
| 2026-05-06 | +900,293,024 | +29.23% | cause unverified |
| 2026-05-08 | +300,301,785 | +7.54% | cause unverified |
| 2026-05-10 | +300,396,935 | +7.02% | cause unverified |
| 2026-07-07 | +389,374,717 | +8.31% | cause unverified |
| 2026-07-08 | -392,696,962 | -7.74% | cause unverified |
| 2026-07-16 | +143,996,725 | +3.07% | cause unverified |
| 2026-07-29 | +311,359,754 | +6.44% | cause unverified |
| 2026-07-30 | -310,977,155 | -6.04% | cause unverified |
| 2026-08-03 | -187,249,000 | -3.87% | cause unverified |
| 2026-08-16 | +144,076,535 | +3.09% | cause unverified |
| 2026-09-03 | +118,988,171 | +2.48% | cause unverified |
| 2026-09-04 | +389,788,578 | +7.92% | cause unverified |
| 2026-09-08 | +465,582,450 | +8.74% | cause unverified |
| 2026-09-16 | +144,076,017 | +2.48% | cause unverified |
| 2026-10-16 | +144,073,846 | +2.40% | cause unverified |
| 2026-11-19 | +328,953,341 | +5.34% | cause unverified |

### Derived supply vs recorder open-interest CMCCirculatingSupply (00:00 UTC row of each day)

- Overlapping days: 31 (2026-10-20 to 2026-11-19)
- Within 0.1%: 30 of 31

Mismatches (1):

| Date (UTC) | Derived (CoinGecko) | CMCCirculatingSupply (Binance) | Binance vs derived |
|---|---|---|---|
| 2026-11-19 | 6,485,265,581 | 6,156,312,240 | -5.07% |
