# Phase 2 plan: features, labels, validation

Written 2026-11-20 (UTC), before any feature is built and before any rule or model is evaluated. Everything this plan fixes must stay fixed once evaluation starts; changes are logged. **Items marked DECIDED were decided by the user on 2026-11-21 (see Decisions below). Items marked PROPOSAL are for you to decide; nothing marked PROPOSAL is decided until you approve it.** Facts come from the files named in brackets or from read-only counts. No model was fitted, no feature built, nothing downloaded for this plan.

## Decisions

**Decided by the user on 2026-11-21.**

1. **Frozen holdout: option B.** Holdout decision times run from 2026-08-01 00:00 UTC onward, with the end open. Development decision times end on 2026-07-31 00:00 UTC (a 24-hour embargo). Nothing on the holdout is used for fitting, thresholds or rule choice. **Caveat, plainly:** the price history including the 2026-08-22 event was already studied, so the holdout is frozen against fitting but it is not unseen. Paper trading is the only truly out-of-sample test.
2. **Primary label: a 24-hour horizon with a 30 percent adverse move**, long and short reported separately and never pooled. The secondary views, 4 hours at 20 percent and 1 hour at 20 percent, are reported but never used to select anything.
3. **Primary lead window: 1 hour.** The 15-minute and 4-hour lead windows are reported only.
4. **Kill criteria (section 11) are approved as proposed, plus one more:** a paper trading period with no risk episode shows false alarms only and must be extended.
5. **Open item for the user:** read the Binance TACUSDT contract specification for the maintenance margin and for whether liquidation uses the mark price or the last price, before any real money. Until then the plan uses the nominal liquidation distance of one third.

Everything not listed here stays a PROPOSAL: the 5-minute decision times, what each state means for you, the Stage A rule list, Stage B, the feature windows, the definition of the event time, the random gate, the first test month and the trial-log format.

## Open questions

**OPEN, not decided. An unverified hypothesis, not a finding.**

- The token cliff date is 2026-07-15 (TGE + 12 months, `src/tacgate/phase2/loaders.py`, `cliff_dates`). About 42 percent of supply (investors 16.6, advisors 3.4 and team 22.1 percent, `data/static/tokenomics.csv`) starts vesting then.
- Our bulk open interest shifts around 2026-07-12 (`bulk_metrics_history_report.md`), and our derived supply steps fall on the 16th of 2026-07, 2026-08, 2026-09 and 2026-10 (`data/static/events.csv`). The cause of either is unknown; a link to the vesting start is only a hypothesis.
- **Consequence to settle before the label builder (task 2):** development data is mostly before the cliff and the holdout (from 2026-08-01) is entirely after it, so the label counts and every result must also be reported split at 2026-07-15.
- Any rule based on calendar dates near the 16th would rest on about 4 points (four monthly steps). It must be logged as a trial and treated as weak.
- **OPEN, not decided:** for the primary 24 h / 30 percent view the holdout has exactly 4 long episodes and 5 short, and the development period has 7 long and 23 short. The holdout rule "no go below 4 episodes" is therefore at its limit for the long side, and any later data change that removes one long episode would make the long-side holdout unusable. Consequence to settle before any rule is evaluated: decide whether the long side is reported as "too few episodes for a verdict" in advance, and whether the short side alone can carry a go decision.
- **OPEN, not decided:** 17.5 percent of Bybit 1m candles have zero volume (123,561 of 707,404) with no missing minutes, so their close may be stale and `bybit_gap` may show a gap that is not a real price difference. A later option is to set the gap to NaN when Bybit volume in the window is zero; this must be logged as a trial before it is evaluated.
- **OPEN, not decided:** development data includes the listing week, where `volume_ratio` reaches about 760 and `range_24h` about 17.8. Any rule using these features may be learning from listing-week behaviour, so every later result using them must also be reported without the first 7 days after listing.
- **OPEN, not decided:** in the development test months (2025-09 to 2026-07) the primary 24 h / 30 percent view has only 5 long and 20 short episodes, and after the 2026-07-15 cliff the short side has 1. With 5 episodes even a capture of 5 of 5 has a two-sided 95 percent lower limit of about 0.48, so the plan's kill criterion (capture at least 50 percent) cannot be demonstrated on the long side. Consequence to settle before any real rule is evaluated: decide whether the long side is declared "too few for a verdict" in advance, whether the short side alone carries the decision, and how a result resting on one post-cliff episode is described.

## 1. What the gate decides

At each decision time t the gate outputs one of **stay out / caution / clear**, using only rows whose known time is at or before t (known-time rules: `gate1_summary.md`, section 2). It flags danger for holding leveraged exposure (cap 3x, isolated margin, 1% risk per trade, stop-loss at entry: `CLAUDE.md`) in the next H hours. It does not predict price direction, and it never places orders (`CLAUDE.md`: market data is read-only).

What you would do with each state (PROPOSAL): **clear**: the normal risk defaults apply; **caution**: no new entries, or new entries at a reduced size you choose (for example half), existing positions keep their stop-loss; **stay out**: no leveraged exposure, flat or spot only.

PROPOSAL: decision times are every 5 minutes (the cadence of the recorder and bulk files, and of the count table below).

## 2. The label (risk event)

At decision time t, let C_t be the close of the 1m candle that ends at t. Over the next H hours (the 1m candles that open in [t, t + H)):

- **Long risk event:** the lowest low falls to C_t x (1 - x) or lower (adverse = fall of at least x).
- **Short risk event:** the highest high rises to C_t x (1 + x) or higher (adverse = spike of at least x).

The two sides are separate labels. We measure with the 1m high and low of the **Binance perp last-price klines, which is a proxy**: mark price klines exist in the bulk archive (493 daily files) but are not downloaded (`binance_bulk_availability.md`). Liquidation engines normally act on a mark price, not on last trades; that is not verified in our sources, so the label must be re-checked once mark price klines are downloaded.

**DECIDED (Decisions, item 2): the primary label is a 24 h horizon with a 30% adverse move**, long and short separate; 4 h at 20% and 1 h at 20% are secondary views, reported only and never used to select anything. The other horizons and thresholds below (1 h, 4 h, 24 h and 10%, 20%, 30%) are counted for reference. The 30% is tied to the nominal liquidation distance at 3x isolated, which is 1/3 = 33.3% before maintenance margin and fees (simple arithmetic; the maintenance margin rate for TACUSDT is not in our data; the contract specification is an open item for the user, Decisions, item 5).

**Counts** (read-only, `src/tacgate/phase2/label_counts.py`, full per-month tables in `docs/label_counts.md`). Episodes = positive decision times merged when closer than H. 141,465 / 141,429 / 141,189 valid decision times for 1 h / 4 h / 24 h (2025-07-15 to 2026-11-18):

| Horizon | Threshold | Long: episodes (positive decision times) | Short: episodes (positive decision times) |
|---|---|---|---|
| 1 h | 10% | 115 (941) | 119 (1,281) |
| 1 h | 20% | 21 (208) | 32 (299) |
| 1 h | 30% | 7 (75) | 15 (114) |
| 4 h | 10% | 124 (3,808) | 127 (5,784) |
| 4 h | 20% | 26 (657) | 38 (1,503) |
| 4 h | 30% | 9 (278) | 20 (646) |
| 24 h | 10% | 89 (21,732) | 84 (27,029) |
| 24 h | 20% | 26 (3,950) | 40 (11,998) |
| 24 h | 30% | 11 (2,124) | 28 (6,925) |

How to read it:

- **Overlapping horizons make the samples not independent.** One fall makes about H/5 consecutive decision times positive (24 h at 30%, long: 2,124 positive decision times belong to 11 episodes, about 190 each). The episode count is the honest sample size; the decision-time count is not.
- **A 24 h label at 10% is positive 15% to 19% of the time** (share of valid decision times), so a gate built on it would be "out" for a large part of the time; at 30% and 1 h it is positive 0.05% to 0.08% of the time.
- **Episodes cluster in time.** For 4 h at 30%, long, 6 of the 9 episodes are in 2026-07 and 2026-08; the launch month 2025-07 is also busy. They are not independent regime-wise either.
- These label episodes are many more than the 7 curated big episodes in `gate1_summary.md` (2025-10-10, 2025-11-26, 2026-05-11, 2026-06-29, 2026-07-07, 2026-08-22, 2026-08-26), because the label counts every 10% to 30% move in the window, not only the named events.

## 3. Frozen holdout

**DECIDED (Decisions, item 1): option B.** No fitting, threshold or rule choice may use the holdout until the single final evaluation (it is frozen against fitting, but not unseen: see the caveat in Decisions). It is separated from the development period by an embargo of at least 24 h (the longest candidate H): development decision times end 2026-07-31 00:00 UTC and the holdout starts 2026-08-01 00:00 UTC. Episode counts below start inside the window (`docs/label_counts.md`):

| Option | 1 h 30% L / S | 4 h 20% L / S | 4 h 30% L / S | 24 h 20% L / S | 24 h 30% L / S | Curated episodes of the 7 inside |
|---|---|---|---|---|---|---|
| **A:** 2026-09-01 to the end (about 3 months) | 0 / 0 | 4 / 5 | 0 / 1 | 3 / 3 | 2 / 2 | none |
| **B:** 2026-08-01 to the end (about 4 months) | 2 / 4 | 8 / 12 | 2 / 4 | 6 / 5 | 4 / 5 | 2 (2026-08-22, 2026-08-26) |
| **C:** 2026-07-01 to the end (about 5 months) | 5 / 7 | 15 / 17 | 6 / 8 | 8 / 12 | 6 / 9 | 3 (2026-07-07, 2026-08-22, 2026-08-26) |

What each option cannot test:

- **A** is a calm period (September to mid-November): at 30% it holds 0 to 2 episodes per label, so it mostly tests false alarms. It cannot test whether the gate catches big moves, and it contains none of the 7 curated episodes.
- **B** holds 4 to 5 episodes per 30%/24 h label and two curated episodes, but those two are 4 days apart (a crash and a spike) and not independent. It cannot test the launch-period regime, and with 4 to 5 episodes even a perfect capture has a wide interval (section 4).
- **C** holds the most episodes (6 and 9 at 30%/24 h) but takes the 2026-07-07 crash out of development, leaves development with only four curated episodes (2025-10-10, 2025-11-26, 2026-05-11, 2026-06-29), and puts the 2026-07-12 shift in the bulk metrics inside the holdout, so a bulk feature could never be fitted across that regime.

**Decision: option B** (DECIDED on 2026-11-21; the recommendation made in the first draft), with the start date frozen now and the end open: data that arrives after the freeze (the recorder keeps running) joins the holdout and is genuinely unseen. Reasons: it holds a real exploit-linked crash and spike and 4 to 5 episodes at 30%/24 h; it keeps the 2026-06-29 spike and 2026-07-07 crash (and the July turbulence) in development, where 7 long and 23 short episodes at 30%/24 h remain (totals 11 and 28 minus 4 and 5); and it avoids putting the 2026-07-12 bulk-data shift in the holdout (the 2026-11-16 shift is still inside it). Its weakness is size: it can show capture of a handful of episodes at best.

## 4. Validation design

- **Expanding-window walk-forward by calendar month** inside the development period. For each test month the training data end at least H hours before the month starts (**embargo of at least H hours**), because label horizons overlap. This is our own design reasoning, not taken from the literature scan (which found no opened source for purged or embargoed validation, `literature_scan.md` section 8).
- PROPOSAL: the first test month comes after 6 months of training (2025-07 to 2025-12), so under holdout B the test months are 2026-01 to 2026-07 (7 months).
- All thresholds and any fitting come from the development period only, and for each test month only from data before its embargo.
- **Fixed metrics, decided now** (the details marked PROPOSAL are still open):
  1. **Capture rate:** the share of risk-event episodes for which caution or stay out was active in the lead window before the event. PROPOSAL: the event time b is the first breach of the threshold in the episode. The lead window is the decision times in [b - L, b - 5 min]; **DECIDED (Decisions, item 3): the primary lead is L = 1 h; L = 15 min and L = 4 h are reported only.**
  2. **Time spent:** the share of decision times in stay out and in caution.
  3. **Lead-time distribution:** minutes between the start of the continuous caution-or-stay-out run and b.
  4. **The same capture rate for a random gate with the same stay-out share.** PROPOSAL: the random gate places blocks of the same length distribution as the gate's own runs at random times, 1,000 draws, reported as mean and a 95% range.
- Report counts and exact binomial (Clopper-Pearson) 95% intervals, never a significance claim the sample cannot support. If every one of n episodes is captured, the lower end of the interval is 0.025^(1/n): n = 5: 0.48, n = 7: 0.59, n = 11: 0.72, n = 28: 0.88 (our arithmetic).
- **With about 7 curated episodes (and tens of clustered label episodes), no result can prove the gate works.** Development results show only what the gate would have done; walk-forward and paper trading (CLAUDE.md, Phase 5, 8+ weeks) must carry the weight.

## 5. Trial log

`docs/trial_log.csv` (header only for now: trial_id, date_utc, family, description, horizon_h, threshold, feature_set, development_result_reference, notes). **Every variant (rule, threshold, horizon, feature set) is written to it BEFORE it is evaluated.** The number of trials is reported with every result, and the choice of label (horizon and threshold) counts as trials too. PROPOSAL: trial_id as T0001, T0002, and any result table must state "N trials so far".

## 6. First feature set

Only from sources whose known times are decided (`gate1_summary.md`). All window lengths below are PROPOSALS.

- **Binance 1m klines (known at candle close):** realized volatility over several trailing windows (for example 15 min, 1 h, 4 h, 24 h), high-low range, returns, volume spikes against a trailing median, distance from the trailing high and low, and **taker flow derived from the klines** (taker_buy_base_volume over volume; decided on 2026-11-21 instead of the bulk taker ratio, `bulk_metrics_history_report.md`).
- **Binance versus Bybit price gap** (both klines, known at candle close): the close difference in basis points.
- **Funding (known at fundingTime):** the level and its position against its own expanding history (rank among past values only).
- **Static files:** time since TGE (2025-07-15), and events used only at or after their known_at_utc; rows with an empty known_at_utc are never used.
- **DeFiLlama and CoinGecko (known at timestamp + 24 h):** only under the 2% rule (a price more than 2% from Binance is excluded; CoinGecko only for market cap and volume).
- **Bulk open interest and long/short ratios: test candidates only**, with the unverified-era flag (before 2026-07-12), bad rows flagged missing and never filled, a day lag (open interest known at our timestamp + 10 minutes only from 2026-10-19, otherwise day end + 24 h; ratios day end + 24 h), and a per-regime stability test before any use (`bulk_equivalence_report.md`, `bulk_metrics_history_report.md`).
- **Not available yet:** bulk depth (`bookDepth`), mark, index and premium klines are not downloaded; our own depth snapshot has 2.1 days.

## 7. Mandatory look-ahead test (a rule for every feature)

A feature value at t must not change if the input data are truncated at t. **Rule:** every feature builder gets an automated test that (a) builds the feature on the full data and on data cut to rows with known_at <= t, for many t including all t of a small fixture, and checks the two values at t are identical (to 1e-12); (b) replaces all data after t with arbitrary values and checks the value at t is unchanged; (c) checks that rows with known_at > t are absent. Trailing windows only; expanding percentiles use past values only. A feature that fails is not used until fixed.

## 8. Stage A rules (hypotheses to test) and Gate 2 baselines

From `literature_scan.md`, section A (evidence level as given there). They are hypotheses, not rules to adopt, and every variant is counted.

| # | Rule | Evidence there | Buildable from data we have now? |
|---|---|---|---|
| 1 | After a liquidation cascade or a loss of book depth, caution or stay out until depth recovers | moderate to weak | **Wait** for depth (bulk `bookDepth` not downloaded). A price-based cascade proxy (large recent 1m moves and volume) can be built now, but it is a different rule and must be logged as such |
| 2 | Thin order book relative to our size: caution or stay out | weak to moderate | **Wait** (depth) |
| 3 | After an exploit becomes known, stay out for a window | moderate | Buildable, but only one usable exploit exists (2026-08-22, known_at 2026-08-24 08:50; the May exploit has an empty known_at and is never used): **cannot be tested** |
| 4 | Flag funding that is extreme against its own history | weak | **Now** |
| 5 | Flag when the reference price disagrees with another venue or an aggregator | moderate (data quality) | **Now** for Binance vs Bybit; aggregators only daily under the 2% rule |
| 6 | Low leverage cap | supports the existing 3x cap | Not a gate signal |
| 7 | Recent realized volatility as a regime flag | weak | **Now** |
| 8 | Caution around large unlocks | weak | **Wait**: no unlock calendar |
| 9 | Taker order-flow variance compression | very weak | **Now**, from klines-derived taker flow (the source used 5-minute data; ours is 1m) |

**Gate 2 baselines:** a realized-volatility rule, a funding-extreme rule, always stay out, no gate (always clear), and a random gate with the same stay-out share (`literature_scan.md` section B; the last three are our own bookends).

## 9. Stage B

A logistic regression, and only if Stage A leaves a clear gap (PROPOSAL: after the development walk-forward, the best Stage A rule misses more than half of the 30%/24 h episodes at a stay-out share of 25% or less). It must beat Stage A on the frozen holdout, and be evaluated once. **With so few episodes an ML model may not be justified at all:** the number of independent episodes in development (tens, clustered) is smaller than the number of candidate features, so a model could fit the history by construction. If we cannot say why a model should work beyond fitting those episodes, we stop at Stage A.

## 10. Ordered task list (one branch each; each must show its output before the next starts)

0. **Approve and freeze** the remaining PROPOSALs in this plan (random gate, trial-log format, feature windows and the other items listed at the end of Decisions) in a short decision record. The holdout, the primary label, the lead window and the kill criteria were decided on 2026-11-21 (Decisions). *Shows:* your written decisions.
1. `feature/phase2-loaders`: loader for the daily and bulk data with the known-time and bad-row rules. *Shows:* the flagged-row counts equal the Gate 1 numbers (for example 25 open-interest rows at or below zero, 3 missing slots), and no row is filled.
2. `feature/phase2-labels`: label builder (long and short, chosen horizons and thresholds). *Shows:* it reproduces `docs/label_counts.md` exactly.
3. `feature/phase2-features`: klines-based features first, each with its look-ahead test. *Shows:* all look-ahead tests pass; no feature touches the holdout.
4. `feature/phase2-harness`: walk-forward harness, the fixed metrics, the random gate, confidence intervals, trial-log writer. *Shows:* it runs on a trivial gate ("always stay out", "no gate") and gives the expected metrics.
5. `feature/phase2-baselines`: the Gate 2 baselines on the development period. *Shows:* baseline results with the trial count.
6. `feature/phase2-stage-a`: the buildable Stage A rules (4, 5, 7, 9, and the price-based cascade proxy). *Shows:* development results next to the baselines, trial count stated; nothing on the holdout.
7. Optional, own branches: download and check mark, index and premium klines and `bookDepth`; re-check the label against mark price; add rules 1 and 2. *Shows:* the usual Gate 1 style report for each file before use.
8. `feature/phase2-stage-b`: only if section 9 allows it.
9. The single frozen-holdout evaluation, then Phase 5 paper trading (8+ weeks).

## 11. Kill criteria (DECIDED)

The written conditions under which we stop and do not trade. **Approved by the user on 2026-11-21 as proposed (Decisions, item 4); the numbers were arbitrary choices that you have now approved.**

- **Data:** a feature that fails its look-ahead test and cannot be fixed is dropped; if the recorder or a key source is down for more than 7 days, evaluation pauses.
- **Development:** if the best Stage A rule on the development walk-forward does not capture at least 50% of the 30%/24 h episodes while spending at most 25% of the time in caution or stay out, or does not beat the random gate's capture by at least 20 percentage points, we stop and do not build Stage B.
- **Trials:** if more than 50 trials are logged before the holdout is evaluated, every result is reported as exploratory only.
- **Holdout (evaluated once):** if capture is below the random gate's capture plus 10 percentage points, or the holdout holds fewer than 4 episodes for the label used, there is no go.
- **Paper trading (8+ weeks):** a paper drawdown beyond 10% of paper capital, or more than 50% of the time in stay out, stops the project.
- **Paper trading with no risk episode (added 2026-11-21):** a paper trading period in which no risk episode occurs shows false alarms only; it proves nothing about capture and must be extended.
- **Non-code:** the legality and tax treatment of crypto futures in India (an open item in `gate1_summary.md`) must be resolved before any real money.

## What I could not source

- Whether the exchange liquidates on mark or last price for TACUSDT, and the maintenance margin rate for TACUSDT (so the 1/3 liquidation distance is nominal). The user will read the contract specification before any real money (Decisions, item 5).
- Any rule of thumb for how many episodes a model needs; none is given here because none was opened in `literature_scan.md`.
- A statistical power figure for any test (not given, by design).
