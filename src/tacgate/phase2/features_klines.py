"""Phase 2 price-based features from 1m klines (Binance perp last price, plus the Bybit perp close for the gap). Features only: no label is read,
nothing is compared with a label, nothing is fitted.

Decision grid: every 5 minutes (the same grid as the labels). At decision time t the candle that closed at t (it opened at t - 60 s) is the newest
candle that may be used: a kline is known at its open + 60 s (loaders.load_klines). The candle that opens at t is never used.

FIXED in advance by the user on 2026-11-21 (proposed by Claude, approved by the user): windows 15 min, 1 h, 4 h, 24 h and a 7 day volume baseline.
They are constants, not parameters of any function.

For a window of w minutes at decision time t, the window is the w candles that opened in [t - w, t); C_t is the close of the newest of them.
  ret_w              C_t / C_(t-w) - 1, C_(t-w) = the close of the candle that closed at t - w (needs w + 1 closes)
  rv_w               standard deviation (ddof = 1) of the w one-minute log returns log(close_i / close_(i-1)) that end inside the window (needs w + 1 closes)
  drawdown_w         C_t / (highest 1m high in the window) - 1          (at most 0)
  runup_w            C_t / (lowest 1m low in the window) - 1            (at least 0)
  range_w            (highest high - lowest low in the window) / C_t
  taker_buy_share_w  taker buy base volume / base volume, summed over the window, klines only (NaN if the window's volume is 0)
  volume_ratio_w     base volume in the window / the mean base volume of all the non-overlapping windows of the same length in the 7 days before the window
                     (the span [t - w - 7 d, t - w), 7 d / w windows)
  bybit_gap          (binance_close_t - bybit_close_t) / binance_close_t, both closes of the candle that closed at t (same open time)
  bybit_gap_abs_max_1h  the largest |gap| over the 60 candles of the last hour (the same gap, candle by candle)

Missing minute: every feature whose inputs include a missing minute is NaN. Not enough history (warm-up, the first 7 days for volume_ratio) is NaN.
Nothing is filled, imputed or interpolated.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from tacgate.phase2 import loaders as ld
from tacgate.phase2.labels import DEVELOPMENT_END_MS

MIN_MS = 60_000
GRID_MIN = 5  # decision times: every 5-minute boundary (the same grid as the labels)
GRID_MS = GRID_MIN * MIN_MS
# FIXED by the user on 2026-11-21 (proposed by Claude, approved by the user). The only window list; nothing else is tunable.
WINDOWS = (("15m", 15), ("1h", 60), ("4h", 240), ("24h", 1440))
BASELINE_DAYS = 7
BYBIT_ABS_MAX_MIN = 60
PAD = max(m for _, m in WINDOWS) + 1  # NaN padding in front of the minute arrays: a window before the first candle is NaN

PER_WINDOW = ("ret", "rv", "drawdown", "runup", "range", "taker_buy_share", "volume_ratio")
SINGLE = ("bybit_gap", "bybit_gap_abs_max_1h")
FEATURE_COLUMNS = tuple(f"{f}_{lab}" for f in PER_WINDOW for lab, _ in WINDOWS) + SINGLE


# -------------------------------------------------------------------- grid ---

def _axis(df: pd.DataFrame) -> tuple[int, int]:
    t = df["ts_ms"].to_numpy(dtype="int64")
    if len(t) == 0:
        raise ValueError("no klines")
    if (t % MIN_MS != 0).any():
        raise ValueError("kline open times must be on minute boundaries")
    if len(np.unique(t)) != len(t):
        raise ValueError("duplicate kline open times")
    return int(t.min()), int((t.max() - t.min()) // MIN_MS) + 1


def _minute_array(df: pd.DataFrame, name: str, first: int, n: int) -> np.ndarray:
    """One column on the minute axis starting at `first`; a minute with no row (or outside the axis) is NaN."""
    a = np.full(n, np.nan)
    idx = (df["ts_ms"].to_numpy(dtype="int64") - first) // MIN_MS
    ok = (idx >= 0) & (idx < n)
    a[idx[ok]] = df[name].to_numpy(dtype="float64")[ok]
    return a


def _padded(a: np.ndarray) -> np.ndarray:
    return np.concatenate([np.full(PAD, np.nan), a])


def _window(P: np.ndarray, js: np.ndarray, width: int, fn, chunk: int = 2000) -> np.ndarray:
    """fn applied to the `width` padded values ending with candle j - 1 (the candle that closes at decision time j), for every row j. fn works along axis 1."""
    view = sliding_window_view(P, width)
    starts = js - width + PAD
    out = np.empty(len(js))
    for a in range(0, len(js), chunk):
        out[a:a + chunk] = fn(view[starts[a:a + chunk]])
    return out


def _check_prices(df: pd.DataFrame, name: str) -> None:
    for c in ("high", "low", "close"):
        if c not in df.columns:
            raise ValueError(f"{name} klines need a {c!r} column")
        if (df[c] <= 0).any():
            raise ValueError(f"{name} klines have a non-positive {c}")


# ---------------------------------------------------------------- features ---

def _ret(v):
    return np.where(np.isnan(v).any(axis=1), np.nan, v[:, -1] / v[:, 0] - 1.0)


def _rv(v):  # v = log closes
    return np.std(np.diff(v, axis=1), axis=1, ddof=1)


def build_features(binance: pd.DataFrame, bybit: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per 5-minute decision time. `binance` and `bybit` are loaders.load_klines tables (ts_ms, high, low, close, volume, taker_buy_base_volume).
    Only candles that opened at least 60 s before the decision time are used. Without `bybit` the Bybit columns are NaN."""
    for c in ("volume", "taker_buy_base_volume"):
        if c not in binance.columns:
            raise ValueError(f"binance klines need a {c!r} column")
    _check_prices(binance, "binance")
    first, n = _axis(binance)
    hi, lo, cl = (_padded(_minute_array(binance, c, first, n)) for c in ("high", "low", "close"))
    vol, tb = (_padded(_minute_array(binance, c, first, n)) for c in ("volume", "taker_buy_base_volume"))
    logc = np.log(cl)  # NaN stays NaN
    j = np.arange(1, n + 1)  # decision time t = first + j minutes; the newest usable candle is candle j - 1
    t = first + j * MIN_MS
    keep = t % GRID_MS == 0
    j, t = j[keep], t[keep]
    c_t = cl[j - 1 + PAD]
    out: dict[str, np.ndarray] = {"decision_ms": t.astype("int64")}
    with np.errstate(invalid="ignore", divide="ignore"):
        for lab, w in WINDOWS:
            hmax, lmin = _window(hi, j, w, lambda v: np.max(v, axis=1)), _window(lo, j, w, lambda v: np.min(v, axis=1))
            sv, st = _window(vol, j, w, lambda v: np.sum(v, axis=1)), _window(tb, j, w, lambda v: np.sum(v, axis=1))
            out[f"ret_{lab}"] = _window(cl, j, w + 1, _ret)
            out[f"rv_{lab}"] = _window(logc, j, w + 1, _rv)
            out[f"drawdown_{lab}"] = c_t / hmax - 1.0
            out[f"runup_{lab}"] = c_t / lmin - 1.0
            out[f"range_{lab}"] = (hmax - lmin) / c_t
            out[f"taker_buy_share_{lab}"] = np.where(sv > 0, st / sv, np.nan)
            step = w // GRID_MIN  # rows per window: the windows of the baseline end at t - k w, which are rows of the same grid
            k_all = BASELINE_DAYS * 24 * 60 // w
            acc = np.zeros(len(j))
            for k in range(1, k_all + 1):
                sh = np.full(len(j), np.nan)
                if k * step < len(j):
                    sh[k * step:] = sv[:len(j) - k * step]
                acc += sh
            base = acc / k_all
            out[f"volume_ratio_{lab}"] = np.where(base > 0, sv / base, np.nan)
        gap = np.full(n, np.nan)
        if bybit is not None and len(bybit):
            _check_prices(bybit, "bybit")
            bc = _minute_array(bybit, "close", first, n)
            gap = (cl[PAD:] - bc) / cl[PAD:]
        out["bybit_gap"] = gap[j - 1]
        out["bybit_gap_abs_max_1h"] = _window(_padded(np.abs(gap)), j, BYBIT_ABS_MAX_MIN, lambda v: np.max(v, axis=1))
    df = pd.DataFrame(out)
    df.insert(1, "known_at_ms", df["decision_ms"])  # a feature row is available at its decision time
    return df[["decision_ms", "known_at_ms", *FEATURE_COLUMNS]]


def development_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Decision times up to 2026-07-31 00:00 UTC. All summary numbers use only these rows."""
    return df[df["decision_ms"] <= DEVELOPMENT_END_MS]


# ------------------------------------------------------------------- report ---

DEFINITIONS = {
    "ret": "close_t / close_(t-w) - 1 (the close of the candle that closed at t - w)",
    "rv": "standard deviation (n - 1) of the w one-minute log returns in the window",
    "drawdown": "close_t / (highest 1m high in the window) - 1; never above 0",
    "runup": "close_t / (lowest 1m low in the window) - 1; never below 0",
    "range": "(highest high - lowest low in the window) / close_t",
    "taker_buy_share": "taker buy base volume / base volume over the window, from the klines only; between 0 and 1; NaN if the window has no volume",
    "volume_ratio": "base volume in the window / mean base volume of the non-overlapping windows of the same length in the 7 days before it",
}


def gap_runs(df: pd.DataFrame) -> list[tuple[int, int]]:
    """(first missing minute open, number of missing minutes) for every hole in a klines table."""
    t = np.sort(df["ts_ms"].to_numpy(dtype="int64"))
    d = np.diff(t)
    return [(int(t[i] + MIN_MS), int(d[i] // MIN_MS - 1)) for i in np.flatnonzero(d > MIN_MS)]


def _fmt(x: float) -> str:
    return "NaN" if not np.isfinite(x) else (f"{x:.4g}" if abs(x) < 1e-3 or abs(x) >= 1e5 else f"{x:.4f}")


def decisions_lines() -> list[str]:
    return ["## Decisions", "",
            "**Decided by the user:**", "",
            "- The windows (15 min, 1 h, 4 h, 24 h) and the 7 day volume baseline were fixed in advance by the user on 2026-11-21 (proposed by Claude, approved by the user). "
            "They are constants in `features_klines.py`, not parameters.",
            "- No feature is compared with any label in this task: no correlation, AUC or hit rate. Summary numbers use the development period only.", "",
            "**OPEN (not decided):**", "",
            "- Whether each feature should later be built from the mark price instead of the last price (mark klines are not downloaded yet).",
            "- How to treat `bybit_gap` when Bybit data has gaps. Today a missing Bybit minute makes it NaN; a Bybit candle with zero volume is used as it is "
            "(its close is the last traded price, possibly stale).",
            "- Whether a volume baseline with a missing minute should stay NaN for 7 days (today's strict rule) or skip only the affected baseline windows. "
            "It does not matter on the current data (no missing minute), but it will after the first gap.", ""]


def render_check(binance_path: Path, bybit_path: Path) -> str:
    b, y = ld.load_klines(binance_path, "binance"), ld.load_klines(bybit_path, "bybit")
    f = build_features(b, y)
    dev = development_rows(f)
    first = pd.Timestamp(int(b.ts_ms.min()), unit="ms", tz="UTC").strftime("%Y-%m-%d %H:%M")
    last = pd.Timestamp(int(b.ts_ms.max()), unit="ms", tz="UTC").strftime("%Y-%m-%d %H:%M")
    gb, gy = gap_runs(b), gap_runs(y)
    L = ["# Phase 2 price-based features check", "",
         f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d')} (UTC) by `python -m tacgate.phase2.features_klines`. Read-only. Features only: no label is read, "
         "nothing is compared with a label, nothing is fitted. Source: Binance TACUSDT perpetual 1m last-price klines "
         f"({first} to {last} UTC) and Bybit TACUSDT perpetual 1m klines, through `loaders.load_klines`.", "",
         "## 1. Rules", "",
         "- Decision times: every 5 minutes, the same grid as the labels. A kline is known at its open + 60 seconds, so at decision time t the candle that closed at t "
         "(opened at t - 60 s) is the newest one used. The candle that opens at t is never used.",
         "- **Fixed windows: 15 minutes, 1 hour, 4 hours, 24 hours. Volume baseline: 7 days.** They were fixed in advance by the user on 2026-11-21 "
         "(proposed by Claude, approved by the user) and are one constant (`WINDOWS`) in the code. Nothing else is a parameter.",
         "- A missing minute inside the inputs of a feature makes that feature NaN. Not enough history yet (warm-up) is NaN. Nothing is filled, imputed or interpolated.", "",
         "## 2. The features", "", "| Feature | Columns | Definition (w = the window) |", "|---|---|---|"]
    for name in PER_WINDOW:
        L.append(f"| {name} | " + ", ".join(f"`{name}_{lab}`" for lab, _ in WINDOWS) + f" | {DEFINITIONS[name]} |")
    L += ["| bybit_gap | `bybit_gap` | (binance close_t - bybit close_t) / binance close_t, both candles opened at t - 60 s |",
          "| bybit_gap_abs_max_1h | `bybit_gap_abs_max_1h` | the largest absolute gap over the 60 candles of the last hour (NaN if any of them is missing) |", "",
          "A window of w minutes is the w candles opened in [t - w, t). `ret` and `rv` need one more close (w + 1 closes), because they start from the close of the candle before the window. "
          "The window labels are 15m, 1h, 4h and 24h.", "",
          "## 3. Candle gaps (days that cause NaN)", "",
          f"- Binance 1m klines: {len(b):,} candles, **{len(gb)} gaps** ({sum(n for _, n in gb)} missing minutes).",
          f"- Bybit 1m klines: {len(y):,} candles, **{len(gy)} gaps** ({sum(n for _, n in gy)} missing minutes). Bybit starts "
          f"{pd.Timestamp(int(y.ts_ms.min()), unit='ms', tz='UTC').strftime('%Y-%m-%d %H:%M')} UTC and ends "
          f"{pd.Timestamp(int(y.ts_ms.max()), unit='ms', tz='UTC').strftime('%Y-%m-%d %H:%M')} UTC; candles after the last Binance candle are not used.", ""]
    for name, g in (("Binance", gb), ("Bybit", gy)):
        for s, k in g:
            L.append(f"- {name}: {k} missing minute(s) from {pd.Timestamp(s, unit='ms', tz='UTC').strftime('%Y-%m-%d %H:%M')} UTC")
    if not gb and not gy:
        L.append("So no candle-gap day causes any NaN. Every NaN below is warm-up (the first window, the first 7 days for the volume ratio, and the first 30 minutes of Bybit data) "
                 "or a window with no volume at all.")
    zv = int((y.zero_volume).sum())
    L += ["", f"Bybit candles with zero volume: {zv:,} of {len(y):,} ({100 * zv / len(y):.1f}%); Binance: {int(b.zero_volume.sum()):,} of {len(b):,}. "
          "They are real rows (not missing), so they are used as they are; the Bybit close of a zero-volume candle may be stale. See OPEN below.", "",
          "## 4. NaN counts", "",
          f"All {len(f):,} decision times, of which {len(dev):,} are in the development period (up to 2026-07-31 00:00 UTC). The NaN rows are the warm-up at the start of the data.", "",
          "| Feature | NaN, all decision times | NaN, development period |", "|---|---|---|"]
    for c in FEATURE_COLUMNS:
        L.append(f"| `{c}` | {int(f[c].isna().sum()):,} | {int(dev[c].isna().sum()):,} |")
    L += ["", "## 5. Summary numbers (development period only: decision times up to 2026-07-31 00:00 UTC)", "",
          "Minimum, median and maximum of the values that are not NaN. Nothing from the holdout is summarised.", "",
          "| Feature | Minimum | Median | Maximum |", "|---|---|---|---|"]
    for c in FEATURE_COLUMNS:
        v = dev[c].dropna()
        L.append(f"| `{c}` | " + " | ".join(_fmt(x) for x in ((v.min(), v.median(), v.max()) if len(v) else (np.nan,) * 3)) + " |")
    inv = []
    for lab, _ in WINDOWS:
        inv.append((f"taker_buy_share_{lab} between 0 and 1", bool(dev[f"taker_buy_share_{lab}"].dropna().between(0, 1).all())))
        inv.append((f"drawdown_{lab} at most 0", bool((dev[f"drawdown_{lab}"].dropna() <= 0).all())))
        inv.append((f"runup_{lab} at least 0", bool((dev[f"runup_{lab}"].dropna() >= 0).all())))
    L += ["", "Bounds on the development period: " + "; ".join(f"{k}: {'holds' if ok else 'VIOLATED'}" for k, ok in inv) + ".", ""]
    L += decisions_lines()
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Price-based feature check report (read-only; no labels).")
    ap.add_argument("--data-dir", default="data/raw")
    ap.add_argument("--report", default="docs/phase2_features_check.md")
    args = ap.parse_args(argv)
    data_dir, report = Path(args.data_dir), Path(args.report)
    r_res, d_res = report.resolve(), data_dir.resolve()
    if r_res == d_res or d_res in r_res.parents:
        print(f"Refusing: --report must not be inside the data directory {data_dir}.")
        return 2
    bp, yp = data_dir / "binance_TACUSDT_1m.csv", data_dir / "bybit_TACUSDT_1m.csv"
    if not bp.exists() or not yp.exists():
        print(f"Missing input: {bp} or {yp}")
        return 2
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_check(bp, yp), encoding="utf-8")
    print(f"report: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
