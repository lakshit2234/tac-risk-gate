"""Phase 2 walk-forward harness (docs/phase2_plan.md, sections 4 and 5). No real rule is built here: only the harness and three trivial gates.

Everything marked FIXED below was fixed in advance by the user on 2026-11-21 (proposed by Claude, approved by the user). Each fixed value is one named constant.

Rule interface: a rule is a callable that gets ONE row of features at decision time t (a dict of feature columns, never a label column, never a later row)
and returns (state_long, state_short); each state is 0 = clear, 1 = caution, 2 = stay out. Long and short are separate and never pooled. The primary alarm is
state 2; the caution share and "caution or stay out" are secondary views. A rule may have an optional fit(train_rows) step.

Walk-forward: expanding window by calendar month, first test month FIRST_TEST_MONTH, test months only over the development period (decision times up to
2026-07-31 00:00 UTC). train_rows holds only rows whose label_known_at_ms is at or before the start of the test month (enforced: EmbargoError).
The development run never reads a holdout row: the klines are cut at the holdout start before anything is built (HoldoutError otherwise).
evaluate_holdout works once only (a lock file).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

import numpy as np
import pandas as pd

from tacgate.phase2 import features_klines as fk
from tacgate.phase2 import labels as lb
from tacgate.phase2 import loaders as ld

MIN_MS = 60_000
GRID_MS = 300_000

# ------------------------------------------------------------ FIXED values ---
CLEAR, CAUTION, STAY_OUT = 0, 1, 2  # FIXED: 0 = clear, 1 = caution, 2 = stay out
PRIMARY_ALARM = STAY_OUT  # FIXED: the primary alarm is state 2; "caution or stay out" (state >= 1) is a secondary view
FIRST_TEST_MONTH = "2025-09"  # FIXED: first test month; expanding window by calendar month
PRIMARY_VIEW = (24, 0.30)  # FIXED: 24 h, 30 percent adverse move
REPORTED_VIEWS = ((4, 0.20), (1, 0.20))  # FIXED: reported only, never used to select
VIEWS = (PRIMARY_VIEW, *REPORTED_VIEWS)
PRIMARY_LEAD_MIN = 60  # FIXED: primary lead window 1 h
REPORTED_LEADS_MIN = (15, 240)  # FIXED: 15 min and 4 h, reported only
LEADS_MIN = (15, 60, 240)
N_SHIFTS = 1000  # FIXED: random gate = circular shifts of the rule's own gate series, inside the test period
SHIFT_SEED = 20261121  # FIXED
CI_ALPHA = 0.05  # FIXED: 95 percent exact (Clopper-Pearson) interval, two-sided
MIN_EPISODES = 4  # FIXED: below this a part prints TOO FEW instead of a verdict
LISTING_START = "2025-07-15"
LISTING_FREE_FROM = "2025-07-22"  # FIXED: "without the first 7 days after listing" = from this date on
TRIAL_WARN_AFTER = 50  # FIXED: more than this many trials = "exploratory only"
TRIAL_LOG = Path("docs/trial_log.csv")
HOLDOUT_LOCK = Path("docs/holdout_used.txt")
RESULTS_DIR = Path("data/processed/trials")  # ignored by git (.gitignore: data/processed/*)
TRIAL_COLUMNS = ["trial_id", "date_utc", "family", "description", "horizon_h", "threshold", "feature_set", "development_result_reference", "notes"]
# NOT a decision: the stay-out and caution probabilities of the built-in random baseline are Claude's choice for the sanity anchor.
RANDOM_GATE_P = (0.10, 0.10)  # (stay out, caution)

ALARMS = {"stay_out": STAY_OUT, "caution_or_stay_out": CAUTION}
SIDES = lb.SIDES


def utc_ms(text: str) -> int:
    return ld.utc_ms(text)


def view_key(view: tuple[int, float]) -> str:
    return f"{view[0]}h_{round(view[1] * 100)}pct"


class HarnessError(RuntimeError):
    pass


class EmbargoError(HarnessError):
    """A training row whose label is not yet known at the start of the test month."""


class HoldoutError(HarnessError):
    """A holdout row was about to be read in a development run, or the holdout was already used."""


class UnknownTrialError(HarnessError):
    """evaluate() was asked for a trial that is not in the trial log."""


# ---------------------------------------------------------------- trial log ---

def read_trial_ids(path: Path = TRIAL_LOG) -> list[str]:
    path = Path(path)
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return [r["trial_id"] for r in csv.DictReader(f)]


def append_trial(family: str, description: str, horizon_h: int, threshold: float, feature_set: str, development_result_reference: str = "", notes: str = "",
                 path: Path = TRIAL_LOG, now: datetime | None = None) -> str:
    """Append ONE row to the trial log (append only: old rows are never read back and rewritten) and return its trial_id (T0001, T0002, ...)."""
    path = Path(path)
    ids = read_trial_ids(path)
    nums = [int(i[1:]) for i in ids if i[:1] == "T" and i[1:].isdigit()]
    trial_id = f"T{(max(nums) if nums else 0) + 1:04d}"
    nl = "\n"
    needs_header, needs_newline = not path.exists() or path.stat().st_size == 0, False
    if not needs_header:
        raw = path.read_bytes()
        nl = "\r\n" if b"\r\n" in raw else "\n"
        needs_newline = not raw.endswith(b"\n")
    ref = development_result_reference or f"data/processed/trials/{trial_id}.json"
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(path, "a", encoding="utf-8", newline="") as f:
        if needs_newline:
            f.write(nl)
        w = csv.writer(f, lineterminator=nl)
        if needs_header:
            w.writerow(TRIAL_COLUMNS)
        w.writerow([trial_id, stamp, family, description, horizon_h, threshold, feature_set, ref, notes])
    return trial_id


# ------------------------------------------------------------------- stats ---

def _log_pmf(i: int, n: int, p: float) -> float:
    return math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * math.log(p) + (n - i) * math.log1p(-p)


def _cdf_le(k: int, n: int, p: float) -> float:
    return min(1.0, sum(math.exp(_log_pmf(i, n, p)) for i in range(0, k + 1)))


def clopper_pearson(k: int, n: int, alpha: float = CI_ALPHA) -> tuple[float, float]:
    """Exact two-sided (1 - alpha) interval for k successes in n trials: each tail alpha / 2. alpha = 0.05 is the 95 percent interval."""
    if n <= 0:
        return (float("nan"), float("nan"))
    if not 0 <= k <= n:
        raise ValueError("k must be between 0 and n")
    a = alpha / 2
    lo = 0.0
    if k > 0:  # P(X >= k | p) = a, increasing in p
        l, h = 0.0, 1.0
        for _ in range(200):
            m = (l + h) / 2
            if 1.0 - _cdf_le(k - 1, n, m) < a:
                l = m
            else:
                h = m
        lo = (l + h) / 2
    hi = 1.0
    if k < n:  # P(X <= k | p) = a, decreasing in p
        l, h = 0.0, 1.0
        for _ in range(200):
            m = (l + h) / 2
            if _cdf_le(k, n, m) > a:
                l = m
            else:
                h = m
        hi = (l + h) / 2
    return lo, hi


def circular_shift(a: np.ndarray, k: int) -> np.ndarray:
    """The gate series shifted circularly by k decision times: same share of alarms, same spell lengths."""
    return np.roll(np.asarray(a), int(k))


# ------------------------------------------------------------------- rules ---

class AlwaysStayOut:
    name = "always_stay_out"

    def __call__(self, row: Mapping) -> tuple[int, int]:
        return STAY_OUT, STAY_OUT


class NeverGate:
    name = "never"

    def __call__(self, row: Mapping) -> tuple[int, int]:
        return CLEAR, CLEAR


class RandomGate:
    """Each side draws its own state independently at every row (a sanity anchor only; the probabilities are Claude's choice, not a decision)."""
    name = "random"

    def __init__(self, seed: int = SHIFT_SEED, p: tuple[float, float] = RANDOM_GATE_P):
        self.rng = np.random.default_rng(seed)
        self.p = p

    def _one(self) -> int:
        u = self.rng.random()
        return STAY_OUT if u < self.p[0] else CAUTION if u < self.p[0] + self.p[1] else CLEAR

    def __call__(self, row: Mapping) -> tuple[int, int]:
        return self._one(), self._one()


def _call_rule(rule, row: Mapping) -> tuple[int, int]:
    out = rule(row)
    try:
        sl, ss = out
    except (TypeError, ValueError):
        raise ValueError("a rule must return (state_long, state_short)") from None
    if sl not in (0, 1, 2) or ss not in (0, 1, 2):
        raise ValueError(f"states must be 0, 1 or 2, got {out!r}")
    return int(sl), int(ss)


# ----------------------------------------------------------------- dataset ---

FORBIDDEN_FEATURE_PREFIXES = ("label_", "adverse_", "complete", "ref_price")


@dataclass
class Dataset:
    features: pd.DataFrame  # decision_ms, known_at_ms, feature columns: what a rule may see
    labels: dict  # (horizon_h, threshold) -> build_labels table on the same rows
    minutes: lb.Minutes  # the minute grid used for the event times
    includes_holdout: bool = False


def make_dataset(features: pd.DataFrame, binance_klines: pd.DataFrame, includes_holdout: bool = False) -> Dataset:
    """Labels for the three views on the same rows as `features`. For a development dataset the klines must already be cut before the holdout."""
    bad = [c for c in features.columns if c.startswith(FORBIDDEN_FEATURE_PREFIXES)]
    if bad:
        raise ValueError(f"label columns in the features: {bad}")
    m = lb.minutes_from_klines(binance_klines)
    feats = features.sort_values("decision_ms").reset_index(drop=True)
    if not includes_holdout:
        feats = feats[feats["decision_ms"] <= lb.DEVELOPMENT_END_MS].reset_index(drop=True)
    labels = {}
    for v in VIEWS:
        t = lb.build_labels(m, v[0], v[1]).set_index("decision_ms")
        missing = set(feats["decision_ms"]) - set(t.index)
        if missing:
            raise ValueError("feature rows outside the label grid")
        labels[v] = t.loc[feats["decision_ms"]].reset_index()
    ds = Dataset(feats, labels, m, includes_holdout)
    assert_development_only(ds)
    return ds


def assert_development_only(ds: Dataset) -> None:
    if not ds.includes_holdout and len(ds.features) and int(ds.features["decision_ms"].max()) > lb.DEVELOPMENT_END_MS:
        raise HoldoutError("a development dataset must not contain decision times after 2026-07-31 00:00 UTC")


def build_dataset(binance: pd.DataFrame, bybit: pd.DataFrame | None = None, include_holdout: bool = False) -> Dataset:
    """Features and labels from loaders.load_klines tables. Without include_holdout the klines are cut at the holdout start FIRST: no later candle is ever read."""
    if not include_holdout:
        binance = binance[binance["ts_ms"] < lb.HOLDOUT_START_MS]
        bybit = None if bybit is None else bybit[bybit["ts_ms"] < lb.HOLDOUT_START_MS]
    return make_dataset(fk.build_features(binance, bybit), binance, include_holdout)


# ------------------------------------------------------------ walk-forward ---

def _month_start(month: str) -> pd.Timestamp:
    return pd.Timestamp(month + "-01", tz="UTC")


def month_blocks(ds: Dataset) -> list[tuple[str, int, int]]:
    """(month, start_ms, end_ms) of every test month from FIRST_TEST_MONTH over the development rows; end is exclusive."""
    last = int(ds.features["decision_ms"].max())
    out, cur = [], _month_start(FIRST_TEST_MONTH)
    while int(cur.timestamp() * 1000) <= min(last, lb.DEVELOPMENT_END_MS):
        nxt = cur + pd.offsets.MonthBegin(1)
        out.append((cur.strftime("%Y-%m"), int(cur.timestamp() * 1000), int(nxt.timestamp() * 1000)))
        cur = nxt
    return out


def train_rows(ds: Dataset, start_ms: int) -> pd.DataFrame:
    """Rows a rule may be fitted on before a test block: features plus the primary-view labels, only rows whose label is known at start_ms."""
    lab = ds.labels[PRIMARY_VIEW]
    mask = (lab["label_known_at_ms"] <= start_ms) & lab["complete"]
    out = ds.features[mask.to_numpy()].copy()
    for c in ("label_long", "label_short", "label_known_at_ms"):
        out[c] = lab.loc[mask, c].to_numpy()
    return out.reset_index(drop=True)


def check_training_rows(train: pd.DataFrame, start_ms: int) -> None:
    """Raises if any training row's label is not known at start_ms, or the row belongs to the holdout."""
    if len(train) == 0:
        return
    if (train["label_known_at_ms"] > start_ms).any():
        raise EmbargoError("a training row has label_known_at_ms after the start of the test block")
    if (train["decision_ms"] > lb.DEVELOPMENT_END_MS).any():
        raise HoldoutError("a training row is in the holdout")


@dataclass
class Gate:
    times: np.ndarray
    states: dict = field(default_factory=dict)  # side -> int array of states


def run_gate(rule, ds: Dataset, blocks: list[tuple[str, int, int | None]]) -> Gate:
    """Walk forward over the blocks: fit (if the rule has fit) on the allowed training rows, then call the rule on every test row, one row at a time."""
    times: list[np.ndarray] = []
    states: dict[str, list[int]] = {"long": [], "short": []}
    f = ds.features
    for _, start, end in blocks:
        if start > lb.DEVELOPMENT_END_MS and not ds.includes_holdout:
            raise HoldoutError("a development run must not test after 2026-07-31 00:00 UTC")
        tr = train_rows(ds, start)
        check_training_rows(tr, start)
        if hasattr(rule, "fit"):
            rule.fit(tr)
        sel = (f["decision_ms"] >= start)
        if end is not None:
            sel &= f["decision_ms"] < end
        if not ds.includes_holdout:
            sel &= f["decision_ms"] <= lb.DEVELOPMENT_END_MS
        block = f[sel.to_numpy()]
        times.append(block["decision_ms"].to_numpy(dtype="int64"))
        for row in block.to_dict("records"):
            sl, ss = _call_rule(rule, row)
            states["long"].append(sl)
            states["short"].append(ss)
    return Gate(np.concatenate(times) if times else np.array([], dtype="int64"), {s: np.array(v, dtype="int8") for s, v in states.items()})


# ---------------------------------------------------------------- episodes ---

@dataclass
class Episode:
    start_ms: int
    end_ms: int
    n_positive: int
    event_ms: int  # OPEN definition: the open of the first 1m candle that crosses the threshold from the reference price of the first positive decision time


def event_time(m: lb.Minutes, start_ms: int, side: str, horizon_h: int, threshold: float) -> int:
    """Open time of the first 1m candle in [start, start + H) whose low (long) or high (short) crosses the threshold from C_start, the same comparison the label uses."""
    i0 = int((start_ms - m.first_open) // MIN_MS)
    ref = m.close[i0 - 1]
    n = horizon_h * 60
    if side == "long":
        hit = m.low[i0:i0 + n] / ref - 1.0 <= -threshold
    else:
        hit = m.high[i0:i0 + n] / ref - 1.0 >= threshold
    k = np.flatnonzero(hit)
    if len(k) == 0:
        raise HarnessError("a positive decision time without a crossing candle")
    return int(start_ms + k[0] * MIN_MS)


def build_episodes(ds: Dataset, view: tuple[int, float], side: str, start_ms: int, end_ms: int | None = None) -> list[Episode]:
    """Label episodes (labels.py definition) of positive decision times inside [start_ms, end_ms], each with its event time."""
    df = ds.labels[view]
    sel = df["decision_ms"] >= start_ms
    if end_ms is not None:
        sel &= df["decision_ms"] <= end_ms
    if not ds.includes_holdout:
        sel &= df["decision_ms"] <= lb.DEVELOPMENT_END_MS
    return [Episode(s, e, n, event_time(ds.minutes, s, side, view[0], view[1])) for s, e, n in lb.label_episodes(df[sel.to_numpy()], side, view[0])]


# ----------------------------------------------------------------- metrics ---

@dataclass
class Part:
    name: str
    row_mask: Callable[[np.ndarray], np.ndarray]
    start_ok: Callable[[int], bool]


def default_parts() -> list[Part]:
    cliff = ld.cliff_dates()["investors"]
    free = utc_ms(LISTING_FREE_FROM)
    return [Part("all", lambda t: np.ones(len(t), bool), lambda s: True),
            Part("before the cliff (2026-07-15)", lambda t: t < cliff, lambda s: s < cliff),
            Part("after the cliff (2026-07-15)", lambda t: t >= cliff, lambda s: s >= cliff),
            Part("without the first 7 days after listing", lambda t: t >= free, lambda s: s >= free)]


def _windows(T: np.ndarray, eps: list[Episode], lead_min: int) -> tuple[np.ndarray, np.ndarray]:
    """Row index range [i0, i1) of the decision times in [event - lead, event - 5 min] that exist in the test period."""
    b = np.array([e.event_ms for e in eps], dtype="int64")
    return np.searchsorted(T, b - lead_min * MIN_MS, "left"), np.searchsorted(T, b - GRID_MS, "right")


def _run_starts(a: np.ndarray) -> np.ndarray:
    idx = np.arange(len(a))
    start = a & ~np.r_[False, a[:-1]]
    return np.maximum.accumulate(np.where(start, idx, -1))


def _pct(x: np.ndarray, q: float) -> float:
    return float(np.percentile(x, q))


def compute_metrics(T: np.ndarray, states: dict, episodes: dict, parts: list[Part] | None = None) -> dict:
    """The fixed metrics for one gate. episodes[(view, side)] are the episodes of the test period; T the decision times of the test period."""
    parts = parts or default_parts()
    N = len(T)
    out: dict = {"n_decision_times": int(N), "shares": {}, "views": {}}
    rng = np.random.default_rng(SHIFT_SEED)
    offsets = rng.integers(1, max(N, 2), size=N_SHIFTS)
    for side in SIDES:
        st = states[side]
        out["shares"][side] = {}
        for p in parts:
            mk = p.row_mask(T)
            n = int(mk.sum())
            out["shares"][side][p.name] = {"rows": n, "stay_out": float((st[mk] == STAY_OUT).mean()) if n else None,
                                           "caution": float((st[mk] == CAUTION).mean()) if n else None,
                                           "caution_or_stay_out": float((st[mk] >= CAUTION).mean()) if n else None}
    for v in VIEWS:
        vk = view_key(v)
        out["views"][vk] = {}
        for side in SIDES:
            eps = episodes[(v, side)]
            out["views"][vk][side] = {}
            for lead in LEADS_MIN:
                i0, i1 = _windows(T, eps, lead) if eps else (np.array([], int), np.array([], int))
                lead_out = {}
                for aname, level in ALARMS.items():
                    a = states[side] >= level
                    cs = np.r_[0, np.cumsum(a)]
                    cap = (cs[i1] - cs[i0]) > 0 if len(eps) else np.array([], bool)
                    rs = _run_starts(a)
                    lead_min = np.full(len(eps), np.nan)
                    for k in np.flatnonzero(cap):
                        seg = np.flatnonzero(a[i0[k]:i1[k]])
                        first = i0[k] + seg[0]
                        lead_min[k] = (eps[k].event_ms - T[rs[first]]) / MIN_MS
                    if len(eps) and N > 1:  # random gate: circular shifts of this gate's own alarm series
                        a2 = np.r_[a, a]
                        cs2 = np.r_[0, np.cumsum(a2)]
                        starts = (i0[None, :] - offsets[:, None]) % N
                        rand = (cs2[starts + (i1 - i0)[None, :]] - cs2[starts]) > 0
                    else:
                        rand = np.zeros((N_SHIFTS, len(eps)), bool)
                    cells = {}
                    for p in parts:
                        sel = np.array([p.start_ok(e.start_ms) for e in eps], bool) if eps else np.array([], bool)
                        n_ep, n_cap = int(sel.sum()), int((cap & sel).sum()) if len(eps) else 0
                        cell = {"episodes": n_ep, "captured": n_cap, "rate": n_cap / n_ep if n_ep else None, "ci_low": None, "ci_high": None,
                                "random_median": None, "random_p2_5": None, "random_p97_5": None,
                                "lead_count": 0, "lead_min": None, "lead_median": None, "lead_max": None, "verdict": "TOO FEW" if n_ep < MIN_EPISODES else ""}
                        if n_ep:
                            cell["ci_low"], cell["ci_high"] = clopper_pearson(n_cap, n_ep)
                            rr = rand[:, sel].mean(axis=1)
                            cell["random_median"], cell["random_p2_5"], cell["random_p97_5"] = _pct(rr, 50), _pct(rr, 2.5), _pct(rr, 97.5)
                            ld_ = lead_min[cap & sel]
                            if len(ld_):
                                cell.update(lead_count=int(len(ld_)), lead_min=float(ld_.min()), lead_median=float(np.median(ld_)), lead_max=float(ld_.max()))
                            if n_ep >= MIN_EPISODES:  # descriptive position only, never a significance claim
                                r = cell["rate"]
                                cell["verdict"] = ("above the random 97.5% value" if r > cell["random_p97_5"] else
                                                   "below the random 2.5% value" if r < cell["random_p2_5"] else "inside the random 2.5%-97.5% range")
                        cells[p.name] = cell
                    lead_out[aname] = cells
                out["views"][vk][side][f"{lead}min"] = lead_out
    return out


# --------------------------------------------------------------- evaluation ---

def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not math.isfinite(float(o)) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def fixed_values() -> dict:
    return {"states": "0 clear, 1 caution, 2 stay out", "primary_alarm": "state 2 (stay out)", "first_test_month": FIRST_TEST_MONTH,
            "development_end_utc": "2026-07-31 00:00", "holdout_start_utc": "2026-08-01 00:00", "primary_view": view_key(PRIMARY_VIEW),
            "reported_views": [view_key(v) for v in REPORTED_VIEWS], "primary_lead_min": PRIMARY_LEAD_MIN, "reported_leads_min": list(REPORTED_LEADS_MIN),
            "n_shifts": N_SHIFTS, "shift_seed": SHIFT_SEED, "ci": "95% exact Clopper-Pearson, two-sided", "min_episodes": MIN_EPISODES,
            "cliff_date_utc": "2026-07-15", "listing_free_from_utc": LISTING_FREE_FROM, "trial_warn_after": TRIAL_WARN_AFTER}


def _check_trial(trial_id: str, trial_log: Path) -> tuple[int, list[str]]:
    ids = read_trial_ids(trial_log)
    if trial_id not in ids:
        raise UnknownTrialError(f"{trial_id!r} is not in the trial log {trial_log}: log every variant BEFORE it is evaluated (append_trial)")
    warns = [f"{len(ids)} trials so far: more than {TRIAL_WARN_AFTER}, exploratory only"] if len(ids) > TRIAL_WARN_AFTER else []
    for w in warns:
        print("WARNING:", w)
    return len(ids), warns


def _episodes_all(ds: Dataset, start_ms: int, end_ms: int | None = None) -> dict:
    return {(v, s): build_episodes(ds, v, s, start_ms, end_ms) for v in VIEWS for s in SIDES}


def _write(result: dict, results_dir: Path, name: str) -> Path:
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    p = results_dir / f"{name}.json"
    p.write_text(json.dumps(_clean(result), indent=1, allow_nan=False), encoding="utf-8")
    return p


def evaluate(rule, trial_id: str, ds: Dataset, trial_log: Path = TRIAL_LOG, results_dir: Path = RESULTS_DIR, write: bool = True) -> dict:
    """Walk-forward evaluation on the DEVELOPMENT period only. The trial must already be in the trial log."""
    n_trials, warns = _check_trial(trial_id, Path(trial_log))
    if ds.includes_holdout:
        raise HoldoutError("a development run needs a development dataset (build_dataset without include_holdout)")
    assert_development_only(ds)
    blocks = month_blocks(ds)
    if not blocks:
        raise HarnessError("no test month in the data")
    gate = run_gate(rule, ds, blocks)
    start = blocks[0][1]
    eps = _episodes_all(ds, start, lb.DEVELOPMENT_END_MS)
    res = {"trial_id": trial_id, "rule": getattr(rule, "name", type(rule).__name__), "trials_so_far": n_trials, "warnings": warns,
           "period": "development", "test_months": [b[0] for b in blocks], "fixed": fixed_values(),
           "episodes": {view_key(v) + "_" + s: len(e) for (v, s), e in eps.items()},
           "metrics": compute_metrics(gate.times, gate.states, eps)}
    if write:
        res["result_file"] = str(_write(res, results_dir, trial_id))
    return res


def evaluate_holdout(rule, trial_id: str, binance: pd.DataFrame, bybit: pd.DataFrame | None = None, lock_path: Path = HOLDOUT_LOCK,
                     trial_log: Path = TRIAL_LOG, results_dir: Path = RESULTS_DIR, write: bool = True) -> dict:
    """The one and only holdout evaluation. Writes the lock file FIRST and refuses to run if it already exists. Never call it in a development run."""
    lock_path = Path(lock_path)
    n_trials, warns = _check_trial(trial_id, Path(trial_log))
    if lock_path.exists():
        raise HoldoutError(f"the holdout was already used ({lock_path})")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(lock_path, "x", encoding="utf-8") as f:  # exclusive: a second call cannot pass
            f.write(f"trial_id: {trial_id}\nused_utc: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n")
    except FileExistsError:
        raise HoldoutError(f"the holdout was already used ({lock_path})") from None
    ds = build_dataset(binance, bybit, include_holdout=True)
    start = lb.HOLDOUT_START_MS
    gate = run_gate(rule, ds, [("holdout", start, None)])
    eps = _episodes_all(ds, start, None)
    res = {"trial_id": trial_id, "rule": getattr(rule, "name", type(rule).__name__), "trials_so_far": n_trials, "warnings": warns, "period": "holdout",
           "fixed": fixed_values(), "episodes": {view_key(v) + "_" + s: len(e) for (v, s), e in eps.items()},
           "metrics": compute_metrics(gate.times, gate.states, eps)}
    if write:
        res["result_file"] = str(_write(res, results_dir, f"{trial_id}_holdout"))
    return res


# ------------------------------------------------------------------ report ---

def _fmt_rate(c: dict) -> str:
    if not c["episodes"]:
        return "no episodes"
    return f"{c['captured']}/{c['episodes']} = {100 * c['rate']:.0f}% [{100 * c['ci_low']:.0f}%, {100 * c['ci_high']:.0f}%]"


def _fmt_rand(c: dict) -> str:
    return "-" if c["random_median"] is None else f"{100 * c['random_median']:.0f}% [{100 * c['random_p2_5']:.0f}%, {100 * c['random_p97_5']:.0f}%]"


def _fmt_lead(c: dict) -> str:
    return "-" if not c["lead_count"] else f"{c['lead_count']}: {c['lead_min']:.0f} / {c['lead_median']:.0f} / {c['lead_max']:.0f} min"


def _pc(x) -> str:
    return "-" if x is None else f"{100 * x:.1f}%"


def render_check(results: list[dict]) -> str:
    fx = results[0]["fixed"]
    pk, lead = view_key(PRIMARY_VIEW), f"{PRIMARY_LEAD_MIN}min"
    by = {r["rule"]: r for r in results}
    names = [r["rule"] for r in results]
    first = results[0]["metrics"]
    L = ["# Phase 2 walk-forward harness check", "",
         f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d')} (UTC) by `python -m tacgate.phase2.walkforward demo`. Development period only; the holdout was not read "
         f"(lock file `docs/holdout_used.txt` {'EXISTS' if HOLDOUT_LOCK.exists() else 'does not exist'}). Trials so far: {results[-1]['trials_so_far']}"
         f"{' (more than 50: exploratory only)' if results[-1]['trials_so_far'] > TRIAL_WARN_AFTER else ''}.", "",
         "**No real rule was evaluated.** Always-stay-out and never are only sanity anchors (a gate that is always on, and no gate at all); the random gate is a third anchor. "
         "Nothing here says anything about a risk gate. The harness is checked; the numbers are not a result.", "",
         "## 1. Fixed values", "",
         "Fixed in advance by the user on 2026-11-21 (proposed by Claude, approved by the user). Each one is a named constant in `src/tacgate/phase2/walkforward.py`.", "",
         "| Item | Value |", "|---|---|",
         "| Rule states | 0 = clear, 1 = caution, 2 = stay out; long and short separate, never pooled |",
         "| Primary alarm | state 2 (stay out); caution share and \"caution or stay out\" are secondary views |",
         f"| Walk-forward | expanding window by calendar month, first test month {fx['first_test_month']}, test months only up to {fx['development_end_utc']} UTC |",
         "| Training rows | only rows whose label is known (label_known_at_ms) at or before the start of the test month; a violation raises an error |",
         f"| Holdout | from {fx['holdout_start_utc']} UTC; never read in a development run; `evaluate_holdout` works once (lock file `docs/holdout_used.txt`) and was not called |",
         f"| Primary view | {pk} (24 h, 30 percent adverse); reported only: 4 h / 20 percent and 1 h / 20 percent, never used to select |",
         f"| Lead window | primary {PRIMARY_LEAD_MIN} min; {', '.join(str(x) for x in REPORTED_LEADS_MIN)} min reported only |",
         f"| Random gate | circular shift of the rule's own gate series inside the test period, {fx['n_shifts']} shifts, seed {fx['shift_seed']}: median and 2.5 / 97.5 percent values of its capture rate |",
         f"| Interval | {fx['ci']} |",
         f"| Too few | fewer than {fx['min_episodes']} episodes in a part prints TOO FEW instead of a verdict |",
         f"| Splits | before / after the cliff {fx['cliff_date_utc']} (from `loaders.cliff_dates`); with / without the first 7 days after listing (2025-07-15 to {fx['listing_free_from_utc']}) |",
         f"| Trial log | `docs/trial_log.csv`, append only; a trial must be logged before it is evaluated; a warning above {TRIAL_WARN_AFTER} trials |", "",
         "Not a decision (Claude's choice for the sanity anchor only): the random baseline gate puts each side in stay-out with probability 10 percent and in caution with probability 10 percent, "
         "independently at every decision time.", "",
         "## 2. What was run", "",
         f"Three baseline trials were logged first (`{'`, `'.join(r['trial_id'] for r in results)}` = {', '.join(names)}), then evaluated over the test months "
         f"{results[0]['test_months'][0]} to {results[0]['test_months'][-1]} ({first['n_decision_times']:,} decision times; the last test month stops at 2026-07-31 00:00 UTC). "
         "Episodes in the test period (the same for every gate):", "",
         "| View | Long episodes | Short episodes |", "|---|---|---|"]
    for v in VIEWS:
        k = view_key(v)
        L.append(f"| {k.replace('_', ' / ').replace('pct', ' percent')} | {results[0]['episodes'][k + '_long']} | {results[0]['episodes'][k + '_short']} |")
    L += ["", "How capture is counted: an episode is captured when the gate was in the alarm state at some decision time in [event - lead, event - 5 minutes], using only decision times that "
          "exist in the test period. The event time is the open of the first 1m candle that crosses the threshold from the reference price of the episode's first positive decision time (OPEN). "
          "The lead time of a captured episode is the minutes from the start of the continuous alarm run (that contains the first alarm decision time inside the lead window) to the event.", "",
          f"## 3. Baseline table: primary view {pk}, lead {PRIMARY_LEAD_MIN} min, alarm = stay out, whole test period", "",
          "Rate = captured / episodes (95 percent exact interval). Random gate = capture rate after circular shifts of the gate's own series (median, 2.5 and 97.5 percent values).", ""]

    def table(view_k: str, lead_k: str, alarm: str, part: str, side: str, heading_extra: bool = False) -> list[str]:
        rows = ["| Gate | Episodes | Capture rate | Random gate | Stay-out share | Caution share | Lead time of captured (count: min / median / max) | Verdict |", "|---|---|---|---|---|---|---|---|"]
        for n in names:
            m = by[n]["metrics"]
            c = m["views"][view_k][side][lead_k][alarm][part]
            sh = m["shares"][side][part]
            rows.append(f"| {n} | {c['episodes']} | {_fmt_rate(c)} | {_fmt_rand(c)} | {_pc(sh['stay_out'])} | {_pc(sh['caution'])} | {_fmt_lead(c)} | {c['verdict'] or 'no verdict (descriptive only)'} |")
        return rows
    for side in SIDES:
        L += [f"### {side.capitalize()} side", ""] + table(pk, lead, "stay_out", "all", side) + [""]
    L += ["## 4. Other lead windows (primary view, stay out, whole test period; reported only)", ""]
    for lead_m in REPORTED_LEADS_MIN:
        for side in SIDES:
            L += [f"### {side.capitalize()}, lead {lead_m} min", ""] + table(pk, f"{lead_m}min", "stay_out", "all", side) + [""]
    L += ["## 5. Reported-only views (lead 60 min, stay out, whole test period; never used to select)", ""]
    for v in REPORTED_VIEWS:
        for side in SIDES:
            L += [f"### {view_key(v).replace('_', ' / ').replace('pct', ' percent')}, {side}", ""] + table(view_key(v), lead, "stay_out", "all", side) + [""]
    L += ["## 6. Secondary view: caution or stay out (primary view, lead 60 min, whole test period)", ""]
    for side in SIDES:
        rows = ["| Gate | Episodes | Capture rate | Random gate | Caution-or-stay-out share |", "|---|---|---|---|---|"]
        for n in names:
            m = by[n]["metrics"]
            c = m["views"][pk][side][lead]["caution_or_stay_out"]["all"]
            rows.append(f"| {n} | {c['episodes']} | {_fmt_rate(c)} | {_fmt_rand(c)} | {_pc(m['shares'][side]['all']['caution_or_stay_out'])} |")
        L += [f"### {side.capitalize()} side", ""] + rows + [""]
    L += ["## 7. Split tables (primary view, lead 60 min, stay out)", "",
          "Each part counts the episodes that START in it and the decision times in it. The test period starts 2025-09-01, so the first 7 days after listing "
          "(2025-07-15 to 2025-07-22) are never in a test month: \"without the first 7 days after listing\" is the same as the whole period here. Those days are in the training rows only.", ""]
    part_names = list(first["shares"]["long"])
    too_few = []
    for side in SIDES:
        for part in part_names:
            L += [f"### {side.capitalize()}: {part}", ""] + table(pk, lead, "stay_out", part, side) + [""]
            for v in VIEWS:
                n_ep = by[names[0]]["metrics"]["views"][view_key(v)][side][lead]["stay_out"][part]["episodes"]
                if n_ep < MIN_EPISODES:
                    too_few.append(f"{view_key(v).replace('_', ' / ').replace('pct', ' percent')}, {side}, {part}: {n_ep} episode(s)")
    L += ["## 8. Where a part is TOO FEW (fewer than 4 episodes)", "",
          "No verdict is printed for these parts (the same episodes for every gate):", ""]
    L += [f"- {s}" for s in too_few] or ["- none"]
    L += ["", "## 9. Reading the anchors", "",
          "- Always stay out captures every episode and sits in stay out 100 percent of the time: the capture rate alone means nothing, which is why the time share is always printed next to it.",
          "- Never captures none and sits in stay out 0 percent of the time.",
          "- The lead time of the always-stay-out gate is huge (tens of thousands of minutes) because its alarm run starts at the first test decision time; it is not a lead time in any useful sense.",
          "- The primary view has only a handful of long episodes in the whole test period (see section 2), so every long-side number above rests on very few events; "
          "even the whole-period long row is close to the 4-episode limit.",
          "- The random gate sits in stay out about 10 percent of the time; its own capture rate and its shifted-series range show what chance alone gives at that share. No significance claim is made anywhere.", "",
          "## Decisions", "",
          "**Decided by the user (fixed on 2026-11-21, proposed by Claude, approved by the user):** every value in section 1; the rule interface (one feature row, states 0 / 1 / 2, long and short separate); "
          "walk-forward by calendar month from 2025-09 with the embargo rule enforced in code; the holdout read only through `evaluate_holdout`, once, behind a lock file; the append-only trial log with "
          "the 50-trial warning; the fixed metrics, the random gate and the exact interval; results in `data/processed/trials/` (ignored by git).", "",
          "**The interval:** it is the two-sided 95 percent exact Clopper-Pearson interval, as the user asked. The numbers 0.527 and 0.473 in the original test spec were one-sided limits "
          "and were a mistake by Claude, not by the code.", "",
          "**OPEN (not decided):**", "",
          "- The event-time definition: the open of the first 1m candle that crosses the threshold from the reference price of the episode's first positive decision time. Other choices (for example the candle close, or the extreme) are possible.",
          "- What caution means: the harness reports it as a secondary view only; how it would change a position or an entry is not decided.",
          "- What to do when the long side has too few episodes (the primary view has few long episodes in the cliff parts and the holdout is at the 4-episode limit): report \"too few for a verdict\" in advance, or something else.", ""]
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------- demo ---

def run_demo(data_dir: Path, report: Path, trial_log: Path = TRIAL_LOG, results_dir: Path = RESULTS_DIR) -> list[dict]:
    """Log three baseline trials (always, never, random), evaluate them on the development period and write the report."""
    if any(i for i in read_trial_ids(trial_log)):
        with open(trial_log, encoding="utf-8", newline="") as f:
            if any(r["family"] == "baseline" for r in csv.DictReader(f)):
                raise HarnessError("the baseline trials are already in the trial log; the demo logs them once")
    b = ld.load_klines(Path(data_dir) / "binance_TACUSDT_1m.csv", "binance")
    y = ld.load_klines(Path(data_dir) / "bybit_TACUSDT_1m.csv", "bybit")
    ds = build_dataset(b, y)
    rules = [AlwaysStayOut(), NeverGate(), RandomGate()]
    notes = {"always_stay_out": "sanity anchor: a gate that is always on", "never": "sanity anchor: no gate", "random": "sanity anchor: random states, 10% stay out and 10% caution per side"}
    ids = [append_trial("baseline", f"{r.name}: {notes[r.name]}", PRIMARY_VIEW[0], PRIMARY_VIEW[1], "none", notes="harness demo, no real rule", path=trial_log) for r in rules]
    results = [evaluate(r, i, ds, trial_log, results_dir) for r, i in zip(rules, ids)]
    Path(report).write_text(render_check(results), encoding="utf-8")
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Walk-forward harness demo: three baseline trials on the development period (never the holdout).")
    ap.add_argument("command", choices=["demo", "report"])
    ap.add_argument("--trials", default="T0001,T0002,T0003")
    ap.add_argument("--data-dir", default="data/raw")
    ap.add_argument("--report", default="docs/phase2_walkforward_check.md")
    args = ap.parse_args(argv)
    d_res, r_res = Path(args.data_dir).resolve(), Path(args.report).resolve()
    if r_res == d_res or d_res in r_res.parents:
        print(f"Refusing: --report must not be inside the data directory {args.data_dir}.")
        return 2
    if args.command == "report":  # re-render the report from saved results; logs nothing, evaluates nothing
        res = [json.loads((RESULTS_DIR / f"{t}.json").read_text(encoding="utf-8")) for t in args.trials.split(",")]
        Path(args.report).write_text(render_check(res), encoding="utf-8")
        print(f"report: {args.report}")
        return 0
    res = run_demo(Path(args.data_dir), Path(args.report))
    for r in res:
        print(r["trial_id"], r["rule"], "->", r.get("result_file"))
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
