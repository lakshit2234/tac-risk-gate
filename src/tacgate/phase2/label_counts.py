"""Read-only count table for the Phase 2 risk-event label. Counts only: no features, no model, nothing is evaluated.

Label (docs/phase2_plan.md, section 2). A decision time t is every 5-minute boundary. C_t is the close of the 1m candle that ends at t. Over the
next H hours (the 1m candles opening in [t, t + H)):
  * a LONG is hit when the lowest low falls to C_t * (1 - x) or lower (adverse = fall of at least x);
  * a SHORT is hit when the highest high rises to C_t * (1 + x) or higher (adverse = spike of at least x).
A decision time is "positive" for a side when that side is hit. Positive decision times closer together than H are merged into one EPISODE, so
overlapping horizons are not counted as separate events.

It reads our Binance perp 1m klines (a proxy for the mark price, whose klines are not downloaded yet). It never writes to the data folder.

Run: python -m tacgate.phase2.label_counts [--data-dir data/raw] [--report docs/label_counts.md]
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from tacgate.data import binance_klines as bk
from tacgate.data.bulk_availability import read_complete
from tacgate.phase2.labels import Minutes, adverse_frame, episodes, forward_extreme, minutes_from_klines  # noqa: F401  (re-exported; one implementation)

MIN_MS = 60_000
GRID_MS = 300_000  # decision times: every 5-minute boundary
HOUR_MS = 3_600_000
DEFAULT_DATA_DIR = Path("data/raw")
DEFAULT_REPORT = Path("docs/label_counts.md")
# PROPOSALS (docs/phase2_plan.md): candidate horizons in hours and candidate adverse-move thresholds as fractions. Not decided.
HORIZONS_H = (1, 4, 24)
THRESHOLDS = (0.10, 0.20, 0.30)
SIDES = ("long", "short")
# PROPOSAL holdout windows, [start, end) in UTC dates, only used to COUNT the episodes each would contain.
PROPOSED_WINDOWS = {
    "A: last 3 months (2026-09-01 to the end)": ("2026-09-01", "2100-01-01"),
    "B: last 4 months (2026-08-01 to the end)": ("2026-08-01", "2100-01-01"),
    "C: last 5 months (2026-07-01 to the end)": ("2026-07-01", "2100-01-01"),
}


def utc_ms(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp() * 1000)


def month_of(ms: int | float) -> str:
    return pd.Timestamp(int(ms), unit="ms", tz="UTC").strftime("%Y-%m")


# ----------------------------------------------------------------- loading ---

def load_minutes(path: Path) -> Minutes:
    """The 1m klines file as a minute grid (a missing minute is NaN). The grid itself is built by the label builder (labels.minutes_from_klines)."""
    df = read_complete(Path(path))
    k = pd.DataFrame({"ts_ms": pd.to_numeric(df["open_time"]).astype("int64"), "high": pd.to_numeric(df["high"]),
                      "low": pd.to_numeric(df["low"]), "close": pd.to_numeric(df["close"])})
    return minutes_from_klines(k)


# ------------------------------------------------------------------- labels ---

@dataclass
class Adverse:
    t_ms: np.ndarray  # decision times with a complete forward window and a known C_t
    adverse_long: np.ndarray  # lowest low in the window / C_t - 1  (<= 0)
    adverse_short: np.ndarray  # highest high in the window / C_t - 1  (>= 0)


def adverse_moves(m: Minutes, horizon_h: int) -> Adverse:
    """The worst move against a long and against a short in the H hours after each decision time (every 5-minute boundary).

    This is the label builder (labels.adverse_frame) restricted to the complete rows, so the count table and the label table cannot disagree."""
    f = adverse_frame(m, horizon_h, step_min=GRID_MS // MIN_MS)
    f = f[f["complete"]]
    return Adverse(f["decision_ms"].to_numpy(), f["adverse_long"].to_numpy(), f["adverse_short"].to_numpy())


def positives(a: Adverse, side: str, threshold: float) -> np.ndarray:
    """Decision times (ms) at which the side would have been hit within the horizon."""
    mask = a.adverse_long <= -threshold if side == "long" else a.adverse_short >= threshold
    return a.t_ms[mask]


# ------------------------------------------------------------------ counting ---

def count_table(m: Minutes, horizons=HORIZONS_H, thresholds=THRESHOLDS) -> dict:
    """Everything the plan needs, as plain numbers: per horizon/threshold/side the positive decision times and episodes, per month."""
    out = {"first_open": m.first_open, "last_open": m.first_open + (m.n - 1) * MIN_MS, "horizons": {}}
    for h in horizons:
        a = adverse_moves(m, h)
        months = pd.Series([month_of(t) for t in a.t_ms])
        valid_by_month = months.value_counts().sort_index().to_dict()
        entry = {"valid_decision_times": int(len(a.t_ms)), "valid_by_month": {k: int(v) for k, v in valid_by_month.items()}, "cells": {}}
        for x in thresholds:
            for side in SIDES:
                pos = positives(a, side, x)
                eps = episodes(pos, h)
                pm = pd.Series([month_of(t) for t in pos]).value_counts().sort_index().to_dict() if len(pos) else {}
                em = pd.Series([month_of(e[0]) for e in eps]).value_counts().sort_index().to_dict() if eps else {}
                entry["cells"][(x, side)] = {"positive": int(len(pos)), "episodes": eps, "positive_by_month": {k: int(v) for k, v in pm.items()},
                                             "episodes_by_month": {k: int(v) for k, v in em.items()}}
        out["horizons"][h] = entry
    return out


def episodes_in_window(eps: list[tuple[int, int, int]], start_ms: int, end_ms: int) -> int:
    """Episodes that START inside [start, end)."""
    return sum(1 for s, _, _ in eps if start_ms <= s < end_ms)


def window_counts(table: dict, windows: dict[str, tuple[str, str]] = PROPOSED_WINDOWS) -> dict:
    out = {}
    for name, (a, b) in windows.items():
        lo, hi = utc_ms(a), utc_ms(b)
        row = {}
        for h, entry in table["horizons"].items():
            for (x, side), cell in entry["cells"].items():
                row[(h, x, side)] = episodes_in_window(cell["episodes"], lo, hi)
        out[name] = row
    return out


# ------------------------------------------------------------------- report ---

def render(table: dict, windows: dict) -> str:
    L = ["# Risk-event label counts (counts only)", "",
         f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d')} (UTC) by `python -m tacgate.phase2.label_counts` from our Binance perp 1m klines "
         f"({pd.Timestamp(table['first_open'], unit='ms', tz='UTC').strftime('%Y-%m-%d %H:%M')} to "
         f"{pd.Timestamp(table['last_open'], unit='ms', tz='UTC').strftime('%Y-%m-%d %H:%M')} UTC). Read-only; no feature, no model. "
         "The horizons and thresholds are PROPOSALS from docs/phase2_plan.md, not decisions.", "",
         "A decision time is every 5-minute boundary. A decision time is positive for a long when the lowest low in the next H hours is at least x below the close at "
         "that time, and for a short when the highest high is at least x above it. Positive decision times closer than H are merged into one episode "
         "(counted in the month the episode starts). Positive decision times of one crash overlap heavily, so they are NOT independent samples: "
         "the number of episodes is the honest count.", "", "## Overall", "",
         "| Horizon | Threshold | Side | Positive decision times | Share of valid decision times | Episodes |", "|---|---|---|---|---|---|"]
    for h, entry in table["horizons"].items():
        for (x, side), cell in entry["cells"].items():
            L.append(f"| {h} h | {100 * x:.0f}% | {side} | {cell['positive']:,} | {100 * cell['positive'] / entry['valid_decision_times']:.2f}% | {len(cell['episodes'])} |")
    L += ["", "Valid decision times (complete forward window): " + ", ".join(f"{h} h: {e['valid_decision_times']:,}" for h, e in table["horizons"].items()) + ".", "",
          "## Per calendar month: episodes (positive decision times)", ""]
    for h, entry in table["horizons"].items():
        months = sorted(entry["valid_by_month"])
        cols = sorted(entry["cells"])
        L += [f"### Horizon {h} h", "", "| Month | Valid decision times | " + " | ".join(f"{100 * x:.0f}% {s}" for x, s in cols) + " |", "|---|---|" + "---|" * len(cols)]
        for mo in months:
            cells = []
            for x, s in cols:
                c = entry["cells"][(x, s)]
                cells.append(f"{c['episodes_by_month'].get(mo, 0)} ({c['positive_by_month'].get(mo, 0)})")
            L.append(f"| {mo} | {entry['valid_by_month'][mo]:,} | " + " | ".join(cells) + " |")
        L.append("")
    L += ["## Episodes that START inside each proposed holdout window", ""]
    keys = [(h, x, s) for h, e in table["horizons"].items() for (x, s) in sorted(e["cells"])]
    L += ["| Window | " + " | ".join(f"{h} h {100 * x:.0f}% {s}" for h, x, s in keys) + " |", "|---|" + "---|" * len(keys)]
    for name, row in windows.items():
        L.append(f"| {name} | " + " | ".join(str(row[k]) for k in keys) + " |")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only label count table for the Phase 2 plan.")
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    args = ap.parse_args(argv)
    data_dir, report = Path(args.data_dir), Path(args.report)
    r_res, d_res = report.resolve(), data_dir.resolve()
    if r_res == d_res or d_res in r_res.parents:
        print(f"Refusing: --report must not be inside the data directory {data_dir}.")
        return 2
    path = data_dir / bk.DEFAULT_OUT.name
    if not path.exists():
        print(f"Klines file not found: {path}")
        return 2
    m = load_minutes(path)
    table = count_table(m)
    wc = window_counts(table)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render(table, wc), encoding="utf-8")
    for h, entry in table["horizons"].items():
        print(f"{h:>2} h: " + "  ".join(f"{100 * x:.0f}%/{s[0]}: {len(entry['cells'][(x, s)]['episodes'])}" for x in THRESHOLDS for s in SIDES))
    print(f"report: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
