"""Phase 2 label builder: the ONE implementation of the risk-event label (docs/phase2_plan.md, section 2, and Decisions).

No features, no models. It reads 1m klines (the output of loaders.load_klines, or a Minutes grid) and returns one row per decision time.

Conventions (identical to the count table, which now calls this module):
  * decision times are the boundaries of the `step_min` grid (default 5 minutes), counted from the klines' own minute grid;
  * the reference price is C_t, the close of the 1m candle that ENDS at t (open time t - 1 minute);
  * the window is the next H hours: the 1m candles that OPEN in [t, t + H) (H x 60 candles, the first opens at t);
  * adverse_long  = lowest low in the window / C_t - 1  (a fall is negative);
    adverse_short = highest high in the window / C_t - 1 (a rise is positive);
  * label_long = adverse_long <= -threshold, label_short = adverse_short >= threshold ("at least x": a move of exactly x counts);
  * label_known_at_ms = decision_ms + H hours: a label may be used only after its whole window has passed;
  * a row is complete only if C_t exists and all H x 60 candles of the window exist. An INCOMPLETE row has NaN labels and NaN adverse values, never 0.
    Nothing is filled, imputed or interpolated: a missing minute stays missing and makes every window that contains it incomplete;
  * long and short are separate columns and are never pooled;
  * an EPISODE is a run of positive decision times of ONE side where consecutive positives are closer than H (gap >= H starts a new episode).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from tacgate.phase2 import loaders as ld

MIN_MS = 60_000
GRID_MS = 300_000
HOUR_MS = 3_600_000
SIDES = ("long", "short")

# Frozen holdout, DECIDED 2026-11-21 (docs/phase2_plan.md, Decisions): development decision times end 2026-07-31 00:00 UTC (24 h embargo),
# holdout decision times start 2026-08-01 00:00 UTC, end open.
DEVELOPMENT_END = "2026-07-31"
HOLDOUT_START = "2026-08-01"


def utc_ms(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp() * 1000)


DEVELOPMENT_END_MS = utc_ms(DEVELOPMENT_END)
HOLDOUT_START_MS = utc_ms(HOLDOUT_START)


# -------------------------------------------------------------------- grid ---

@dataclass
class Minutes:
    """The 1m candles on a complete minute grid. A missing minute is NaN (nothing is filled)."""
    first_open: int
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray

    @property
    def n(self) -> int:
        return len(self.close)


def minutes_from_klines(klines: pd.DataFrame) -> Minutes:
    """A minute grid from a klines table with ts_ms (the open time), high, low and close. Missing minutes become NaN rows of the grid."""
    for c in ("ts_ms", "high", "low", "close"):
        if c not in klines.columns:
            raise ValueError(f"klines need a {c!r} column")
    k = klines.sort_values("ts_ms", kind="stable")
    t = k["ts_ms"].to_numpy(dtype="int64")
    if len(t) == 0:
        raise ValueError("no klines")
    if (t % MIN_MS != 0).any():
        raise ValueError("kline open times must be on minute boundaries")
    if len(np.unique(t)) != len(t):
        raise ValueError("duplicate kline open times")
    first = int(t[0])
    n = int((t[-1] - first) // MIN_MS) + 1
    idx = (t - first) // MIN_MS

    def col(name: str) -> np.ndarray:
        a = np.full(n, np.nan)
        a[idx] = k[name].to_numpy(dtype="float64")
        return a

    return Minutes(first, col("high"), col("low"), col("close"))


def forward_extreme(values: np.ndarray, width: int, kind: str) -> np.ndarray:
    """out[j] = min (or max) of values[j : j + width]; NaN where the window runs past the end or has a missing minute."""
    s = pd.Series(values[::-1])
    r = s.rolling(width, min_periods=width).min() if kind == "min" else s.rolling(width, min_periods=width).max()
    return r.to_numpy()[::-1]


# ------------------------------------------------------------------ builder ---

def adverse_frame(m: Minutes, horizon_h: int, step_min: int = 5) -> pd.DataFrame:
    """decision_ms, ref_price, adverse_long, adverse_short, complete: one row per decision time (incomplete rows keep NaN values)."""
    if horizon_h <= 0 or int(horizon_h) != horizon_h:
        raise ValueError("horizon_h must be a positive whole number of hours")
    if step_min <= 0 or int(step_min) != step_min:
        raise ValueError("step_min must be a positive whole number of minutes")
    width = int(horizon_h) * 60
    fmin = np.append(forward_extreme(m.low, width, "min"), np.nan)  # index n = the boundary after the last candle: no window
    fmax = np.append(forward_extreme(m.high, width, "max"), np.nan)
    j = np.arange(1, m.n + 1)  # decision time t = open of candle j; its close C_t is candle j - 1
    t = m.first_open + j * MIN_MS
    keep = t % (int(step_min) * MIN_MS) == 0
    j, t = j[keep], t[keep]
    ref, lo, hi = m.close[j - 1], fmin[j], fmax[j]
    complete = ~np.isnan(ref) & ~np.isnan(lo) & ~np.isnan(hi)
    with np.errstate(invalid="ignore", divide="ignore"):
        adv_long = np.where(complete, lo / ref - 1.0, np.nan)
        adv_short = np.where(complete, hi / ref - 1.0, np.nan)
    return pd.DataFrame({"decision_ms": t.astype("int64"), "ref_price": np.where(complete, ref, np.nan),
                         "adverse_long": adv_long, "adverse_short": adv_short, "complete": complete})


def build_labels(klines, horizon_h: int, threshold: float, step_min: int = 5) -> pd.DataFrame:
    """One row per decision time on the grid. Columns: decision_ms, ref_price, adverse_long, adverse_short, label_long, label_short, label_known_at_ms,
    complete. The labels are 1.0 / 0.0 for a complete window and NaN (never 0) for an incomplete one."""
    if not 0 < threshold < 1:
        raise ValueError("threshold is a fraction between 0 and 1")
    m = klines if hasattr(klines, "first_open") else minutes_from_klines(klines)  # a Minutes grid (duck-typed: also works when run as __main__)
    f = adverse_frame(m, horizon_h, step_min)
    c = f["complete"].to_numpy()
    out = f[["decision_ms", "ref_price", "adverse_long", "adverse_short"]].copy()
    out["label_long"] = np.where(c, (f["adverse_long"].to_numpy() <= -threshold).astype("float64"), np.nan)
    out["label_short"] = np.where(c, (f["adverse_short"].to_numpy() >= threshold).astype("float64"), np.nan)
    out["label_known_at_ms"] = out["decision_ms"] + int(horizon_h) * HOUR_MS
    out["complete"] = c
    return out


def known_labels(df: pd.DataFrame, as_of_ms: int) -> pd.DataFrame:
    """The labelled rows that may be used at as_of_ms: the label window has passed (label_known_at_ms <= as_of_ms) and the row is complete."""
    return ld.asof(df, as_of_ms, known_col="label_known_at_ms").loc[lambda d: d["complete"]]


# ----------------------------------------------------------------- episodes ---

def episodes(times_ms: np.ndarray, horizon_h: int) -> list[tuple[int, int, int]]:
    """Merge positive decision times closer than H into episodes: (start_ms, end_ms, positive decision times). A gap of exactly H starts a new one."""
    if len(times_ms) == 0:
        return []
    t = np.sort(np.asarray(times_ms, dtype="int64"))
    cuts = np.flatnonzero(np.diff(t) >= horizon_h * HOUR_MS) + 1
    return [(int(g[0]), int(g[-1]), int(len(g))) for g in np.split(t, cuts)]


def positive_times(df: pd.DataFrame, side: str) -> np.ndarray:
    """Decision times (ms) at which the side was hit. Only the one side's column is read: long and short are never pooled."""
    if side not in SIDES:
        raise ValueError("side must be 'long' or 'short'")
    return df.loc[df[f"label_{side}"] == 1.0, "decision_ms"].to_numpy(dtype="int64")


def label_episodes(df: pd.DataFrame, side: str, horizon_h: int) -> list[tuple[int, int, int]]:
    return episodes(positive_times(df, side), horizon_h)


# ------------------------------------------------------------------ periods ---

@dataclass
class Periods:
    """Report-only splits of a label table (no selection logic)."""
    development: pd.DataFrame  # decision_ms up to 2026-07-31 00:00 UTC
    embargo: pd.DataFrame  # the 24 h in between (in neither)
    holdout: pd.DataFrame  # decision_ms from 2026-08-01 00:00 UTC
    pre_cliff: pd.DataFrame  # decision_ms before the cliff date
    post_cliff: pd.DataFrame  # decision_ms from the cliff date on
    cliff_ms: int


def split_periods(df: pd.DataFrame, tokenomics_path=None) -> Periods:
    """Development / holdout (24 h embargo between) and pre / post the cliff date (loaders.cliff_dates, 2026-07-15). Report only."""
    cliff = ld.cliff_dates(tokenomics_path)["investors"]
    d = df["decision_ms"]
    return Periods(development=df[d <= DEVELOPMENT_END_MS], embargo=df[(d > DEVELOPMENT_END_MS) & (d < HOLDOUT_START_MS)],
                   holdout=df[d >= HOLDOUT_START_MS], pre_cliff=df[d < cliff], post_cliff=df[d >= cliff], cliff_ms=cliff)


# ------------------------------------------------------------------- report ---

VIEWS = ((24, 0.30), (4, 0.20), (1, 0.20))  # DECIDED 2026-11-21: primary 24 h / 30 %, secondary 4 h / 20 % and 1 h / 20 % (reported only)
ALL_CELLS = tuple((h, x) for h in (1, 4, 24) for x in (0.10, 0.20, 0.30))
MIN_EPISODES = 4


def parse_label_counts_doc(text: str) -> tuple[dict, dict]:
    """(h, x %, side) -> (positive decision times, episodes) and h -> valid decision times, read from docs/label_counts.md."""
    import re
    rx = re.compile(r"^\| (\d+) h \| (\d+)% \| (long|short) \| ([\d,]+) \| [\d.]+% \| (\d+) \|$")
    cells = {}
    for line in text.splitlines():
        m = rx.match(line)
        if m:
            cells[(int(m.group(1)), int(m.group(2)), m.group(3))] = (int(m.group(4).replace(",", "")), int(m.group(5)))
    vline = re.search(r"Valid decision times.*", text)
    valid = {int(h): int(n.replace(",", "")) for h, n in re.findall(r"(\d+) h: ([\d,]+)", vline.group(0))} if vline else {}
    return cells, valid


def _month(ms: int) -> str:
    return pd.Timestamp(int(ms), unit="ms", tz="UTC").strftime("%Y-%m")


def month_bounds(month: str) -> tuple[int, int]:
    start = pd.Timestamp(month + "-01", tz="UTC")
    return int(start.timestamp() * 1000), int((start + pd.offsets.MonthBegin(1)).timestamp() * 1000)


def _part_counts(df: pd.DataFrame, side: str, eps: list, lo: int | None, hi: int | None) -> tuple[int, int]:
    """(positive decision times, episodes starting) inside [lo, hi) of decision time (None = open)."""
    def inside(t):
        return (lo is None or t >= lo) and (hi is None or t < hi)
    pos = sum(1 for t in positive_times(df, side) if inside(t))
    return pos, sum(1 for s, _, _ in eps if inside(s))


def decisions_lines() -> list[str]:
    return ["## Decisions", "",
            "**Already decided by the user (docs/phase2_plan.md, 2026-11-21):**", "",
            "- Frozen holdout, option B: development decision times end 2026-07-31 00:00 UTC, a 24 hour embargo, holdout from 2026-08-01 00:00 UTC.",
            "- Primary label: 24 hours / 30 percent, long and short separate. Secondary views (reported only): 4 hours / 20 percent and 1 hour / 20 percent.",
            "- Long and short are never pooled. A label is known only after its whole window has passed. No fill, impute or interpolation.",
            "- The count table and the builder are one implementation (label_counts.py calls labels.py).", "",
            "**OPEN (not decided):**", "",
            "- Whether the cliff date 2026-07-15 becomes part of the validation design, or stays a report-only split (it is an unverified hypothesis).",
            "- What to do about parts with fewer than 4 episodes (merge, drop, or report only).",
            "- Whether to use mark-price klines instead of the last-price klines the labels use now (mark klines are not downloaded yet).", ""]


def render_check(klines_path, doc_text: str, tokenomics_path=None) -> tuple[str, int]:
    """The plain-words check report and the number of mismatching cells (0 = every cell reproduces)."""
    from tacgate.phase2 import label_counts as lc
    m = lc.load_minutes(klines_path)
    cells, valid = parse_label_counts_doc(doc_text)
    built = {h: {x: build_labels(m, h, x) for x in (0.10, 0.20, 0.30)} for h in (1, 4, 24)}
    mismatches = 0
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    L = ["# Phase 2 label builder check", "",
         f"Generated {today} (UTC) by `python -m tacgate.phase2.labels`. Read-only. No feature, no model, no selection. "
         "The builder (`src/tacgate/phase2/labels.py`) is the only implementation of the label: `label_counts.py` now calls it, so the count table and the label table "
         "cannot disagree. Last-price 1m klines are used (mark klines are not downloaded yet).", "",
         "## 1. Does the builder reproduce docs/label_counts.md?", "",
         "Every cell of the Overall table: positive 5-minute decision times and episodes, builder output against the document.", "",
         "| Horizon | Threshold | Side | Positive decision times (doc / builder) | Episodes (doc / builder) | Result |", "|---|---|---|---|---|---|"]
    for h, x in ALL_CELLS:
        for side in SIDES:
            df = built[h][x]
            pos, eps = len(positive_times(df, side)), len(label_episodes(df, side, h))
            dp, de = cells.get((h, round(x * 100), side), (None, None))
            ok = (dp, de) == (pos, eps)
            mismatches += 0 if ok else 1
            dps = "-" if dp is None else format(dp, ",")
            L.append(f"| {h} h | {x * 100:.0f}% | {side} | {dps} / {pos:,} | {de} / {eps} | {'match' if ok else 'MISMATCH'} |")
    vrow = []
    for h in (1, 4, 24):
        n = int(built[h][0.10]["complete"].sum())
        ok = valid.get(h) == n
        mismatches += 0 if ok else 1
        vrow.append(f"{h} h: doc {valid.get(h, 0):,} / builder {n:,} ({'match' if ok else 'MISMATCH'})")
    verdict = "All cells match." if mismatches == 0 else f"{mismatches} cell(s) MISMATCH. Stopped: nothing was adjusted to force a match."
    L += ["", "Valid decision times (complete forward window): " + "; ".join(vrow) + ".", "", f"**{verdict}**", ""]
    if mismatches:
        return "\n".join(L) + "\n", mismatches

    first = pd.Timestamp(m.first_open, unit="ms", tz="UTC").strftime("%Y-%m-%d")
    L += ["## 2. The same counts, split", "",
          "An episode is counted in the part where it STARTS (its first positive decision time), found on the whole series, so one episode is never split. "
          "Positive decision times are counted per part by their own time. Development ends 2026-07-31 00:00 UTC; the 24 hours in between are the embargo "
          "(in neither); the holdout starts 2026-08-01 00:00 UTC. Cliff date: 2026-07-15 (an unverified hypothesis; report only). "
          f"Data starts {first}. Each cell reads: episodes (positive decision times). A part with fewer than {MIN_EPISODES} episodes is marked **FEW**.", ""]
    low: list[str] = []
    for h, x in VIEWS:
        df = built[h][x]
        p = split_periods(df, tokenomics_path)
        parts = [("development", None, DEVELOPMENT_END_MS + 1, p.development), ("embargo", DEVELOPMENT_END_MS + 1, HOLDOUT_START_MS, p.embargo),
                 ("holdout", HOLDOUT_START_MS, None, p.holdout), ("before the cliff", None, p.cliff_ms, p.pre_cliff),
                 ("after the cliff", p.cliff_ms, None, p.post_cliff)]
        L += [f"### {h} h / {x * 100:.0f}%", "", "| Part | Valid decision times | Long | Short |", "|---|---|---|---|"]
        for name, lo, hi, frame in parts:
            row = []
            for side in SIDES:
                pos, ne = _part_counts(df, side, label_episodes(df, side, h), lo, hi)
                few = ne < MIN_EPISODES and name != "embargo"
                if few:
                    low.append(f"{h} h / {x * 100:.0f}% {side}, {name}: {ne} episode(s)")
                row.append(f"{ne} ({pos:,}){' **FEW**' if few else ''}")
            L.append(f"| {name} | {int(frame['complete'].sum()):,} | " + " | ".join(row) + " |")
        L.append("")
        L += ["| Month | Valid decision times | Long | Short |", "|---|---|---|---|"]
        for mo in sorted({_month(t) for t in df.loc[df["complete"], "decision_ms"]}):
            lo, hi = month_bounds(mo)
            row = []
            for side in SIDES:
                pos, ne = _part_counts(df, side, label_episodes(df, side, h), lo, hi)
                row.append(f"{ne} ({pos:,}){' **FEW**' if ne < MIN_EPISODES else ''}")
            nv = int(((df["decision_ms"] >= lo) & (df["decision_ms"] < hi) & df["complete"]).sum())
            L.append(f"| {mo} | {nv:,} | " + " | ".join(row) + " |")
        L.append("")
    L += ["## 3. Where there are too few episodes", "",
          f"Plainly: the parts below have fewer than {MIN_EPISODES} episodes (development, holdout and cliff parts only; single calendar months are marked **FEW** "
          "in the tables above and most are thin). Nothing can be learned or tested honestly from a part with so few independent events.", ""]
    L += [f"- {s}" for s in low] if low else ["- none"]
    L += [""] + decisions_lines()
    return "\n".join(L) + "\n", 0


def main(argv: list[str] | None = None) -> int:
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser(description="Label builder check report (read-only).")
    ap.add_argument("--data-dir", default="data/raw")
    ap.add_argument("--report", default="docs/phase2_labels_check.md")
    ap.add_argument("--doc", default="docs/label_counts.md")
    args = ap.parse_args(argv)
    data_dir, report = Path(args.data_dir), Path(args.report)
    r_res, d_res = report.resolve(), data_dir.resolve()
    if r_res == d_res or d_res in r_res.parents:
        print(f"Refusing: --report must not be inside the data directory {data_dir}.")
        return 2
    path = data_dir / "binance_TACUSDT_1m.csv"
    if not path.exists() or not Path(args.doc).exists():
        print(f"Missing input: {path} or {args.doc}")
        return 2
    text, bad = render_check(path, Path(args.doc).read_text(encoding="utf-8"))
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text, encoding="utf-8")
    print(f"report: {report}; mismatching cells: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
