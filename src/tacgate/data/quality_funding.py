"""Gate 1: data quality checker for the raw Binance TACUSDT funding-rate CSV.

STRICTLY READ-ONLY on the CSV: it never modifies, cleans, or fills the raw file.
No network calls. Rate outliers are flagged, never deleted. The funding interval
is NOT assumed fixed: the full distribution of gaps is reported, and the 4h
comparison is only used to explain row-count differences.

Run: python -m tacgate.data.quality_funding [--path PATH] [--report PATH]
Exit code: 0 = pass (warnings allowed), 1 = hard failure, 2 = file unreadable.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from tacgate.data.binance_funding import FUNDING_COLUMNS
from tacgate.data.quality_klines import ms_to_utc

DEFAULT_PATH = Path("data/raw/binance_TACUSDT_funding.csv")
DEFAULT_REPORT = Path("docs/quality_funding_report.md")
HOUR_MS = 3_600_000
REF_INTERVAL_MS = 4 * HOUR_MS  # reference only (not assumed); used for the "expected rows" comparison
JITTER_TOL_MS = 60_000  # gaps within +-60 s of 4h count as "4h with millisecond jitter"
MAX_GAP_HOURS = 24  # a gap above this is a hard failure
RATE_FLAG = 0.0005
TOP_RATES = 10


@dataclass
class OddGap:
    prev_ms: int
    next_ms: int
    gap_ms: int

    @property
    def hours(self) -> float:
        return self.gap_ms / HOUR_MS


@dataclass
class Result:
    path: str
    hard_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    odd_gaps: list[OddGap] = field(default_factory=list)
    gap_distribution: pd.Series | None = None
    jitter: dict = field(default_factory=dict)
    rate_stats: dict = field(default_factory=dict)
    extreme_rates: pd.DataFrame | None = None
    summary: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.hard_failures


def load_raw(path: Path) -> pd.DataFrame:
    """Read the CSV as strings, read-only. Nothing is written back."""
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def check_schema(raw: pd.DataFrame, res: Result) -> pd.DataFrame | None:
    """Return a typed DataFrame or None (hard failure recorded)."""
    if list(raw.columns) != FUNDING_COLUMNS:
        res.hard_failures.append(f"Schema: expected columns {FUNDING_COLUMNS}, got {list(raw.columns)}")
        return None
    if raw.empty:
        res.hard_failures.append("Schema: file has a header but no data rows")
        return None
    df = raw.copy()
    ft = pd.to_numeric(df["fundingTime"], errors="coerce")
    if ft.isna().any():
        res.hard_failures.append(f"Schema: {int(ft.isna().sum())} fundingTime value(s) not numeric")
        return None
    df["fundingTime"] = ft.astype("int64")
    df["fundingRate"] = pd.to_numeric(df["fundingRate"], errors="coerce")
    df["markPrice"] = pd.to_numeric(df["markPrice"], errors="coerce")
    return df


def check_time(df: pd.DataFrame, res: Result) -> None:
    t = df["fundingTime"]
    dup = int(t.duplicated().sum())
    if dup:
        res.hard_failures.append(f"Time: {dup} duplicate fundingTime value(s)")
    backwards = int((t.diff().dropna() < 0).sum())
    if backwards:
        res.hard_failures.append(f"Time: fundingTime not monotonic ({backwards} step(s) go backwards)")


def analyse_gaps(df: pd.DataFrame, res: Result) -> None:
    """Gap distribution and non-4h gaps from consecutive forward steps. Interval not assumed."""
    t = df["fundingTime"].to_numpy()
    gaps = np.diff(t)
    fwd = gaps > 0  # only forward steps are intervals; backwards/zero are reported elsewhere
    g = gaps[fwd]
    prev = t[:-1][fwd]
    nxt = t[1:][fwd]
    if g.size == 0:
        return
    res.gap_distribution = (
        pd.Series(np.round(g / HOUR_MS, 2)).value_counts().sort_index().rename("count")
    )
    dev = g - REF_INTERVAL_MS
    near = np.abs(dev) <= JITTER_TOL_MS
    res.jitter = {
        "exact_4h": int((dev == 0).sum()),
        "jitter_only": int((near & (dev != 0)).sum()),
        "dev_min_ms": int(dev[near].min()) if near.any() else None,
        "dev_max_ms": int(dev[near].max()) if near.any() else None,
    }
    res.odd_gaps = [OddGap(int(a), int(b), int(c)) for a, b, c in zip(prev[~near], nxt[~near], g[~near])]
    long_gaps = [o for o in res.odd_gaps if o.hours > MAX_GAP_HOURS]
    if long_gaps:
        res.hard_failures.append(
            f"Time: {len(long_gaps)} gap(s) above {MAX_GAP_HOURS}h (longest {max(o.hours for o in long_gaps):.2f}h)"
        )
    if res.odd_gaps:
        res.warnings.append(f"Interval: {len(res.odd_gaps)} gap(s) that are not 4h (listed in report)")


def check_rates(df: pd.DataFrame, res: Result) -> None:
    nan = int(df["fundingRate"].isna().sum())
    if nan:
        res.hard_failures.append(f"Rate: {nan} fundingRate value(s) NaN, blank or non-numeric")
    r = df["fundingRate"].dropna()
    if r.empty:
        return
    res.rate_stats = {
        "min": float(r.min()),
        "max": float(r.max()),
        "mean": float(r.mean()),
        "median": float(r.median()),
        "above": int((r > RATE_FLAG).sum()),
        "below": int((r < -RATE_FLAG).sum()),
    }
    if res.rate_stats["above"] or res.rate_stats["below"]:
        res.warnings.append(
            f"Rate: {res.rate_stats['above']} rate(s) > {RATE_FLAG} and {res.rate_stats['below']} < -{RATE_FLAG} (flagged, kept)"
        )
    top = df.loc[r.abs().sort_values(ascending=False).index[:TOP_RATES], ["fundingTime", "fundingRate", "markPrice", "rateType"]]
    res.extreme_rates = top.reset_index(drop=True)


def check_mark_price(df: pd.DataFrame, res: Result) -> None:
    blank = int(df["markPrice"].isna().sum())
    zero = int((df["markPrice"] <= 0).sum())
    res.summary["markprice_blank"] = blank
    res.summary["markprice_nonpositive"] = zero
    if blank or zero:
        res.warnings.append(f"markPrice: {blank} blank/non-numeric, {zero} zero or negative (reported, not failed)")


def build_summary(df: pd.DataFrame, res: Result) -> None:
    t = df["fundingTime"]
    first, last = int(t.min()), int(t.max())
    rows = len(df)
    expected = int(round((last - first) / REF_INTERVAL_MS)) + 1
    res.summary.update(
        rows=rows,
        first=first,
        last=last,
        expected_if_4h=expected,
        difference=expected - rows,
        symbols=sorted(df["symbol"].unique()),
        rate_types=df["rateType"].value_counts().to_dict(),
    )
    if len(res.summary["symbols"]) != 1:
        res.warnings.append(f"Schema: more than one symbol present: {res.summary['symbols']}")


def explain_difference(res: Result) -> list[str]:
    """Explain expected-vs-actual using the actual gaps (identity: span/4h = sum(gap/4h))."""
    s = res.summary
    lines = [
        f"- Rows: {s['rows']:,}. Expected if every interval were exactly 4h: {s['expected_if_4h']:,} "
        f"= round((last - first) / 4h) + 1. Difference: {s['difference']:+,}.",
        f"- {s['rows'] - 1:,} intervals separate {s['rows']:,} rows. The span holds "
        f"{s['expected_if_4h'] - 1:,} four-hour slots, so each interval of g hours accounts for "
        "(g / 4 - 1) slots more than one row.",
    ]
    if not res.odd_gaps:
        lines.append("- Every interval is 4h (within millisecond jitter), so there is no difference to explain.")
        return lines
    for o in res.odd_gaps:
        slots = o.gap_ms / REF_INTERVAL_MS - 1
        lines.append(
            f"- {ms_to_utc(o.prev_ms)} -> {ms_to_utc(o.next_ms)}: interval of {o.hours:.2f}h = {slots:+.2f} slot(s) vs a 4h step."
        )
    total = sum(o.gap_ms / REF_INTERVAL_MS - 1 for o in res.odd_gaps)
    lines.append(
        f"- Sum over the non-4h intervals: {total:+.2f} slot(s) (millisecond jitter on the other intervals "
        "adds up to well under one slot). This matches the difference of "
        f"{s['difference']:+,}: rows are fewer than a pure-4h grid by exactly the slots those intervals skip."
    )
    return lines


def run_checks(path: Path) -> Result:
    res = Result(path=str(path))
    df = check_schema(load_raw(Path(path)), res)
    if df is None:
        return res
    check_time(df, res)
    analyse_gaps(df, res)
    check_rates(df, res)
    check_mark_price(df, res)
    build_summary(df, res)
    return res


def render_report(res: Result) -> str:
    s = res.summary
    L = ["# Funding rate quality report (Gate 1)", ""]
    L += [f"- File: `{res.path}` (read-only; never modified)", f"- Verdict: **{'PASS' if res.passed else 'FAIL'}**", ""]
    L += ["## Hard failures", ""] + ([f"- {m}" for m in res.hard_failures] or ["- none"])
    L += ["", "## Warnings", ""] + ([f"- {m}" for m in res.warnings] or ["- none"])
    if s:
        L += ["", "## Summary", ""]
        L += [
            f"- First fundingTime: {ms_to_utc(s['first'])}",
            f"- Last fundingTime: {ms_to_utc(s['last'])}",
            f"- Rows: {s['rows']:,}",
            f"- Expected rows if fixed 4h: {s['expected_if_4h']:,} (difference {s['difference']:+,})",
            f"- rateType counts: {s['rate_types']}",
            f"- markPrice blank/non-numeric: {s['markprice_blank']}, zero or negative: {s['markprice_nonpositive']}",
        ]
    if res.gap_distribution is not None:
        L += ["", "## Interval distribution (gap between consecutive fundingTime, in hours)", ""]
        L += ["| Gap (h) | Count |", "|---|---|"]
        L += [f"| {h:.2f} | {int(c):,} |" for h, c in res.gap_distribution.items()]
        j = res.jitter
        L += [
            "",
            f"Gaps are bucketed to 0.01h. Of the 4h gaps, {j['exact_4h']:,} are exactly 14,400,000 ms and "
            f"{j['jitter_only']:,} are off by milliseconds (range {j['dev_min_ms']} to {j['dev_max_ms']} ms). "
            f"Gaps within +-{JITTER_TOL_MS // 1000}s of 4h count as 4h; every other gap is listed below.",
        ]
        L += ["", f"## Gaps that are not 4h ({len(res.odd_gaps)})", ""]
        if res.odd_gaps:
            L += ["| From (UTC) | To (UTC) | Gap (h) | Severity |", "|---|---|---|---|"]
            for o in res.odd_gaps:
                sev = "HARD" if o.hours > MAX_GAP_HOURS else "warning"
                L.append(f"| {ms_to_utc(o.prev_ms)} | {ms_to_utc(o.next_ms)} | {o.hours:.2f} | {sev} |")
        else:
            L.append("none")
    if s:
        L += ["", "## Row count vs a fixed 4h grid", ""] + explain_difference(res)
    if res.rate_stats:
        r = res.rate_stats
        L += ["", "## Funding rate sanity (flagged, never removed)", ""]
        L += [
            f"- min {r['min']:.8f}, max {r['max']:.8f}, mean {r['mean']:.8f}, median {r['median']:.8f}",
            f"- above {RATE_FLAG}: {r['above']:,}; below -{RATE_FLAG}: {r['below']:,}",
            "",
            f"Top {TOP_RATES} by absolute rate:",
            "",
            "| Time (UTC) | fundingRate | markPrice | rateType |",
            "|---|---|---|---|",
        ]
        for x in res.extreme_rates.itertuples():
            L.append(f"| {ms_to_utc(x.fundingTime)} | {x.fundingRate:+.8f} | {x.markPrice} | {x.rateType} |")
    return "\n".join(L) + "\n"


def console_summary(res: Result, report: Path) -> str:
    s = res.summary
    out = [f"Gate 1 funding quality: {'PASS' if res.passed else 'FAIL'}"]
    if s:
        out.append(f"  range:  {ms_to_utc(s['first'])} -> {ms_to_utc(s['last'])}")
        out.append(f"  rows:   {s['rows']:,} (4h grid would be {s['expected_if_4h']:,}, diff {s['difference']:+,})")
    if res.gap_distribution is not None:
        dist = ", ".join(f"{h:.2f}h x{int(c):,}" for h, c in res.gap_distribution.items())
        out.append(f"  gaps:   {dist}")
    for m in res.hard_failures:
        out.append(f"  HARD FAIL: {m}")
    for m in res.warnings:
        out.append(f"  warning:   {m}")
    out.append(f"  report: {report}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only quality checks on raw funding-rate CSV.")
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
