"""Gate 1: data quality checker for the three daily external files, plus cross-checks.

Files (names and columns come from the fetcher modules, nothing is guessed):
  CoinGecko market chart  coingecko_market_chart.COLUMNS   (timestamp_ms, price, market_cap, total_volume, fetched_at_ms)
  DeFiLlama chain TVL     defillama.TVL.columns            (timestamp_ms, tvl, fetched_at_ms)
  DeFiLlama price         defillama.PRICE.columns          (timestamp_ms, price, confidence, fetched_at_ms)
Cross-checks also read the Binance 1m klines and the recorder open-interest file.

STRICTLY READ-ONLY and no network. Each file is read once into memory, a partial last line is ignored,
nothing is rewritten, cleaned, clipped or filled. Odd values are flagged, never changed.

Part A (each file alone): schema, numbers, ordering, positivity, spacing vs 24 h, no row on the current UTC
day, no look-ahead. Integrity problems are HARD failures; gaps and value oddities are warnings.
Part B (cross-checks): each external price vs the Binance 1m open at the nearest minute, CoinGecko vs
DeFiLlama, derived circulating supply (market_cap / price) with "supply step" candidates, and that derived
supply vs the CMCCirculatingSupply field in the recorder open-interest file. Mismatches are warnings only.

Timing rule (docs/phase0_sources.md, errata): every daily external row is treated as known at
timestamp + 24 h, never earlier. fetched_at_ms is checked, but it is not the known-at time for these rows.

Run: python -m tacgate.data.quality_daily_external [--dir data/raw] [--report docs/quality_daily_external_report.md]
Exit code: 0 = pass (warnings allowed), 1 = hard failure, 2 = file error.
"""
from __future__ import annotations

import argparse
import io
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from tacgate.data import binance_klines as bk
from tacgate.data import coingecko_market_chart as cgm
from tacgate.data import defillama as dl
from tacgate.data.binance_klines import now_ms
from tacgate.data.quality_klines import ms_to_utc
from tacgate.data.quality_recorder import FileProblem, read_once
from tacgate.data.recorder import DATASETS

DEFAULT_DIR = Path("data/raw")
DEFAULT_REPORT = Path("docs/quality_daily_external_report.md")
DAY_MS = 86_400_000
HOUR_MS = 3_600_000
SPACING_TOL_MS = HOUR_MS  # spacing vs 24 h; DeFiLlama price timestamps jitter by seconds
TVL_JUMP = 0.5  # TVL change vs the previous day above this is listed
SUPPLY_STEP = 0.01  # derived supply change vs the previous day above this is a "supply step" candidate
SUPPLY_MATCH_TOL = 0.001  # derived supply vs recorder CMCCirculatingSupply
PRICE_THRESHOLDS = (0.01, 0.02, 0.05)
TOP_N = 20

OI_DATASET = next(d for d in DATASETS if d.name == "open_interest")
CG_NAME = cgm.DEFAULT_OUT.name
TVL_NAME = dl.TVL.default_out.name
PRICE_NAME = dl.PRICE.default_out.name
KLINES_NAME = bk.DEFAULT_OUT.name

# label -> (file name, expected columns, columns that must be > 0, columns that must be >= 0, allowed blank)
DAILY_FILES = {
    "coingecko": (CG_NAME, cgm.COLUMNS, ["price", "market_cap", "total_volume"], [], []),
    "defillama_tvl": (TVL_NAME, dl.TVL.columns, [], ["tvl"], []),
    "defillama_price": (PRICE_NAME, dl.PRICE.columns, ["price"], [], ["confidence"]),
}
MAIN_COLUMNS = {
    "coingecko": ["price", "market_cap", "total_volume"],
    "defillama_tvl": ["tvl"],
    "defillama_price": ["price", "confidence"],
}


@dataclass
class Result:
    directory: str
    now: int
    hard_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    files: dict[str, dict] = field(default_factory=dict)
    cross: dict = field(default_factory=dict)
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)  # cleaned working copies (memory only)

    @property
    def passed(self) -> bool:
        return not self.hard_failures


def _ts(ms) -> str:
    return "n/a" if ms is None else ms_to_utc(ms)


def _date(ms) -> str:
    return pd.Timestamp(int(ms), unit="ms", tz="UTC").strftime("%Y-%m-%d")


def nominal_ms(ts_ms: int | float) -> int:
    """The nearest UTC midnight (price timestamps sit seconds either side of midnight)."""
    return int(round(ts_ms / DAY_MS)) * DAY_MS


# ---------------------------------------------------------------- loading ---

def load_frame(path: Path, columns: list[str], label: str, res: Result) -> pd.DataFrame | None:
    """Read a CSV once, ignore a partial last line. All-string frame, or None on a schema failure.

    A missing/unreadable file raises FileProblem (exit 2)."""
    data, ignored = read_once(path)
    if ignored:
        res.warnings.append(f"{label}: ignored a partial last line ({ignored} bytes)")
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


# ------------------------------------------------------------------ part A ---

def check_daily(label: str, df: pd.DataFrame, positive: list[str], non_negative: list[str], allow_blank: list[str],
                res: Result) -> None:
    info: dict = {"rows": len(df)}
    res.files[label] = info
    num = pd.DataFrame(index=df.index)
    bad_numeric = False
    for c in df.columns:
        v = pd.to_numeric(df[c], errors="coerce")
        blank = int((df[c] == "").sum())
        n_bad = int((v.isna() | ~np.isfinite(v.fillna(0))).sum())
        if c in allow_blank:
            non_blank_bad = n_bad - blank
            if non_blank_bad:
                res.hard_failures.append(f"{label}: {non_blank_bad} non-numeric (not blank) value(s) in {c}")
                bad_numeric = True
            if blank:
                res.warnings.append(f"{label}: {blank} blank value(s) in {c}")
        elif n_bad:
            res.hard_failures.append(f"{label}: {n_bad} NaN/blank/non-numeric value(s) in {c}")
            bad_numeric = True
        num[c] = v
    info["numeric_ok"] = not bad_numeric

    ts_ok = num["timestamp_ms"].notna() & (num["timestamp_ms"] == num["timestamp_ms"].round())
    if int((~ts_ok).sum()) and not num["timestamp_ms"].isna().any():
        res.hard_failures.append(f"{label}: {int((~ts_ok).sum())} timestamp(s) are not whole milliseconds")
    num = num[num["timestamp_ms"].notna()].copy()
    num["timestamp_ms"] = num["timestamp_ms"].astype("int64")

    for c in positive:
        n = int((num[c] <= 0).sum())
        if n:
            res.hard_failures.append(f"{label}: {n} value(s) in {c} that are not positive")
    for c in non_negative:
        n = int((num[c] < 0).sum())
        if n:
            res.hard_failures.append(f"{label}: {n} negative value(s) in {c}")

    steps_raw = np.diff(num["timestamp_ms"].to_numpy())
    info["duplicates"] = int((steps_raw == 0).sum())
    info["out_of_order"] = int((steps_raw < 0).sum())
    if info["duplicates"]:
        res.hard_failures.append(f"{label}: {info['duplicates']} duplicate timestamp(s)")
    if info["out_of_order"]:
        res.hard_failures.append(f"{label}: timestamps not strictly increasing ({info['out_of_order']} backwards step(s))")

    today = res.now // DAY_MS
    n_today = int((num["timestamp_ms"] // DAY_MS >= today).sum())
    info["current_day_rows"] = n_today
    if n_today:
        res.hard_failures.append(f"{label}: {n_today} row(s) dated on the current UTC day or later (live partial day)")

    la = num[num["fetched_at_ms"] < num["timestamp_ms"]]
    info["lookahead_violations"] = len(la)
    if len(la):
        res.hard_failures.append(f"{label}: {len(la)} look-ahead violation(s): fetched_at_ms before timestamp_ms")
    # Not a failure: rows fetched before timestamp + 24 h. Their known-at time is timestamp + 24 h, not fetched_at_ms.
    info["fetched_before_known_at"] = int((num["fetched_at_ms"] < num["timestamp_ms"] + DAY_MS).sum())

    work = num.drop_duplicates("timestamp_ms").sort_values("timestamp_ms").reset_index(drop=True)
    if work.empty:
        return
    res.frames[label] = work
    info["first"], info["last"] = int(work["timestamp_ms"].iloc[0]), int(work["timestamp_ms"].iloc[-1])

    steps = np.diff(work["timestamp_ms"].to_numpy())
    info["distribution"] = (
        pd.Series(np.round(steps / HOUR_MS)).value_counts().sort_index().rename("count") if len(steps) else None
    )
    gap_mask = steps > DAY_MS + SPACING_TOL_MS
    short_mask = steps < DAY_MS - SPACING_TOL_MS
    ts = work["timestamp_ms"].to_numpy()
    info["gaps"] = [(int(ts[i]), int(ts[i + 1]), max(int(round(steps[i] / DAY_MS)) - 1, 0)) for i in np.flatnonzero(gap_mask)]
    info["short_steps"] = [(int(ts[i]), int(ts[i + 1])) for i in np.flatnonzero(short_mask)]
    info["missing_days"] = sum(g[2] for g in info["gaps"])
    info["max_jitter_s"] = float(np.abs(steps - DAY_MS).max() / 1000) if len(steps) else 0.0
    if info["gaps"]:
        res.warnings.append(f"{label}: {len(info['gaps'])} gap(s) above 25 h, {info['missing_days']} missing day(s)")
    if info["short_steps"]:
        res.warnings.append(f"{label}: {len(info['short_steps'])} step(s) shorter than 23 h")

    info["stats"] = {
        c: {"min": float(work[c].min()), "max": float(work[c].max()), "median": float(work[c].median()),
            "min_ts": int(work.loc[work[c].idxmin(), "timestamp_ms"]),
            "max_ts": int(work.loc[work[c].idxmax(), "timestamp_ms"])}
        for c in MAIN_COLUMNS[label] if work[c].notna().any()
    }
    if label == "defillama_tvl":
        prev = work["tvl"].shift()
        with np.errstate(divide="ignore", invalid="ignore"):
            pct = np.where(prev > 0, work["tvl"] / prev - 1, np.where(work["tvl"] > 0, np.inf, 0.0))
        mask = (prev.notna()) & (np.abs(pct) > TVL_JUMP)
        info["tvl_jumps"] = [
            (int(work.loc[i, "timestamp_ms"]), float(prev[i]), float(work.loc[i, "tvl"]), float(pct[i]))
            for i in np.flatnonzero(mask)
        ]
        if info["tvl_jumps"]:
            res.warnings.append(f"{label}: {len(info['tvl_jumps'])} day(s) with TVL change above 50% vs the previous day")


# ------------------------------------------------------------------ part B ---

def compare_stats(joined: pd.DataFrame, a: str, b: str) -> dict:
    """joined has columns ts (ms), a, b. Signed pct = a / b - 1; stats are on the absolute value."""
    d = joined.copy()
    d["pct"] = d[a] / d[b] - 1
    d["abs"] = d["pct"].abs()
    out = {
        "n": len(d),
        "mean": float(d["abs"].mean()), "median": float(d["abs"].median()),
        "p99": float(d["abs"].quantile(0.99)), "max": float(d["abs"].max()),
        "above": {t: int((d["abs"] > t).sum()) for t in PRICE_THRESHOLDS},
        "top": [(int(r.ts), float(getattr(r, a)), float(getattr(r, b)), float(r.pct))
                for r in d.sort_values("abs", ascending=False).head(TOP_N).itertuples()],
    }
    month = d["ts"].map(lambda t: _date(nominal_ms(t))[:7])
    over2 = d[d["abs"] > 0.02]
    out["by_month_over2"] = {m: (int((month[over2.index] == m).sum()), int((month == m).sum()))
                             for m in sorted(set(month[over2.index]))}
    return out


def price_vs_binance(label: str, klines_open: pd.Series, res: Result) -> None:
    if label not in res.frames:
        return
    w = res.frames[label][["timestamp_ms", "price"]].copy()
    # the Binance 1m open at the nearest minute to each external timestamp
    w["bn"] = (w["timestamp_ms"] / 60_000).round().astype("int64").mul(60_000).map(klines_open)
    covered = w.dropna(subset=["bn"])
    cmp = compare_stats(covered.rename(columns={"timestamp_ms": "ts"}), "price", "bn")
    cmp["unmatched"] = len(w) - len(covered)
    res.cross[f"{label}_vs_binance"] = cmp
    n2 = cmp["above"][0.02]
    if n2:
        res.warnings.append(f"{label} price differs from the Binance 1m open by more than 2% on {n2} of {cmp['n']} days")


def coingecko_vs_defillama(res: Result) -> None:
    if "coingecko" not in res.frames or "defillama_price" not in res.frames:
        return
    cg = res.frames["coingecko"][["timestamp_ms", "price"]].copy()
    d = res.frames["defillama_price"][["timestamp_ms", "price"]].copy()
    cg["day"], d["day"] = cg["timestamp_ms"].map(nominal_ms), d["timestamp_ms"].map(nominal_ms)
    j = cg.merge(d, on="day", suffixes=("_cg", "_dl")).rename(columns={"day": "ts"})
    if j.empty:
        res.warnings.append("coingecko vs defillama: no overlapping days")
        return
    cmp = compare_stats(j, "price_cg", "price_dl")
    res.cross["coingecko_vs_defillama"] = cmp
    if cmp["above"][0.02]:
        res.warnings.append(f"coingecko vs defillama price differ by more than 2% on {cmp['above'][0.02]} of {cmp['n']} days")


def derived_supply(res: Result) -> pd.DataFrame | None:
    if "coingecko" not in res.frames:
        return None
    w = res.frames["coingecko"]
    w = w[(w["price"] > 0) & w["market_cap"].notna()]
    s = pd.DataFrame({"ts": w["timestamp_ms"], "supply": w["market_cap"] / w["price"]}).reset_index(drop=True)
    if s.empty:
        return None
    prev = s["supply"].shift()
    pct = s["supply"] / prev - 1
    steps = s[(pct.abs() > SUPPLY_STEP) & prev.notna()]
    res.cross["supply"] = {
        "n": len(s),
        "first": (int(s["ts"].iloc[0]), float(s["supply"].iloc[0])),
        "last": (int(s["ts"].iloc[-1]), float(s["supply"].iloc[-1])),
        "min": (int(s.loc[s["supply"].idxmin(), "ts"]), float(s["supply"].min())),
        "max": (int(s.loc[s["supply"].idxmax(), "ts"]), float(s["supply"].max())),
        "steps": [(int(s.loc[i, "ts"]), float(s.loc[i, "supply"] - prev[i]), float(pct[i])) for i in steps.index],
    }
    return s


def supply_vs_recorder(s: pd.DataFrame | None, oi: pd.DataFrame, res: Result) -> None:
    if s is None:
        return
    mid = oi[oi["timestamp"] % DAY_MS == 0][["timestamp", "CMCCirculatingSupply"]]  # the 00:00 UTC row of each day
    j = s.merge(mid, left_on="ts", right_on="timestamp")
    out = {"overlap": len(j), "oi_rows": len(oi), "match": 0, "mismatches": []}
    if len(j):
        j = j.assign(diff=j["CMCCirculatingSupply"] / j["supply"] - 1)
        ok = j["diff"].abs() <= SUPPLY_MATCH_TOL
        out["match"] = int(ok.sum())
        out["first"], out["last"] = int(j["ts"].iloc[0]), int(j["ts"].iloc[-1])
        out["mismatches"] = [(int(r.ts), float(r.supply), float(r.CMCCirculatingSupply), float(r.diff))
                             for r in j[~ok].itertuples()]
        if out["mismatches"]:
            res.warnings.append(f"derived supply vs recorder CMCCirculatingSupply: {len(out['mismatches'])} of "
                                f"{len(j)} overlapping day(s) differ by more than 0.1%")
    else:
        res.warnings.append("derived supply vs recorder CMCCirculatingSupply: no overlapping 00:00 UTC rows")
    res.cross["supply_vs_recorder"] = out


def load_klines_open(path: Path, res: Result) -> pd.Series | None:
    df = load_frame(path, bk.COLUMNS, "binance_klines", res)
    if df is None:
        return None
    t = pd.to_numeric(df["open_time"], errors="coerce")
    o = pd.to_numeric(df["open"], errors="coerce")
    ok = t.notna() & o.notna()
    if int((~ok).sum()):
        res.warnings.append(f"binance_klines: {int((~ok).sum())} row(s) with a non-numeric open_time/open ignored in the cross-check")
    s = pd.Series(o[ok].to_numpy(), index=t[ok].astype("int64").to_numpy())
    return s[~s.index.duplicated()]


def load_oi(path: Path, res: Result) -> pd.DataFrame | None:
    df = load_frame(path, OI_DATASET.columns, "open_interest", res)
    if df is None:
        return None
    out = pd.DataFrame({
        "timestamp": pd.to_numeric(df["timestamp"], errors="coerce"),
        "CMCCirculatingSupply": pd.to_numeric(df["CMCCirculatingSupply"], errors="coerce"),
    }).dropna()
    out["timestamp"] = out["timestamp"].astype("int64")
    return out


def run_checks(directory: Path, now: int | None = None) -> Result:
    directory = Path(directory)
    res = Result(str(directory), now_ms() if now is None else now)
    raw: dict[str, pd.DataFrame | None] = {}
    for label, (name, columns, *_rest) in DAILY_FILES.items():
        raw[label] = load_frame(directory / name, columns, label, res)  # FileProblem if the file is missing
    klines = load_klines_open(directory / KLINES_NAME, res)
    oi = load_oi(OI_DATASET.csv_path(directory), res)
    for label, (name, columns, pos, nonneg, blank) in DAILY_FILES.items():
        if raw[label] is not None:
            check_daily(label, raw[label], pos, nonneg, blank, res)
    if klines is not None:
        for label in ("coingecko", "defillama_price"):
            price_vs_binance(label, klines, res)
    coingecko_vs_defillama(res)
    supply = derived_supply(res)
    if oi is not None:
        supply_vs_recorder(supply, oi, res)
    return res


# ------------------------------------------------------------------ report ---

def _pct(x: float) -> str:
    return f"{100 * x:+.2f}%" if np.isfinite(x) else "inf"


def _cmp_section(title: str, c: dict, a_name: str, b_name: str) -> list[str]:
    L = ["", f"### {title}", ""]
    L += [f"- Days compared: {c['n']:,}" + (f" ({c['unmatched']:,} external days had no Binance minute)" if c.get("unmatched") else ""),
          f"- Absolute difference: mean {100 * c['mean']:.3f}%, median {100 * c['median']:.3f}%, p99 {100 * c['p99']:.2f}%, max {100 * c['max']:.2f}%"]
    for t in PRICE_THRESHOLDS:
        L.append(f"- Days above {100 * t:g}%: {c['above'][t]:,} ({100 * c['above'][t] / c['n']:.1f}%)")
    L.append(f"- Share within 1%: {100 * (1 - c['above'][0.01] / c['n']):.1f}%")
    if c["by_month_over2"]:
        L += ["", "Days above 2%, by month (days above 2% / days compared that month):", "", "| Month | Above 2% | Compared |", "|---|---|---|"]
        L += [f"| {m} | {n2} | {n} |" for m, (n2, n) in c["by_month_over2"].items()]
    L += ["", f"The {len(c['top'])} largest differences (date = nearest UTC midnight; {a_name} vs {b_name}):", "",
          f"| Date | {a_name} | {b_name} | Difference |", "|---|---|---|---|"]
    L += [f"| {_date(nominal_ms(t))} | {a:.8g} | {b:.8g} | {_pct(p)} |" for t, a, b, p in c["top"]]
    return L


def render_report(res: Result) -> str:
    L = ["# Daily external data quality report (Gate 1)", ""]
    L += [f"- Directory: `{res.directory}` (read-only; each file read once; a partial last line is ignored; no network)",
          f"- Checked at: {_ts(res.now)}", f"- Verdict: **{'PASS' if res.passed else 'FAIL'}**",
          "- Timing rule: every daily row from these three files is treated as **known at timestamp + 24 h**, never earlier. "
          "`fetched_at_ms` is only checked for look-ahead (it must be at or after the timestamp), it is not the known-at time.", ""]
    L += ["## Hard failures", ""] + ([f"- {m}" for m in res.hard_failures] or ["- none"])
    L += ["", "## Warnings and flags", ""] + ([f"- {m}" for m in res.warnings] or ["- none"])

    L += ["", "# Part A: each file on its own"]
    for label, d in res.files.items():
        L += ["", f"## {label}", ""]
        L += [f"- Rows: {d['rows']:,}; first {_ts(d.get('first'))}, last {_ts(d.get('last'))}",
              f"- Duplicates: {d['duplicates']}; out-of-order steps: {d['out_of_order']}; rows on the current UTC day: {d['current_day_rows']}; "
              f"look-ahead violations: {d['lookahead_violations']}",
              f"- Rows fetched before timestamp + 24 h (allowed; known-at is still timestamp + 24 h): {d['fetched_before_known_at']}"]
        if d["distribution"] is not None:
            L += [f"- Largest deviation of a step from 24 h: {d['max_jitter_s']:,.0f} s (tolerance {SPACING_TOL_MS // 1000:,} s)",
                  "", "Spacing distribution (hours between consecutive timestamps, rounded):", "", "| Hours | Count |", "|---|---|"]
            L += [f"| {h:g} | {int(c):,} |" for h, c in d["distribution"].items()]
        L += ["", f"Gaps above 25 h ({len(d['gaps'])}; {d['missing_days']} missing day(s); listed, not failures):", ""]
        if d["gaps"]:
            L += ["| From (UTC) | To (UTC) | Missing days |", "|---|---|---|"] + [f"| {_ts(a)} | {_ts(b)} | {m} |" for a, b, m in d["gaps"]]
        else:
            L += ["none"]
        if d["short_steps"]:
            L += ["", f"Steps shorter than 23 h ({len(d['short_steps'])}):", ""] + [f"- {_ts(a)} to {_ts(b)}" for a, b in d["short_steps"]]
        if d["stats"]:
            L += ["", "Main values (flagged, never clipped):", "", "| Column | Min | Min date | Max | Max date | Median |", "|---|---|---|---|---|---|"]
            L += [f"| {c} | {s['min']:.8g} | {_date(s['min_ts'])} | {s['max']:.8g} | {_date(s['max_ts'])} | {s['median']:.8g} |"
                  for c, s in d["stats"].items()]
        if "tvl_jumps" in d:
            L += ["", f"Days where TVL changed by more than 50% vs the previous day ({len(d['tvl_jumps'])}):", ""]
            if d["tvl_jumps"]:
                L += ["| Date (UTC) | Previous TVL | TVL | Change |", "|---|---|---|---|"]
                L += [f"| {_date(t)} | {p:,.0f} | {v:,.0f} | {_pct(c)} |" for t, p, v, c in d["tvl_jumps"]]
            else:
                L += ["none"]

    L += ["", "# Part B: cross-checks"]
    for key, title, a, b in (
        ("coingecko_vs_binance", "CoinGecko price vs Binance 1m open (nearest minute)", "coingecko", "binance"),
        ("defillama_price_vs_binance", "DeFiLlama price vs Binance 1m open (nearest minute)", "defillama", "binance"),
        ("coingecko_vs_defillama", "CoinGecko price vs DeFiLlama price (same nearest-midnight day)", "coingecko", "defillama"),
    ):
        if key in res.cross:
            L += _cmp_section(title, res.cross[key], a, b)
    s = res.cross.get("supply")
    if s:
        L += ["", "### Derived circulating supply from CoinGecko (market_cap / price)", "",
              f"- Days: {s['n']:,}",
              f"- First: {s['first'][1]:,.0f} ({_date(s['first'][0])}); last: {s['last'][1]:,.0f} ({_date(s['last'][0])})",
              f"- Min: {s['min'][1]:,.0f} ({_date(s['min'][0])}); max: {s['max'][1]:,.0f} ({_date(s['max'][0])})",
              "", f"Supply step candidates (change above {100 * SUPPLY_STEP:g}% vs the previous stored day): {len(s['steps'])}", ""]
        if s["steps"]:
            L += ["| Date (UTC) | Change (tokens) | Change | Cause |", "|---|---|---|---|"]
            L += [f"| {_date(t)} | {d:+,.0f} | {_pct(p)} | cause unverified |" for t, d, p in s["steps"]]
        else:
            L += ["none"]
    r = res.cross.get("supply_vs_recorder")
    if r:
        L += ["", "### Derived supply vs recorder open-interest CMCCirculatingSupply (00:00 UTC row of each day)", "",
              f"- Overlapping days: {r['overlap']:,}" + (f" ({_date(r['first'])} to {_date(r['last'])})" if r["overlap"] else ""),
              f"- Within {100 * SUPPLY_MATCH_TOL:g}%: {r['match']:,} of {r['overlap']:,}",
              "", f"Mismatches ({len(r['mismatches'])}):", ""]
        if r["mismatches"]:
            L += ["| Date (UTC) | Derived (CoinGecko) | CMCCirculatingSupply (Binance) | Binance vs derived |", "|---|---|---|---|"]
            L += [f"| {_date(t)} | {a:,.0f} | {b:,.0f} | {_pct(p)} |" for t, a, b, p in r["mismatches"]]
        else:
            L += ["none"]
    return "\n".join(L) + "\n"


def console_summary(res: Result, report: Path) -> str:
    out = [f"Gate 1 daily external quality: {'PASS' if res.passed else 'FAIL'}   (checked {_ts(res.now)})"]
    for label, d in res.files.items():
        out.append(f"  {label:16s} rows {d['rows']:,}  {_date(d['first']) if 'first' in d else 'n/a'} to "
                   f"{_date(d['last']) if 'last' in d else 'n/a'}  gaps {len(d.get('gaps', []))} ({d.get('missing_days', 0)} days)  "
                   f"current-day rows {d['current_day_rows']}  lookahead {d['lookahead_violations']}")
    for key, name in (("coingecko_vs_binance", "CoinGecko vs Binance"), ("defillama_price_vs_binance", "DeFiLlama vs Binance"),
                      ("coingecko_vs_defillama", "CoinGecko vs DeFiLlama")):
        c = res.cross.get(key)
        if c:
            out.append(f"  {name:24s} days {c['n']:,}  median {100 * c['median']:.3f}%  p99 {100 * c['p99']:.2f}%  max {100 * c['max']:.1f}%  "
                       f">1% {c['above'][0.01]}  >2% {c['above'][0.02]}  >5% {c['above'][0.05]}  "
                       f"within 1%: {100 * (1 - c['above'][0.01] / c['n']):.1f}%")
    s = res.cross.get("supply")
    if s:
        out.append(f"  derived supply: first {s['first'][1]:,.0f}, last {s['last'][1]:,.0f}, steps >1%: {len(s['steps'])}")
        for t, d, p in s["steps"]:
            out.append(f"    supply step {_date(t)}: {d:+,.0f} ({_pct(p)}) cause unverified")
    r = res.cross.get("supply_vs_recorder")
    if r:
        out.append(f"  supply vs recorder: {r['match']} of {r['overlap']} days within 0.1%; mismatches {len(r['mismatches'])}")
        for t, a, b, p in r["mismatches"]:
            out.append(f"    {_date(t)}: derived {a:,.0f} vs Binance {b:,.0f} ({_pct(p)})")
    for m in res.hard_failures:
        out.append(f"  HARD FAIL: {m}")
    for m in res.warnings:
        out.append(f"  warning:   {m}")
    out.append(f"  report: {report}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only quality checks on the daily external files.")
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
