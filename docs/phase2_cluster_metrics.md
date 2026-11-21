# Phase 2 cluster-aware capture and remaining move (reported only)

Generated 2026-11-21 (UTC) by `python -m tacgate.phase2.cluster_metrics`. Development period only (test months 2025-09 to 2026-07, decision times up to 2026-07-31 00:00 UTC); the holdout was not read or evaluated. The seven logged trials (T0001 to T0007) are re-reported; **no new trial was logged and no rule, threshold or window changed.** These are views, not selection criteria: the table order is the trial order, nothing is ranked, and no rule is picked.

**Read this first.** With so few clusters no capture rate here supports a claim that a gate works, and none is made. A percentage always has its count next to it.

## 1. Fixed definitions

Fixed in advance by the user on 2026-11-22 (proposed by Claude, approved by the user); each value is a named constant in `src/tacgate/phase2/cluster_metrics.py`. Long and short are always separate.

1. **Clusters** (per side and per view): sort the episodes by start time. An episode joins the current cluster if its start is within 24 hours of the previous episode's start in that cluster (chained; "within" includes exactly 24 hours). Otherwise it starts a new cluster.
2. **Cluster-aware capture:** the first episode of each cluster is the one tested, with the harness's own capture rule (stay out at some decision time in the 1 hour lead window before its event time). Captured / clusters with the two-sided 95 percent exact Clopper-Pearson interval; TOO FEW under 4 clusters. The all-episode capture is printed next to it.
3. **Remaining adverse move:** the alarm time is the first decision time of the continuous stay-out spell that contains the first stay-out decision time inside the lead window, looking back no further than 24 hours before the event time; no such spell means not captured. For a captured episode the remaining move is the largest adverse move after the alarm time within the next 24 hours (1m low for long, 1m high for short), against the reference price at the alarm time. The already-happened move is the adverse move from the reference price of the episode's first positive decision time to the reference price at the alarm time. For a not-captured episode the remaining move is the whole move: the largest adverse move in the 24 hours after its first positive decision time, against its reference price. A move is a plain fraction (a fall for long, a rise for short); the already-happened move can be negative (the price went the other way before the alarm).

Every number is on the Binance last-price klines (not mark price), as in the labels.

## 2. The re-run is the same run

The saved results do not contain the per-decision gate series, so the same rules and the same seeded anchors were re-run on the development period without writing any trial row. Before anything else every existing metric (episodes, capture, shares, intervals, random gate, lead times, cut-offs, NaN counts) of all seven trials was recomputed and compared with the saved number: **13,894 values compared, 0 differences.** (Had one differed, the run would have stopped here.)

## 3. Episodes and clusters

| View | Side | Episodes | Clusters |
|---|---|---|---|
| 24h / 30 percent | long | 5 | 5 |
| 24h / 30 percent | short | 20 | 20 |
| 4h / 20 percent | long | 15 | 11 |
| 4h / 20 percent | short | 22 | 20 |
| 1h / 20 percent | long | 12 | 10 |
| 1h / 20 percent | short | 19 | 13 |

Plainly: in the primary view (24h / 30 percent) there are 5 long episodes in 5 clusters and 20 short episodes in 20 clusters. Here the cluster count equals the episode count, and that is structural: two 24 hour episodes are separated by at least 24 hours between the end of one and the start of the next, so their starts are always more than 24 hours apart (an exact tie is the only way they could be merged). **The 24 hour chaining gap therefore cannot merge any episode of the 24 h view;** the cluster view only changes the 4 h and 1 h views, where episodes are shorter. This is raised as OPEN below.

## 4. Primary view 24h / 30 percent: capture, all episodes and clusters

Lead window 1 hour, alarm = stay out, whole test period. Trials in trial order.

### Long side

| Trial | Episodes | Clusters | All-episode capture | Cluster-aware capture (first episode of each cluster) | Verdict |
|---|---|---|---|---|---|
| T0001 always stay out | 5 | 5 | 5/5 = 100% [48%, 100%] | 5/5 = 100% [48%, 100%] | descriptive only |
| T0002 never | 5 | 5 | 0/5 = 0% [0%, 52%] | 0/5 = 0% [0%, 52%] | descriptive only |
| T0003 random | 5 | 5 | 4/5 = 80% [28%, 99%] | 4/5 = 80% [28%, 99%] | descriptive only |
| T0004 R1 realized_volatility | 5 | 5 | 5/5 = 100% [48%, 100%] | 5/5 = 100% [48%, 100%] | descriptive only |
| T0005 R2 funding_extreme | 5 | 5 | 0/5 = 0% [0%, 52%] | 0/5 = 0% [0%, 52%] | descriptive only |
| T0006 R3 exchange_gap | 5 | 5 | 3/5 = 60% [15%, 95%] | 3/5 = 60% [15%, 95%] | descriptive only |
| T0007 R4 price_cascade | 5 | 5 | 5/5 = 100% [48%, 100%] | 5/5 = 100% [48%, 100%] | descriptive only |

### Short side

| Trial | Episodes | Clusters | All-episode capture | Cluster-aware capture (first episode of each cluster) | Verdict |
|---|---|---|---|---|---|
| T0001 always stay out | 20 | 20 | 20/20 = 100% [83%, 100%] | 20/20 = 100% [83%, 100%] | descriptive only |
| T0002 never | 20 | 20 | 0/20 = 0% [0%, 17%] | 0/20 = 0% [0%, 17%] | descriptive only |
| T0003 random | 20 | 20 | 16/20 = 80% [56%, 94%] | 16/20 = 80% [56%, 94%] | descriptive only |
| T0004 R1 realized_volatility | 20 | 20 | 17/20 = 85% [62%, 97%] | 17/20 = 85% [62%, 97%] | descriptive only |
| T0005 R2 funding_extreme | 20 | 20 | 7/20 = 35% [15%, 59%] | 7/20 = 35% [15%, 59%] | descriptive only |
| T0006 R3 exchange_gap | 20 | 20 | 7/20 = 35% [15%, 59%] | 7/20 = 35% [15%, 59%] | descriptive only |
| T0007 R4 price_cascade | 20 | 20 | 19/20 = 95% [75%, 100%] | 19/20 = 95% [75%, 100%] | descriptive only |

## 5. Primary view 24h / 30 percent: the move after the alarm

Remaining move = what was still ahead after the first alarm (captured episodes), the already-happened move = what had already happened when the alarm came, and for a not-captured episode the whole move counts as unprotected. The last column mixes both as the definition says. An always-on gate has its alarm time pushed back to 24 hours before the event by the look-back cap, which is why its remaining move is the 24 hour move from there.

### Long side

| Trial | Captured episodes | Remaining move, captured: median [range] | Already-happened move, captured: median | Not captured: whole move, median | Remaining move, all episodes: median |
|---|---|---|---|---|---|
| T0001 always stay out | 5 of 5 | 30.1% [0.0% to 60.7%] (n=5) | 0.0% (n=5) | - | 30.1% (n=5) |
| T0002 never | 0 of 5 | - | - | 33.6% (n=5) | 33.6% (n=5) |
| T0003 random | 4 of 5 | 68.3% [43.4% to 94.3%] (n=4) | -16.6% (n=4) | 30.1% (n=1) | 54.6% (n=5) |
| T0004 R1 realized_volatility | 5 of 5 | 52.7% [0.0% to 88.3%] (n=5) | 9.6% (n=5) | - | 52.7% (n=5) |
| T0005 R2 funding_extreme | 0 of 5 | - | - | 33.6% (n=5) | 33.6% (n=5) |
| T0006 R3 exchange_gap | 3 of 5 | 23.8% [6.0% to 83.1%] (n=3) | 8.2% (n=3) | 45.4% (n=2) | 30.1% (n=5) |
| T0007 R4 price_cascade | 5 of 5 | 63.3% [28.0% to 94.2%] (n=5) | 2.6% (n=5) | - | 63.3% (n=5) |

### Short side

| Trial | Captured episodes | Remaining move, captured: median [range] | Already-happened move, captured: median | Not captured: whole move, median | Remaining move, all episodes: median |
|---|---|---|---|---|---|
| T0001 always stay out | 20 of 20 | 30.1% [5.7% to 44.5%] (n=20) | 0.0% (n=20) | - | 30.1% (n=20) |
| T0002 never | 0 of 20 | - | - | 30.7% (n=20) | 30.7% (n=20) |
| T0003 random | 16 of 20 | 26.2% [2.0% to 233.3%] (n=16) | 20.5% (n=16) | 30.2% (n=4) | 30.2% (n=20) |
| T0004 R1 realized_volatility | 17 of 20 | 33.2% [3.6% to 268.8%] (n=17) | 16.5% (n=17) | 31.2% (n=3) | 32.2% (n=20) |
| T0005 R2 funding_extreme | 7 of 20 | 30.4% [21.3% to 36.8%] (n=7) | 3.8% (n=7) | 30.2% (n=13) | 30.4% (n=20) |
| T0006 R3 exchange_gap | 7 of 20 | 28.3% [0.3% to 46.5%] (n=7) | 8.5% (n=7) | 30.6% (n=13) | 30.5% (n=20) |
| T0007 R4 price_cascade | 19 of 20 | 30.7% [2.0% to 266.4%] (n=19) | 16.5% (n=19) | 44.5% (n=1) | 31.9% (n=20) |

## 6. Reported-only views (never used to select)

### 4h / 20 percent, long side: capture

| Trial | Episodes | Clusters | All-episode capture | Cluster-aware capture (first episode of each cluster) | Verdict |
|---|---|---|---|---|---|
| T0001 always stay out | 15 | 11 | 15/15 = 100% [78%, 100%] | 11/11 = 100% [72%, 100%] | descriptive only |
| T0002 never | 15 | 11 | 0/15 = 0% [0%, 22%] | 0/11 = 0% [0%, 28%] | descriptive only |
| T0003 random | 15 | 11 | 11/15 = 73% [45%, 92%] | 8/11 = 73% [39%, 94%] | descriptive only |
| T0004 R1 realized_volatility | 15 | 11 | 14/15 = 93% [68%, 100%] | 10/11 = 91% [59%, 100%] | descriptive only |
| T0005 R2 funding_extreme | 15 | 11 | 2/15 = 13% [2%, 40%] | 2/11 = 18% [2%, 52%] | descriptive only |
| T0006 R3 exchange_gap | 15 | 11 | 7/15 = 47% [21%, 73%] | 7/11 = 64% [31%, 89%] | descriptive only |
| T0007 R4 price_cascade | 15 | 11 | 14/15 = 93% [68%, 100%] | 10/11 = 91% [59%, 100%] | descriptive only |

### 4h / 20 percent, long side: the move after the alarm

| Trial | Captured episodes | Remaining move, captured: median [range] | Already-happened move, captured: median | Not captured: whole move, median | Remaining move, all episodes: median |
|---|---|---|---|---|---|
| T0001 always stay out | 15 of 15 | 6.9% [0.2% to 92.1%] (n=15) | 17.3% (n=15) | - | 6.9% (n=15) |
| T0002 never | 0 of 15 | - | - | 23.8% (n=15) | 23.8% (n=15) |
| T0003 random | 11 of 15 | 24.2% [7.5% to 94.3%] (n=11) | 2.9% (n=11) | 23.0% (n=4) | 23.8% (n=15) |
| T0004 R1 realized_volatility | 14 of 15 | 14.8% [0.0% to 88.3%] (n=14) | 11.9% (n=14) | 23.9% (n=1) | 15.7% (n=15) |
| T0005 R2 funding_extreme | 2 of 15 | 4.5% [1.3% to 7.7%] (n=2) | 23.9% (n=2) | 23.9% (n=13) | 23.8% (n=15) |
| T0006 R3 exchange_gap | 7 of 15 | 6.0% [0.2% to 83.1%] (n=7) | 19.5% (n=7) | 26.9% (n=8) | 21.7% (n=15) |
| T0007 R4 price_cascade | 14 of 15 | 27.7% [8.4% to 94.2%] (n=14) | 1.0% (n=14) | 23.9% (n=1) | 27.7% (n=15) |

### 4h / 20 percent, short side: capture

| Trial | Episodes | Clusters | All-episode capture | Cluster-aware capture (first episode of each cluster) | Verdict |
|---|---|---|---|---|---|
| T0001 always stay out | 22 | 20 | 22/22 = 100% [85%, 100%] | 20/20 = 100% [83%, 100%] | descriptive only |
| T0002 never | 22 | 20 | 0/22 = 0% [0%, 15%] | 0/20 = 0% [0%, 17%] | descriptive only |
| T0003 random | 22 | 20 | 12/22 = 55% [32%, 76%] | 12/20 = 60% [36%, 81%] | descriptive only |
| T0004 R1 realized_volatility | 22 | 20 | 17/22 = 77% [55%, 92%] | 15/20 = 75% [51%, 91%] | descriptive only |
| T0005 R2 funding_extreme | 22 | 20 | 8/22 = 36% [17%, 59%] | 7/20 = 35% [15%, 59%] | descriptive only |
| T0006 R3 exchange_gap | 22 | 20 | 8/22 = 36% [17%, 59%] | 7/20 = 35% [15%, 59%] | descriptive only |
| T0007 R4 price_cascade | 22 | 20 | 20/22 = 91% [71%, 99%] | 18/20 = 90% [68%, 99%] | descriptive only |

### 4h / 20 percent, short side: the move after the alarm

| Trial | Captured episodes | Remaining move, captured: median [range] | Already-happened move, captured: median | Not captured: whole move, median | Remaining move, all episodes: median |
|---|---|---|---|---|---|
| T0001 always stay out | 22 of 22 | 22.3% [4.3% to 51.6%] (n=22) | -0.7% (n=22) | - | 22.3% (n=22) |
| T0002 never | 0 of 22 | - | - | 31.0% (n=22) | 31.0% (n=22) |
| T0003 random | 12 of 22 | 23.2% [2.0% to 206.1%] (n=12) | 6.1% (n=12) | 39.6% (n=10) | 24.7% (n=22) |
| T0004 R1 realized_volatility | 17 of 22 | 25.7% [2.1% to 268.8%] (n=17) | 6.2% (n=17) | 32.1% (n=5) | 29.7% (n=22) |
| T0005 R2 funding_extreme | 8 of 22 | 21.5% [8.8% to 36.8%] (n=8) | 0.5% (n=8) | 29.8% (n=14) | 28.9% (n=22) |
| T0006 R3 exchange_gap | 8 of 22 | 32.0% [0.3% to 278.5%] (n=8) | 4.6% (n=8) | 29.9% (n=14) | 29.9% (n=22) |
| T0007 R4 price_cascade | 20 of 22 | 26.7% [2.0% to 277.4%] (n=20) | 5.1% (n=20) | 43.1% (n=2) | 29.2% (n=22) |

### 1h / 20 percent, long side: capture

| Trial | Episodes | Clusters | All-episode capture | Cluster-aware capture (first episode of each cluster) | Verdict |
|---|---|---|---|---|---|
| T0001 always stay out | 12 | 10 | 12/12 = 100% [74%, 100%] | 10/10 = 100% [69%, 100%] | descriptive only |
| T0002 never | 12 | 10 | 0/12 = 0% [0%, 26%] | 0/10 = 0% [0%, 31%] | descriptive only |
| T0003 random | 12 | 10 | 7/12 = 58% [28%, 85%] | 7/10 = 70% [35%, 93%] | descriptive only |
| T0004 R1 realized_volatility | 12 | 10 | 11/12 = 92% [62%, 100%] | 9/10 = 90% [55%, 100%] | descriptive only |
| T0005 R2 funding_extreme | 12 | 10 | 1/12 = 8% [0%, 38%] | 1/10 = 10% [0%, 45%] | descriptive only |
| T0006 R3 exchange_gap | 12 | 10 | 6/12 = 50% [21%, 79%] | 6/10 = 60% [26%, 88%] | descriptive only |
| T0007 R4 price_cascade | 12 | 10 | 11/12 = 92% [62%, 100%] | 9/10 = 90% [55%, 100%] | descriptive only |

### 1h / 20 percent, long side: the move after the alarm

| Trial | Captured episodes | Remaining move, captured: median [range] | Already-happened move, captured: median | Not captured: whole move, median | Remaining move, all episodes: median |
|---|---|---|---|---|---|
| T0001 always stay out | 12 of 12 | 6.0% [0.0% to 92.7%] (n=12) | 29.4% (n=12) | - | 6.0% (n=12) |
| T0002 never | 0 of 12 | - | - | 28.9% (n=12) | 28.9% (n=12) |
| T0003 random | 7 of 12 | 24.3% [17.9% to 94.3%] (n=7) | 1.5% (n=7) | 29.4% (n=5) | 28.0% (n=12) |
| T0004 R1 realized_volatility | 11 of 12 | 13.9% [0.0% to 88.3%] (n=11) | 13.3% (n=11) | 24.2% (n=1) | 16.4% (n=12) |
| T0005 R2 funding_extreme | 1 of 12 | 1.3% [1.3% to 1.3%] (n=1) | 33.1% (n=1) | 29.4% (n=11) | 28.9% (n=12) |
| T0006 R3 exchange_gap | 6 of 12 | 11.2% [0.2% to 83.1%] (n=6) | 15.0% (n=6) | 28.9% (n=6) | 24.0% (n=12) |
| T0007 R4 price_cascade | 11 of 12 | 27.7% [10.5% to 94.2%] (n=11) | 2.4% (n=11) | 24.2% (n=1) | 27.7% (n=12) |

### 1h / 20 percent, short side: capture

| Trial | Episodes | Clusters | All-episode capture | Cluster-aware capture (first episode of each cluster) | Verdict |
|---|---|---|---|---|---|
| T0001 always stay out | 19 | 13 | 19/19 = 100% [82%, 100%] | 13/13 = 100% [75%, 100%] | descriptive only |
| T0002 never | 19 | 13 | 0/19 = 0% [0%, 18%] | 0/13 = 0% [0%, 25%] | descriptive only |
| T0003 random | 19 | 13 | 13/19 = 68% [43%, 87%] | 9/13 = 69% [39%, 91%] | descriptive only |
| T0004 R1 realized_volatility | 19 | 13 | 17/19 = 89% [67%, 99%] | 11/13 = 85% [55%, 98%] | descriptive only |
| T0005 R2 funding_extreme | 19 | 13 | 10/19 = 53% [29%, 76%] | 6/13 = 46% [19%, 75%] | descriptive only |
| T0006 R3 exchange_gap | 19 | 13 | 5/19 = 26% [9%, 51%] | 4/13 = 31% [9%, 61%] | descriptive only |
| T0007 R4 price_cascade | 19 | 13 | 18/19 = 95% [74%, 100%] | 12/13 = 92% [64%, 100%] | descriptive only |

### 1h / 20 percent, short side: the move after the alarm

| Trial | Captured episodes | Remaining move, captured: median [range] | Already-happened move, captured: median | Not captured: whole move, median | Remaining move, all episodes: median |
|---|---|---|---|---|---|
| T0001 always stay out | 19 of 19 | 30.4% [0.1% to 188.0%] (n=19) | -6.7% (n=19) | - | 30.4% (n=19) |
| T0002 never | 0 of 19 | - | - | 32.7% (n=19) | 32.7% (n=19) |
| T0003 random | 13 of 19 | 25.4% [2.0% to 233.3%] (n=13) | 2.6% (n=13) | 38.0% (n=6) | 28.4% (n=19) |
| T0004 R1 realized_volatility | 17 of 19 | 35.7% [2.1% to 268.8%] (n=17) | -0.3% (n=17) | 117.5% (n=2) | 35.7% (n=19) |
| T0005 R2 funding_extreme | 10 of 19 | 32.4% [17.9% to 80.4%] (n=10) | -5.5% (n=10) | 45.0% (n=9) | 34.3% (n=19) |
| T0006 R3 exchange_gap | 5 of 19 | 25.1% [0.3% to 46.5%] (n=5) | -1.0% (n=5) | 33.9% (n=14) | 31.5% (n=19) |
| T0007 R4 price_cascade | 18 of 19 | 32.7% [2.0% to 266.4%] (n=18) | 0.3% (n=18) | 29.0% (n=1) | 32.4% (n=19) |

## 7. What the cluster view does to the baselines

- 24h / 30 percent, long: 5 episodes in 5 clusters: nothing merges, so the cluster view equals the episode view.
- 24h / 30 percent, short: 20 episodes in 20 clusters: nothing merges, so the cluster view equals the episode view.
- 4h / 20 percent, long: 15 episodes merge into 11 clusters. Episode view against cluster view: R1 14/15 episodes vs 10/11 clusters; R2 2/15 episodes vs 2/11 clusters; R3 7/15 episodes vs 7/11 clusters; R4 14/15 episodes vs 10/11 clusters.
- 4h / 20 percent, short: 22 episodes merge into 20 clusters. Episode view against cluster view: R1 17/22 episodes vs 15/20 clusters; R2 8/22 episodes vs 7/20 clusters; R3 8/22 episodes vs 7/20 clusters; R4 20/22 episodes vs 18/20 clusters.
- 1h / 20 percent, long: 12 episodes merge into 10 clusters. Episode view against cluster view: R1 11/12 episodes vs 9/10 clusters; R2 1/12 episodes vs 1/10 clusters; R3 6/12 episodes vs 6/10 clusters; R4 11/12 episodes vs 9/10 clusters.
- 1h / 20 percent, short: 19 episodes merge into 13 clusters. Episode view against cluster view: R1 17/19 episodes vs 11/13 clusters; R2 10/19 episodes vs 6/13 clusters; R3 5/19 episodes vs 4/13 clusters; R4 18/19 episodes vs 12/13 clusters.

In plain words: in the primary 24 h view the cluster view changes nothing, because nothing merges. In the 4 h and 1 h views the cluster view lowers the count of events, and the capture rate moves by a few points either way (R1 and R4, the bar named in the plan: R1 4h / 20 percent long: 93% of episodes (14/15) against 91% of clusters (10/11); R4 4h / 20 percent long: 93% of episodes (14/15) against 91% of clusters (10/11); R1 4h / 20 percent short: 77% of episodes (17/22) against 75% of clusters (15/20); R4 4h / 20 percent short: 91% of episodes (20/22) against 90% of clusters (18/20); R1 1h / 20 percent long: 92% of episodes (11/12) against 90% of clusters (9/10); R4 1h / 20 percent long: 92% of episodes (11/12) against 90% of clusters (9/10); R1 1h / 20 percent short: 89% of episodes (17/19) against 85% of clusters (11/13); R4 1h / 20 percent short: 95% of episodes (18/19) against 92% of clusters (12/13)). The point is not the size of that move: each cluster-aware rate rests on 4 to 20 independent events, with intervals as wide as the tables show.

Reading: where episodes merge, the number of independent events is the cluster count, not the episode count, and the cluster-aware rate rests on that smaller number. Where a rule's alarm stays on through a cluster, the all-episode rate counts the later episodes as captured too; the cluster-aware rate does not. No rate in any table supports a claim, and no rule is picked from this report.

## Decisions

**Decided by the user (2026-11-22, proposed by Claude, approved by the user):** the three definitions in section 1 (clusters chained within 24 hours; capture of the first episode of each cluster; remaining and already-happened move with the 24 hour look-back and the 24 hour horizon); that both are reported-only views, not selection criteria; that no new trial is logged, no rule, threshold or window changes, and the holdout is not read in this task.

**OPEN (not decided):**

- Whether the 24 hour chaining gap is right. By construction it cannot merge any episode of the 24 h view (section 3); a longer gap, or chaining on event times, would be a different definition and would have to be logged before it is used.
- Whether the remaining move should later use the mark price instead of the last-price klines.
- The 24 hour chaining gap cannot see multi-day clustering. In the primary 24 h view the episode definition already merges positives that overlap, so clusters equal episodes; but episodes recur every few days in 2026-07 and 2026-08, and a rule that stays on through a volatile period captures all of them. Before any real rule is evaluated, add a reported-only sensitivity view with a 7 day chaining gap (a sensitivity view, not a selection criterion, and not tuned), and report how many clusters it gives per side.

