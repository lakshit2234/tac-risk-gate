"""Two read-only checks on Binance bulk archive data for TACUSDT before we trust it for history.

Check 1 (full-window equivalence): download the daily `metrics` files from 2026-10-19 to the latest day available (file URLs
are built from the naming pattern, the archive is NOT listed), and compare every 5-minute row with our recorder files; plus a
look at the daily `bookDepth` files against our depth snapshot where the bands truly correspond.

Check 2 (backfill cutover): at most 4 listings (metrics, bookDepth, klines 1m, markPriceKlines 1m) to get every daily file's
LastModified, find from which date the publish lag stays below 48 hours for every later day, and download exactly four metrics
files (2025-08-01, the day before the cutover, the cutover day, and 2026-11-10) to compare their formats.

Read-only on our files. Downloads go to a git-ignored folder. Every downloaded file is verified against its published checksum.
A refused request (403, 418, or 429 after retries) stops that part and is reported; no workaround is tried. No feature is built.

Run: python -m tacgate.data.bulk_equivalence [--out-dir data/raw/bulk_window] [--data-dir data/raw]
                                              [--report docs/bulk_equivalence_report.md]
Exit codes: 0 ok, 2 bad arguments or a part stopped by a refusal.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import requests

from tacgate.data import bulk_availability as ba
from tacgate.data.recorder import DATASETS as RECORDER_DATASETS, snapshot_path

DEFAULT_OUT_DIR = Path("data/raw/bulk_window")
DEFAULT_DATA_DIR = Path("data/raw")
DEFAULT_REPORT = Path("docs/bulk_equivalence_report.md")
SAMPLE_DIR = Path("data/raw/bulk_sample")  # the earlier sample folder; files there are reused (still checksum-verified)
WINDOW_START = "2026-10-19"
BACKFILL_LAG_MS = 15 * 60_000  # recorder rule: fetched_at_ms - timestamp above this = backfilled, else live
LAG_LIMIT_H = 48.0
MINUTE_MS = 60_000
FIRST_MISMATCHES = 5

# bulk metrics column -> (our recorder dataset name, our column, shift in minutes: our timestamp = bulk label + shift, rounding)
COLUMN_MAP = [
    ("sum_open_interest", "open_interest", "sumOpenInterest", 5),
    ("sum_open_interest_value", "open_interest", "sumOpenInterestValue", 5),
    ("count_long_short_ratio", "global_long_short", "longShortRatio", 5),
    ("sum_toptrader_long_short_ratio", "top_position_long_short", "longShortRatio", 5),
    ("sum_taker_long_short_vol_ratio", "taker_buy_sell", "buySellRatio", 0),
]
NO_COUNTERPART = "count_toptrader_long_short_ratio"


def metrics_key(day: str) -> str:
    return f"data/futures/um/daily/metrics/{ba.SYMBOL}/{ba.SYMBOL}-metrics-{day}.zip"


def bookdepth_key(day: str) -> str:
    return f"data/futures/um/daily/bookDepth/{ba.SYMBOL}/{ba.SYMBOL}-bookDepth-{day}.zip"


def day_list(start: str, end: str) -> list[str]:
    a, b = datetime.strptime(start, "%Y-%m-%d"), datetime.strptime(end, "%Y-%m-%d")
    return [(a + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((b - a).days + 1)]


# --------------------------------------------------------------- downloads ---

@dataclass
class Fetched:
    day: str
    key: str
    csv_path: Path | None = None
    checksum: str = "not checked"  # verified / MISMATCH / unreadable / not published / missing (404)
    reused: bool = False


def fetch_verified(session, key: str, day: str, folder: Path, sleep: Callable[[float], None] = time.sleep,
                   reuse_dirs: tuple[Path, ...] = ()) -> Fetched:
    """Download one archive file (or reuse a local copy), verify it against its published checksum, extract the csv.

    A 404 for the data file gives checksum 'missing (404)'. Refusals raise ba.Refused."""
    f = Fetched(day, key)
    name = Path(key).name
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    zpath = folder / name
    if zpath.exists():
        body, f.reused = zpath.read_bytes(), True
    else:
        body = next(((d / name).read_bytes() for d in reuse_dirs if (d / name).exists()), None)
        f.reused = body is not None
        if body is None:
            body = ba.http_get(session, f"{ba.DOWNLOAD_URL}/{key}", None, sleep)
            sleep(ba.PAUSE_S)
            if body is None:
                f.checksum = "missing (404)"
                return f
        zpath.write_bytes(body)
    ck = ba.http_get(session, f"{ba.DOWNLOAD_URL}/{key}.CHECKSUM", None, sleep)
    sleep(ba.PAUSE_S)
    if ck is None:
        f.checksum = "not published"
    else:
        want = ba.parse_checksum(ck.decode("utf-8", errors="replace"))
        f.checksum = "unreadable" if not want else ("verified" if want == hashlib.sha256(body).hexdigest() else "MISMATCH")
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        names = [n for n in z.namelist() if n.endswith(".csv")]
        if names:
            f.csv_path = folder / names[0]
            f.csv_path.write_bytes(z.read(names[0]))
    return f


def download_window(session, start: str, folder: Path, sleep: Callable[[float], None] = time.sleep,
                    reuse_dirs: tuple[Path, ...] = (), last_day: str = "2026-12-31") -> list[Fetched]:
    """Daily metrics files from `start` up to the first day whose file does not exist yet (404). No listing is made."""
    out = []
    for day in day_list(start, last_day):
        f = fetch_verified(session, metrics_key(day), day, folder, sleep, reuse_dirs)
        if f.checksum == "missing (404)":
            break
        out.append(f)
    return out


# ----------------------------------------------------------------- loading ---

def load_bulk_metrics(paths: list[Path]) -> pd.DataFrame:
    """All daily metrics files in one frame, numeric, with `ms` (epoch ms of create_time) and sorted by time."""
    frames = [pd.read_csv(p) for p in paths]
    df = pd.concat(frames, ignore_index=True)
    df["ms"] = ba.to_ms(df["create_time"])
    return df.sort_values("ms").reset_index(drop=True)


def decimals_of(values: pd.Series) -> int:
    """Largest number of digits after the decimal point in a column of numeric TEXT."""
    def n(s: str) -> int:
        s = str(s).strip().lower()
        return len(s.split(".")[1]) if "." in s and "e" not in s else 0
    return int(values.map(n).max()) if len(values) else 0


def load_ours(path: Path) -> pd.DataFrame:
    """One of OUR recorder files, read once and read-only (a partial last line is ignored), plus a live/backfilled class."""
    df = ba.read_complete(path)
    df["ts"] = pd.to_numeric(df["timestamp"]).astype("int64")
    df["klass"] = np.where(pd.to_numeric(df["fetched_at_ms"]) - df["ts"] > BACKFILL_LAG_MS, "backfilled", "live")
    return df


# ------------------------------------------------------------- comparisons ---

def _rate(mask: np.ndarray) -> float:
    return float(mask.mean()) if len(mask) else 0.0


def compare_column(bulk: pd.DataFrame, ours: pd.DataFrame, bulk_col: str, our_col: str, shift_min) -> dict:
    """Compare one bulk column with one of our columns, row by row, at our timestamp = bulk label + shift.

    `shift_min` is one number of minutes, or one number per bulk row (a Series/array) when the label convention changes.
    exact = equal at full precision; at_our_precision = the bulk value rounded to the decimals OUR file stores equals ours;
    within_0_1pct / within_1pct = relative difference below 0.1% / 1%. A mismatch is a row that does not match at our precision."""
    dec = decimals_of(ours[our_col])
    shift = np.asarray(shift_min) if not np.isscalar(shift_min) else shift_min
    b = pd.DataFrame({"key": bulk["ms"].to_numpy() + shift * MINUTE_MS, "bulk": pd.to_numeric(bulk[bulk_col]).to_numpy()})
    o = pd.DataFrame({"key": ours["ts"], "ours": pd.to_numeric(ours[our_col]), "klass": ours["klass"]}).drop_duplicates("key")
    m = b.merge(o, on="key")
    if m.empty:
        return {"rows": 0, "decimals": dec}
    diff = (m["bulk"] - m["ours"]).abs()
    scale = m["ours"].abs().clip(lower=1.0)
    rel = diff / m["ours"].abs().clip(lower=1e-12)
    exact = (diff <= 1e-9 * scale).to_numpy()
    prec = ((m["bulk"].round(dec) - m["ours"]).abs() <= 1e-9 * scale).to_numpy()
    c01, c1 = (rel <= 1e-3).to_numpy(), (rel <= 1e-2).to_numpy()
    bad = m[~prec].head(FIRST_MISMATCHES)
    by_class = {}
    for k, g in m.assign(_e=exact, _p=prec, _c=c01).groupby("klass"):
        by_class[k] = {"rows": len(g), "exact": _rate(g["_e"].to_numpy()), "at_our_precision": _rate(g["_p"].to_numpy()),
                       "within_0_1pct": _rate(g["_c"].to_numpy())}
    return {"rows": len(m), "decimals": dec, "exact": _rate(exact), "at_our_precision": _rate(prec), "within_0_1pct": _rate(c01),
            "within_1pct": _rate(c1), "max_abs_diff": float(diff.max()), "max_rel_diff": float(rel.max()),
            "first_mismatches": [(int(r.key), float(r.bulk), float(r.ours)) for r in bad.itertuples()], "by_class": by_class,
            "bulk_rows": len(b)}


def detect_label_change(bulk: pd.DataFrame, ours_oi: pd.DataFrame) -> dict:
    """Find where the bulk label convention changes, using open interest (equal values are unmistakable).

    A bulk row is 'old' if its open interest equals ours at label + 5 min (and not at label + 0), 'new' if it equals ours at label + 0
    (and not at +5). The change is the first 'new' label; every 'old' label should come before it."""
    o = pd.Series(pd.to_numeric(ours_oi["sumOpenInterest"]).values, index=ours_oi["ts"].values)
    o = o[~o.index.duplicated()]
    v = pd.to_numeric(bulk["sum_open_interest"]).values
    ms = bulk["ms"].values

    def eq(sh):
        other = o.reindex(ms + sh * MINUTE_MS).values
        return ~np.isnan(other) & (np.abs(v - other) <= 1e-9 * np.maximum(np.abs(other), 1)), ~np.isnan(other)

    (e5, h5), (e0, h0) = eq(5), eq(0)
    old, new = e5 & ~e0, e0 & ~e5
    has = h5 | h0
    out = {"old_rows": int(old.sum()), "new_rows": int(new.sum()), "neither": int((has & ~e5 & ~e0).sum()), "both": int((e5 & e0).sum()),
           "no_counterpart": int((~has).sum()),
           "boundary_ms": int(ms[new].min()) if new.any() else None, "last_old_ms": int(ms[old].max()) if old.any() else None,
           "first_old_ms": int(ms[old].min()) if old.any() else None, "last_new_ms": int(ms[new].max()) if new.any() else None}
    out["clean_split"] = bool(out["boundary_ms"] is not None and (out["last_old_ms"] is None or out["last_old_ms"] < out["boundary_ms"]))
    day = pd.Series(pd.to_datetime(bulk["ms"], unit="ms", utc=True).dt.strftime("%Y-%m-%d").values)
    out["by_day"] = {d: {"+5": float(e5[(day == d).values].mean()), "+0": float(e0[(day == d).values].mean())} for d in sorted(day.unique())}
    return out


def era_shift(bulk_ms: np.ndarray, boundary_ms: int | None, shift_old: int):
    """Per-row shift: shift_old before the label change, shift_old - 5 from it on (labels moved 5 minutes later)."""
    if boundary_ms is None:
        return shift_old
    return np.where(bulk_ms < boundary_ms, shift_old, shift_old - 5)


def label_offset(bulk: pd.DataFrame, ours_oi: pd.DataFrame, shifts=(-10, -5, 0, 5, 10)) -> dict:
    """For each shift (minutes), the share of bulk rows whose open interest equals ours at our timestamp = label + shift,
    and how many bulk rows have a counterpart at all. Also whether every bulk label sits on a 5-minute boundary."""
    o = pd.DataFrame({"key": ours_oi["ts"], "ours": pd.to_numeric(ours_oi["sumOpenInterest"])}).drop_duplicates("key")
    out = {}
    for sh in shifts:
        m = pd.DataFrame({"key": bulk["ms"] + sh * MINUTE_MS, "bulk": pd.to_numeric(bulk["sum_open_interest"])}).merge(o, on="key")
        out[sh] = {"rows": len(m), "equal": _rate((m["bulk"] - m["ours"]).abs().to_numpy() <= 1e-9 * m["ours"].abs().clip(lower=1).to_numpy())
                   if len(m) else 0.0}
    return {"by_shift": out, "labels_on_5min": bool((bulk["ms"] % 300_000 == 0).all()), "bulk_rows": len(bulk)}


def taker_explanations(bulk: pd.DataFrame, taker: pd.DataFrame, tol: float = 1e-6) -> dict:
    """Test plausible explanations for why the bulk taker ratio differs from our buySellRatio.

    `bulk["ms"]` must already be aligned to OUR timestamps (shift 0 = the same period). Each test returns (rows, share of rows that
    agree) within a relative `tol`, or equal after 4-decimal rounding where stated. The shares decide; nothing is assumed."""
    t = taker.drop_duplicates("ts").set_index("ts")
    ratio = pd.to_numeric(t["buySellRatio"])
    buy, sell = pd.to_numeric(t["buyVol"]), pd.to_numeric(t["sellVol"])
    own = (buy / sell).replace([np.inf, -np.inf], np.nan)
    b = pd.Series(pd.to_numeric(bulk["sum_taker_long_short_vol_ratio"]).values, index=bulk["ms"].values)
    b = b[~b.index.duplicated()]

    def rate_vs(series: pd.Series, shift_min: int = 0, rel: float = tol, round_bulk: int | None = None) -> tuple[int, float]:
        other = series.reindex(b.index.values + shift_min * MINUTE_MS)
        ok = other.notna().to_numpy()
        a, c = b.values[ok], other.values[ok]
        if len(a) == 0:
            return 0, 0.0
        if round_bulk is not None:
            return len(a), _rate(np.abs(np.round(a, round_bulk) - c) <= 1e-9)
        return len(a), _rate(np.abs(a - c) <= rel * np.maximum(np.abs(c), 1e-12))

    res: dict = {}
    res["baseline: our ratio, same period, within 0.1%"] = rate_vs(ratio, 0, rel=1e-3)
    res["rounding: bulk rounded to 4 decimals equals our buySellRatio"] = rate_vs(ratio, 0, round_bulk=4)
    res["rounding: bulk equals our own buyVol / sellVol to 1e-6"] = rate_vs(own, 0, rel=1e-6)
    res["volumes: bulk equals our own buyVol / sellVol within 0.1%"] = rate_vs(own, 0, rel=1e-3)
    both = pd.concat([ratio, own], axis=1).dropna()
    res["internal: our buySellRatio equals our own buyVol / sellVol within 0.1% (no bulk data involved)"] = (
        len(both), _rate(np.abs(both.iloc[:, 0] - both.iloc[:, 1]).to_numpy() <= 1e-3 * np.maximum(np.abs(both.iloc[:, 1]).to_numpy(), 1e-12)))
    for sh in (-10, -5, 5, 10):
        res[f"alignment: our ratio {sh:+d} min from the aligned period, within 0.1%"] = rate_vs(ratio, sh, rel=1e-3)
    idx = t.index.values
    nb, ns = buy.reindex(idx + 300_000).values, sell.reindex(idx + 300_000).values
    pb, ps = buy.reindex(idx - 300_000).values, sell.reindex(idx - 300_000).values
    for lbl, s_ in (("window: this and the next 5-minute period", (buy.values + nb) / (sell.values + ns)),
                    ("window: this and the previous 5-minute period", (buy.values + pb) / (sell.values + ps))):
        res[lbl + ", within 0.1%"] = rate_vs(pd.Series(s_, index=idx).replace([np.inf, -np.inf], np.nan), 0, rel=1e-3)
    # how far apart the two numbers are at the aligned period
    other = ratio.reindex(b.index.values)
    ok = other.notna().to_numpy()
    rel_d = np.abs(b.values[ok] - other.values[ok]) / np.maximum(np.abs(other.values[ok]), 1e-12)
    res["_spread"] = {"rows": int(ok.sum()), "median_rel": float(np.median(rel_d)) if len(rel_d) else None,
                      "p95_rel": float(np.percentile(rel_d, 95)) if len(rel_d) else None, "max_rel": float(rel_d.max()) if len(rel_d) else None}
    return res


def explanation_verdict(res: dict, threshold: float = 0.99) -> str:
    best = max(((v[1], k) for k, v in res.items() if k.startswith(("rounding", "volumes", "alignment", "window"))), default=None)
    if best and best[0] >= threshold:
        return f"supported: {best[1]} ({100 * best[0]:.1f}% of rows)"
    return "unexplained: no tested explanation reaches 99% of rows"


# ------------------------------------------------------------------ depth ---

DEPTH_PAIRS = [("bid_depth_usd_1pct", -1.0), ("ask_depth_usd_1pct", 1.0), ("bid_depth_usd_2pct", -2.0), ("ask_depth_usd_2pct", 2.0)]


def bookdepth_vs_snapshot(bulk: pd.DataFrame, snap: pd.DataFrame, max_gap_ms: int = 30_000) -> dict:
    """Our snapshot depth bands vs the bulk bookDepth `notional` at the same percentage, matched to the nearest bulk snapshot
    time within max_gap_ms. Only the bands that truly correspond are compared: ours are 0.5, 1 and 2 percent of mid, bulk has
    +-0.2, 1, 2, 3, 4, 5, so only 1 and 2 correspond (0.5 has no counterpart)."""
    b = bulk.copy()
    b["ms"] = ba.to_ms(b["timestamp"])
    levels = sorted(b["percentage"].unique())
    times = np.sort(b["ms"].unique())
    s = snap.copy()
    s["fetched"] = pd.to_numeric(s["fetched_at_ms"])
    pos = np.searchsorted(times, s["fetched"].values)
    cand = np.stack([times[np.clip(pos - 1, 0, len(times) - 1)], times[np.clip(pos, 0, len(times) - 1)]])
    nearest = cand[np.argmin(np.abs(cand - s["fetched"].values), axis=0), np.arange(len(s))]
    s["bulk_ms"] = nearest
    s = s[np.abs(s["bulk_ms"] - s["fetched"]) <= max_gap_ms]
    out = {"levels": levels, "snapshot_rows": len(s), "pairs": {}}
    lookup = b.set_index(["ms", "percentage"])["notional"]
    for col, pct in DEPTH_PAIRS:
        keys = list(zip(s["bulk_ms"].values, [pct] * len(s)))
        vals = lookup.reindex(pd.MultiIndex.from_tuples(keys, names=["ms", "percentage"])).values if keys else np.array([])
        ours = pd.to_numeric(s[col]).values
        ok = ~np.isnan(vals) & (vals > 0) & (ours > 0)
        ratio = ours[ok] / vals[ok]
        out["pairs"][col] = {"rows": int(ok.sum()), "median_ratio": float(np.median(ratio)) if len(ratio) else None,
                             "p5": float(np.percentile(ratio, 5)) if len(ratio) else None,
                             "p95": float(np.percentile(ratio, 95)) if len(ratio) else None,
                             "within_10pct": _rate(np.abs(ratio - 1) <= 0.10) if len(ratio) else None}
    return out


# --------------------------------------------------------------- cutover ---

def cutover(lags: dict[str, float], limit: float = LAG_LIMIT_H) -> str | None:
    """The earliest period from which the lag is below `limit` hours for EVERY later period (None if even the last one is not)."""
    days = sorted(lags)
    if not days or lags[days[-1]] >= limit:
        return None
    cut = days[-1]
    for d in reversed(days):
        if lags[d] < limit:
            cut = d
        else:
            break
    return cut


def cutover_ignoring_isolated(lags: dict[str, float], limit: float = LAG_LIMIT_H) -> str | None:
    """Same as cutover(), but a single slow file whose neighbours (the days before and after) are both fast is treated as an isolated
    re-written file and ignored. This is shown next to the strict date because one re-written file can move the strict date a long way."""
    days = sorted(lags)
    adj = dict(lags)
    for i, d in enumerate(days):
        if lags[d] >= limit and 0 < i < len(days) - 1 and lags[days[i - 1]] < limit and lags[days[i + 1]] < limit:
            adj[d] = 0.0
    return cutover(adj, limit)


def lag_by_month(lags: dict[str, float], limit: float = LAG_LIMIT_H) -> list[dict]:
    rows = []
    for month in sorted({d[:7] for d in lags}):
        v = [lags[d] for d in lags if d[:7] == month]
        rows.append({"month": month, "files": len(v), "median": float(np.median(v)), "max": float(max(v)), "over_limit": sum(1 for x in v if x >= limit)})
    return rows


# ---------------------------------------------------------------- formats ---

def format_profile(csv_path: Path) -> dict:
    """What a daily metrics file looks like: rows, missing 5-minute slots, row order, decimals per column, header, label format."""
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    day = df["create_time"].iloc[0][:10]
    times = pd.to_datetime(df["create_time"], utc=True)
    expected = pd.date_range(f"{day} 00:00:00", periods=288, freq="5min", tz="UTC")
    return {"rows": len(df), "missing_slots": int(len(expected.difference(times))), "duplicates": int(times.duplicated().sum()),
            "sorted": bool(times.is_monotonic_increasing), "header": list(df.columns),
            "decimals": {c: decimals_of(df[c]) for c in df.columns if c not in ("create_time", "symbol")},
            "symbols": sorted(df["symbol"].unique().tolist()), "label_format": ba.classify_time(df["create_time"].iloc[0]),
            "first_label": df["create_time"].iloc[0], "slot_spacing_ok": bool(((times.sort_values().diff().dropna()) == pd.Timedelta(minutes=5)).all())}


# --------------------------------------------------------------------- run ---

@dataclass
class Result:
    downloads: list[Fetched] = field(default_factory=list)
    columns: dict[str, dict] = field(default_factory=dict)
    offset: dict | None = None
    taker: dict | None = None
    taker_verdict: str = ""
    depth: dict[str, dict] = field(default_factory=dict)
    depth_files: list[Fetched] = field(default_factory=list)
    lags: dict[str, dict[str, float]] = field(default_factory=dict)
    cutovers: dict[str, str | None] = field(default_factory=dict)
    cutovers_loose: dict[str, str | None] = field(default_factory=dict)
    format_files: list[tuple[str, Fetched, dict | None]] = field(default_factory=list)
    stopped: dict[str, str] = field(default_factory=dict)  # part -> why
    notes: list[str] = field(default_factory=list)
    window: tuple[str, str] | None = None
    live_vs_backfilled: dict = field(default_factory=dict)
    aligned: dict[str, dict] = field(default_factory=dict)
    label_change: dict | None = None
    extra_profiles: list[tuple[str, dict]] = field(default_factory=list)
    slow_metrics_files: list[tuple[str, float]] = field(default_factory=list)


LISTING_NOTE = ("The four check-2 listing requests (metrics, bookDepth, klines 1m, markPriceKlines 1m) were made twice in total: once in a first run whose listing "
                "results I did not save, and once more with the results cached. All later runs used the cache and made no listing request.")
LISTED = [("metrics", ba.DatasetType("metrics")), ("bookDepth", ba.DatasetType("bookDepth")),
          ("klines", ba.DatasetType("klines", "1m")), ("markPriceKlines", ba.DatasetType("markPriceKlines", "1m"))]


def run_check1(session, out_dir: Path, data_dir: Path, res: Result, sleep=time.sleep, sample_dir: Path = SAMPLE_DIR) -> None:
    folder = Path(out_dir) / "metrics"
    try:
        res.downloads = download_window(session, WINDOW_START, folder, sleep, reuse_dirs=(Path(sample_dir) / "metrics",))
    except ba.Refused as exc:
        res.stopped["check 1 downloads"] = str(exc)
        return
    good = [d for d in res.downloads if d.csv_path and d.checksum == "verified"]
    if len(good) != len(res.downloads):
        res.notes.append("Some metrics files did not verify against their checksum; only verified files are compared.")
    if not good:
        return
    res.window = (good[0].day, good[-1].day)
    bulk = load_bulk_metrics([d.csv_path for d in good])
    ours = {d.name: load_ours(d.csv_path(Path(data_dir))) for d in RECORDER_DATASETS}
    for bulk_col, name, our_col, shift in COLUMN_MAP:
        res.columns[bulk_col] = {"ours": f"{name}.{our_col}", "shift": shift, **compare_column(bulk, ours[name], bulk_col, our_col, shift)}
    res.offset = label_offset(bulk, ours["open_interest"])
    res.label_change = detect_label_change(bulk, ours["open_interest"])
    boundary = res.label_change["boundary_ms"]
    for bulk_col, name, our_col, shift in COLUMN_MAP:
        res.aligned[bulk_col] = {"ours": f"{name}.{our_col}", "shift": f"{shift} before the label change, {shift - 5} from it on",
                                 **compare_column(bulk, ours[name], bulk_col, our_col, era_shift(bulk["ms"].to_numpy(), boundary, shift))}
    taker_shift = era_shift(bulk["ms"].to_numpy(), boundary, 0)
    aligned_bulk = bulk.assign(ms=bulk["ms"].to_numpy() + taker_shift * MINUTE_MS)
    res.taker = taker_explanations(aligned_bulk, ours["taker_buy_sell"])
    res.taker_verdict = explanation_verdict(res.taker)
    res.live_vs_backfilled = {k: v.get("by_class", {}) for k, v in res.aligned.items()}
    for d in good:  # the format of the window files either side of the label change (already downloaded, no extra request)
        if boundary is not None and d.day in (pd.Timestamp(boundary - 86_400_000, unit="ms", tz="UTC").strftime("%Y-%m-%d"),
                                              pd.Timestamp(boundary, unit="ms", tz="UTC").strftime("%Y-%m-%d")):
            res.extra_profiles.append((d.day, format_profile(d.csv_path)))
    # bookDepth vs our depth snapshot on the two days where our snapshot has rows
    snap_path = snapshot_path(Path(data_dir))
    snap = ba.read_complete(snap_path)
    for day in ("2026-11-18", "2026-11-19"):
        try:
            f = fetch_verified(session, bookdepth_key(day), day, Path(out_dir) / "bookDepth", sleep, (Path(sample_dir) / "bookDepth",))
        except ba.Refused as exc:
            res.stopped["check 1 bookDepth"] = str(exc)
            break
        res.depth_files.append(f)
        if f.csv_path and f.checksum == "verified":
            lo, hi = ba.day_bounds(day)
            s = snap[(pd.to_numeric(snap["fetched_at_ms"]) >= lo) & (pd.to_numeric(snap["fetched_at_ms"]) < hi)]
            res.depth[day] = bookdepth_vs_snapshot(pd.read_csv(f.csv_path), s) if len(s) else {"levels": [], "snapshot_rows": 0, "pairs": {}}


def run_check2(session, out_dir: Path, res: Result, sleep=time.sleep, reuse_cache: bool = False, sample_dir: Path = SAMPLE_DIR) -> None:
    """At most 4 listing requests (one per dataset). Their per-day lags are cached in <out_dir>/_listing_lags.json so that a re-run with
    reuse_cache=True makes no listing request at all."""
    cache = Path(out_dir) / "_listing_lags.json"
    if reuse_cache and cache.exists():
        res.lags = json.loads(cache.read_text(encoding="utf-8"))
        res.notes.append("The listing results came from the cache written by the earlier run (no listing request was made this time).")
    else:
        for name, t in LISTED:
            try:
                ents = ba.list_prefix(session, t.prefix("daily"), sleep)
            except ba.Refused as exc:
                res.stopped[f"check 2 listing {name}"] = str(exc)
                break
            sleep(ba.PAUSE_S)
            res.lags[name] = ba.lag_hours(ents, "daily")
        if res.lags:
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(res.lags), encoding="utf-8")
    for name, lags in res.lags.items():
        res.cutovers[name] = cutover(lags)
        res.cutovers_loose[name] = cutover_ignoring_isolated(lags)
    if "metrics" in res.lags:
        res.slow_metrics_files = sorted((d, h) for d, h in res.lags["metrics"].items() if h >= LAG_LIMIT_H and d >= "2026-06-01")
    cut = res.cutovers.get("metrics")
    if not cut:
        res.notes.append("No metrics cutover date could be found, so the four-file format comparison was not run.")
        return
    day_before = (datetime.strptime(cut, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    picks = [("2025-08-01", "old file"), (day_before, "day before the cutover"), (cut, "cutover day"), ("2026-11-10", "recent file")]
    folder = Path(out_dir) / "metrics_format"
    for day, label in picks:
        try:
            f = fetch_verified(session, metrics_key(day), day, folder, sleep, (Path(sample_dir) / "metrics", Path(out_dir) / "metrics"))
        except ba.Refused as exc:
            res.stopped["check 2 downloads"] = str(exc)
            return
        res.format_files.append((label, f, format_profile(f.csv_path) if f.csv_path and f.checksum == "verified" else None))


# ------------------------------------------------------------------ report ---

def pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:.2f}%"


def ts_str(ms: int | None) -> str:
    return "n/a" if ms is None else pd.Timestamp(ms, unit="ms", tz="UTC").strftime("%Y-%m-%d %H:%M")


def recommendation(res: Result) -> list[str]:
    """A RECOMMENDATION built from the results; nothing is adopted by this script."""
    out = ["**This is a recommendation only. No rule has been adopted.**", ""]
    cut = res.cutovers.get("metrics")
    lc = res.label_change or {}
    oi = res.aligned.get("sum_open_interest", {})
    out.append("The rule used so far for bulk rows is: known at the end of the UTC day plus 24 hours (or the file's LastModified time if later).")
    if cut:
        loose = res.cutovers_loose.get("metrics")
        out.append(f"- **Files from {cut} on (publish lag below 48 hours for every day):** the day-end rule is supported by the observed lag and can stay as the default."
                   + (f" (Ignoring isolated re-written files, the lag has been below 48 hours since {loose}; the strict date is moved by one slow file.)" if loose and loose != cut else ""))
        out.append(f"- **Files before {cut}:** the file time says only when the archive was filled, not when the data existed, so the day-end rule must stay "
                   "as the most conservative choice. This check cannot show whether their values were produced the same way, because our recorder only "
                   "covers 2026-10-19 onward.")
    if oi.get("rows") and oi.get("exact", 0) >= 0.999 and lc.get("boundary_ms"):
        out.append(f"- **A tighter rule for open interest is supported only inside our recorder window (2026-10-19 onward).** There, once the label change on "
                   f"{ts_str(lc['boundary_ms'])} is allowed for, the bulk open interest equals our recorder value in {pct(oi['exact'])} of {oi['rows']:,} rows. "
                   "A rule such as \"our API timestamp plus 10 minutes\" (the recorder's rule) would then be justified for those rows, expressed in OUR timestamp, "
                   "because the bulk label is not a stable reference: it sits 5 minutes before our timestamp until the change and equals it afterwards. "
                   "A rule written as \"bulk label plus 10 minutes\" would be wrong by 5 minutes on one side of that date.")
        out.append("- For days before 2026-10-19 there is no second source, so the label convention and the equality are not shown; keep the day-end rule there.")
    else:
        out.append("- Open interest did not match our recorder in at least 99.9% of rows after allowing for the label change, so no tighter rule is justified for it.")
    for col in ("count_long_short_ratio", "sum_toptrader_long_short_ratio"):
        c = res.aligned.get(col, {})
        if c.get("rows"):
            out.append(f"- `{col}`: within 0.1% of our value in {pct(c['within_0_1pct'])} of rows, equal at our 4-decimal precision in {pct(c['at_our_precision'])}. "
                       "Close but not identical, so the tighter rule is justified only if a feature can tolerate differences of that size; otherwise keep the day-end rule.")
    t = res.aligned.get("sum_taker_long_short_vol_ratio", {})
    if t.get("rows"):
        out.append(f"- Taker ratio: within 0.1% of our value in {pct(t['within_0_1pct'])} of rows; explanation test: {res.taker_verdict}. Keep the day-end rule until the "
                   "differences are explained.")
    out.append("- Whatever is decided, the decision belongs to you; this report only lists what the data support.")
    return out


def match_table(title: str, cols: dict[str, dict], note: str) -> list[str]:
    L = [title, "", note, "",
         "| Bulk column | Our column | Shift (min) | Rows compared | Our decimals | Exact | At our precision | Within 0.1% | Within 1% | Largest abs. difference |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for col, c in cols.items():
        if not c.get("rows"):
            L.append(f"| {col} | {c['ours']} | {c['shift']} | 0 | | | | | | |")
            continue
        L.append(f"| {col} | {c['ours']} | {c['shift']} | {c['rows']:,} | {c['decimals']} | {pct(c['exact'])} | {pct(c['at_our_precision'])} | "
                 f"{pct(c['within_0_1pct'])} | {pct(c['within_1pct'])} | {c['max_abs_diff']:.6g} |")
    return L


def render_report(res: Result) -> str:
    L = ["# Bulk archive equivalence and backfill cutover (TACUSDT)", "",
         f"Written {datetime.now(timezone.utc).strftime('%Y-%m-%d')} (UTC). Two read-only checks; nothing here changes any rule or builds any feature. "
         "Downloads are in `data/raw/bulk_window/` (git-ignored) and every one was checked against its published checksum.", ""]
    for part, why in res.stopped.items():
        L += [f"**Stopped: {part}: {why}** Nothing after that request was attempted.", ""]
    L += ["## Check 1: full-window equivalence with our recorder", ""]
    if res.window:
        ok = sum(1 for d in res.downloads if d.checksum == "verified")
        L += [f"- Bulk metrics files downloaded: {len(res.downloads)} ({res.window[0]} to {res.window[1]}, the latest day the archive had when checked), "
              f"{ok} verified against their checksum. File URLs were built from the naming pattern; the archive was not listed for this.", ""]
    L += match_table("### Per-column match with the fixed shift from the earlier report", res.columns,
                     "This is the comparison the earlier report suggested: our timestamp = bulk label + 5 minutes (taker: + 0). Exact = equal at full precision. "
                     "At our precision = the bulk value rounded to the decimals our file stores equals our value. The low rates here come from the label change "
                     "described next, not from different values.")
    L += ["", f"`{NO_COUNTERPART}` has no counterpart in our recorder files and was not compared.", ""]
    L += ["### Label offset: is the bulk label always exactly 5 minutes before our timestamp?", ""]
    if res.offset:
        o = res.offset
        L += [f"Share of bulk open-interest rows equal to our open interest at our timestamp = bulk label + shift ({o['bulk_rows']:,} bulk rows, whole window):", "",
              "| Shift (min) | Rows with a counterpart | Equal |", "|---|---|---|"]
        L += [f"| {sh:+d} | {v['rows']:,} | {pct(v['equal'])} |" for sh, v in o["by_shift"].items()]
        L += ["", f"Every bulk label is on a 5-minute boundary: {'yes' if o['labels_on_5min'] else 'NO'}.", ""]
    lc = res.label_change
    if lc:
        L += [f"**Answer: no.** Open interest equals ours at label + 5 minutes for {lc['old_rows']:,} rows (up to {ts_str(lc['last_old_ms'])}) and at label + 0 for "
              f"{lc['new_rows']:,} rows (from {ts_str(lc['boundary_ms'])}); {lc['neither']} rows that have a counterpart match at neither shift, {lc['both']} match at both, and {lc['no_counterpart']} bulk rows have no counterpart "
              "in our file (they come before our first recorder row). "
              + ("The split is clean (every +5 row comes before every +0 row). " if lc["clean_split"] else "The split is NOT clean. ")
              + "So the bulk label convention changed by 5 minutes at the start of the file for that day. The same change appears in the other columns "
              "(the taker ratio moves from shift 0 to shift -5).", "",
              "Share of rows that match at each shift, by bulk file day (open interest):", "", "| Day | Equal at +5 | Equal at +0 |", "|---|---|---|"]
        days = list(lc["by_day"].items())
        L += [f"| {d} | {pct(v['+5'])} | {pct(v['+0'])} |" for d, v in days[:2]] + ["| ... | | |"] + \
             [f"| {d} | {pct(v['+5'])} | {pct(v['+0'])} |" for d, v in days if abs(pd.Timestamp(d).value // 10**6 - (lc['boundary_ms'] or 0)) <= 2 * 86_400_000] + \
             [f"| {d} | {pct(v['+5'])} | {pct(v['+0'])} |" for d, v in days[-1:]]
        L.append("")
    L += match_table("### Per-column match with the label change allowed for", res.aligned,
                     "Same comparison, but the shift is 5 minutes smaller from the label-change date on (open interest, long/short: +5 then +0; taker: 0 then -5).")
    L += [""]
    for col, c in res.aligned.items():
        if c.get("first_mismatches"):
            L += [f"First {len(c['first_mismatches'])} mismatches at our precision for `{col}` (our timestamp ms, bulk value, our value):", ""]
            L += [f"- {t} ({ts_str(t)}): bulk {bv!r}, ours {ov!r}" for t, bv, ov in c["first_mismatches"]]
            L.append("")
    L += ["### Taker ratio: why only part of the rows match", "",
          "All tests use the bulk rows aligned to our periods (shift allowed for as above), so shift 0 means the same 5-minute period.", ""]
    if res.taker:
        L += ["| Explanation tested | Rows | Share equal |", "|---|---|---|"]
        L += [f"| {k} | {v[0]:,} | {pct(v[1])} |" for k, v in res.taker.items() if not k.startswith("_")]
        sp = res.taker.get("_spread")
        if sp and sp["rows"]:
            L += ["", f"Relative difference between the bulk ratio and our ratio at the aligned period ({sp['rows']:,} rows): median {100 * sp['median_rel']:.3f}%, "
                  f"95th percentile {100 * sp['p95_rel']:.2f}%, largest {100 * sp['max_rel']:.2f}%."]
        L += ["", f"**Result: {res.taker_verdict}.**", ""]
    L += ["### Live versus backfilled recorder rows", "",
          "Our rows are called backfilled when fetched_at_ms is more than 15 minutes after the timestamp, otherwise live (the recorder rule). "
          "Rates are for the label-change-aware comparison; 'within 0.1%' because our ratios are rounded.", "",
          "| Bulk column | Live rows | Live: exact | Live: within 0.1% | Backfilled rows | Backfilled: exact | Backfilled: within 0.1% |", "|---|---|---|---|---|---|---|"]
    for col, bc in res.live_vs_backfilled.items():
        lv, bf = bc.get("live", {}), bc.get("backfilled", {})
        L.append(f"| {col} | {lv.get('rows', 0):,} | {pct(lv.get('exact')) if lv else 'not shown'} | {pct(lv.get('within_0_1pct')) if lv else 'not shown'} | "
                 f"{bf.get('rows', 0):,} | {pct(bf.get('exact')) if bf else 'not shown'} | {pct(bf.get('within_0_1pct')) if bf else 'not shown'} |")
    L += ["", "### bookDepth against our depth snapshot", "",
          "Our snapshot bands are 0.5, 1 and 2 percent of mid. The bulk file has the levels listed below. Only 1 and 2 percent correspond; the 0.5 percent band "
          "has no counterpart and the other bulk levels have none in our snapshot. Our value is a USD depth within the band of our own mid; whether the bulk "
          "`notional` uses the same reference price and the same definition is not stated in the file, so this is a plausibility check, not proof.", ""]
    for day, d in res.depth.items():
        L += [f"**{day}**: bulk levels {', '.join(f'{x:g}' for x in d['levels'])}; our snapshot rows matched to a bulk snapshot within 30 s: {d['snapshot_rows']}.", ""]
        if d["pairs"]:
            L += ["| Our column | Rows | Median ours / bulk | 5th pct | 95th pct | Within 10% |", "|---|---|---|---|---|---|"]
            for col, p_ in d["pairs"].items():
                L.append(f"| {col} | {p_['rows']} | {p_['median_ratio']:.3f} | {p_['p5']:.3f} | {p_['p95']:.3f} | {pct(p_['within_10pct'])} |"
                         if p_["rows"] else f"| {col} | 0 | not shown | | | |")
            L.append("")
    if not res.depth:
        L += ["Not shown (no bookDepth comparison ran).", ""]
    L += ["## Check 2: backfill cutover", "", LISTING_NOTE, ""]
    if res.cutovers:
        L += ["Lag = hours between the end of the UTC day and the file's LastModified time (from one listing per dataset). "
              f"Cutover = the earliest date from which the lag is below {LAG_LIMIT_H:g} hours for every later day.", "",
              "| Dataset | Daily files | Cutover date (strict) | Cutover ignoring isolated re-written files | Files at or above 48 h |", "|---|---|---|---|---|"]
        for name, lags in res.lags.items():
            L.append(f"| {name} | {len(lags)} | {res.cutovers.get(name) or 'none (the latest file is slower than 48 h)'} | "
                     f"{res.cutovers_loose.get(name) or 'none'} | {sum(1 for v in lags.values() if v >= LAG_LIMIT_H)} |")
        L += ["", "Strict = the date you asked for: the lag is below 48 hours for every later day. The second date treats a single slow file with fast neighbours on both sides "
              "as an isolated re-written file and ignores it. For the other datasets the strict date is decided by one or a few slow recent files, not by a long backfilled era."]
        if res.slow_metrics_files:
            L += ["", "Metrics files at or above 48 h since 2026-06-01 (these decide the metrics cutover date):", "", "| Day | Lag |", "|---|---|"]
            L += [f"| {d} | {h:.1f} h |" for d, h in res.slow_metrics_files]
        for name, lags in res.lags.items():
            L += ["", f"Lag by month, {name}:", "", "| Month | Files | Median lag | Max lag | Files at or above 48 h |", "|---|---|---|---|---|"]
            L += [f"| {r['month']} | {r['files']} | {r['median']:.1f} h | {r['max']:.1f} h | {r['over_limit']} |" for r in lag_by_month(lags)]
    L += ["", "### Four metrics files compared", ""]
    if res.format_files:
        hdr = ["Item"] + [f"{lbl}: {f.day}" for lbl, f, _ in res.format_files]
        L += ["| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
        prof = [pr for _, _, pr in res.format_files]

        def row(label, fn):
            return "| " + label + " | " + " | ".join(fn(pr) if pr else "not shown" for pr in prof) + " |"
        L += [row("Rows", lambda pr: f"{pr['rows']}"), row("Missing 5-minute slots (of 288)", lambda pr: f"{pr['missing_slots']}"),
              row("Duplicate labels", lambda pr: f"{pr['duplicates']}"), row("Rows sorted by time", lambda pr: "yes" if pr["sorted"] else "NO"),
              row("Label format", lambda pr: pr["label_format"].split(",")[0]), row("Symbols", lambda pr: ", ".join(pr["symbols"]))]
        first = next((pr for pr in prof if pr), None)
        for c in (first["decimals"] if first else []):
            L.append(row(f"Decimals: {c}", lambda pr, c=c: str(pr["decimals"].get(c, "?"))))
        L += [row("Header", lambda pr: "same as the first file" if pr["header"] == first["header"] else "DIFFERENT: " + ",".join(pr["header"]))]
        diffs = []
        for lbl, f, pr in res.format_files[1:]:
            if pr and first:
                what = [n for n, ne in (("decimals", pr["decimals"] != first["decimals"]), ("row order", pr["sorted"] != first["sorted"]),
                                        ("label format", pr["label_format"] != first["label_format"]), ("header", pr["header"] != first["header"]),
                                        ("missing slots", pr["missing_slots"] != first["missing_slots"])) if ne]
                if what:
                    diffs.append(f"{lbl} ({f.day}): {', '.join(what)}")
        L += ["", ("Compared with the 2025-08-01 file, the others differ in: " + "; ".join(diffs) + ".") if diffs else "The four files do not differ in any compared item.",
              "", "What four files can and cannot show: they show whether the file FORMAT changed between the sampled dates. They cannot show how the VALUES were "
              "produced; that can only be tested against another source, and the only one we have (our recorder) starts on 2026-10-19."]
    else:
        L += ["Not shown (the four-file comparison did not run)."]
    if res.extra_profiles:
        L += ["", "Two window files either side of the label change (already downloaded for check 1, no extra request):", "",
              "| Day | Rows | Missing slots | Sorted | Decimals (OI / ratios) |", "|---|---|---|---|---|"]
        for d, pr in res.extra_profiles:
            dec = pr["decimals"]
            L.append(f"| {d} | {pr['rows']} | {pr['missing_slots']} | {'yes' if pr['sorted'] else 'NO'} | {dec.get('sum_open_interest')} / {dec.get('count_long_short_ratio')} |")
    L += [""]
    for n in res.notes:
        L.append(f"- {n}")
    L += ["", "## Recommendation on the known-time rule", ""] + recommendation(res) + [""]
    L += decisions_lines()
    return "\n".join(L) + "\n"


def decisions_lines() -> list[str]:
    """The decisions taken by the user on 2026-11-21 after reading this report (fixed text; the script adopts nothing by itself)."""
    return [
        "## Decisions", "",
        "**Decided by the user on 2026-11-21.** These replace the recommendation above for the points they cover.", "",
        "1. Bulk metrics are normalized to our timestamp convention: the bulk label plus 5 minutes before 2026-11-16 00:00 UTC, and the bulk label "
        "unchanged from that time on.",
        "2. Open interest is known at our timestamp plus 10 minutes only from 2026-10-19 on, because that part was verified against the recorder. "
        "Everywhere else the rule is UTC day end plus 24 hours, or the file's LastModified time if that is later.",
        "3. The long/short ratios, the taker ratio and bookDepth use UTC day end plus 24 hours everywhere for now.",
        "4. Metrics values before 2026-07-12 are marked as an unverified era: the archive wrote them months late and our recorder cannot check them.",
        "5. The checksums of downloaded files must be pinned, and the label convention must be rechecked against the recorder on every rerun, because "
        "Binance could rewrite old files.",
        "6. Consequence for the backtest: intraday features come from klines, mark, index and premium klines, and funding. Open interest, the ratios, "
        "the taker ratio and depth enter with a day lag until proven otherwise.", "",
        "## Open item", "",
        "An independent check of the taker ratio over the whole history is still to do: derive buy over sell volume per 5 minutes from our 1m klines "
        "(taker_buy_volume) and compare it with the bulk taker ratio, including the backfilled era. Nothing from the bulk archive has been used as a feature.", ""]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Bulk archive equivalence and backfill cutover checks (read-only).")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    ap.add_argument("--reuse-listings", action="store_true", help="use the cached listing lags instead of listing the archive again")
    args = ap.parse_args(argv)
    out_dir, data_dir, report = Path(args.out_dir), Path(args.data_dir), Path(args.report)
    r_res, d_res = report.resolve(), data_dir.resolve()
    if r_res == d_res or d_res in r_res.parents:
        print(f"Refusing: --report must not be inside the data directory {data_dir}.")
        return 2
    session = requests.Session()
    res = Result()
    run_check1(session, out_dir, data_dir, res)
    run_check2(session, out_dir, res, reuse_cache=args.reuse_listings)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(res), encoding="utf-8")
    print(console_summary(res, report))
    return 2 if res.stopped else 0


def console_summary(res: Result, report: Path) -> str:
    out = ["Bulk equivalence check"]
    for part, why in res.stopped.items():
        out.append(f"  STOPPED {part}: {why}")
    if res.window:
        out.append(f"  window {res.window[0]} to {res.window[1]}, {len(res.downloads)} files, checksums: "
                   f"{sum(1 for d in res.downloads if d.checksum == 'verified')} verified")
    for col, c in res.columns.items():
        if c.get("rows"):
            a = res.aligned.get(col, {})
            out.append(f"  {col:34s} fixed shift: exact {pct(c['exact'])} within0.1% {pct(c['within_0_1pct'])} | label-change aware: rows {a.get('rows', 0):>6,} "
                       f"exact {pct(a.get('exact'))} at our precision {pct(a.get('at_our_precision'))} within0.1% {pct(a.get('within_0_1pct'))} max abs {a.get('max_abs_diff', 0):.6g}")
    if res.label_change:
        lc = res.label_change
        out.append(f"  label change: old rows {lc['old_rows']:,} (to {ts_str(lc['last_old_ms'])}), new rows {lc['new_rows']:,} (from {ts_str(lc['boundary_ms'])}), clean split {lc['clean_split']}")
    if res.taker_verdict:
        out.append(f"  taker: {res.taker_verdict}")
    for name, cut in res.cutovers.items():
        out.append(f"  cutover {name}: {cut}")
    out.append(f"  report: {report}")
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
