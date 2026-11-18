"""Gate 1: data quality checker for the raw Binance TACUSDT 1m klines CSV.

STRICTLY READ-ONLY on the CSV: it never modifies, cleans, or fills the raw file.
Outliers are flagged, never deleted. Results go to a markdown report (a different
file) and a short console summary.

Run: python -m tacgate.data.quality_klines [--path PATH] [--report PATH]
Exit code: 0 = pass (warnings allowed), 1 = hard failure, 2 = file unreadable.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from tacgate.data.binance_klines import COLUMNS, INTERVAL_MS

DEFAULT_PATH = Path("data/raw/binance_TACUSDT_1m.csv")
DEFAULT_REPORT = Path("docs/quality_klines_report.md")
MAX_GAP_MINUTES = 15  # a gap longer than this is a hard failure
CLOSE_OFFSET_MS = INTERVAL_MS - 1  # close_time == open_time + 59999
TOP_RETURNS = 20
PRICE_COLS = ["open", "high", "low", "close"]


@dataclass
class Gap:
    start_ms: int  # first missing minute
    end_ms: int  # last missing minute
    minutes: int  # number of missing 1m candles


@dataclass
class Result:
    path: str
    hard_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    outliers: pd.DataFrame | None = None
    summary: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.hard_failures


def ms_to_utc(ms: int | float) -> str:
    return pd.Timestamp(int(ms), unit="ms", tz="UTC").strftime("%Y-%m-%d %H:%M:%S UTC")


def load_raw(path: Path) -> pd.DataFrame:
    """Read the CSV as strings, read-only. Nothing is written back."""
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def check_schema(raw: pd.DataFrame, res: Result) -> pd.DataFrame | None:
    """Return a numeric DataFrame, or None (with hard failures recorded) on schema error."""
    if list(raw.columns) != COLUMNS:
        res.hard_failures.append(
            f"Schema: expected columns {COLUMNS}, got {list(raw.columns)}"
        )
        return None
    if raw.empty:
        res.hard_failures.append("Schema: file has a header but no data rows")
        return None
    num = raw.apply(pd.to_numeric, errors="coerce")
    bad = num.isna().sum()
    bad = bad[bad > 0]
    if not bad.empty:
        detail = ", ".join(f"{c}: {n}" for c, n in bad.items())
        res.hard_failures.append(f"Schema: non-numeric/empty values (rows per column) {detail}")
        return None
    num["open_time"] = num["open_time"].astype("int64")
    num["close_time"] = num["close_time"].astype("int64")
    return num


def check_time(df: pd.DataFrame, res: Result) -> None:
    ot = df["open_time"].to_numpy()
    dup = int(df["open_time"].duplicated().sum())
    if dup:
        res.hard_failures.append(f"Time: {dup} duplicate open_time value(s)")
    diffs = np.diff(ot)
    backwards = int((diffs < 0).sum())
    if backwards:
        res.hard_failures.append(f"Time: open_time not monotonic ({backwards} step(s) go backwards)")
    unaligned = int((ot % INTERVAL_MS != 0).sum())
    if unaligned:
        res.hard_failures.append(f"Time: {unaligned} open_time value(s) not on a whole minute")
    off_grid = int(((diffs > 0) & (diffs % INTERVAL_MS != 0)).sum())
    if off_grid:
        res.hard_failures.append(f"Time: {off_grid} spacing(s) not a multiple of 60000 ms")

    idx = np.nonzero(diffs > INTERVAL_MS)[0]
    for i in idx:
        missing = int(diffs[i] // INTERVAL_MS) - 1
        res.gaps.append(Gap(int(ot[i] + INTERVAL_MS), int(ot[i + 1] - INTERVAL_MS), missing))
    long_gaps = [g for g in res.gaps if g.minutes > MAX_GAP_MINUTES]
    short_gaps = [g for g in res.gaps if g.minutes <= MAX_GAP_MINUTES]
    if long_gaps:
        res.hard_failures.append(
            f"Time: {len(long_gaps)} gap(s) longer than {MAX_GAP_MINUTES} min "
            f"(longest {max(g.minutes for g in long_gaps)} min)"
        )
    if short_gaps:
        res.warnings.append(
            f"Time: {len(short_gaps)} gap(s) of {MAX_GAP_MINUTES} min or less "
            f"({sum(g.minutes for g in short_gaps)} candles missing)"
        )

    bad_close = int((df["close_time"] != df["open_time"] + CLOSE_OFFSET_MS).sum())
    if bad_close:
        res.hard_failures.append(f"close_time: {bad_close} row(s) where close_time != open_time + 59999")


def check_ohlc(df: pd.DataFrame, res: Result) -> None:
    o, h, l, c = (df[x] for x in PRICE_COLS)
    high_bad = int((h < pd.concat([o, c, l], axis=1).max(axis=1)).sum())
    low_bad = int((l > pd.concat([o, c, h], axis=1).min(axis=1)).sum())
    price_bad = int((df[PRICE_COLS] <= 0).any(axis=1).sum())
    vol_bad = int((df["volume"] < 0).sum())
    trades_bad = int((df["trades"] < 0).sum())
    for n, msg in [
        (high_bad, "high < max(open, close, low)"),
        (low_bad, "low > min(open, close, high)"),
        (price_bad, "a price <= 0"),
        (vol_bad, "volume < 0"),
        (trades_bad, "trades < 0"),
    ]:
        if n:
            res.hard_failures.append(f"OHLC: {n} row(s) with {msg}")


def check_zero_volume(df: pd.DataFrame, res: Result) -> None:
    n = int((df["volume"] == 0).sum())
    res.summary["zero_volume"] = n
    if n:
        res.warnings.append(f"Volume: {n} zero-volume candle(s)")


def find_outliers(df: pd.DataFrame, n: int = TOP_RETURNS) -> pd.DataFrame:
    """Top-n absolute close-to-close 1m returns. Flagged only; nothing is removed."""
    ret = df["close"].pct_change()
    gap = df["open_time"].diff() != INTERVAL_MS
    out = pd.DataFrame(
        {
            "open_time": df["open_time"],
            "utc": pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.strftime("%Y-%m-%d %H:%M"),
            "prev_close": df["close"].shift(1),
            "close": df["close"],
            "return_pct": ret * 100,
            "after_gap": gap,
        }
    )
    out = out.iloc[1:]
    out = out.reindex(out["return_pct"].abs().sort_values(ascending=False).index)
    return out.head(n).reset_index(drop=True)


def build_summary(df: pd.DataFrame, res: Result) -> None:
    first, last = int(df["open_time"].min()), int(df["open_time"].max())
    expected = (last - first) // INTERVAL_MS + 1
    lo, hi = df.loc[df["low"].idxmin()], df.loc[df["high"].idxmax()]
    res.summary.update(
        rows=len(df),
        first=first,
        last=last,
        expected_rows=expected,
        missing_rows=expected - df["open_time"].nunique(),
        min_price=float(lo["low"]),
        min_price_time=int(lo["open_time"]),
        max_price=float(hi["high"]),
        max_price_time=int(hi["open_time"]),
    )


def run_checks(path: Path) -> Result:
    res = Result(path=str(path))
    raw = load_raw(Path(path))
    df = check_schema(raw, res)
    if df is None:
        return res  # cannot run further checks on a bad schema
    check_time(df, res)
    check_ohlc(df, res)
    check_zero_volume(df, res)
    res.outliers = find_outliers(df)
    build_summary(df, res)
    return res


def render_report(res: Result) -> str:
    s = res.summary
    lines = ["# Klines quality report (Gate 1)", ""]
    lines += [f"- File: `{res.path}` (read-only; never modified)"]
    lines += [f"- Verdict: **{'PASS' if res.passed else 'FAIL'}**", ""]
    lines += ["## Hard failures", ""]
    lines += [f"- {m}" for m in res.hard_failures] or ["- none"]
    lines += ["", "## Warnings", ""]
    lines += [f"- {m}" for m in res.warnings] or ["- none"]
    if s:
        lines += ["", "## Summary", ""]
        lines += [
            f"- First candle: {ms_to_utc(s['first'])}",
            f"- Last candle: {ms_to_utc(s['last'])}",
            f"- Rows: {s['rows']:,}",
            f"- Expected rows from time span: {s['expected_rows']:,} (missing: {s['missing_rows']:,})",
            f"- Zero-volume candles: {s['zero_volume']:,}",
            f"- Min price (low): {s['min_price']} at {ms_to_utc(s['min_price_time'])}",
            f"- Max price (high): {s['max_price']} at {ms_to_utc(s['max_price_time'])}",
        ]
        lines += ["", f"## Gaps ({len(res.gaps)})", ""]
        if res.gaps:
            lines += ["| Start (UTC) | End (UTC) | Length (min) | Severity |", "|---|---|---|---|"]
            for g in res.gaps:
                sev = "HARD" if g.minutes > MAX_GAP_MINUTES else "warning"
                lines.append(f"| {ms_to_utc(g.start_ms)} | {ms_to_utc(g.end_ms)} | {g.minutes} | {sev} |")
        else:
            lines.append("none")
    if res.outliers is not None:
        lines += [
            "",
            f"## Top {TOP_RETURNS} absolute 1-minute returns (flagged, not removed)",
            "",
            "| Time (UTC) | Prev close | Close | Return % | After gap |",
            "|---|---|---|---|---|",
        ]
        for r in res.outliers.itertuples():
            lines.append(
                f"| {r.utc} | {r.prev_close} | {r.close} | {r.return_pct:+.2f} | {'yes' if r.after_gap else 'no'} |"
            )
    return "\n".join(lines) + "\n"


def console_summary(res: Result, report: Path) -> str:
    s = res.summary
    out = [f"Gate 1 klines quality: {'PASS' if res.passed else 'FAIL'}"]
    if s:
        out.append(f"  range:    {ms_to_utc(s['first'])} -> {ms_to_utc(s['last'])}")
        out.append(f"  rows:     {s['rows']:,} (expected {s['expected_rows']:,}, missing {s['missing_rows']:,})")
        out.append(f"  gaps:     {len(res.gaps)} (hard: {sum(g.minutes > MAX_GAP_MINUTES for g in res.gaps)})")
        out.append(f"  zero-vol: {s['zero_volume']:,}")
        out.append(
            f"  price:    min {s['min_price']} ({ms_to_utc(s['min_price_time'])}), "
            f"max {s['max_price']} ({ms_to_utc(s['max_price_time'])})"
        )
    for m in res.hard_failures:
        out.append(f"  HARD FAIL: {m}")
    for m in res.warnings:
        out.append(f"  warning:   {m}")
    out.append(f"  report:   {report}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only quality checks on raw klines CSV.")
    ap.add_argument("--path", default=str(DEFAULT_PATH))
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    args = ap.parse_args(argv)
    path, report = Path(args.path), Path(args.report)

    if path.resolve() == report.resolve():
        print("Refusing: --report must not be the raw CSV path.")
        return 2
    if not path.exists():
        print(f"File not found: {path}")
        return 2
    try:
        res = run_checks(path)
    except Exception as exc:  # unreadable / malformed CSV
        print(f"Could not read {path}: {exc}")
        return 2
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(res), encoding="utf-8")
    print(console_summary(res, report))
    return 0 if res.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
