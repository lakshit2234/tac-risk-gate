"""Phase 2 Gate 2 baseline rules (docs/literature_scan.md, Gate 2 baselines). Four plain percentile rules in the walk-forward interface.

FIXED in advance by the user on 2026-11-22 (proposed by Claude, approved by the user); every value is a named constant and nothing else is tried:
  * cut-offs are percentiles of the feature over the TRAINING rows only, computed in fit(train_rows) and fixed for the whole test month;
  * high-risk tail: state 2 (stay out) at or above the 95th percentile, state 1 (caution) at or above the 90th, else 0;
    low-risk tail: state 2 at or below the 5th percentile, state 1 at or below the 10th, else 0;
  * a NaN feature gives state 0 (clear); the rule counts those decision times.

  R1 realized_volatility  x = rv_1h; high is risky; the same state for long and short
  R2 funding_extreme      x = the latest funding rate known at t (funding known at fundingTime); long: high is risky; short: low is risky
  R3 exchange_gap         x = bybit_gap_abs_max_1h; high is risky; the same state for long and short
  R4 price_cascade        long: x = drawdown_1h, low is risky; short: x = runup_1h, high is risky
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from tacgate.phase2 import loaders as ld
from tacgate.phase2 import walkforward as wf

# ------------------------------------------------------------ FIXED values ---
PCT_STAY_OUT_HIGH = 95  # high tail: state 2 at or above this percentile of the training rows
PCT_CAUTION_HIGH = 90  # high tail: state 1 at or above this percentile
PCT_STAY_OUT_LOW = 5  # low tail: state 2 at or below this percentile
PCT_CAUTION_LOW = 10  # low tail: state 1 at or below this percentile
HIGH, LOW = "high", "low"
FUNDING_COLUMN = "funding_rate"  # added to the features by add_funding: the latest funding rate known at t
TRIAL_FAMILY = "stage_a_baseline"
RULE_NAMES = ("realized_volatility", "funding_extreme", "exchange_gap", "price_cascade")
FIXED_ON = "2026-11-22"


# ----------------------------------------------------------------- funding ---

def latest_funding(decision_ms: np.ndarray, funding: pd.DataFrame) -> np.ndarray:
    """The latest funding rate known at each decision time: the newest row with known_at_ms <= t (known at fundingTime, never earlier). NaN before the first one.
    Rows with a bad value (a missing rate or mark price) are skipped."""
    f = funding.loc[~funding["bad_value"], ["known_at_ms", "fundingRate"]].sort_values("known_at_ms")
    left = pd.DataFrame({"decision_ms": np.asarray(decision_ms, dtype="int64")})
    order = left["decision_ms"].argsort(kind="stable").to_numpy()
    merged = pd.merge_asof(left.iloc[order], f, left_on="decision_ms", right_on="known_at_ms", direction="backward", allow_exact_matches=True)
    out = np.empty(len(left))
    out[order] = merged["fundingRate"].to_numpy(dtype="float64")
    return out


def add_funding(ds: wf.Dataset, funding: pd.DataFrame) -> wf.Dataset:
    """The same dataset with a `funding_rate` feature column (the latest funding rate known at each decision time)."""
    feats = ds.features.copy()
    feats[FUNDING_COLUMN] = latest_funding(feats["decision_ms"].to_numpy(), funding)
    return wf.Dataset(feats, ds.labels, ds.minutes, ds.includes_holdout)


# ------------------------------------------------------------------- rules ---

class PercentileRule:
    """One feature (and one tail) per side. fit() takes the cut-offs from the training rows only; calling the rule never changes them."""

    def __init__(self, name: str, long_feature: str, long_tail: str, short_feature: str, short_tail: str):
        self.name = name
        self.spec = {"long": (long_feature, long_tail), "short": (short_feature, short_tail)}
        self.cutoffs: dict = {}
        self.history: list[dict] = []  # one entry per fit (one per test month)
        self.n_calls = 0
        self.n_nan = {"long": 0, "short": 0}

    @property
    def features(self) -> list[str]:
        return sorted({f for f, _ in self.spec.values()})

    def fit(self, train: pd.DataFrame) -> None:
        if "label_known_at_ms" not in train.columns:
            raise ValueError("fit needs the training rows from the harness (with label_known_at_ms)")
        self.cutoffs = {}
        entry = {"n_train_rows": int(len(train))}
        for side, (feat, tail) in self.spec.items():
            if feat not in train.columns:
                raise KeyError(f"training rows have no {feat!r} column")
            x = train[feat].to_numpy(dtype="float64")
            x = x[np.isfinite(x)]
            if len(x) == 0:
                self.cutoffs[side] = None
            else:
                hi, lo = (PCT_STAY_OUT_HIGH, PCT_CAUTION_HIGH) if tail == HIGH else (PCT_STAY_OUT_LOW, PCT_CAUTION_LOW)
                self.cutoffs[side] = (float(np.percentile(x, hi)), float(np.percentile(x, lo)))  # (stay-out cut-off, caution cut-off)
            entry[side] = {"feature": feat, "tail": tail, "n_finite": int(len(x)), "stay_out_cutoff": None if self.cutoffs[side] is None else self.cutoffs[side][0],
                           "caution_cutoff": None if self.cutoffs[side] is None else self.cutoffs[side][1]}
        self.history.append(entry)

    def _state(self, side: str, row) -> int:
        feat, tail = self.spec[side]
        x = row[feat]
        if x is None or not np.isfinite(x):
            self.n_nan[side] += 1
            return 0
        cut = self.cutoffs.get(side)
        if cut is None:
            return 0
        if tail == HIGH:
            return 2 if x >= cut[0] else 1 if x >= cut[1] else 0
        return 2 if x <= cut[0] else 1 if x <= cut[1] else 0

    def __call__(self, row) -> tuple[int, int]:
        if not self.cutoffs:
            raise RuntimeError("call fit(train_rows) before the rule is used")
        self.n_calls += 1
        return self._state("long", row), self._state("short", row)

    def info(self) -> dict:
        return {"features": self.features, "spec": {s: list(v) for s, v in self.spec.items()}, "n_decision_times": self.n_calls,
                "n_nan_state_clear": dict(self.n_nan), "fits": self.history}


def make_rules() -> list[PercentileRule]:
    return [PercentileRule("realized_volatility", "rv_1h", HIGH, "rv_1h", HIGH),
            PercentileRule("funding_extreme", FUNDING_COLUMN, HIGH, FUNDING_COLUMN, LOW),
            PercentileRule("exchange_gap", "bybit_gap_abs_max_1h", HIGH, "bybit_gap_abs_max_1h", HIGH),
            PercentileRule("price_cascade", "drawdown_1h", LOW, "runup_1h", HIGH)]


# ---------------------------------------------------------------- the run ---

def _baseline_logged(trial_log: Path) -> bool:
    p = Path(trial_log)
    if not p.exists():
        return False
    with open(p, encoding="utf-8", newline="") as f:
        return any(r["family"] == TRIAL_FAMILY for r in csv.DictReader(f))


def run_baselines(data_dir: Path, trial_log: Path = wf.TRIAL_LOG, results_dir: Path = wf.RESULTS_DIR) -> list[dict]:
    """Log four trials (one per rule), then evaluate each on the development period only. Never touches the holdout."""
    if _baseline_logged(trial_log):
        raise wf.HarnessError("the stage_a_baseline trials are already in the trial log; they are logged once")
    data_dir = Path(data_dir)
    b = ld.load_klines(data_dir / "binance_TACUSDT_1m.csv", "binance")
    y = ld.load_klines(data_dir / "bybit_TACUSDT_1m.csv", "bybit")
    fu = ld.load_funding(data_dir / "binance_TACUSDT_funding.csv")
    ds = add_funding(wf.build_dataset(b, y), fu)  # development dataset: klines are cut before the holdout first
    rules = make_rules()
    desc = {"realized_volatility": "R1 rv_1h: stay out at or above the 95th percentile, caution at or above the 90th; same state for long and short",
            "funding_extreme": "R2 funding rate: long high is risky (95th/90th), short low is risky (5th/10th)",
            "exchange_gap": "R3 bybit_gap_abs_max_1h: stay out at or above the 95th percentile, caution at or above the 90th; same state for long and short",
            "price_cascade": "R4 long: drawdown_1h low is risky (5th/10th); short: runup_1h high is risky (95th/90th)"}
    ids = [wf.append_trial(TRIAL_FAMILY, desc[r.name], wf.PRIMARY_VIEW[0], wf.PRIMARY_VIEW[1], "+".join(r.features),
                           notes=f"Gate 2 baseline, fixed {FIXED_ON}; development period only", path=trial_log) for r in rules]
    out = []
    for r, tid in zip(rules, ids):
        res = wf.evaluate(r, tid, ds, trial_log=trial_log, results_dir=results_dir, write=False)
        res["rule_info"] = r.info()
        res["result_file"] = str(wf._write(res, results_dir, tid))
        out.append(res)
    return out


# ------------------------------------------------------------------ report ---

LABELS = {"realized_volatility": "R1 realized_volatility", "funding_extreme": "R2 funding_extreme", "exchange_gap": "R3 exchange_gap", "price_cascade": "R4 price_cascade",
          "always_stay_out": "always stay out", "never": "never", "random": "random"}
PK = wf.view_key(wf.PRIMARY_VIEW)
LEAD = f"{wf.PRIMARY_LEAD_MIN}min"


def _cell(res: dict, side: str, view: str = PK, lead: str = LEAD, alarm: str = "stay_out", part: str = "all") -> dict:
    return res["metrics"]["views"][view][side][lead][alarm][part]


def _row(res: dict, side: str, part: str = "all", view: str = PK, lead: str = LEAD, alarm: str = "stay_out", nan: bool = False) -> str:
    c, sh = _cell(res, side, view, lead, alarm, part), res["metrics"]["shares"][side][part]
    nan_txt = ""
    if nan:
        n = res.get("rule_info", {}).get("n_nan_state_clear", {}).get(side)
        nan_txt = f" {'-' if n is None else format(n, ',')} |"
    return (f"| {LABELS.get(res['rule'], res['rule'])} | {c['episodes']} | {wf._fmt_rate(c)} | {wf._fmt_rand(c)} | {wf._pc(sh['stay_out'])} | {wf._pc(sh['caution'])} | "
            f"{wf._fmt_lead(c)} |{nan_txt} {c['verdict'] or 'descriptive only'} |")


HEAD = "| Gate | Episodes | Capture rate (95% interval) | Random gate: median [2.5%, 97.5%] | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |"
SEP = "|---|---|---|---|---|---|---|---|"
HEAD_NAN = HEAD.replace(" Verdict |", " NaN decision times (state 0) | Verdict |")
SEP_NAN = SEP + "---|"


def render_report(anchors: list[dict], rules: list[dict]) -> str:
    allr = rules + anchors
    n_trials = max(r["trials_so_far"] for r in allr)
    months = rules[0]["test_months"]
    ndt = rules[0]["metrics"]["n_decision_times"]
    L = ["# Phase 2 Gate 2 baseline rules (descriptive)", "",
         f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d')} (UTC) by `python -m tacgate.phase2.rules_baseline`. Development period only (decision times up to 2026-07-31 00:00 UTC); "
         f"the holdout was not read or evaluated (`docs/holdout_used.txt` {'EXISTS' if wf.HOLDOUT_LOCK.exists() else 'does not exist'}). Trials so far: {n_trials}"
         f"{' (more than 50: exploratory only)' if n_trials > wf.TRIAL_WARN_AFTER else ''}.", "",
         "**What this is.** A description of what four plain percentile rules would have done on the development data, next to three anchors. **No rule is chosen. No result is a claim that a gate works.** "
         "With 5 long and 20 short episodes in the primary view (24 h, 30 percent) the intervals are wide and most differences between rules are inside them. "
         "R4 reacts during the move, so its lead time is expected to be near zero; a short lead time there is the rule working as built, not a weakness of the data.", "",
         "## 1. The four rules and their fixed values", "",
         f"Fixed in advance by the user on {FIXED_ON} (proposed by Claude, approved by the user). Each value is a named constant in `src/tacgate/phase2/rules_baseline.py`; nothing else was tried.", "",
         f"- Cut-offs are percentiles of the feature over the training rows only (rows whose label is known at or before the start of the test month, enforced by the harness), computed in `fit` and fixed for the whole test month.",
         f"- High tail: state 2 (stay out) at or above the {PCT_STAY_OUT_HIGH}th percentile, state 1 (caution) at or above the {PCT_CAUTION_HIGH}th, else 0. "
         f"Low tail: state 2 at or below the {PCT_STAY_OUT_LOW}th percentile, state 1 at or below the {PCT_CAUTION_LOW}th, else 0.",
         "- A NaN feature gives state 0 (clear); the decision times where that happened are counted in section 4.", "",
         "| Rule | Long side | Short side |", "|---|---|---|",
         "| R1 realized_volatility | `rv_1h`, high is risky | `rv_1h`, high is risky (same state as long) |",
         "| R2 funding_extreme | latest funding rate known at t, high is risky | latest funding rate known at t, low is risky |",
         "| R3 exchange_gap | `bybit_gap_abs_max_1h`, high is risky | `bybit_gap_abs_max_1h`, high is risky (same state as long) |",
         "| R4 price_cascade | `drawdown_1h`, low is risky | `runup_1h`, high is risky |", "",
         "Funding is the latest rate whose fundingTime is at or before t (`loaders.load_funding`: known at fundingTime), rows with a missing rate or mark price skipped; before the first funding row it is NaN.", "",
         "## 2. What was run", "",
         f"Four trials were logged first (`{'`, `'.join(r['trial_id'] for r in rules)}`, family `{TRIAL_FAMILY}`, horizon 24 h, threshold 0.3), then each rule was evaluated with the walk-forward harness over the test months "
         f"{months[0]} to {months[-1]} ({ndt:,} decision times) with the harness's fixed metrics, random gate and splits. The three anchors are the harness trials "
         f"`{'`, `'.join(r['trial_id'] for r in anchors)}`. Episodes in the test period: " + "; ".join(
             f"{wf.view_key(v).replace('_', ' / ').replace('pct', ' percent')}: {rules[0]['episodes'][wf.view_key(v) + '_long']} long, {rules[0]['episodes'][wf.view_key(v) + '_short']} short" for v in wf.VIEWS) + ".", "",
         f"## 3. Comparison: primary view {PK}, lead 60 min, alarm = stay out, whole test period", "",
         "Capture rate = captured / episodes. The random gate is the gate's own alarm series shifted circularly (1,000 shifts): what the same amount of stay-out time gives by chance. "
         "The verdict column only says where the rate sits against that range, or TOO FEW; it is not a significance claim.", ""]
    for side in wf.SIDES:
        L += [f"### {side.capitalize()} side", "", HEAD_NAN, SEP_NAN] + [_row(r, side, nan=True) for r in allr] + [""]
    L += ["## 4. NaN decision times per rule", "",
          "Decision times where the feature was NaN and the state was forced to 0 (clear), over all test decision times:", "",
          "| Rule | Test decision times | NaN, long side | NaN, short side | Share, long | Share, short |", "|---|---|---|---|---|---|"]
    for r in rules:
        i = r["rule_info"]
        n = i["n_decision_times"]
        L.append(f"| {LABELS[r['rule']]} | {n:,} | {i['n_nan_state_clear']['long']:,} | {i['n_nan_state_clear']['short']:,} | "
                 f"{100 * i['n_nan_state_clear']['long'] / n:.2f}% | {100 * i['n_nan_state_clear']['short'] / n:.2f}% |")
    L += ["", "The test months start on 2025-09-01, so the feature warm-up at the start of the data (the first hour, day or 7 days) is in the training rows, not in the test period. "
          "R3 has NaN decision times only where Bybit data are missing in the last hour; R2 only before the first usable funding row.", "",
          "## 5. Each rule on its own", "",
          "Primary view, lead 60 min, stay out. The splits are the harness's: before and after the 2026-07-15 cliff, and without the first 7 days after listing "
          "(that week is never in a test month, so that row equals the whole period). Then the other lead windows and the secondary view caution or stay out.", ""]
    for r in rules:
        L += [f"### {LABELS[r['rule']]}", ""]
        for side in wf.SIDES:
            L += [f"**{side.capitalize()} side: splits**", "", HEAD, SEP]
            for part in r["metrics"]["shares"][side]:
                L.append(_row(r, side, part).replace(f"| {LABELS[r['rule']]} |", f"| {part} |", 1))
            L += ["", f"**{side.capitalize()} side: other lead windows and caution or stay out (whole period)**", "",
                  "| View | Capture rate | Random gate | Stay-out or caution-or-stay-out share | Lead time of captured |", "|---|---|---|---|---|"]
            for lead, alarm, share_key in (("15min", "stay_out", "stay_out"), ("240min", "stay_out", "stay_out"), (LEAD, "caution_or_stay_out", "caution_or_stay_out")):
                c = _cell(r, side, lead=lead, alarm=alarm)
                sh = r["metrics"]["shares"][side]["all"][share_key]
                L.append(f"| lead {lead.replace('min', ' min')}, {alarm.replace('_', ' ')} | {wf._fmt_rate(c)} | {wf._fmt_rand(c)} | {wf._pc(sh)} | {wf._fmt_lead(c)} |")
            L.append("")
    L += ["## 6. Reported-only views (never used to select): lead 60 min, stay out, whole test period", "",
          "| Rule | View | Side | Episodes | Capture rate | Random gate | Stay-out share |", "|---|---|---|---|---|---|---|"]
    for r in rules:
        for v in wf.REPORTED_VIEWS:
            for side in wf.SIDES:
                c = _cell(r, side, view=wf.view_key(v))
                L.append(f"| {LABELS[r['rule']]} | {wf.view_key(v).replace('_', ' / ').replace('pct', ' percent')} | {side} | {c['episodes']} | {wf._fmt_rate(c)} | {wf._fmt_rand(c)} | "
                         f"{wf._pc(r['metrics']['shares'][side]['all']['stay_out'])} |")
    L += ["", "## 7. Cut-offs (first and last test month)", "",
          "| Rule | Side | Feature, tail | Month | Training rows | Stay-out cut-off | Caution cut-off |", "|---|---|---|---|---|---|---|"]
    for r in rules:
        fits = r["rule_info"]["fits"]
        for side in wf.SIDES:
            for k in (0, len(fits) - 1):
                f = fits[k][side]
                co = lambda x: "-" if x is None else f"{x:.6g}"  # noqa: E731
                L.append(f"| {LABELS[r['rule']]} | {side} | `{f['feature']}`, {f['tail']} | {months[k]} | {fits[k]['n_train_rows']:,} | {co(f['stay_out_cutoff'])} | {co(f['caution_cutoff'])} |")
    too_few = []
    for r in rules:
        for v in wf.VIEWS:
            for side in wf.SIDES:
                for part in r["metrics"]["shares"][side]:
                    c = _cell(r, side, view=wf.view_key(v), part=part)
                    if c["episodes"] < wf.MIN_EPISODES:
                        too_few.append((wf.view_key(v).replace('_', ' / ').replace('pct', ' percent'), side, part, c["episodes"]))
    seen = sorted(set(too_few))
    L += ["", "## 8. Where a part is TOO FEW (fewer than 4 episodes)", "",
          "No verdict is printed for these parts. The episodes are the same for every gate:", ""]
    L += [f"- {v}, {s}, {p}: {n} episode(s)" for v, s, p, n in seen] or ["- none"]
    by = {r["rule"]: r for r in rules}
    r2s = by["funding_extreme"]["metrics"]["shares"]["short"]["all"]
    r2l = by["funding_extreme"]["metrics"]["shares"]["long"]["all"]
    r4l, r4s = _cell(by["price_cascade"], "long"), _cell(by["price_cascade"], "short")
    L += ["", "## 9. Reading the numbers (descriptive only)", "",
          f"- **Stay-out share against the percentile.** R1, R3 and R4 sit in stay out about 5 to 9 percent of the time, as a 95th (or 5th) percentile cut-off suggests. "
          f"R2 does not: its short side sat in stay out {wf._pc(r2s['stay_out'])} of the time and its long side {wf._pc(r2l['stay_out'])} (caution {wf._pc(r2l['caution'])}). "
          "The reason is ties, not a bug: funding sits at one floor value, 0.00005, in about 58 percent of the funding rows in the funding file, so in later months both short-side cut-offs "
          "equal that value (section 7) and \"at or below\" the cut-off includes every row at the floor. The rule was run exactly as fixed; no tie handling was tried.",
          f"- **R4 lead time.** It was expected to be near zero. Measured median lead: long {wf._fmt_lead(r4l)}; short {wf._fmt_lead(r4s)}. The lead is measured from the start of the alarm run to the event time "
          "(the first candle that crosses 30 percent from the episode's reference price, OPEN), and a 1-hour fall or rise can pass its 5th or 95th percentile before that crossing.",
          "- **Capture next to share.** A capture rate is only readable next to the stay-out share and the random gate: R2's short capture (35 percent) comes with a stay-out share above 40 percent and sits inside the random range.",
          "- **Few episodes.** With 5 long episodes a capture of 5 of 5 has a lower limit of about 48 percent; the long-side intervals overlap widely. Nothing here picks a rule.", ""]
    L += ["## Decisions", "",
          f"**Decided by the user ({FIXED_ON}, proposed by Claude, approved by the user):** the four rules and every value in section 1 (the percentile cut-offs 95 / 90 and 5 / 10 from the training rows only, "
          "fixed for the test month; NaN gives clear; the features and tails of R1 to R4); that no other threshold, window or variant is tried in this task; the metrics, the random gate and the splits are the "
          "harness's, fixed on 2026-11-21. Four trials were logged before they were evaluated.", "",
          "**OPEN (not decided):**", "",
          "- Whether the kill criterion check (capture at least 50 percent) should be reported at all for baselines. It is not reported here.",
          "- Funding staleness between funding times: the latest funding rate is held until the next funding time, so at some decision times it is up to 8 hours old (4 hours in some periods). No age limit is applied.",
          "- The zero-volume Bybit issue: 17.5 percent of Bybit 1m candles have zero volume, so their close may be stale and `bybit_gap` (and R3) may show a gap that is not a real price difference. It is kept as it is.",
          "- Raised by this run, not asked: how to treat ties at a percentile cut-off (R2: the funding floor value 0.00005 holds about 58 percent of the funding rows, so its short-side stay-out share is above 40 percent). Nothing was changed.",
          "- Episodes cluster in time (mostly 2026-07 and 2026-08), and a rule that turns on at the first crash of a cluster stays on through the aftershocks, so later episodes in the same cluster count as captured. The capture rates above therefore overstate skill, and the number of independent events is far smaller than the episode count. A cluster-aware view (episodes grouped when their start times are within 24 hours, capture reported for the first episode of each cluster) must be added to the harness as a reported-only metric before any real rule is evaluated.",
          "- Capture does not measure how much of the adverse move was still ahead when the alarm came. For R4 the alarm is triggered by the start of the same move, so capture can be high while the gate protects little. A metric for the remaining adverse move after the first alarm must be defined before any real rule is evaluated.",
          "- Any rule that must beat these baselines at Gate 2 faces R1 and R4 as the bar.",
          ""]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gate 2 baseline rules: log four trials, evaluate on the development period, write the report (never the holdout).")
    ap.add_argument("command", choices=["run", "report"])
    ap.add_argument("--data-dir", default="data/raw")
    ap.add_argument("--report", default="docs/phase2_gate2_baselines.md")
    ap.add_argument("--rule-trials", default="T0004,T0005,T0006,T0007")
    ap.add_argument("--anchor-trials", default="T0001,T0002,T0003")
    args = ap.parse_args(argv)
    d_res, r_res = Path(args.data_dir).resolve(), Path(args.report).resolve()
    if r_res == d_res or d_res in r_res.parents:
        print(f"Refusing: --report must not be inside the data directory {args.data_dir}.")
        return 2
    load = lambda ids: [json.loads((wf.RESULTS_DIR / f"{t}.json").read_text(encoding="utf-8")) for t in ids.split(",")]  # noqa: E731
    rules = run_baselines(Path(args.data_dir)) if args.command == "run" else load(args.rule_trials)
    if args.command == "run":
        rules = [json.loads(Path(r["result_file"]).read_text(encoding="utf-8")) for r in rules]  # the saved (cleaned) form, so run and report render the same
    Path(args.report).write_text(render_report(load(args.anchor_trials), rules), encoding="utf-8")
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
