"""Cross-exchange price check for TACUSDT 1m klines: Binance vs Bybit.

Part A: Bybit's own data quality (same rules as quality_klines.py, adapted to
the Bybit columns). Part B: comparison on the timestamps present in both files.

STRICTLY READ-ONLY on both CSVs. No network. Differences and outliers are
flagged, never clipped or fixed. Only Part A problems (and bad schemas) are
hard failures; Part B findings are reported for a human to judge.

Run: python -m tacgate.data.crosscheck_klines [--binance PATH] [--bybit PATH] [--report PATH]
Exit code: 0 = pass (flags allowed), 1 = hard failure, 2 = file error.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from tacgate.data.binance_klines import COLUMNS as BINANCE_COLUMNS
from tacgate.data.bybit_klines import COLUMNS as BYBIT_COLUMNS
from tacgate.data.quality_klines import INTERVAL_MS, MAX_GAP_MINUTES, Gap, ms_to_utc

DEFAULT_BINANCE = Path("data/raw/binance_TACUSDT_1m.csv")
DEFAULT_BYBIT = Path("data/raw/bybit_TACUSDT_1m.csv")
DEFAULT_REPORT = Path("docs/crosscheck_klines_report.md")
DIFF_FLAG_PCT = 1.0  # close differs by more than this many percent -> flagged
LOW_PRICE_FLAG = 0.0005
LOW_PRICE_TARGET = 0.00031
TOP_DIFFS = 10
TOP_FLAGGED = 20
EXAMPLES = 5
PRICE_COLS = ["open", "high", "low", "close"]


@dataclass
class Result:
    binance_path: str
    bybit_path: str
    hard_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    bybit_summary: dict = field(default_factory=dict)
    overlap: dict = field(default_factory=dict)
    extremes: dict = field(default_factory=dict)
    diff_stats: dict = field(default_factory=dict)
    top_diffs: pd.DataFrame | None = None
    flagged: pd.DataFrame | None = None
    low_price: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.hard_failures


# ---------------------------------------------------------------- loading ---

def load_numeric(path: Path, columns: list[str], label: str, res: Result) -> pd.DataFrame | None:
    """Read a CSV read-only and parse every column as a number; hard-fail on schema problems."""
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    if list(raw.columns) != columns:
        res.hard_failures.append(f"{label} schema: expected columns {columns}, got {list(raw.columns)}")
        return None
    if raw.empty:
        res.hard_failures.append(f"{label} schema: file has a header but no data rows")
        return None
    num = raw.apply(pd.to_numeric, errors="coerce")
    bad = num.isna().sum()
    bad = bad[bad > 0]
    if not bad.empty:
        detail = ", ".join(f"{c}: {n}" for c, n in bad.items())
        res.hard_failures.append(f"{label} schema: non-numeric/empty values (rows per column) {detail}")
        return None
    num["open_time"] = num["open_time"].astype("int64")
    return num


# ------------------------------------------------------- Part A: Bybit QA ---

def check_bybit(df: pd.DataFrame, res: Result) -> None:
    ot = df["open_time"].to_numpy()
    dup = int(df["open_time"].duplicated().sum())
    if dup:
        res.hard_failures.append(f"Bybit time: {dup} duplicate open_time value(s)")
    diffs = np.diff(ot)
    backwards = int((diffs < 0).sum())
    if backwards:
        res.hard_failures.append(f"Bybit time: open_time not monotonic ({backwards} step(s) go backwards)")
    unaligned = int((ot % INTERVAL_MS != 0).sum())
    if unaligned:
        res.hard_failures.append(f"Bybit time: {unaligned} open_time value(s) not on a whole minute")
    off_grid = int(((diffs > 0) & (diffs % INTERVAL_MS != 0)).sum())
    if off_grid:
        res.hard_failures.append(f"Bybit time: {off_grid} spacing(s) not a multiple of 60000 ms")

    for i in np.nonzero(diffs > INTERVAL_MS)[0]:
        res.gaps.append(Gap(int(ot[i] + INTERVAL_MS), int(ot[i + 1] - INTERVAL_MS), int(diffs[i] // INTERVAL_MS) - 1))
    long_gaps = [g for g in res.gaps if g.minutes > MAX_GAP_MINUTES]
    short_gaps = [g for g in res.gaps if g.minutes <= MAX_GAP_MINUTES]
    if long_gaps:
        res.hard_failures.append(
            f"Bybit time: {len(long_gaps)} gap(s) longer than {MAX_GAP_MINUTES} min (longest {max(g.minutes for g in long_gaps)} min)"
        )
    if short_gaps:
        res.warnings.append(
            f"Bybit time: {len(short_gaps)} gap(s) of {MAX_GAP_MINUTES} min or less ({sum(g.minutes for g in short_gaps)} candles missing)"
        )

    o, h, l, c = (df[x] for x in PRICE_COLS)
    high_bad = int((h < pd.concat([o, c, l], axis=1).max(axis=1)).sum())
    low_bad = int((l > pd.concat([o, c, h], axis=1).min(axis=1)).sum())
    price_bad = int((df[PRICE_COLS] <= 0).any(axis=1).sum())
    for n, msg in [
        (high_bad, "high < max(open, close, low)"),
        (low_bad, "low > min(open, close, high)"),
        (price_bad, "a price <= 0"),
        (int((df["volume"] < 0).sum()), "volume < 0"),
        (int((df["turnover"] < 0).sum()), "turnover < 0"),
    ]:
        if n:
            res.hard_failures.append(f"Bybit OHLC: {n} row(s) with {msg}")

    first, last = int(df["open_time"].min()), int(df["open_time"].max())
    expected = (last - first) // INTERVAL_MS + 1
    zero_vol = int((df["volume"] == 0).sum())
    res.bybit_summary = dict(
        rows=len(df), first=first, last=last, expected_rows=expected,
        missing_rows=expected - df["open_time"].nunique(), zero_volume=zero_vol,
    )
    if zero_vol:
        res.warnings.append(f"Bybit volume: {zero_vol} zero-volume candle(s)")


# --------------------------------------------------- Part B: comparison -----

def _extreme(df: pd.DataFrame) -> dict:
    lo, hi = df.loc[df["low"].idxmin()], df.loc[df["high"].idxmax()]
    return dict(
        rows=len(df), low=float(lo["low"]), low_time=int(lo["open_time"]),
        high=float(hi["high"]), high_time=int(hi["open_time"]),
    )


def _only_in_one(only: np.ndarray, lo: int, hi: int) -> dict:
    """Split minutes missing from the other file into outside vs inside the shared time range."""
    only = np.sort(only)
    inside = only[(only >= lo) & (only <= hi)]
    return dict(
        count=len(only),
        outside_range=len(only) - len(inside),
        inside_range=len(inside),
        first=[int(x) for x in only[:EXAMPLES]],
        last=[int(x) for x in only[-EXAMPLES:]] if len(only) else [],
        inside_examples=[int(x) for x in inside[:EXAMPLES]],
    )


def lows_below(df: pd.DataFrame) -> dict:
    below = df[df["low"] < LOW_PRICE_FLAG].sort_values("low")
    return dict(
        count_below_flag=len(below),
        count_at_or_below_target=int((df["low"] <= LOW_PRICE_TARGET).sum()),
        lowest=below.head(EXAMPLES)[["open_time", "low"]].reset_index(drop=True),
        min_low=float(df["low"].min()),
    )


def compare(bn: pd.DataFrame, by: pd.DataFrame, res: Result) -> None:
    res.extremes = {"Binance": _extreme(bn), "Bybit": _extreme(by)}
    res.low_price = {"Binance": lows_below(bn), "Bybit": lows_below(by)}

    m = bn.merge(by, on="open_time", suffixes=("_bn", "_by")).sort_values("open_time").reset_index(drop=True)
    t_bn, t_by = set(bn["open_time"]), set(by["open_time"])
    both = t_bn & t_by
    if not both:
        res.hard_failures.append("Compare: no timestamps present in both files")
        return
    lo, hi = int(m["open_time"].min()), int(m["open_time"].max())
    res.overlap = dict(
        rows=len(m), first=lo, last=hi,
        only_binance=_only_in_one(np.fromiter(t_bn - t_by, dtype="int64"), lo, hi),
        only_bybit=_only_in_one(np.fromiter(t_by - t_bn, dtype="int64"), lo, hi),
    )
    for name, key in (("Binance", "only_binance"), ("Bybit", "only_bybit")):
        n = res.overlap[key]["inside_range"]
        if n:
            res.warnings.append(f"Compare: {n} minute(s) inside the shared range exist only in {name}")

    pct = (m["close_by"] / m["close_bn"] - 1.0) * 100.0
    m["diff_pct"] = pct
    ab = pct.abs()
    res.diff_stats = dict(
        mean=float(pct.mean()), median=float(pct.median()),
        p99_abs=float(ab.quantile(0.99)), max_abs=float(ab.max()),
        over_flag=int((ab > DIFF_FLAG_PCT).sum()),
    )
    cols = ["open_time", "close_bn", "close_by", "diff_pct", "volume_bn", "volume_by"]
    order = ab.sort_values(ascending=False).index
    res.top_diffs = m.loc[order[:TOP_DIFFS], cols].reset_index(drop=True)
    res.flagged = m.loc[[i for i in order if ab[i] > DIFF_FLAG_PCT][:TOP_FLAGGED], cols].reset_index(drop=True)
    if res.diff_stats["over_flag"]:
        res.warnings.append(f"Compare: {res.diff_stats['over_flag']} minute(s) where close differs by more than {DIFF_FLAG_PCT}%")

    # returns only between consecutive minutes that exist in BOTH files (no look-ahead, no filling)
    consecutive = m["open_time"].diff() == INTERVAL_MS
    r_bn, r_by = m["close_bn"].pct_change(), m["close_by"].pct_change()
    ok = consecutive & r_bn.notna() & r_by.notna()
    n_ret = int(ok.sum())
    corr = float(np.corrcoef(r_bn[ok], r_by[ok])[0, 1]) if n_ret > 2 else float("nan")
    res.diff_stats.update(return_corr=corr, return_pairs=n_ret)


def run_checks(binance_path: Path, bybit_path: Path) -> Result:
    res = Result(str(binance_path), str(bybit_path))
    by = load_numeric(Path(bybit_path), BYBIT_COLUMNS, "Bybit", res)
    bn = load_numeric(Path(binance_path), BINANCE_COLUMNS, "Binance", res)
    if by is not None:
        check_bybit(by, res)
    if bn is not None and bn["open_time"].duplicated().any():
        res.hard_failures.append("Binance time: duplicate open_time values; cannot compare (run quality_klines)")
    if bn is None or by is None or res.hard_failures:
        return res  # Part B needs two clean, parseable files
    compare(bn, by, res)
    return res


# ----------------------------------------------------------------- report ---

def _ts(ms) -> str:
    return ms_to_utc(ms)


def _price_table(df: pd.DataFrame, extra: bool = True) -> list[str]:
    L = ["| Time (UTC) | Binance close | Bybit close | Diff % | Binance vol | Bybit vol |", "|---|---|---|---|---|---|"]
    for r in df.itertuples():
        L.append(f"| {_ts(r.open_time)} | {r.close_bn} | {r.close_by} | {r.diff_pct:+.3f} | {r.volume_bn:g} | {r.volume_by:g} |")
    return L


def _only_lines(name: str, d: dict) -> list[str]:
    L = [
        f"- Only in {name}: {d['count']:,} minute(s) ({d['outside_range']:,} outside the shared time range, "
        f"{d['inside_range']:,} inside it, i.e. missing from the other file)"
    ]
    if d["count"]:
        L.append(f"  - first: {', '.join(_ts(x) for x in d['first'])}")
        L.append(f"  - last: {', '.join(_ts(x) for x in d['last'])}")
    if d["inside_range"]:
        L.append(f"  - inside the shared range: {', '.join(_ts(x) for x in d['inside_examples'])}")
    return L


def render_report(res: Result) -> str:
    L = ["# Cross-exchange klines check: Binance vs Bybit (TACUSDT 1m)", ""]
    L += [f"- Binance file: `{res.binance_path}` (read-only)", f"- Bybit file: `{res.bybit_path}` (read-only)"]
    L += [f"- Verdict: **{'PASS' if res.passed else 'FAIL'}** (Part A problems are hard failures; Part B items are flags)", ""]
    L += ["## Hard failures", ""] + ([f"- {m}" for m in res.hard_failures] or ["- none"])
    L += ["", "## Warnings and flags", ""] + ([f"- {m}" for m in res.warnings] or ["- none"])

    s = res.bybit_summary
    if s:
        L += ["", "## Part A: Bybit data quality", ""]
        L += [
            f"- First candle: {_ts(s['first'])}",
            f"- Last candle: {_ts(s['last'])}",
            f"- Rows: {s['rows']:,} (expected {s['expected_rows']:,}, missing {s['missing_rows']:,})",
            f"- Zero-volume candles: {s['zero_volume']:,}",
            "",
            f"### Gaps ({len(res.gaps)})",
            "",
        ]
        if res.gaps:
            L += ["| Start (UTC) | End (UTC) | Length (min) | Severity |", "|---|---|---|---|"]
            for g in res.gaps:
                L.append(f"| {_ts(g.start_ms)} | {_ts(g.end_ms)} | {g.minutes} | {'HARD' if g.minutes > MAX_GAP_MINUTES else 'warning'} |")
        else:
            L.append("none")

    if res.extremes:
        L += ["", "## Part B: all-time low and high per exchange (whole files, from 1m low/high)", ""]
        L += ["| | Binance | Bybit |", "|---|---|---|"]
        b, y = res.extremes["Binance"], res.extremes["Bybit"]
        L += [
            f"| Rows | {b['rows']:,} | {y['rows']:,} |",
            f"| All-time low | {b['low']} at {_ts(b['low_time'])} | {y['low']} at {_ts(y['low_time'])} |",
            f"| All-time high | {b['high']} at {_ts(b['high_time'])} | {y['high']} at {_ts(y['high_time'])} |",
        ]
    if res.low_price:
        L += ["", f"### Low prices (1m low below {LOW_PRICE_FLAG}; is {LOW_PRICE_TARGET} ever reached?)", ""]
        for name, d in res.low_price.items():
            L.append(
                f"- {name}: lowest low {d['min_low']}; lows below {LOW_PRICE_FLAG}: {d['count_below_flag']:,}; "
                f"lows at or below {LOW_PRICE_TARGET}: {d['count_at_or_below_target']:,}"
            )
            for r in d["lowest"].itertuples():
                L.append(f"  - {r.low} at {_ts(r.open_time)}")
    if res.overlap:
        o = res.overlap
        L += ["", "## Part B: overlap", ""]
        L += [f"- Overlapping minutes: {o['rows']:,} ({_ts(o['first'])} to {_ts(o['last'])})"]
        L += _only_lines("Binance", o["only_binance"]) + _only_lines("Bybit", o["only_bybit"])
    if res.diff_stats:
        d = res.diff_stats
        L += ["", "## Part B: close-to-close difference, (Bybit / Binance - 1) in %", ""]
        L += [
            f"- mean {d['mean']:+.4f}, median {d['median']:+.4f}, p99 of absolute {d['p99_abs']:.4f}, max absolute {d['max_abs']:.4f}",
            f"- Correlation of 1m close-to-close returns: {d['return_corr']:.4f} (over {d['return_pairs']:,} consecutive-minute pairs present in both files)",
            "",
            f"### Top {TOP_DIFFS} largest differences",
            "",
        ] + _price_table(res.top_diffs)
        L += ["", f"### Minutes where close differs by more than {DIFF_FLAG_PCT}%: {d['over_flag']:,} (top {TOP_FLAGGED} shown)", ""]
        L += _price_table(res.flagged) if len(res.flagged) else ["none"]
    return "\n".join(L) + "\n"


def console_summary(res: Result, report: Path) -> str:
    out = [f"Cross-exchange klines check: {'PASS' if res.passed else 'FAIL'}"]
    s = res.bybit_summary
    if s:
        out.append(f"  Bybit:   {s['rows']:,} rows (expected {s['expected_rows']:,}), {len(res.gaps)} gap(s), {s['zero_volume']:,} zero-volume")
    if res.overlap:
        o = res.overlap
        out.append(f"  overlap: {o['rows']:,} minutes; only Binance {o['only_binance']['count']:,}, only Bybit {o['only_bybit']['count']:,}")
    if res.extremes:
        for n, e in res.extremes.items():
            out.append(f"  {n:8s} low {e['low']} ({_ts(e['low_time'])}), high {e['high']} ({_ts(e['high_time'])})")
    if res.diff_stats:
        d = res.diff_stats
        out.append(
            f"  close diff %: mean {d['mean']:+.4f}, median {d['median']:+.4f}, p99|.| {d['p99_abs']:.4f}, "
            f"max|.| {d['max_abs']:.4f}; >1%: {d['over_flag']:,}; return corr {d['return_corr']:.4f}"
        )
    for n, d in res.low_price.items():
        out.append(f"  {n:8s} lows < {LOW_PRICE_FLAG}: {d['count_below_flag']:,}; lows <= {LOW_PRICE_TARGET}: {d['count_at_or_below_target']:,}")
    for m in res.hard_failures:
        out.append(f"  HARD FAIL: {m}")
    for m in res.warnings:
        out.append(f"  flag:      {m}")
    out.append(f"  report: {report}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only Binance vs Bybit TACUSDT 1m price cross-check.")
    ap.add_argument("--binance", default=str(DEFAULT_BINANCE))
    ap.add_argument("--bybit", default=str(DEFAULT_BYBIT))
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    args = ap.parse_args(argv)
    bn, by, report = Path(args.binance), Path(args.bybit), Path(args.report)

    if report.resolve() in (bn.resolve(), by.resolve()):
        print("Refusing: --report must not be one of the raw CSV paths.")
        return 2
    for p in (bn, by):
        if not p.exists():
            print(f"File not found: {p}")
            return 2
    try:
        res = run_checks(bn, by)
    except Exception as exc:  # unreadable / malformed CSV
        print(f"Could not read inputs: {exc}")
        return 2
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(res), encoding="utf-8")
    print(console_summary(res, report))
    return 0 if res.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
