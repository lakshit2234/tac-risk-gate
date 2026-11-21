# Phase 2 walk-forward harness check

Generated 2026-11-21 (UTC) by `python -m tacgate.phase2.walkforward demo`. Development period only; the holdout was not read (lock file `docs/holdout_used.txt` does not exist). Trials so far: 3.

**No real rule was evaluated.** Always-stay-out and never are only sanity anchors (a gate that is always on, and no gate at all); the random gate is a third anchor. Nothing here says anything about a risk gate. The harness is checked; the numbers are not a result.

## 1. Fixed values

Fixed in advance by the user on 2026-11-21 (proposed by Claude, approved by the user). Each one is a named constant in `src/tacgate/phase2/walkforward.py`.

| Item | Value |
|---|---|
| Rule states | 0 = clear, 1 = caution, 2 = stay out; long and short separate, never pooled |
| Primary alarm | state 2 (stay out); caution share and "caution or stay out" are secondary views |
| Walk-forward | expanding window by calendar month, first test month 2025-09, test months only up to 2026-07-31 00:00 UTC |
| Training rows | only rows whose label is known (label_known_at_ms) at or before the start of the test month; a violation raises an error |
| Holdout | from 2026-08-01 00:00 UTC; never read in a development run; `evaluate_holdout` works once (lock file `docs/holdout_used.txt`) and was not called |
| Primary view | 24h_30pct (24 h, 30 percent adverse); reported only: 4 h / 20 percent and 1 h / 20 percent, never used to select |
| Lead window | primary 60 min; 15, 240 min reported only |
| Random gate | circular shift of the rule's own gate series inside the test period, 1000 shifts, seed 20261121: median and 2.5 / 97.5 percent values of its capture rate |
| Interval | 95% exact Clopper-Pearson, two-sided |
| Too few | fewer than 4 episodes in a part prints TOO FEW instead of a verdict |
| Splits | before / after the cliff 2026-07-15 (from `loaders.cliff_dates`); with / without the first 7 days after listing (2025-07-15 to 2025-07-22) |
| Trial log | `docs/trial_log.csv`, append only; a trial must be logged before it is evaluated; a warning above 50 trials |

Not a decision (Claude's choice for the sanity anchor only): the random baseline gate puts each side in stay-out with probability 10 percent and in caution with probability 10 percent, independently at every decision time.

## 2. What was run

Three baseline trials were logged first (`T0001`, `T0002`, `T0003` = always_stay_out, never, random), then evaluated over the test months 2025-09 to 2026-07 (95,905 decision times; the last test month stops at 2026-07-31 00:00 UTC). Episodes in the test period (the same for every gate):

| View | Long episodes | Short episodes |
|---|---|---|
| 24h / 30 percent | 5 | 20 |
| 4h / 20 percent | 15 | 22 |
| 1h / 20 percent | 12 | 19 |

How capture is counted: an episode is captured when the gate was in the alarm state at some decision time in [event - lead, event - 5 minutes], using only decision times that exist in the test period. The event time is the open of the first 1m candle that crosses the threshold from the reference price of the episode's first positive decision time (OPEN). The lead time of a captured episode is the minutes from the start of the continuous alarm run (that contains the first alarm decision time inside the lead window) to the event.

## 3. Baseline table: primary view 24h_30pct, lead 60 min, alarm = stay out, whole test period

Rate = captured / episodes (95 percent exact interval). Random gate = capture rate after circular shifts of the gate's own series (median, 2.5 and 97.5 percent values).

### Long side

| Gate | Episodes | Capture rate | Random gate | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| always_stay_out | 5 | 5/5 = 100% [48%, 100%] | 100% [100%, 100%] | 100.0% | 0.0% | 5: 57434 / 437348 / 449350 min | inside the random 2.5%-97.5% range |
| never | 5 | 0/5 = 0% [0%, 52%] | 0% [0%, 0%] | 0.0% | 0.0% | - | inside the random 2.5%-97.5% range |
| random | 5 | 4/5 = 80% [28%, 99%] | 80% [20%, 100%] | 10.0% | 10.0% | 4: 19 / 42 / 43 min | inside the random 2.5%-97.5% range |

### Short side

| Gate | Episodes | Capture rate | Random gate | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| always_stay_out | 20 | 20/20 = 100% [83%, 100%] | 100% [100%, 100%] | 100.0% | 0.0% | 20: 57473 / 305072 / 459207 min | inside the random 2.5%-97.5% range |
| never | 20 | 0/20 = 0% [0%, 17%] | 0% [0%, 0%] | 0.0% | 0.0% | - | inside the random 2.5%-97.5% range |
| random | 20 | 16/20 = 80% [56%, 94%] | 70% [45%, 90%] | 9.8% | 10.0% | 16: 8 / 40 / 60 min | inside the random 2.5%-97.5% range |

## 4. Other lead windows (primary view, stay out, whole test period; reported only)

### Long, lead 15 min

| Gate | Episodes | Capture rate | Random gate | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| always_stay_out | 5 | 5/5 = 100% [48%, 100%] | 100% [100%, 100%] | 100.0% | 0.0% | 5: 57434 / 437348 / 449350 min | inside the random 2.5%-97.5% range |
| never | 5 | 0/5 = 0% [0%, 52%] | 0% [0%, 0%] | 0.0% | 0.0% | - | inside the random 2.5%-97.5% range |
| random | 5 | 0/5 = 0% [0%, 52%] | 20% [0%, 60%] | 10.0% | 10.0% | - | inside the random 2.5%-97.5% range |

### Short, lead 15 min

| Gate | Episodes | Capture rate | Random gate | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| always_stay_out | 20 | 20/20 = 100% [83%, 100%] | 100% [100%, 100%] | 100.0% | 0.0% | 20: 57473 / 305072 / 459207 min | inside the random 2.5%-97.5% range |
| never | 20 | 0/20 = 0% [0%, 17%] | 0% [0%, 0%] | 0.0% | 0.0% | - | inside the random 2.5%-97.5% range |
| random | 20 | 5/20 = 25% [9%, 49%] | 20% [5%, 35%] | 9.8% | 10.0% | 5: 8 / 9 / 15 min | inside the random 2.5%-97.5% range |

### Long, lead 240 min

| Gate | Episodes | Capture rate | Random gate | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| always_stay_out | 5 | 5/5 = 100% [48%, 100%] | 100% [100%, 100%] | 100.0% | 0.0% | 5: 57434 / 437348 / 449350 min | inside the random 2.5%-97.5% range |
| never | 5 | 0/5 = 0% [0%, 52%] | 0% [0%, 0%] | 0.0% | 0.0% | - | inside the random 2.5%-97.5% range |
| random | 5 | 5/5 = 100% [48%, 100%] | 100% [80%, 100%] | 10.0% | 10.0% | 5: 43 / 213 / 237 min | inside the random 2.5%-97.5% range |

### Short, lead 240 min

| Gate | Episodes | Capture rate | Random gate | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| always_stay_out | 20 | 20/20 = 100% [83%, 100%] | 100% [100%, 100%] | 100.0% | 0.0% | 20: 57473 / 305072 / 459207 min | inside the random 2.5%-97.5% range |
| never | 20 | 0/20 = 0% [0%, 17%] | 0% [0%, 0%] | 0.0% | 0.0% | - | inside the random 2.5%-97.5% range |
| random | 20 | 20/20 = 100% [83%, 100%] | 100% [95%, 100%] | 9.8% | 10.0% | 20: 148 / 218 / 240 min | inside the random 2.5%-97.5% range |

## 5. Reported-only views (lead 60 min, stay out, whole test period; never used to select)

### 4h / 20 percent, long

| Gate | Episodes | Capture rate | Random gate | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| always_stay_out | 15 | 15/15 = 100% [78%, 100%] | 100% [100%, 100%] | 100.0% | 0.0% | 15: 57434 / 287106 / 449350 min | inside the random 2.5%-97.5% range |
| never | 15 | 0/15 = 0% [0%, 22%] | 0% [0%, 0%] | 0.0% | 0.0% | - | inside the random 2.5%-97.5% range |
| random | 15 | 11/15 = 73% [45%, 92%] | 67% [47%, 87%] | 10.0% | 10.0% | 11: 14 / 42 / 60 min | inside the random 2.5%-97.5% range |

### 4h / 20 percent, short

| Gate | Episodes | Capture rate | Random gate | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| always_stay_out | 22 | 22/22 = 100% [85%, 100%] | 100% [100%, 100%] | 100.0% | 0.0% | 22: 57466 / 349264 / 448814 min | inside the random 2.5%-97.5% range |
| never | 22 | 0/22 = 0% [0%, 15%] | 0% [0%, 0%] | 0.0% | 0.0% | - | inside the random 2.5%-97.5% range |
| random | 22 | 12/22 = 55% [32%, 76%] | 68% [50%, 86%] | 9.8% | 10.0% | 12: 11 / 50 / 60 min | inside the random 2.5%-97.5% range |

### 1h / 20 percent, long

| Gate | Episodes | Capture rate | Random gate | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| always_stay_out | 12 | 12/12 = 100% [74%, 100%] | 100% [100%, 100%] | 100.0% | 0.0% | 12: 57434 / 180610 / 449345 min | inside the random 2.5%-97.5% range |
| never | 12 | 0/12 = 0% [0%, 26%] | 0% [0%, 0%] | 0.0% | 0.0% | - | inside the random 2.5%-97.5% range |
| random | 12 | 7/12 = 58% [28%, 85%] | 67% [42%, 92%] | 10.0% | 10.0% | 7: 10 / 41 / 52 min | inside the random 2.5%-97.5% range |

### 1h / 20 percent, short

| Gate | Episodes | Capture rate | Random gate | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| always_stay_out | 19 | 19/19 = 100% [82%, 100%] | 100% [100%, 100%] | 100.0% | 0.0% | 19: 57466 / 434307 / 449383 min | inside the random 2.5%-97.5% range |
| never | 19 | 0/19 = 0% [0%, 18%] | 0% [0%, 0%] | 0.0% | 0.0% | - | inside the random 2.5%-97.5% range |
| random | 19 | 13/19 = 68% [43%, 87%] | 68% [47%, 89%] | 9.8% | 10.0% | 13: 11 / 41 / 56 min | inside the random 2.5%-97.5% range |

## 6. Secondary view: caution or stay out (primary view, lead 60 min, whole test period)

### Long side

| Gate | Episodes | Capture rate | Random gate | Caution-or-stay-out share |
|---|---|---|---|---|
| always_stay_out | 5 | 5/5 = 100% [48%, 100%] | 100% [100%, 100%] | 100.0% |
| never | 5 | 0/5 = 0% [0%, 52%] | 0% [0%, 0%] | 0.0% |
| random | 5 | 4/5 = 80% [28%, 99%] | 100% [60%, 100%] | 19.9% |

### Short side

| Gate | Episodes | Capture rate | Random gate | Caution-or-stay-out share |
|---|---|---|---|---|
| always_stay_out | 20 | 20/20 = 100% [83%, 100%] | 100% [100%, 100%] | 100.0% |
| never | 20 | 0/20 = 0% [0%, 17%] | 0% [0%, 0%] | 0.0% |
| random | 20 | 20/20 = 100% [83%, 100%] | 90% [80%, 100%] | 19.8% |

## 7. Split tables (primary view, lead 60 min, stay out)

Each part counts the episodes that START in it and the decision times in it. The test period starts 2025-09-01, so the first 7 days after listing (2025-07-15 to 2025-07-22) are never in a test month: "without the first 7 days after listing" is the same as the whole period here. Those days are in the training rows only.

### Long: all

| Gate | Episodes | Capture rate | Random gate | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| always_stay_out | 5 | 5/5 = 100% [48%, 100%] | 100% [100%, 100%] | 100.0% | 0.0% | 5: 57434 / 437348 / 449350 min | inside the random 2.5%-97.5% range |
| never | 5 | 0/5 = 0% [0%, 52%] | 0% [0%, 0%] | 0.0% | 0.0% | - | inside the random 2.5%-97.5% range |
| random | 5 | 4/5 = 80% [28%, 99%] | 80% [20%, 100%] | 10.0% | 10.0% | 4: 19 / 42 / 43 min | inside the random 2.5%-97.5% range |

### Long: before the cliff (2026-07-15)

| Gate | Episodes | Capture rate | Random gate | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| always_stay_out | 5 | 5/5 = 100% [48%, 100%] | 100% [100%, 100%] | 100.0% | 0.0% | 5: 57434 / 437348 / 449350 min | inside the random 2.5%-97.5% range |
| never | 5 | 0/5 = 0% [0%, 52%] | 0% [0%, 0%] | 0.0% | 0.0% | - | inside the random 2.5%-97.5% range |
| random | 5 | 4/5 = 80% [28%, 99%] | 80% [20%, 100%] | 10.0% | 10.0% | 4: 19 / 42 / 43 min | inside the random 2.5%-97.5% range |

### Long: after the cliff (2026-07-15)

| Gate | Episodes | Capture rate | Random gate | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| always_stay_out | 0 | no episodes | - | 100.0% | 0.0% | - | TOO FEW |
| never | 0 | no episodes | - | 0.0% | 0.0% | - | TOO FEW |
| random | 0 | no episodes | - | 9.7% | 10.1% | - | TOO FEW |

### Long: without the first 7 days after listing

| Gate | Episodes | Capture rate | Random gate | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| always_stay_out | 5 | 5/5 = 100% [48%, 100%] | 100% [100%, 100%] | 100.0% | 0.0% | 5: 57434 / 437348 / 449350 min | inside the random 2.5%-97.5% range |
| never | 5 | 0/5 = 0% [0%, 52%] | 0% [0%, 0%] | 0.0% | 0.0% | - | inside the random 2.5%-97.5% range |
| random | 5 | 4/5 = 80% [28%, 99%] | 80% [20%, 100%] | 10.0% | 10.0% | 4: 19 / 42 / 43 min | inside the random 2.5%-97.5% range |

### Short: all

| Gate | Episodes | Capture rate | Random gate | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| always_stay_out | 20 | 20/20 = 100% [83%, 100%] | 100% [100%, 100%] | 100.0% | 0.0% | 20: 57473 / 305072 / 459207 min | inside the random 2.5%-97.5% range |
| never | 20 | 0/20 = 0% [0%, 17%] | 0% [0%, 0%] | 0.0% | 0.0% | - | inside the random 2.5%-97.5% range |
| random | 20 | 16/20 = 80% [56%, 94%] | 70% [45%, 90%] | 9.8% | 10.0% | 16: 8 / 40 / 60 min | inside the random 2.5%-97.5% range |

### Short: before the cliff (2026-07-15)

| Gate | Episodes | Capture rate | Random gate | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| always_stay_out | 19 | 19/19 = 100% [82%, 100%] | 100% [100%, 100%] | 100.0% | 0.0% | 19: 57473 / 286989 / 448907 min | inside the random 2.5%-97.5% range |
| never | 19 | 0/19 = 0% [0%, 18%] | 0% [0%, 0%] | 0.0% | 0.0% | - | inside the random 2.5%-97.5% range |
| random | 19 | 15/19 = 79% [54%, 94%] | 68% [47%, 89%] | 9.8% | 10.0% | 15: 8 / 39 / 60 min | inside the random 2.5%-97.5% range |

### Short: after the cliff (2026-07-15)

| Gate | Episodes | Capture rate | Random gate | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| always_stay_out | 1 | 1/1 = 100% [2%, 100%] | 100% [100%, 100%] | 100.0% | 0.0% | 1: 459207 / 459207 / 459207 min | TOO FEW |
| never | 1 | 0/1 = 0% [0%, 98%] | 0% [0%, 0%] | 0.0% | 0.0% | - | TOO FEW |
| random | 1 | 1/1 = 100% [2%, 100%] | 100% [0%, 100%] | 9.9% | 9.9% | 1: 52 / 52 / 52 min | TOO FEW |

### Short: without the first 7 days after listing

| Gate | Episodes | Capture rate | Random gate | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |
|---|---|---|---|---|---|---|---|
| always_stay_out | 20 | 20/20 = 100% [83%, 100%] | 100% [100%, 100%] | 100.0% | 0.0% | 20: 57473 / 305072 / 459207 min | inside the random 2.5%-97.5% range |
| never | 20 | 0/20 = 0% [0%, 17%] | 0% [0%, 0%] | 0.0% | 0.0% | - | inside the random 2.5%-97.5% range |
| random | 20 | 16/20 = 80% [56%, 94%] | 70% [45%, 90%] | 9.8% | 10.0% | 16: 8 / 40 / 60 min | inside the random 2.5%-97.5% range |

## 8. Where a part is TOO FEW (fewer than 4 episodes)

No verdict is printed for these parts (the same episodes for every gate):

- 24h / 30 percent, long, after the cliff (2026-07-15): 0 episode(s)
- 4h / 20 percent, long, after the cliff (2026-07-15): 0 episode(s)
- 1h / 20 percent, long, after the cliff (2026-07-15): 0 episode(s)
- 24h / 30 percent, short, after the cliff (2026-07-15): 1 episode(s)
- 4h / 20 percent, short, after the cliff (2026-07-15): 0 episode(s)
- 1h / 20 percent, short, after the cliff (2026-07-15): 0 episode(s)

## 9. Reading the anchors

- Always stay out captures every episode and sits in stay out 100 percent of the time: the capture rate alone means nothing, which is why the time share is always printed next to it.
- Never captures none and sits in stay out 0 percent of the time.
- The lead time of the always-stay-out gate is huge (tens of thousands of minutes) because its alarm run starts at the first test decision time; it is not a lead time in any useful sense.
- The primary view has only a handful of long episodes in the whole test period (see section 2), so every long-side number above rests on very few events; even the whole-period long row is close to the 4-episode limit.
- The random gate sits in stay out about 10 percent of the time; its own capture rate and its shifted-series range show what chance alone gives at that share. No significance claim is made anywhere.

## Decisions

**Decided by the user (fixed on 2026-11-21, proposed by Claude, approved by the user):** every value in section 1; the rule interface (one feature row, states 0 / 1 / 2, long and short separate); walk-forward by calendar month from 2025-09 with the embargo rule enforced in code; the holdout read only through `evaluate_holdout`, once, behind a lock file; the append-only trial log with the 50-trial warning; the fixed metrics, the random gate and the exact interval; results in `data/processed/trials/` (ignored by git).

**The interval:** it is the two-sided 95 percent exact Clopper-Pearson interval, as the user asked. The numbers 0.527 and 0.473 in the original test spec were one-sided limits and were a mistake by Claude, not by the code.

**OPEN (not decided):**

- The event-time definition: the open of the first 1m candle that crosses the threshold from the reference price of the episode's first positive decision time. Other choices (for example the candle close, or the extreme) are possible.
- What caution means: the harness reports it as a secondary view only; how it would change a position or an entry is not decided.
- What to do when the long side has too few episodes (the primary view has few long episodes in the cliff parts and the holdout is at the 4-episode limit): report "too few for a verdict" in advance, or something else.

