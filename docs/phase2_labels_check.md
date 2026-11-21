# Phase 2 label builder check

Generated 2026-11-21 (UTC) by `python -m tacgate.phase2.labels`. Read-only. No feature, no model, no selection. The builder (`src/tacgate/phase2/labels.py`) is the only implementation of the label: `label_counts.py` now calls it, so the count table and the label table cannot disagree. Last-price 1m klines are used (mark klines are not downloaded yet).

## 1. Does the builder reproduce docs/label_counts.md?

Every cell of the Overall table: positive 5-minute decision times and episodes, builder output against the document.

| Horizon | Threshold | Side | Positive decision times (doc / builder) | Episodes (doc / builder) | Result |
|---|---|---|---|---|---|
| 1 h | 10% | long | 941 / 941 | 115 / 115 | match |
| 1 h | 10% | short | 1,281 / 1,281 | 119 / 119 | match |
| 1 h | 20% | long | 208 / 208 | 21 / 21 | match |
| 1 h | 20% | short | 299 / 299 | 32 / 32 | match |
| 1 h | 30% | long | 75 / 75 | 7 / 7 | match |
| 1 h | 30% | short | 114 / 114 | 15 / 15 | match |
| 4 h | 10% | long | 3,808 / 3,808 | 124 / 124 | match |
| 4 h | 10% | short | 5,784 / 5,784 | 127 / 127 | match |
| 4 h | 20% | long | 657 / 657 | 26 / 26 | match |
| 4 h | 20% | short | 1,503 / 1,503 | 38 / 38 | match |
| 4 h | 30% | long | 278 / 278 | 9 / 9 | match |
| 4 h | 30% | short | 646 / 646 | 20 / 20 | match |
| 24 h | 10% | long | 21,732 / 21,732 | 89 / 89 | match |
| 24 h | 10% | short | 27,029 / 27,029 | 84 / 84 | match |
| 24 h | 20% | long | 3,950 / 3,950 | 26 / 26 | match |
| 24 h | 20% | short | 11,998 / 11,998 | 40 / 40 | match |
| 24 h | 30% | long | 2,124 / 2,124 | 11 / 11 | match |
| 24 h | 30% | short | 6,925 / 6,925 | 28 / 28 | match |

Valid decision times (complete forward window): 1 h: doc 141,465 / builder 141,465 (match); 4 h: doc 141,429 / builder 141,429 (match); 24 h: doc 141,189 / builder 141,189 (match).

**All cells match.**

## 2. The same counts, split

An episode is counted in the part where it STARTS (its first positive decision time), found on the whole series, so one episode is never split. Positive decision times are counted per part by their own time. Development ends 2026-07-31 00:00 UTC; the 24 hours in between are the embargo (in neither); the holdout starts 2026-08-01 00:00 UTC. Cliff date: 2026-07-15 (an unverified hypothesis; report only). Data starts 2025-07-15. Each cell reads: episodes (positive decision times). A part with fewer than 4 episodes is marked **FEW**.

### 24 h / 30%

| Part | Valid decision times | Long | Short |
|---|---|---|---|
| development | 109,602 | 7 (1,317) | 23 (5,430) |
| embargo | 287 | 0 (0) | 0 (0) |
| holdout | 31,300 | 4 (807) | 5 (1,495) |
| before the cliff | 104,993 | 7 (1,317) | 22 (5,413) |
| after the cliff | 36,196 | 4 (807) | 6 (1,512) |

| Month | Valid decision times | Long | Short |
|---|---|---|---|
| 2025-07 | 4,769 | 2 (123) **FEW** | 2 (259) **FEW** |
| 2025-08 | 8,928 | 0 (0) **FEW** | 1 (265) **FEW** |
| 2025-09 | 8,640 | 0 (0) **FEW** | 0 (0) **FEW** |
| 2025-10 | 8,928 | 1 (290) **FEW** | 4 (689) |
| 2025-11 | 8,640 | 1 (12) **FEW** | 3 (384) **FEW** |
| 2025-12 | 8,928 | 0 (0) **FEW** | 1 (270) **FEW** |
| 2026-01 | 8,928 | 0 (0) **FEW** | 1 (244) **FEW** |
| 2026-02 | 8,064 | 0 (0) **FEW** | 0 (0) **FEW** |
| 2026-03 | 8,928 | 0 (0) **FEW** | 1 (60) **FEW** |
| 2026-04 | 8,640 | 0 (0) **FEW** | 3 (1,108) **FEW** |
| 2026-05 | 8,928 | 0 (0) **FEW** | 1 (663) **FEW** |
| 2026-06 | 8,640 | 1 (74) **FEW** | 2 (591) **FEW** |
| 2026-07 | 8,928 | 2 (818) **FEW** | 4 (897) |
| 2026-08 | 8,928 | 2 (633) **FEW** | 3 (954) **FEW** |
| 2026-09 | 8,640 | 1 (171) **FEW** | 1 (1) **FEW** |
| 2026-10 | 8,928 | 0 (0) **FEW** | 0 (0) **FEW** |
| 2026-11 | 4,804 | 1 (3) **FEW** | 1 (540) **FEW** |

### 4 h / 20%

| Part | Valid decision times | Long | Short |
|---|---|---|---|
| development | 109,602 | 18 (433) | 26 (1,058) |
| embargo | 287 | 0 (0) | 0 (0) |
| holdout | 31,540 | 8 (224) | 12 (445) |
| before the cliff | 104,993 | 18 (433) | 26 (1,058) |
| after the cliff | 36,436 | 8 (224) | 12 (445) |

| Month | Valid decision times | Long | Short |
|---|---|---|---|
| 2025-07 | 4,769 | 3 (28) **FEW** | 3 (77) **FEW** |
| 2025-08 | 8,928 | 0 (0) **FEW** | 1 (46) **FEW** |
| 2025-09 | 8,640 | 0 (0) **FEW** | 0 (0) **FEW** |
| 2025-10 | 8,928 | 3 (71) **FEW** | 5 (165) |
| 2025-11 | 8,640 | 2 (21) **FEW** | 1 (66) **FEW** |
| 2025-12 | 8,928 | 1 (8) **FEW** | 1 (51) **FEW** |
| 2026-01 | 8,928 | 1 (48) **FEW** | 1 (48) **FEW** |
| 2026-02 | 8,064 | 0 (0) **FEW** | 0 (0) **FEW** |
| 2026-03 | 8,928 | 1 (2) **FEW** | 1 (48) **FEW** |
| 2026-04 | 8,640 | 0 (0) **FEW** | 2 (92) **FEW** |
| 2026-05 | 8,928 | 0 (0) **FEW** | 4 (114) |
| 2026-06 | 8,640 | 0 (0) **FEW** | 2 (96) **FEW** |
| 2026-07 | 8,928 | 7 (255) | 5 (255) |
| 2026-08 | 8,928 | 4 (154) | 7 (337) |
| 2026-09 | 8,640 | 1 (48) **FEW** | 1 (4) **FEW** |
| 2026-10 | 8,928 | 0 (0) **FEW** | 0 (0) **FEW** |
| 2026-11 | 5,044 | 3 (22) **FEW** | 4 (104) |

### 1 h / 20%

| Part | Valid decision times | Long | Short |
|---|---|---|---|
| development | 109,602 | 14 (140) | 22 (210) |
| embargo | 287 | 0 (0) | 0 (0) |
| holdout | 31,576 | 7 (68) | 10 (89) |
| before the cliff | 104,993 | 14 (140) | 22 (210) |
| after the cliff | 36,472 | 7 (68) | 10 (89) |

| Month | Valid decision times | Long | Short |
|---|---|---|---|
| 2025-07 | 4,769 | 2 (15) **FEW** | 2 (13) **FEW** |
| 2025-08 | 8,928 | 0 (0) **FEW** | 1 (9) **FEW** |
| 2025-09 | 8,640 | 0 (0) **FEW** | 0 (0) **FEW** |
| 2025-10 | 8,928 | 3 (27) **FEW** | 2 (25) **FEW** |
| 2025-11 | 8,640 | 2 (14) **FEW** | 1 (26) **FEW** |
| 2025-12 | 8,928 | 1 (8) **FEW** | 1 (5) **FEW** |
| 2026-01 | 8,928 | 1 (12) **FEW** | 1 (12) **FEW** |
| 2026-02 | 8,064 | 0 (0) **FEW** | 0 (0) **FEW** |
| 2026-03 | 8,928 | 0 (0) **FEW** | 1 (12) **FEW** |
| 2026-04 | 8,640 | 0 (0) **FEW** | 2 (19) **FEW** |
| 2026-05 | 8,928 | 0 (0) **FEW** | 0 (0) **FEW** |
| 2026-06 | 8,640 | 0 (0) **FEW** | 2 (34) **FEW** |
| 2026-07 | 8,928 | 5 (64) | 9 (55) |
| 2026-08 | 8,928 | 5 (51) | 8 (83) |
| 2026-09 | 8,640 | 1 (12) **FEW** | 1 (4) **FEW** |
| 2026-10 | 8,928 | 0 (0) **FEW** | 0 (0) **FEW** |
| 2026-11 | 5,080 | 1 (5) **FEW** | 1 (2) **FEW** |

## 3. Where there are too few episodes

Plainly: the parts below have fewer than 4 episodes (development, holdout and cliff parts only; single calendar months are marked **FEW** in the tables above and most are thin). Nothing can be learned or tested honestly from a part with so few independent events.

- none

## Decisions

**Already decided by the user (docs/phase2_plan.md, 2026-11-21):**

- Frozen holdout, option B: development decision times end 2026-07-31 00:00 UTC, a 24 hour embargo, holdout from 2026-08-01 00:00 UTC.
- Primary label: 24 hours / 30 percent, long and short separate. Secondary views (reported only): 4 hours / 20 percent and 1 hour / 20 percent.
- Long and short are never pooled. A label is known only after its whole window has passed. No fill, impute or interpolation.
- The count table and the builder are one implementation (label_counts.py calls labels.py).

**OPEN (not decided):**

- Whether the cliff date 2026-07-15 becomes part of the validation design, or stays a report-only split (it is an unverified hypothesis).
- What to do about parts with fewer than 4 episodes (merge, drop, or report only).
- Whether to use mark-price klines instead of the last-price klines the labels use now (mark klines are not downloaded yet).

