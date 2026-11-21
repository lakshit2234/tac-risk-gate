# Phase 2 Gate 2 baseline rules (descriptive)

Generated 2026-11-21 (UTC) by `python -m tacgate.phase2.rules_baseline`. Development period only (decision times up to 2026-07-31 00:00 UTC); the holdout was not read or evaluated (`docs/holdout_used.txt` does not exist). Trials so far: 7.

**What this is.** A description of what four plain percentile rules would have done on the development data, next to three anchors. **No rule is chosen. No result is a claim that a gate works.** With 5 long and 20 short episodes in the primary view (24 h, 30 percent) the intervals are wide and most differences between rules are inside them. R4 reacts during the move, so its lead time is expected to be near zero; a short lead time there is the rule working as built, not a weakness of the data.

## 1. The four rules and their fixed values

Fixed in advance by the user on 2026-11-22 (proposed by Claude, approved by the user). Each value is a named constant in `src/tacgate/phase2/rules_baseline.py`; nothing else was tried.

- Cut-offs are percentiles of the feature over the training rows only (rows whose label is known at or before the start of the test month, enforced by the harness), computed in `fit` and fixed for the whole test month.
- High tail: state 2 (stay out) at or above the 95th percentile, state 1 (caution) at or above the 90th, else 0. Low tail: state 2 at or below the 5th percentile, state 1 at or below the 10th, else 0.
- A NaN feature gives state 0 (clear); the decision times where that happened are counted in section 4.

| Rule | Long side | Short side |
|---|---|---|
| R1 realized_volatility | `rv_1h`, high is risky | `rv_1h`, high is risky (same state as long) |
| R2 funding_extreme | latest funding rate known at t, high is risky | latest funding rate known at t, low is risky |
| R3 exchange_gap | `bybit_gap_abs_max_1h`, high is risky | `bybit_gap_abs_max_1h`, high is risky (same state as long) |
| R4 price_cascade | `drawdown_1h`, low is risky | `runup_1h`, high is risky |

Funding is the latest rate whose fundingTime is at or before t (`loaders.load_funding`: known at fundingTime), rows with a missing rate or mark price skipped; before the first funding row it is NaN.

## 2. What was run

Four trials were logged first (`T0004`, `T0005`, `T0006`, `T0007`, family `stage_a_baseline`, horizon 24 h, threshold 0.3), then each rule was evaluated with the walk-forward harness over the test months 2025-09 to 2026-07 (95,905 decision times) with the harness's fixed metrics, random gate and splits. The three anchors are the harness trials `T0001`, `T0002`, `T0003`. Episodes in the test period: 24h / 30 percent: 5 long, 20 short; 4h / 20 percent: 15 long, 22 short; 1h / 20 percent: 12 long, 19 short.

## 3. Comparison: primary view 24h_30pct, lead 60 min, alarm = stay out, whole test period

Capture rate = captured / episodes. The random gate is the gate's own alarm series shifted circularly (1,000 shifts): what the same amount of stay-out time gives by chance. The verdict column only says where the rate sits against that range, or TOO FEW; it is not a significance claim.

### Long side

| Gate | Episodes | Capture rate (95% interval) | Random gate: median [2.5%, 97.5%] | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | NaN decision times (state 0) | Verdict |
|---|---|---|---|---|---|---|---|---|
| R1 realized_volatility | 5 | 5/5 = 100% [48%, 100%] | 0% [0%, 40%] | 6.2% | 4.3% | 5: 14 / 258 / 650 min | 0 | above the random 97.5% value |
| R2 funding_extreme | 5 | 0/5 = 0% [0%, 52%] | 0% [0%, 40%] | 8.8% | 22.5% | - | 0 | inside the random 2.5%-97.5% range |
| R3 exchange_gap | 5 | 3/5 = 60% [15%, 95%] | 0% [0%, 60%] | 9.3% | 7.0% | 3: 75 / 133 / 429 min | 0 | inside the random 2.5%-97.5% range |
| R4 price_cascade | 5 | 5/5 = 100% [48%, 100%] | 0% [0%, 60%] | 5.5% | 4.3% | 5: 19 / 68 / 158 min | 0 | above the random 97.5% value |
| always stay out | 5 | 5/5 = 100% [48%, 100%] | 100% [100%, 100%] | 100.0% | 0.0% | 5: 57434 / 437348 / 449350 min | - | inside the random 2.5%-97.5% range |
| never | 5 | 0/5 = 0% [0%, 52%] | 0% [0%, 0%] | 0.0% | 0.0% | - | - | inside the random 2.5%-97.5% range |
| random | 5 | 4/5 = 80% [28%, 99%] | 80% [20%, 100%] | 10.0% | 10.0% | 4: 19 / 42 / 43 min | - | inside the random 2.5%-97.5% range |

### Short side

| Gate | Episodes | Capture rate (95% interval) | Random gate: median [2.5%, 97.5%] | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | NaN decision times (state 0) | Verdict |
|---|---|---|---|---|---|---|---|---|
| R1 realized_volatility | 20 | 17/20 = 85% [62%, 97%] | 5% [0%, 25%] | 6.2% | 4.3% | 17: 5 / 72 / 317 min | 0 | above the random 97.5% value |
| R2 funding_extreme | 20 | 7/20 = 35% [15%, 59%] | 45% [25%, 70%] | 44.9% | 10.6% | 7: 219 / 1278 / 9172 min | 0 | inside the random 2.5%-97.5% range |
| R3 exchange_gap | 20 | 7/20 = 35% [15%, 59%] | 10% [0%, 30%] | 9.3% | 7.0% | 7: 14 / 168 / 1167 min | 0 | above the random 97.5% value |
| R4 price_cascade | 20 | 19/20 = 95% [75%, 100%] | 10% [0%, 30%] | 5.2% | 4.2% | 19: 5 / 53 / 198 min | 0 | above the random 97.5% value |
| always stay out | 20 | 20/20 = 100% [83%, 100%] | 100% [100%, 100%] | 100.0% | 0.0% | 20: 57473 / 305072 / 459207 min | - | inside the random 2.5%-97.5% range |
| never | 20 | 0/20 = 0% [0%, 17%] | 0% [0%, 0%] | 0.0% | 0.0% | - | - | inside the random 2.5%-97.5% range |
| random | 20 | 16/20 = 80% [56%, 94%] | 70% [45%, 90%] | 9.8% | 10.0% | 16: 8 / 40 / 60 min | - | inside the random 2.5%-97.5% range |

## 4. NaN decision times per rule

Decision times where the feature was NaN and the state was forced to 0 (clear), over all test decision times:

| Rule | Test decision times | NaN, long side | NaN, short side | Share, long | Share, short |
|---|---|---|---|---|---|
| R1 realized_volatility | 95,905 | 0 | 0 | 0.00% | 0.00% |
| R2 funding_extreme | 95,905 | 0 | 0 | 0.00% | 0.00% |
| R3 exchange_gap | 95,905 | 0 | 0 | 0.00% | 0.00% |
| R4 price_cascade | 95,905 | 0 | 0 | 0.00% | 0.00% |

The test months start on 2025-09-01, so the feature warm-up at the start of the data (the first hour, day or 7 days) is in the training rows, not in the test period. R3 has NaN decision times only where Bybit data are missing in the last hour; R2 only before the first usable funding row.

## 5. Each rule on its own

Primary view, lead 60 min, stay out. The splits are the harness's: before and after the 2026-07-15 cliff, and without the first 7 days after listing (that week is never in a test month, so that row equals the whole period). Then the other lead windows and the secondary view caution or stay out.

### R1 realized_volatility

**Long side: splits**

| Gate | Episodes | Capture rate (95% interval) | Random gate: median [2.5%, 97.5%] | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| all | 5 | 5/5 = 100% [48%, 100%] | 0% [0%, 40%] | 6.2% | 4.3% | 5: 14 / 258 / 650 min | above the random 97.5% value |
| before the cliff (2026-07-15) | 5 | 5/5 = 100% [48%, 100%] | 0% [0%, 40%] | 6.2% | 4.0% | 5: 14 / 258 / 650 min | above the random 97.5% value |
| after the cliff (2026-07-15) | 0 | no episodes | - | 6.1% | 9.7% | - | TOO FEW |
| without the first 7 days after listing | 5 | 5/5 = 100% [48%, 100%] | 0% [0%, 40%] | 6.2% | 4.3% | 5: 14 / 258 / 650 min | above the random 97.5% value |

**Long side: other lead windows and caution or stay out (whole period)**

| View | Capture rate | Random gate | Stay-out or caution-or-stay-out share | Lead time of captured |
|---|---|---|---|---|
| lead 15 min, stay out | 5/5 = 100% [48%, 100%] | 0% [0%, 40%] | 6.2% | 5: 14 / 258 / 650 min |
| lead 240 min, stay out | 5/5 = 100% [48%, 100%] | 20% [0%, 60%] | 6.2% | 5: 14 / 338 / 650 min |
| lead 60 min, caution or stay out | 5/5 = 100% [48%, 100%] | 10% [0%, 60%] | 10.5% | 5: 14 / 258 / 650 min |

**Short side: splits**

| Gate | Episodes | Capture rate (95% interval) | Random gate: median [2.5%, 97.5%] | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| all | 20 | 17/20 = 85% [62%, 97%] | 5% [0%, 25%] | 6.2% | 4.3% | 17: 5 / 72 / 317 min | above the random 97.5% value |
| before the cliff (2026-07-15) | 19 | 16/19 = 84% [60%, 97%] | 5% [0%, 26%] | 6.2% | 4.0% | 16: 5 / 72 / 317 min | above the random 97.5% value |
| after the cliff (2026-07-15) | 1 | 1/1 = 100% [2%, 100%] | 0% [0%, 100%] | 6.1% | 9.7% | 1: 52 / 52 / 52 min | TOO FEW |
| without the first 7 days after listing | 20 | 17/20 = 85% [62%, 97%] | 5% [0%, 25%] | 6.2% | 4.3% | 17: 5 / 72 / 317 min | above the random 97.5% value |

**Short side: other lead windows and caution or stay out (whole period)**

| View | Capture rate | Random gate | Stay-out or caution-or-stay-out share | Lead time of captured |
|---|---|---|---|---|
| lead 15 min, stay out | 15/20 = 75% [51%, 91%] | 5% [0%, 20%] | 6.2% | 15: 5 / 72 / 317 min |
| lead 240 min, stay out | 18/20 = 90% [68%, 99%] | 15% [0%, 35%] | 6.2% | 18: 5 / 130 / 340 min |
| lead 60 min, caution or stay out | 20/20 = 100% [83%, 100%] | 15% [0%, 35%] | 10.5% | 20: 5 / 107 / 1133 min |

### R2 funding_extreme

**Long side: splits**

| Gate | Episodes | Capture rate (95% interval) | Random gate: median [2.5%, 97.5%] | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| all | 5 | 0/5 = 0% [0%, 52%] | 0% [0%, 40%] | 8.8% | 22.5% | - | inside the random 2.5%-97.5% range |
| before the cliff (2026-07-15) | 5 | 0/5 = 0% [0%, 52%] | 0% [0%, 40%] | 9.3% | 23.6% | - | inside the random 2.5%-97.5% range |
| after the cliff (2026-07-15) | 0 | no episodes | - | 0.0% | 0.0% | - | TOO FEW |
| without the first 7 days after listing | 5 | 0/5 = 0% [0%, 52%] | 0% [0%, 40%] | 8.8% | 22.5% | - | inside the random 2.5%-97.5% range |

**Long side: other lead windows and caution or stay out (whole period)**

| View | Capture rate | Random gate | Stay-out or caution-or-stay-out share | Lead time of captured |
|---|---|---|---|---|
| lead 15 min, stay out | 0/5 = 0% [0%, 52%] | 0% [0%, 40%] | 8.8% | - |
| lead 240 min, stay out | 0/5 = 0% [0%, 52%] | 10% [0%, 60%] | 8.8% | - |
| lead 60 min, caution or stay out | 2/5 = 40% [5%, 85%] | 20% [0%, 80%] | 31.3% | 2: 1638 / 23776 / 45914 min |

**Short side: splits**

| Gate | Episodes | Capture rate (95% interval) | Random gate: median [2.5%, 97.5%] | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| all | 20 | 7/20 = 35% [15%, 59%] | 45% [25%, 70%] | 44.9% | 10.6% | 7: 219 / 1278 / 9172 min | inside the random 2.5%-97.5% range |
| before the cliff (2026-07-15) | 19 | 7/19 = 37% [16%, 62%] | 47% [26%, 68%] | 43.3% | 11.2% | 7: 219 / 1278 / 9172 min | inside the random 2.5%-97.5% range |
| after the cliff (2026-07-15) | 1 | 0/1 = 0% [0%, 98%] | 0% [0%, 100%] | 77.1% | 0.0% | - | TOO FEW |
| without the first 7 days after listing | 20 | 7/20 = 35% [15%, 59%] | 45% [25%, 70%] | 44.9% | 10.6% | 7: 219 / 1278 / 9172 min | inside the random 2.5%-97.5% range |

**Short side: other lead windows and caution or stay out (whole period)**

| View | Capture rate | Random gate | Stay-out or caution-or-stay-out share | Lead time of captured |
|---|---|---|---|---|
| lead 15 min, stay out | 7/20 = 35% [15%, 59%] | 45% [25%, 65%] | 44.9% | 7: 219 / 1278 / 9172 min |
| lead 240 min, stay out | 8/20 = 40% [19%, 64%] | 50% [30%, 75%] | 44.9% | 8: 219 / 1652 / 9172 min |
| lead 60 min, caution or stay out | 11/20 = 55% [32%, 77%] | 55% [35%, 80%] | 55.5% | 11: 108 / 601 / 10379 min |

### R3 exchange_gap

**Long side: splits**

| Gate | Episodes | Capture rate (95% interval) | Random gate: median [2.5%, 97.5%] | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| all | 5 | 3/5 = 60% [15%, 95%] | 0% [0%, 60%] | 9.3% | 7.0% | 3: 75 / 133 / 429 min | inside the random 2.5%-97.5% range |
| before the cliff (2026-07-15) | 5 | 3/5 = 60% [15%, 95%] | 0% [0%, 60%] | 9.8% | 7.3% | 3: 75 / 133 / 429 min | inside the random 2.5%-97.5% range |
| after the cliff (2026-07-15) | 0 | no episodes | - | 0.0% | 0.0% | - | TOO FEW |
| without the first 7 days after listing | 5 | 3/5 = 60% [15%, 95%] | 0% [0%, 60%] | 9.3% | 7.0% | 3: 75 / 133 / 429 min | inside the random 2.5%-97.5% range |

**Long side: other lead windows and caution or stay out (whole period)**

| View | Capture rate | Random gate | Stay-out or caution-or-stay-out share | Lead time of captured |
|---|---|---|---|---|
| lead 15 min, stay out | 3/5 = 60% [15%, 95%] | 0% [0%, 60%] | 9.3% | 3: 75 / 133 / 429 min |
| lead 240 min, stay out | 3/5 = 60% [15%, 95%] | 20% [0%, 60%] | 9.3% | 3: 263 / 280 / 429 min |
| lead 60 min, caution or stay out | 3/5 = 60% [15%, 95%] | 20% [0%, 80%] | 16.3% | 3: 75 / 193 / 439 min |

**Short side: splits**

| Gate | Episodes | Capture rate (95% interval) | Random gate: median [2.5%, 97.5%] | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| all | 20 | 7/20 = 35% [15%, 59%] | 10% [0%, 30%] | 9.3% | 7.0% | 7: 14 / 168 / 1167 min | above the random 97.5% value |
| before the cliff (2026-07-15) | 19 | 7/19 = 37% [16%, 62%] | 11% [0%, 32%] | 9.8% | 7.3% | 7: 14 / 168 / 1167 min | above the random 97.5% value |
| after the cliff (2026-07-15) | 1 | 0/1 = 0% [0%, 98%] | 0% [0%, 100%] | 0.0% | 0.0% | - | TOO FEW |
| without the first 7 days after listing | 20 | 7/20 = 35% [15%, 59%] | 10% [0%, 30%] | 9.3% | 7.0% | 7: 14 / 168 / 1167 min | above the random 97.5% value |

**Short side: other lead windows and caution or stay out (whole period)**

| View | Capture rate | Random gate | Stay-out or caution-or-stay-out share | Lead time of captured |
|---|---|---|---|---|
| lead 15 min, stay out | 7/20 = 35% [15%, 59%] | 10% [0%, 25%] | 9.3% | 7: 14 / 168 / 1167 min |
| lead 240 min, stay out | 11/20 = 55% [32%, 77%] | 20% [5%, 35%] | 9.3% | 11: 14 / 169 / 1167 min |
| lead 60 min, caution or stay out | 9/20 = 45% [23%, 68%] | 20% [5%, 40%] | 16.3% | 9: 14 / 178 / 1649 min |

### R4 price_cascade

**Long side: splits**

| Gate | Episodes | Capture rate (95% interval) | Random gate: median [2.5%, 97.5%] | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| all | 5 | 5/5 = 100% [48%, 100%] | 0% [0%, 60%] | 5.5% | 4.3% | 5: 19 / 68 / 158 min | above the random 97.5% value |
| before the cliff (2026-07-15) | 5 | 5/5 = 100% [48%, 100%] | 0% [0%, 60%] | 5.3% | 4.0% | 5: 19 / 68 / 158 min | above the random 97.5% value |
| after the cliff (2026-07-15) | 0 | no episodes | - | 7.8% | 9.7% | - | TOO FEW |
| without the first 7 days after listing | 5 | 5/5 = 100% [48%, 100%] | 0% [0%, 60%] | 5.5% | 4.3% | 5: 19 / 68 / 158 min | above the random 97.5% value |

**Long side: other lead windows and caution or stay out (whole period)**

| View | Capture rate | Random gate | Stay-out or caution-or-stay-out share | Lead time of captured |
|---|---|---|---|---|
| lead 15 min, stay out | 4/5 = 80% [28%, 99%] | 0% [0%, 40%] | 5.5% | 4: 10 / 44 / 158 min |
| lead 240 min, stay out | 5/5 = 100% [48%, 100%] | 20% [0%, 80%] | 5.5% | 5: 19 / 235 / 243 min |
| lead 60 min, caution or stay out | 5/5 = 100% [48%, 100%] | 20% [0%, 60%] | 9.8% | 5: 19 / 93 / 158 min |

**Short side: splits**

| Gate | Episodes | Capture rate (95% interval) | Random gate: median [2.5%, 97.5%] | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| all | 20 | 19/20 = 95% [75%, 100%] | 10% [0%, 30%] | 5.2% | 4.2% | 19: 5 / 53 / 198 min | above the random 97.5% value |
| before the cliff (2026-07-15) | 19 | 18/19 = 95% [74%, 100%] | 11% [0%, 32%] | 5.1% | 3.9% | 18: 5 / 54 / 198 min | above the random 97.5% value |
| after the cliff (2026-07-15) | 1 | 1/1 = 100% [2%, 100%] | 0% [0%, 100%] | 7.4% | 11.4% | 1: 37 / 37 / 37 min | TOO FEW |
| without the first 7 days after listing | 20 | 19/20 = 95% [75%, 100%] | 10% [0%, 30%] | 5.2% | 4.2% | 19: 5 / 53 / 198 min | above the random 97.5% value |

**Short side: other lead windows and caution or stay out (whole period)**

| View | Capture rate | Random gate | Stay-out or caution-or-stay-out share | Lead time of captured |
|---|---|---|---|---|
| lead 15 min, stay out | 17/20 = 85% [62%, 97%] | 5% [0%, 20%] | 5.2% | 17: 5 / 19 / 86 min |
| lead 240 min, stay out | 19/20 = 95% [75%, 100%] | 20% [5%, 45%] | 5.2% | 19: 9 / 168 / 317 min |
| lead 60 min, caution or stay out | 20/20 = 100% [83%, 100%] | 20% [5%, 45%] | 9.4% | 20: 9 / 76 / 198 min |

## 6. Reported-only views (never used to select): lead 60 min, stay out, whole test period

| Rule | View | Side | Episodes | Capture rate | Random gate | Stay-out share |
|---|---|---|---|---|---|---|
| R1 realized_volatility | 4h / 20 percent | long | 15 | 14/15 = 93% [68%, 100%] | 7% [0%, 33%] | 6.2% |
| R1 realized_volatility | 4h / 20 percent | short | 22 | 17/22 = 77% [55%, 92%] | 9% [0%, 27%] | 6.2% |
| R1 realized_volatility | 1h / 20 percent | long | 12 | 11/12 = 92% [62%, 100%] | 8% [0%, 33%] | 6.2% |
| R1 realized_volatility | 1h / 20 percent | short | 19 | 17/19 = 89% [67%, 99%] | 5% [0%, 37%] | 6.2% |
| R2 funding_extreme | 4h / 20 percent | long | 15 | 2/15 = 13% [2%, 40%] | 7% [0%, 27%] | 8.8% |
| R2 funding_extreme | 4h / 20 percent | short | 22 | 8/22 = 36% [17%, 59%] | 45% [23%, 77%] | 44.9% |
| R2 funding_extreme | 1h / 20 percent | long | 12 | 1/12 = 8% [0%, 38%] | 8% [0%, 33%] | 8.8% |
| R2 funding_extreme | 1h / 20 percent | short | 19 | 10/19 = 53% [29%, 76%] | 42% [16%, 79%] | 44.9% |
| R3 exchange_gap | 4h / 20 percent | long | 15 | 7/15 = 47% [21%, 73%] | 7% [0%, 47%] | 9.3% |
| R3 exchange_gap | 4h / 20 percent | short | 22 | 8/22 = 36% [17%, 59%] | 9% [0%, 27%] | 9.3% |
| R3 exchange_gap | 1h / 20 percent | long | 12 | 6/12 = 50% [21%, 79%] | 8% [0%, 42%] | 9.3% |
| R3 exchange_gap | 1h / 20 percent | short | 19 | 5/19 = 26% [9%, 51%] | 11% [0%, 47%] | 9.3% |
| R4 price_cascade | 4h / 20 percent | long | 15 | 14/15 = 93% [68%, 100%] | 7% [0%, 40%] | 5.5% |
| R4 price_cascade | 4h / 20 percent | short | 22 | 20/22 = 91% [71%, 99%] | 9% [0%, 32%] | 5.2% |
| R4 price_cascade | 1h / 20 percent | long | 12 | 11/12 = 92% [62%, 100%] | 8% [0%, 42%] | 5.5% |
| R4 price_cascade | 1h / 20 percent | short | 19 | 18/19 = 95% [74%, 100%] | 11% [0%, 42%] | 5.2% |

## 7. Cut-offs (first and last test month)

| Rule | Side | Feature, tail | Month | Training rows | Stay-out cut-off | Caution cut-off |
|---|---|---|---|---|---|---|
| R1 realized_volatility | long | `rv_1h`, high | 2025-09 | 13,410 | 0.00556907 | 0.00437023 |
| R1 realized_volatility | long | `rv_1h`, high | 2026-07 | 100,674 | 0.0046609 | 0.00351268 |
| R1 realized_volatility | short | `rv_1h`, high | 2025-09 | 13,410 | 0.00556907 | 0.00437023 |
| R1 realized_volatility | short | `rv_1h`, high | 2026-07 | 100,674 | 0.0046609 | 0.00351268 |
| R2 funding_extreme | long | `funding_rate`, high | 2025-09 | 13,410 | 0.00016248 | 5e-05 |
| R2 funding_extreme | long | `funding_rate`, high | 2026-07 | 100,674 | 0.00055489 | 0.00039028 |
| R2 funding_extreme | short | `funding_rate`, low | 2025-09 | 13,410 | -0.00055761 | -3.72e-05 |
| R2 funding_extreme | short | `funding_rate`, low | 2026-07 | 100,674 | 5e-05 | 5e-05 |
| R3 exchange_gap | long | `bybit_gap_abs_max_1h`, high | 2025-09 | 13,410 | 0.00419815 | 0.00375094 |
| R3 exchange_gap | long | `bybit_gap_abs_max_1h`, high | 2026-07 | 100,674 | 0.00632603 | 0.00556586 |
| R3 exchange_gap | short | `bybit_gap_abs_max_1h`, high | 2025-09 | 13,410 | 0.00419815 | 0.00375094 |
| R3 exchange_gap | short | `bybit_gap_abs_max_1h`, high | 2026-07 | 100,674 | 0.00632603 | 0.00556586 |
| R4 price_cascade | long | `drawdown_1h`, low | 2025-09 | 13,410 | -0.0431713 | -0.0325868 |
| R4 price_cascade | long | `drawdown_1h`, low | 2026-07 | 100,674 | -0.0343434 | -0.0245046 |
| R4 price_cascade | short | `runup_1h`, high | 2025-09 | 13,410 | 0.0489126 | 0.0366257 |
| R4 price_cascade | short | `runup_1h`, high | 2026-07 | 100,674 | 0.0368183 | 0.0254741 |

## 8. Where a part is TOO FEW (fewer than 4 episodes)

No verdict is printed for these parts. The episodes are the same for every gate:

- 1h / 20 percent, long, after the cliff (2026-07-15): 0 episode(s)
- 1h / 20 percent, short, after the cliff (2026-07-15): 0 episode(s)
- 24h / 30 percent, long, after the cliff (2026-07-15): 0 episode(s)
- 24h / 30 percent, short, after the cliff (2026-07-15): 1 episode(s)
- 4h / 20 percent, long, after the cliff (2026-07-15): 0 episode(s)
- 4h / 20 percent, short, after the cliff (2026-07-15): 0 episode(s)

## 9. Reading the numbers (descriptive only)

- **Stay-out share against the percentile.** R1, R3 and R4 sit in stay out about 5 to 9 percent of the time, as a 95th (or 5th) percentile cut-off suggests. R2 does not: its short side sat in stay out 44.9% of the time and its long side 8.8% (caution 22.5%). The reason is ties, not a bug: funding sits at one floor value, 0.00005, in about 58 percent of the funding rows in the funding file, so in later months both short-side cut-offs equal that value (section 7) and "at or below" the cut-off includes every row at the floor. The rule was run exactly as fixed; no tie handling was tried.
- **R4 lead time.** It was expected to be near zero. Measured median lead: long 5: 19 / 68 / 158 min; short 19: 5 / 53 / 198 min. The lead is measured from the start of the alarm run to the event time (the first candle that crosses 30 percent from the episode's reference price, OPEN), and a 1-hour fall or rise can pass its 5th or 95th percentile before that crossing.
- **Capture next to share.** A capture rate is only readable next to the stay-out share and the random gate: R2's short capture (35 percent) comes with a stay-out share above 40 percent and sits inside the random range.
- **Few episodes.** With 5 long episodes a capture of 5 of 5 has a lower limit of about 48 percent; the long-side intervals overlap widely. Nothing here picks a rule.

## Decisions

**Decided by the user (2026-11-22, proposed by Claude, approved by the user):** the four rules and every value in section 1 (the percentile cut-offs 95 / 90 and 5 / 10 from the training rows only, fixed for the test month; NaN gives clear; the features and tails of R1 to R4); that no other threshold, window or variant is tried in this task; the metrics, the random gate and the splits are the harness's, fixed on 2026-11-21. Four trials were logged before they were evaluated.

**OPEN (not decided):**

- Whether the kill criterion check (capture at least 50 percent) should be reported at all for baselines. It is not reported here.
- Funding staleness between funding times: the latest funding rate is held until the next funding time, so at some decision times it is up to 8 hours old (4 hours in some periods). No age limit is applied.
- The zero-volume Bybit issue: 17.5 percent of Bybit 1m candles have zero volume, so their close may be stale and `bybit_gap` (and R3) may show a gap that is not a real price difference. It is kept as it is.
- Raised by this run, not asked: how to treat ties at a percentile cut-off (R2: the funding floor value 0.00005 holds about 58 percent of the funding rows, so its short-side stay-out share is above 40 percent). Nothing was changed.
- Episodes cluster in time (mostly 2026-07 and 2026-08), and a rule that turns on at the first crash of a cluster stays on through the aftershocks, so later episodes in the same cluster count as captured. The capture rates above therefore overstate skill, and the number of independent events is far smaller than the episode count. A cluster-aware view (episodes grouped when their start times are within 24 hours, capture reported for the first episode of each cluster) must be added to the harness as a reported-only metric before any real rule is evaluated.
- Capture does not measure how much of the adverse move was still ahead when the alarm came. For R4 the alarm is triggered by the start of the same move, so capture can be high while the gate protects little. A metric for the remaining adverse move after the first alarm must be defined before any real rule is evaluated.
- Any rule that must beat these baselines at Gate 2 faces R1 and R4 as the bar.

