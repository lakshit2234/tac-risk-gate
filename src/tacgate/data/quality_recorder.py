"""Gate 1: data quality checker for the forward recorder files.

Checks the 4 history files (open interest, global long/short, top-position
long/short, taker buy/sell) and the snapshot file written by recorder.py.

STRICTLY READ-ONLY. The recorder may be running and appending right now, so each
file is read ONCE into memory, a partial last line is ignored, and nothing is
locked, rewritten, cleaned or filled. Odd values are flagged, never clipped.
No network. Only data-integrity problems are hard failures; gaps (PC off or
asleep) and value oddities are warnings.

Run: python -m tacgate.data.quality_recorder [--dir data/raw] [--report docs/quality_recorder_report.md]
Exit code: 0 = pass (warnings allowed), 1 = hard failure, 2 = file error.
"""
from __future__ import annotations

import argparse
import io
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from tacgate.data.binance_klines import now_ms
from tacgate.data.quality_klines import ms_to_utc
from tacgate.data.recorder import DATASETS, PERIOD_MS, SNAPSHOT_COLUMNS, Dataset, snapshot_path

DEFAULT_DIR = Path("data/raw")
DEFAULT_REPORT = Path("docs/quality_recorder_report.md")
BACKFILL_LAG_MS = 15 * 60_000  # fetched_at_ms - timestamp above this = BACKFILLED, else LIVE
SNAPSHOT_SPACING_MS = 300_000
SNAPSHOT_GAP_MS = 10 * 60_000  # snapshot gaps above this are listed
STALE_MINUTES = 15
SHARE_TOL = 0.001  # longAccount + shortAccount must be within this of 1
RATIO_REL_TOL = 0.01  # ratio vs recomputed ratio (values are rounded to 4 decimals)
RATIO_ABS_TOL = 0.001
MARK_INDEX_TOL = 0.05
CLOCK_SKEW_TOL_MS = 2_000
TOP_EXTREMES = 5
MAIN_VALUE = {
    "open_interest": "sumOpenInterest",
    "global_long_short": "longShortRatio",
    "top_position_long_short": "longShortRatio",
    "taker_buy_sell": "buySellRatio",
}
SLIPPAGE_COLS = [c for c in SNAPSHOT_COLUMNS if c.startswith("slippage_bps_")]
DEPTH_COLS = [c for c in SNAPSHOT_COLUMNS if "_depth_usd_" in c]


@dataclass
class Result:
    directory: str
    now: int
    hard_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    datasets: dict[str, dict] = field(default_factory=dict)
    snapshot: dict = field(default_factory=dict)
    running: dict = field(default_factory=dict)
    log_summary: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.hard_failures


class FileProblem(Exception):
    """A file is missing or unreadable (exit code 2)."""


# ----------------------------------------------------------------- loading ---

def read_once(path: Path) -> tuple[bytes, int]:
    """Read the whole file once. Returns (complete lines only, bytes ignored from a partial last line)."""
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise FileProblem(f"Cannot read {path}: {exc}") from exc
    if not data:
        return b"", 0
    cut = data.rfind(b"\n") + 1  # 0 if there is no newline at all
    return data[:cut], len(data) - cut


def load_frame(path: Path, columns: list[str], label: str, res: Result) -> pd.DataFrame | None:
    """Read a CSV once, ignore a partial last line, return all-string frame or None on a schema failure."""
    data, ignored = read_once(path)
    if ignored:
        res.warnings.append(f"{label}: ignored a partial last line ({ignored} bytes), probably being written right now")
    if not data:
        res.hard_failures.append(f"{label} schema: file is empty (no complete header line)")
        return None
    try:
        df = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
        res.hard_failures.append(f"{label} schema: malformed CSV ({exc})")
        return None
    if list(df.columns) != columns:
        res.hard_failures.append(f"{label} schema: expected columns {columns}, got {list(df.columns)}")
        return None
    if df.empty:
        res.hard_failures.append(f"{label} schema: header but no data rows")
        return None
    return df


def to_numeric(df: pd.DataFrame, label: str, res: Result, allow_blank: list[str] | None = None,
               skip: tuple[str, ...] = ("symbol",)) -> pd.DataFrame:
    """Parse every column numeric (except `skip`). Blank/NaN cells are a hard failure unless allow_blank."""
    out = df.copy()
    allow_blank = allow_blank or []
    for c in out.columns:
        if c in skip:
            continue
        num = pd.to_numeric(out[c], errors="coerce")
        n = int(num.isna().sum())
        if c in allow_blank:
            blanks = int((out[c] == "").sum())
            non_blank_bad = n - blanks
            if non_blank_bad:
                res.hard_failures.append(f"{label}: {non_blank_bad} non-numeric (not blank) value(s) in {c}")
        elif n:
            res.hard_failures.append(f"{label}: {n} NaN/blank/non-numeric value(s) in {c}")
        out[c] = num
    return out


def distribution(steps: np.ndarray, unit_ms: int, ndigits: int) -> pd.Series:
    return pd.Series(np.round(steps / unit_ms, ndigits)).value_counts().sort_index().rename("count")


# ---------------------------------------------------------- history files ---

def check_history(ds: Dataset, directory: Path, res: Result) -> None:
    label = ds.name
    path = ds.csv_path(directory)
    df = load_frame(path, ds.columns, label, res)
    if df is None:
        return
    df = to_numeric(df, label, res)
    if "symbol" in df and (df["symbol"] != "TACUSDT").any():
        res.warnings.append(f"{label}: symbol other than TACUSDT present: {sorted(df['symbol'].unique())}")
    if df[["timestamp", "fetched_at_ms"]].isna().any().any():
        return  # cannot analyse time on unparseable timestamps (hard failure already recorded)
    df["timestamp"] = df["timestamp"].astype("int64")
    df["fetched_at_ms"] = df["fetched_at_ms"].astype("int64")
    t, f = df["timestamp"].to_numpy(), df["fetched_at_ms"].to_numpy()
    info: dict = {"rows": len(df)}
    res.datasets[label] = info

    dup = int(df["timestamp"].duplicated().sum())
    if dup:
        res.hard_failures.append(f"{label}: {dup} duplicate timestamp(s)")
    steps = np.diff(t)
    backwards = int((steps < 0).sum())
    if backwards:
        res.hard_failures.append(f"{label}: timestamp not monotonic ({backwards} step(s) go backwards)")
    if int((np.diff(f) < 0).sum()):
        res.warnings.append(f"{label}: fetched_at_ms goes backwards {int((np.diff(f) < 0).sum())} time(s) (clock change?)")

    # spacing, gaps, coverage (the 5-minute spacing is the reference; nothing is filled)
    fwd = steps[steps > 0]
    info["distribution"] = distribution(fwd, 60_000, 1) if fwd.size else None
    idx = np.nonzero(steps > PERIOD_MS)[0]
    gaps = [(int(t[i]), int(t[i + 1]), int(round(steps[i] / PERIOD_MS)) - 1) for i in idx]
    info["gaps"] = gaps
    info["missing_slots"] = sum(g[2] for g in gaps)
    first, last = int(t.min()), int(t.max())
    expected = int(round((last - first) / PERIOD_MS)) + 1
    info.update(first=first, last=last, expected=expected, coverage=100.0 * len(df) / expected)
    if gaps:
        res.warnings.append(
            f"{label}: {len(gaps)} gap(s) above 5 min, {info['missing_slots']:,} slot(s) missing, "
            f"coverage {info['coverage']:.2f}% ({len(df):,} of {expected:,} slots)"
        )

    # backfilled vs live, and the look-ahead check
    lag = f - t
    live = lag <= BACKFILL_LAG_MS
    bf = ~live
    info["backfilled"] = _group(t, bf)
    info["live"] = _group(t, live)
    if live.any():
        first_live = int(t[live].min())
        exp_to_last = int(round((last - first_live) / PERIOD_MS)) + 1
        exp_to_now = max(1, int((res.now - first_live) // PERIOD_MS) + 1)
        info["live_coverage_to_last"] = 100.0 * int(live.sum()) / exp_to_last
        info["live_coverage_to_now"] = 100.0 * int(live.sum()) / exp_to_now
        info["live_median_lag_min"] = float(np.median(lag[live])) / 60_000
    info["median_lag_min_all"] = float(np.median(lag)) / 60_000
    violations = int((lag < 0).sum())
    info["lookahead_violations"] = violations
    if violations:
        res.hard_failures.append(
            f"{label}: look-ahead, {violations} live row(s) with fetched_at_ms < timestamp (known before it existed)"
        )

    _consistency(ds, df, info, res)
    _stats(ds, df, info)


def _group(t: np.ndarray, mask: np.ndarray) -> dict:
    n = int(mask.sum())
    return {"count": n, "first": int(t[mask].min()) if n else None, "last": int(t[mask].max()) if n else None}


def _flag(info: dict, res: Result, label: str, msg: str, n: int, examples: pd.Series | None = None) -> None:
    info.setdefault("flags", []).append((msg, n))
    if n:
        ex = f" (e.g. {', '.join(ms_to_utc(x) for x in examples.head(3))})" if examples is not None else ""
        res.warnings.append(f"{label}: flag, {n:,} row(s) {msg}{ex}")


def _consistency(ds: Dataset, df: pd.DataFrame, info: dict, res: Result) -> None:
    lbl = ds.name
    if ds.name in ("global_long_short", "top_position_long_short"):
        bad_sum = (df["longAccount"] + df["shortAccount"] - 1).abs() > SHARE_TOL
        _flag(info, res, lbl, f"where longAccount + shortAccount is not within {SHARE_TOL} of 1", int(bad_sum.sum()), df.loc[bad_sum, "timestamp"])
        with np.errstate(divide="ignore", invalid="ignore"):
            calc = df["longAccount"] / df["shortAccount"]
        diff = (df["longShortRatio"] - calc).abs()
        bad = ~((diff <= RATIO_ABS_TOL) | (diff <= RATIO_REL_TOL * df["longShortRatio"].abs()))
        _flag(info, res, lbl, "where longShortRatio differs from longAccount / shortAccount", int(bad.sum()), df.loc[bad, "timestamp"])
    elif ds.name == "taker_buy_sell":
        with np.errstate(divide="ignore", invalid="ignore"):
            calc = df["buyVol"] / df["sellVol"]
        diff = (df["buySellRatio"] - calc).abs()
        bad = ~((diff <= RATIO_ABS_TOL) | (diff <= RATIO_REL_TOL * df["buySellRatio"].abs()))
        _flag(info, res, lbl, "where buySellRatio differs from buyVol / sellVol", int(bad.sum()), df.loc[bad, "timestamp"])
    elif ds.name == "open_interest":
        bad = ~(df["sumOpenInterest"] > 0)
        _flag(info, res, lbl, "where sumOpenInterest is not > 0", int(bad.sum()), df.loc[bad, "timestamp"])


def _stats(ds: Dataset, df: pd.DataFrame, info: dict) -> None:
    col = MAIN_VALUE[ds.name]
    v = df[col].dropna()
    if v.empty:
        return
    med = float(v.median())
    far = (v - med).abs().sort_values(ascending=False).index[:TOP_EXTREMES]
    info["stats"] = {
        "col": col, "min": float(v.min()), "max": float(v.max()), "median": med,
        "extremes": df.loc[far, ["timestamp", col]].reset_index(drop=True),
    }


# ----------------------------------------------------------- snapshot file ---

def check_snapshot(directory: Path, res: Result) -> None:
    label = "snapshot"
    df = load_frame(snapshot_path(directory), SNAPSHOT_COLUMNS, label, res)
    if df is None:
        return
    df = to_numeric(df, label, res, allow_blank=SLIPPAGE_COLS, skip=())
    if df["fetched_at_ms"].isna().any():
        return
    f = df["fetched_at_ms"].astype("int64").to_numpy()
    info: dict = {"rows": len(df)}
    res.snapshot = info

    dup = int(pd.Series(f).duplicated().sum())
    if dup:
        res.hard_failures.append(f"{label}: {dup} duplicate fetched_at_ms value(s)")
    steps = np.diff(f)
    if int((steps < 0).sum()):
        res.hard_failures.append(f"{label}: fetched_at_ms not monotonic ({int((steps < 0).sum())} step(s) go backwards)")

    fwd = steps[steps > 0]
    info["distribution"] = distribution(fwd, 1000, 0) if fwd.size else None  # seconds
    idx = np.nonzero(steps > SNAPSHOT_GAP_MS)[0]
    info["gaps"] = [(int(f[i]), int(f[i + 1])) for i in idx]
    first, last = int(f.min()), int(f.max())
    expected = int((last - first) // SNAPSHOT_SPACING_MS) + 1
    info.update(first=first, last=last, expected=expected, coverage=100.0 * len(df) / expected)
    info["span_hours"] = (last - first) / 3_600_000
    info["covered_hours"] = float(steps[(steps > 0) & (steps <= SNAPSHOT_GAP_MS)].sum()) / 3_600_000
    if info["gaps"]:
        res.warnings.append(
            f"{label}: {len(info['gaps'])} gap(s) above 10 min; coverage {info['coverage']:.1f}% of 5-min slots "
            f"({len(df):,} rows; rows from a shorter test interval raise this)"
        )

    crossed = df["best_bid"] >= df["best_ask"]
    if int(crossed.sum()):
        res.hard_failures.append(f"{label}: {int(crossed.sum())} crossed book row(s) (best_bid >= best_ask)")
    info["flags"] = []

    def flag(msg: str, mask: pd.Series) -> None:
        n = int(mask.sum())
        info["flags"].append((msg, n))
        if n:
            res.warnings.append(f"{label}: flag, {n:,} row(s) {msg}")

    flag("with spread_bps <= 0", df["spread_bps"] <= 0)
    flag("with a negative depth value", (df[DEPTH_COLS] < 0).any(axis=1))
    for side in ("buy", "sell"):
        a, b = df[f"slippage_bps_{side}_1000"], df[f"slippage_bps_{side}_5000"]
        flag(f"where {side} slippage for 5000 is below 1000", (b < a) & a.notna() & b.notna())
    flag(f"where mark and index differ by more than {MARK_INDEX_TOL:.0%}", (df["mark"] / df["index"] - 1).abs() > MARK_INDEX_TOL)
    flag("where nextFundingTime is not after fetched_at_ms", df["nextFundingTime"] <= df["fetched_at_ms"])
    flag(f"where the local clock is more than {CLOCK_SKEW_TOL_MS // 1000}s behind server_time_ms", df["server_time_ms"] - df["fetched_at_ms"] > CLOCK_SKEW_TOL_MS)

    info["filled_ok_share"] = float((df["filled_ok"] == 1).mean()) * 100
    info["blank_slippage_cells"] = int(df[SLIPPAGE_COLS].isna().sum().sum())
    info["spread_median_bps"] = float(df["spread_bps"].median())


def check_running(res: Result) -> None:
    last = res.snapshot.get("last")
    if last is None:
        return
    age = (res.now - last) / 60_000
    res.running = {"newest": last, "age_min": age, "ok": age <= STALE_MINUTES}
    if age > STALE_MINUTES:
        res.warnings.append(f"Recorder may be stopped: newest snapshot row is {age:,.0f} min old (limit {STALE_MINUTES})")


def summarize_log(directory: Path, res: Result) -> None:
    path = Path(directory) / "recorder_errors.log"
    if not path.exists():
        res.log_summary = {"lines": 0, "kinds": {}, "last": []}
        return
    data, _ = read_once(path)
    lines = [ln for ln in data.decode("utf-8", errors="replace").splitlines() if ln.strip()]
    kinds: dict[str, int] = {}
    for ln in lines:
        parts = ln.split(" | ", 2)
        kinds[parts[1] if len(parts) > 1 else "?"] = kinds.get(parts[1] if len(parts) > 1 else "?", 0) + 1
    res.log_summary = {"lines": len(lines), "kinds": kinds, "last": lines[-5:]}


def run_checks(directory: Path, now: int | None = None) -> Result:
    res = Result(str(directory), now_ms() if now is None else now)
    for ds in DATASETS:
        check_history(ds, Path(directory), res)
    check_snapshot(Path(directory), res)
    check_running(res)
    summarize_log(Path(directory), res)
    return res


# ------------------------------------------------------------------ report ---

def _ts(ms) -> str:
    return "n/a" if ms is None else ms_to_utc(ms)


def render_report(res: Result) -> str:
    L = ["# Recorder data quality report (Gate 1)", ""]
    L += [f"- Directory: `{res.directory}` (read-only; each file read once; a partial last line is ignored)"]
    L += [f"- Checked at: {_ts(res.now)}", f"- Verdict: **{'PASS' if res.passed else 'FAIL'}**", ""]
    if res.running:
        r = res.running
        L += ["## Is the recorder running?", "",
              f"- Newest snapshot row: {_ts(r['newest'])} ({r['age_min']:,.1f} min ago). "
              + ("Looks running." if r["ok"] else f"**Recorder may be stopped** (older than {STALE_MINUTES} min).")]
        ls = res.log_summary
        if ls:
            L += [f"- recorder_errors.log: {ls['lines']} line(s) {ls['kinds']}"] + [f"  - `{x}`" for x in ls["last"]]
        L += [""]
    L += ["## Hard failures", ""] + ([f"- {m}" for m in res.hard_failures] or ["- none"])
    L += ["", "## Warnings and flags", ""] + ([f"- {m}" for m in res.warnings] or ["- none"])

    for name, d in res.datasets.items():
        L += ["", f"## History: {name}", ""]
        L += [
            f"- Rows: {d['rows']:,}; first {_ts(d['first'])}, last {_ts(d['last'])}",
            f"- Expected slots at 5 min: {d['expected']:,}; coverage {d['coverage']:.2f}%; missing slots {d['missing_slots']:,}",
        ]
        bf, lv = d["backfilled"], d["live"]
        L += [
            f"- BACKFILLED (fetched_at_ms - timestamp > 15 min): {bf['count']:,} rows, {_ts(bf['first'])} to {_ts(bf['last'])}",
            f"- LIVE: {lv['count']:,} rows, {_ts(lv['first'])} to {_ts(lv['last'])}",
        ]
        if "live_coverage_to_last" in d:
            L += [
                f"- Live coverage since the first live row: {d['live_coverage_to_last']:.2f}% (to the last row), "
                f"{d['live_coverage_to_now']:.2f}% (to now)",
                f"- Median fetched_at_ms - timestamp: live {d['live_median_lag_min']:.2f} min, all rows {d['median_lag_min_all']:.1f} min",
            ]
        L += [f"- Look-ahead violations (fetched before the timestamp): {d['lookahead_violations']}"]
        if d["distribution"] is not None:
            L += ["", "Spacing distribution (minutes between consecutive timestamps):", "", "| Minutes | Count |", "|---|---|"]
            L += [f"| {m:g} | {int(c):,} |" for m, c in d["distribution"].items()]
        L += ["", f"Gaps above 5 min ({len(d['gaps'])}):", ""]
        if d["gaps"]:
            L += ["| From (UTC) | To (UTC) | Missing slots |", "|---|---|---|"]
            L += [f"| {_ts(a)} | {_ts(b)} | {m:,} |" for a, b, m in d["gaps"]]
        else:
            L += ["none"]
        if d.get("flags"):
            L += ["", "Consistency (flag only): " + "; ".join(f"{m}: {n:,}" for m, n in d["flags"])]
        s = d.get("stats")
        if s:
            L += ["", f"`{s['col']}`: min {s['min']}, max {s['max']}, median {s['median']}", "",
                  f"Top {TOP_EXTREMES} furthest from the median (flagged, not clipped):", "", "| Time (UTC) | Value |", "|---|---|"]
            L += [f"| {_ts(int(r.timestamp))} | {getattr(r, s['col'])} |" for r in s["extremes"].itertuples()]

    s = res.snapshot
    if s:
        L += ["", "## Snapshot", ""]
        L += [
            f"- Rows: {s['rows']:,}; first {_ts(s['first'])}, last {_ts(s['last'])}",
            f"- Span {s['span_hours']:.2f} h; hours actually covered (steps of 10 min or less): {s['covered_hours']:.2f} h",
            f"- Coverage vs 5-min slots: {s['coverage']:.1f}% ({s['rows']:,} of {s['expected']:,})",
            f"- filled_ok share: {s['filled_ok_share']:.1f}%; blank slippage cells: {s['blank_slippage_cells']:,}; median spread {s['spread_median_bps']:.2f} bps",
        ]
        if s["distribution"] is not None:
            L += ["", "Spacing distribution (seconds between rows):", "", "| Seconds | Count |", "|---|---|"]
            L += [f"| {sec:g} | {int(c):,} |" for sec, c in s["distribution"].items()]
        L += ["", f"Gaps above 10 min ({len(s['gaps'])}):", ""]
        L += (["| From (UTC) | To (UTC) |", "|---|---|"] + [f"| {_ts(a)} | {_ts(b)} |" for a, b in s["gaps"]]) if s["gaps"] else ["none"]
        L += ["", "Row checks (flag only): " + "; ".join(f"{m}: {n:,}" for m, n in s["flags"])]
    return "\n".join(L) + "\n"


def console_summary(res: Result, report: Path) -> str:
    out = [f"Gate 1 recorder quality: {'PASS' if res.passed else 'FAIL'}   (checked {_ts(res.now)})"]
    for name, d in res.datasets.items():
        live = d["live"]
        cov = f"{d['live_coverage_to_last']:.1f}%/{d['live_coverage_to_now']:.1f}% (to last/now)" if "live_coverage_to_last" in d else "n/a"
        out.append(
            f"  {name:24s} rows {d['rows']:,}  cov {d['coverage']:.2f}%  gaps {len(d['gaps'])} ({d['missing_slots']:,} slots)  "
            f"backfilled {d['backfilled']['count']:,} / live {live['count']:,}  live cov {cov}  lookahead {d['lookahead_violations']}"
        )
    s = res.snapshot
    if s:
        out.append(
            f"  {'snapshot':24s} rows {s['rows']:,}  {s['span_hours']:.2f} h span ({s['covered_hours']:.2f} h covered)  "
            f"gaps>10min {len(s['gaps'])}  filled_ok {s['filled_ok_share']:.0f}%  blanks {s['blank_slippage_cells']}"
        )
    if res.running:
        r = res.running
        out.append(
            f"  recorder running: {'yes' if r['ok'] else 'NO - may be stopped'} (newest snapshot {_ts(r['newest'])}, {r['age_min']:,.0f} min ago)"
        )
    for m in res.hard_failures:
        out.append(f"  HARD FAIL: {m}")
    for m in res.warnings:
        out.append(f"  warning:   {m}")
    out.append(f"  report: {report}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only quality checks on the forward recorder files.")
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    args = ap.parse_args(argv)
    directory, report = Path(args.dir), Path(args.report)

    d_res, r_res = directory.resolve(), report.resolve()
    if r_res == d_res or d_res in r_res.parents:
        print(f"Refusing: --report must not be inside the data directory {directory}.")
        return 2
    if not directory.is_dir():
        print(f"Directory not found: {directory}")
        return 2
    try:
        res = run_checks(directory)
    except FileProblem as exc:
        print(str(exc))
        return 2
    except Exception as exc:  # unexpected read/parse problem
        print(f"Could not check {directory}: {exc}")
        return 2
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(res), encoding="utf-8")
    print(console_summary(res, report))
    return 0 if res.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
