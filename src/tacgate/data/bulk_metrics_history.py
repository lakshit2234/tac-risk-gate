"""Download the full daily `metrics` history for TACUSDT USD-M futures from the Binance bulk archive, build a normalized file from it,
run quality checks, and cross-check the bulk taker ratio against our own 1m klines.

No features and no models. Read-only on our existing files. Nothing is committed by this script.

Rules (from docs/bulk_equivalence_report.md, "Decisions", decided by the user on 2026-11-21):
  * ts_ours_ms = bulk label + 5 minutes before 2026-11-16 00:00 UTC, the label itself from that time on;
  * known_at_oi_ms = ts_ours_ms + 10 minutes only from 2026-10-19 on; otherwise the later of (UTC day end of the file date + 24 h) and LastModified;
  * known_at_other_ms (every other column) = the later of (UTC day end of the file date + 24 h) and LastModified, always;
  * unverified_era = true for rows before 2026-07-12.

Download rules: sequential requests with a short pause; a refusal (403, 418, 429 after retries) stops the run at once; every file is verified
against its published checksum; an existing file is never overwritten (a changed upstream file is saved next to it as `.rev`); files that are
already downloaded and verified are skipped. The cached listing from the earlier bulk_equivalence run (data/raw/bulk_window/_listing_lags.json) is
reused for LastModified; only if it is missing is ONE listing request for metrics made.

Run: python -m tacgate.data.bulk_metrics_history [--data-dir data/raw] [--report docs/bulk_metrics_history_report.md]
Exit codes: 0 ok, 2 bad arguments, or the download stopped because a request was refused.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
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

from tacgate.data import binance_klines as bk
from tacgate.data import bulk_availability as ba
from tacgate.data import bulk_equivalence as be

DEFAULT_DATA_DIR = Path("data/raw")
DEFAULT_REPORT = Path("docs/bulk_metrics_history_report.md")
MANIFEST_PATH = Path("data/static/bulk_metrics_manifest.csv")
LAGS_CACHE = Path("data/raw/bulk_window/_listing_lags.json")
REUSE_DIRS = (Path("data/raw/bulk_window/metrics"), Path("data/raw/bulk_window/metrics_format"), Path("data/raw/bulk_sample/metrics"))
FIRST_DAY = "2025-07-15"
PAUSE_S = 0.4
DAY_MS = 86_400_000
MIN_MS = 60_000
FIVE_MIN_MS = 300_000


def utc_ms(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp() * 1000)


LABEL_CHANGE_MS = utc_ms("2026-11-16")
OI_VERIFIED_FROM_MS = utc_ms("2026-10-19")
UNVERIFIED_BEFORE_MS = utc_ms("2026-07-12")

METRIC_COLS = ["create_time", "symbol", "sum_open_interest", "sum_open_interest_value", "count_toptrader_long_short_ratio",
               "sum_toptrader_long_short_ratio", "count_long_short_ratio", "sum_taker_long_short_vol_ratio"]
OUT_COLUMNS = ["bulk_label_ms", "ts_ours_ms"] + METRIC_COLS + ["file_date", "last_modified_ms", "known_at_oi_ms", "known_at_other_ms", "unverified_era"]
MANIFEST_COLUMNS = ["file_date", "url", "expected_checksum", "actual_checksum", "verified", "last_modified_utc", "downloaded_at_utc", "size", "revision"]
RATIO_COLS = ["count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio", "count_long_short_ratio", "sum_taker_long_short_vol_ratio"]
DIST_COLS = ["sum_open_interest"] + RATIO_COLS

log_lines: list[str] = []


def iso(ms: int | float) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def day_ms(day: str) -> int:
    return utc_ms(day)


# -------------------------------------------------------------- LastModified ---

def load_lags(path: Path) -> dict[str, float]:
    """Per-day publish lag (hours after the UTC day end) cached by the earlier bulk_equivalence run, for the metrics listing."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["metrics"]


def last_modified_ms(day: str, lag_hours: float) -> int:
    """LastModified of the day's file: the UTC day end plus the cached lag. Accurate to the second (the lag was stored as float hours)."""
    return day_ms(day) + DAY_MS + int(round(lag_hours * 3600)) * 1000


def fetch_lags_listing(session, sleep: Callable[[float], None] = time.sleep) -> dict[str, float]:
    """ONE listing request for metrics, only used if the cache is missing."""
    ents = ba.list_prefix(session, be.LISTED[0][1].prefix("daily"), sleep)
    return ba.lag_hours(ents, "daily")


# ------------------------------------------------------------------ downloads ---

@dataclass
class Outcome:
    day: str
    url: str
    expected: str = ""
    actual: str = ""
    status: str = ""  # verified / mismatch / no checksum / revision / missing
    verified: bool = False
    size: int = 0
    path: Path | None = None
    rev_path: Path | None = None
    reused: bool = False
    downloaded_at: str = ""
    note: str = ""


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _unused_rev_path(zpath: Path) -> Path:
    n = 0
    while True:
        cand = zpath.with_name(zpath.name + (".rev" if n == 0 else f".rev{n + 1}"))
        if not cand.exists():
            return cand
        n += 1


def ensure_file(session, day: str, zips_dir: Path, reuse_dirs: tuple[Path, ...] = (), pinned: str | None = None,
                sleep: Callable[[float], None] = time.sleep) -> Outcome:
    """Make sure the day's zip is on disk and verified against its published checksum. Never overwrites an existing file.

    A local file whose checksum differs from the published one is kept, and the new download is saved beside it as .rev (and reported)."""
    key = be.metrics_key(day)
    name = Path(key).name
    zdir = Path(zips_dir)
    zdir.mkdir(parents=True, exist_ok=True)
    zpath = zdir / name
    out = Outcome(day, f"{ba.DOWNLOAD_URL}/{key}")
    ck = ba.http_get(session, f"{ba.DOWNLOAD_URL}/{key}.CHECKSUM", None, sleep)
    sleep(PAUSE_S)
    out.expected = ba.parse_checksum(ck.decode("utf-8", errors="replace")) if ck else ""
    if pinned and out.expected and pinned != out.expected:
        out.note = "the published checksum differs from the pinned one in the manifest"
    if not zpath.exists():
        for d in reuse_dirs:
            if (Path(d) / name).exists():
                shutil.copy2(Path(d) / name, zpath)
                out.reused = True
                break
    if zpath.exists():
        out.reused = True  # a copy is already on disk (from an earlier run or an earlier folder): it is verified, not downloaded again
        body = zpath.read_bytes()
        out.actual, out.size, out.path = sha256(body), len(body), zpath
        out.downloaded_at = iso(zpath.stat().st_mtime * 1000)
        if not out.expected:
            out.status = "no checksum"
            return out
        if out.actual == out.expected:
            out.status, out.verified = "verified", True
            return out
        # the local file is not the published one any more: keep it, save the new download beside it
        new = ba.http_get(session, out.url, None, sleep)
        sleep(PAUSE_S)
        if new is None:
            out.status = "missing"
            return out
        new_sha = sha256(new)
        same = next((c for c in sorted(zdir.glob(name + ".rev*")) if sha256(c.read_bytes()) == new_sha), None)
        if same is not None:  # this very revision was already saved by an earlier run: do not save it again
            out.rev_path = same
        else:
            out.rev_path = _unused_rev_path(zpath)
            out.rev_path.write_bytes(new)
        out.status = "revision"
        out.note = (out.note + "; " if out.note else "") + (
            "the new download matches the published checksum" if new_sha == out.expected else "the new download does not match the published checksum either")
        out.downloaded_at = iso(time.time() * 1000)
        return out
    body = ba.http_get(session, out.url, None, sleep)
    sleep(PAUSE_S)
    if body is None:
        out.status = "missing"
        return out
    zpath.write_bytes(body)
    out.actual, out.size, out.path, out.downloaded_at = sha256(body), len(body), zpath, iso(time.time() * 1000)
    if not out.expected:
        out.status = "no checksum"
    elif out.actual == out.expected:
        out.status, out.verified = "verified", True
    else:
        out.status = "mismatch"
    return out


def read_manifest(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_manifest(path: Path, rows: list[dict]) -> None:
    """Append-only: existing rows are never rewritten."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS)
        if new_file:
            w.writeheader()
        w.writerows(rows)


def manifest_row(o: Outcome, lm_ms: int | None, revision: int = 0) -> dict:
    return {"file_date": o.day, "url": o.url, "expected_checksum": o.expected, "actual_checksum": o.actual,
            "verified": "yes" if o.verified else "no", "last_modified_utc": iso(lm_ms) if lm_ms else "", "downloaded_at_utc": o.downloaded_at,
            "size": o.size, "revision": revision}


@dataclass
class DownloadResult:
    outcomes: list[Outcome] = field(default_factory=list)
    stopped: str = ""
    revisions: list[Outcome] = field(default_factory=list)
    failures: list[Outcome] = field(default_factory=list)


def download_all(session, days: list[str], zips_dir: Path, manifest_path: Path, lags: dict[str, float],
                 reuse_dirs: tuple[Path, ...] = (), sleep: Callable[[float], None] = time.sleep,
                 on_progress: Callable[[str], None] | None = None) -> DownloadResult:
    """Sequentially ensure every day's file; append new manifest rows; stop at once on a refusal."""
    res = DownloadResult()
    existing = read_manifest(manifest_path)
    pinned = {r["file_date"]: r["expected_checksum"] for r in existing if r["revision"] == "0"}
    have_rows = {(r["file_date"], r["revision"]) for r in existing}
    for i, day in enumerate(days):
        try:
            o = ensure_file(session, day, zips_dir, reuse_dirs, pinned.get(day), sleep)
        except ba.Refused as exc:
            res.stopped = f"{day}: {exc}"
            break
        res.outcomes.append(o)
        lm = last_modified_ms(day, lags[day]) if day in lags else None
        new_rows = []
        if o.status != "missing" and (day, "0") not in have_rows:
            new_rows.append(manifest_row(o, lm, 0))
        if o.status == "revision":
            res.revisions.append(o)
            rev_sha = sha256(o.rev_path.read_bytes())
            if not any(r["file_date"] == day and r["actual_checksum"] == rev_sha for r in existing):  # one manifest row per distinct revision
                n = max((int(rv) for d, rv in have_rows if d == day), default=0) + 1
                rev_out = Outcome(day, o.url, o.expected, rev_sha, "revision", rev_sha == o.expected, o.rev_path.stat().st_size, o.rev_path, None, False,
                                  o.downloaded_at, o.note)
                new_rows.append(manifest_row(rev_out, lm, revision=n))
        elif o.status in ("mismatch", "no checksum", "missing"):
            res.failures.append(o)
        if new_rows:
            append_manifest(manifest_path, new_rows)
            existing += new_rows
            have_rows |= {(r["file_date"], str(r["revision"])) for r in new_rows}
        if on_progress and (i + 1) % 25 == 0:
            on_progress(f"{i + 1}/{len(days)} days processed")
    return res


# ---------------------------------------------------------------- normalizing ---

def ts_ours(label_ms: int) -> int:
    """Our timestamp convention: label + 5 minutes before 2026-11-16 00:00 UTC, the label itself from then on."""
    return label_ms + 5 * MIN_MS if label_ms < LABEL_CHANGE_MS else label_ms


def day_rows(csv_text: str, file_date: str, lm_ms: int) -> list[list[str]]:
    """Normalized output rows for one day file, sorted by time. Original values are kept as text, unchanged."""
    rdr = csv.reader(io.StringIO(csv_text))
    header = next(rdr)
    if header != METRIC_COLS:
        raise ValueError(f"unexpected header {header}")
    day_end_plus_24h = day_ms(file_date) + 2 * DAY_MS
    other = max(day_end_plus_24h, lm_ms)
    out = []
    for r in rdr:
        if not r:
            continue
        label = int(pd.Timestamp(r[0], tz="UTC").timestamp() * 1000)
        ts = ts_ours(label)
        oi = ts + 10 * MIN_MS if ts >= OI_VERIFIED_FROM_MS else other
        out.append([str(label), str(ts)] + r + [file_date, str(lm_ms), str(oi), str(other), "true" if label < UNVERIFIED_BEFORE_MS else "false"])
    out.sort(key=lambda x: int(x[0]))
    return out


def read_zip_csv(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.endswith(".csv")]
        return z.read(names[0]).decode("utf-8")


def append_normalized(out_path: Path, outcomes: list[Outcome], lags: dict[str, float]) -> dict:
    """Append the rows of verified days that are not in the file yet. Rows already written are never rewritten.

    A day already present is left alone (a changed upstream file would be reported by the download step). Days are appended in date order;
    if an older day arrives after newer ones it is still appended (never inserted) and counted as out of order."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    present = set()
    if out_path.exists() and out_path.stat().st_size:
        present = set(pd.read_csv(out_path, usecols=["file_date"], dtype=str)["file_date"].unique())
    need_header = not out_path.exists() or out_path.stat().st_size == 0
    added_days, rows_added, out_of_order, last = 0, 0, 0, max(present) if present else ""
    with out_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if need_header:
            w.writerow(OUT_COLUMNS)
        for o in sorted(outcomes, key=lambda x: x.day):
            if not o.verified or o.day in present or not o.path:
                continue
            rows = day_rows(read_zip_csv(o.path), o.day, last_modified_ms(o.day, lags[o.day]))
            w.writerows(rows)
            f.flush()
            added_days += 1
            rows_added += len(rows)
            if last and o.day < last:
                out_of_order += 1
            last = max(last, o.day)
    return {"days_added": added_days, "rows_added": rows_added, "out_of_order_days": out_of_order, "days_already_present": len(present)}


# ------------------------------------------------------------------ quality ---

def load_normalized(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"symbol": str, "create_time": str, "file_date": str, "unverified_era": str})
    return df


def quality_checks(df: pd.DataFrame) -> dict:
    """Facts only. Per-day rows, missing 5-minute slots, duplicates, order, non-positive open interest, ratio ranges, open-interest jumps."""
    q: dict = {"rows": len(df)}
    if df.empty:
        return q
    label = df["bulk_label_ms"]
    q["first_label"], q["last_label"] = int(label.min()), int(label.max())
    day = pd.to_datetime(label, unit="ms", utc=True).dt.strftime("%Y-%m-%d")
    per_day = day.value_counts().sort_index()
    q["days"] = int(len(per_day))
    q["days_not_288"] = {d: int(n) for d, n in per_day.items() if n != 288}
    expected = np.arange(label.min(), label.max() + 1, FIVE_MIN_MS)
    missing = np.setdiff1d(expected, label.to_numpy())
    q["missing_slots"] = int(len(missing))
    q["missing_examples"] = [iso(int(m)) for m in missing[:10]]
    q["missing_by_day"] = {d: int(n) for d, n in pd.Series(pd.to_datetime(missing, unit="ms", utc=True).strftime("%Y-%m-%d")).value_counts().sort_index().items()} if len(missing) else {}
    q["duplicates"] = int(label.duplicated().sum())
    q["in_order"] = bool(label.is_monotonic_increasing)
    q["out_of_order_steps"] = int((label.diff().dropna() < 0).sum())
    oi = pd.to_numeric(df["sum_open_interest"], errors="coerce")
    q["oi_non_positive"] = int((oi <= 0).sum())
    q["oi_nan"] = int(oi.isna().sum())
    zero_days = day[(oi <= 0).to_numpy()].value_counts().sort_index()
    q["oi_non_positive_days"] = {d: int(n) for d, n in zero_days.items()}
    q["ratio_ranges"] = {}
    for c in RATIO_COLS:
        v = pd.to_numeric(df[c], errors="coerce")
        q["ratio_ranges"][c] = {"min": float(v.min()), "max": float(v.max()), "non_positive": int((v <= 0).sum()), "nan": int(v.isna().sum())}
    s = df.assign(_oi=oi).sort_values("bulk_label_ms")
    chg = (s["_oi"] / s["_oi"].shift() - 1)
    jumps = s[(chg.abs() > 0.5) & (s["bulk_label_ms"].diff() == FIVE_MIN_MS)]
    q["oi_jumps"] = [(int(r.bulk_label_ms), float(chg.loc[i])) for i, r in jumps.iterrows()]
    q["oi_jumps_after_gap"] = int(((chg.abs() > 0.5) & (s["bulk_label_ms"].diff() != FIVE_MIN_MS)).sum())
    q["symbols"] = sorted(df["symbol"].unique().tolist())
    return q


def monthly_distribution(df: pd.DataFrame, cols: list[str] = DIST_COLS) -> dict[str, list[dict]]:
    month = pd.to_datetime(df["bulk_label_ms"], unit="ms", utc=True).dt.strftime("%Y-%m")
    out = {}
    for c in cols:
        v = pd.to_numeric(df[c], errors="coerce")
        rows = []
        for m, g in v.groupby(month):
            g = g.dropna()
            rows.append({"month": m, "n": int(len(g)), "median": float(g.median()), "p5": float(g.quantile(0.05)), "p95": float(g.quantile(0.95))})
        out[c] = rows
    return out


def break_check(df: pd.DataFrame, around: str, days: int = 14, cols: list[str] = DIST_COLS) -> dict:
    """Median, 5th and 95th percentile of each column in the `days` days before and after a date (facts only)."""
    t = day_ms(around)
    lab = df["bulk_label_ms"]
    out = {}
    for c in cols:
        v = pd.to_numeric(df[c], errors="coerce")
        row = {}
        for side, m in (("before", (lab >= t - days * DAY_MS) & (lab < t)), ("after", (lab >= t) & (lab < t + days * DAY_MS))):
            g = v[m].dropna()
            row[side] = {"n": int(len(g)), "median": float(g.median()) if len(g) else None, "p5": float(g.quantile(0.05)) if len(g) else None,
                         "p95": float(g.quantile(0.95)) if len(g) else None}
        out[c] = row
    return out


def label_convention_recheck(df: pd.DataFrame, oi_ours: pd.DataFrame) -> dict:
    """Decision 5: recheck the label convention against the recorder. Open interest at ts_ours_ms must equal our recorder value."""
    o = pd.Series(pd.to_numeric(oi_ours["sumOpenInterest"]).values, index=pd.to_numeric(oi_ours["timestamp"]).astype("int64").values)
    o = o[~o.index.duplicated()]
    b = pd.to_numeric(df["sum_open_interest"]).values
    other = o.reindex(df["ts_ours_ms"].values).values
    ok = ~np.isnan(other)
    eq = np.abs(b[ok] - other[ok]) <= 1e-9 * np.maximum(np.abs(other[ok]), 1)
    mism = df.loc[ok].loc[~eq]
    return {"rows_compared": int(ok.sum()), "equal": float(eq.mean()) if ok.sum() else None,
            "first_mismatch_labels": [iso(int(x)) for x in mism["bulk_label_ms"].head(5)]}


# ----------------------------------------------------------- taker cross-check ---

def derived_taker_ratio(klines: pd.DataFrame) -> pd.DataFrame:
    """Buy over sell volume per 5-minute window from 1m klines (base units): buy = taker_buy_base_volume, sell = volume - buy.

    Indexed by the window START (ms). Only windows with all five minutes are kept."""
    t = pd.to_numeric(klines["open_time"]).astype("int64")
    vol, buy = pd.to_numeric(klines["volume"]), pd.to_numeric(klines["taker_buy_base_volume"])
    g = pd.DataFrame({"w": (t // FIVE_MIN_MS) * FIVE_MIN_MS, "buy": buy.values, "vol": vol.values}).groupby("w").agg(buy=("buy", "sum"), vol=("vol", "sum"), n=("buy", "size"))
    g = g[g["n"] == 5].copy()
    g["sell"] = g["vol"] - g["buy"]
    g["ratio"] = (g["buy"] / g["sell"]).replace([np.inf, -np.inf], np.nan)
    return g


ALIGNMENTS = {"window ending at ts_ours_ms (starts 5 min before it)": -FIVE_MIN_MS, "window starting at ts_ours_ms": 0}


def agreement(a: np.ndarray, b: np.ndarray) -> dict:
    """a = source being tested, b = reference. Shares of rows within 0.1% / 1% (relative to b) and absolute differences."""
    ok = ~np.isnan(a) & ~np.isnan(b)
    a, b = a[ok], b[ok]
    if len(a) == 0:
        return {"rows": 0}
    d = np.abs(a - b)
    rel = d / np.maximum(np.abs(b), 1e-12)
    return {"rows": int(len(a)), "within_0_1pct": float((rel <= 1e-3).mean()), "within_1pct": float((rel <= 1e-2).mean()),
            "median_abs": float(np.median(d)), "p95_abs": float(np.percentile(d, 95))}


def taker_alignment(df: pd.DataFrame, derived: pd.DataFrame) -> dict:
    bulk = pd.to_numeric(df["sum_taker_long_short_vol_ratio"]).values
    out = {}
    for name, off in ALIGNMENTS.items():
        key = df["ts_ours_ms"].to_numpy() + off
        out[name] = agreement(bulk, derived["ratio"].reindex(key).values)
    best = max(out, key=lambda k: (out[k].get("within_0_1pct", 0), out[k].get("within_1pct", 0)))
    return {"by_alignment": out, "best": best}


def taker_by_month_and_era(df: pd.DataFrame, derived: pd.DataFrame, offset: int) -> dict:
    key = df["ts_ours_ms"].to_numpy() + offset
    bulk = pd.to_numeric(df["sum_taker_long_short_vol_ratio"]).values
    ref = derived["ratio"].reindex(key).values
    month = pd.to_datetime(df["bulk_label_ms"], unit="ms", utc=True).dt.strftime("%Y-%m").values
    era = np.where(df["unverified_era"].astype(str).str.lower() == "true", "before 2026-07-12", "2026-07-12 and later")
    rows = [dict(month=m, **agreement(bulk[month == m], ref[month == m])) for m in sorted(set(month))]
    eras = {e: agreement(bulk[era == e], ref[era == e]) for e in ("before 2026-07-12", "2026-07-12 and later")}
    return {"months": rows, "eras": eras}


def recorder_taker_comparison(df: pd.DataFrame, derived: pd.DataFrame, taker_ours: pd.DataFrame, offset: int) -> dict:
    """Recorder window only: the ratio our recorder got from the API vs the klines-derived ratio, and the bulk ratio vs the same derived
    ratio on the SAME periods, so the two sources are compared on equal footing. Our taker timestamp is the period start."""
    ours = pd.Series(pd.to_numeric(taker_ours["buySellRatio"]).values, index=pd.to_numeric(taker_ours["timestamp"]).astype("int64").values)
    ours = ours[~ours.index.duplicated()]
    # bulk row -> the recorder period start it corresponds to: ts_ours_ms - 5 min (the window ending at ts_ours_ms)
    bulk = pd.Series(pd.to_numeric(df["sum_taker_long_short_vol_ratio"]).values, index=(df["ts_ours_ms"].to_numpy() + offset))
    bulk = bulk[~bulk.index.duplicated()]
    common = ours.index.intersection(bulk.index)
    ref = derived["ratio"].reindex(common).values
    return {"api": agreement(ours.reindex(common).values, ref), "bulk": agreement(bulk.reindex(common).values, ref), "periods": int(len(common))}


def better_source(cmp: dict) -> str:
    a, b = cmp["api"], cmp["bulk"]
    if not a.get("rows") or not b.get("rows"):
        return "not shown (no common periods)"
    if a["within_1pct"] < 0.9 and b["within_1pct"] < 0.9:
        return "neither agrees well with the klines (both are within 1% of the derived ratio in fewer than 90% of periods)"
    d = b["within_0_1pct"] - a["within_0_1pct"]
    if abs(d) < 0.05:
        return "no clear difference (the shares within 0.1% differ by less than 5 percentage points)"
    return ("the bulk ratio" if d > 0 else "the API ratio (our recorder)") + " agrees better with the klines"


# --------------------------------------------------------------------- report ---

def pct(x) -> str:
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{100 * x:.2f}%"


@dataclass
class Report:
    download: DownloadResult | None = None
    normalized: dict = field(default_factory=dict)
    first_last: tuple[int, int] | None = None
    quality: dict = field(default_factory=dict)
    monthly: dict = field(default_factory=dict)
    breaks: dict = field(default_factory=dict)
    recheck: dict | None = None
    taker_align: dict | None = None
    taker_monthly: dict | None = None
    recorder_cmp: dict | None = None
    odd: list[str] = field(default_factory=list)
    manifest_rows: int = 0
    lag_source: str = ""
    history: list[str] = field(default_factory=list)


def collect_odd(r: Report) -> list[str]:
    odd = []
    q = r.quality
    if r.download:
        if r.download.stopped:
            odd.append(f"The download stopped: {r.download.stopped}")
        for o in r.download.revisions:
            odd.append(f"REVISION: the archive file for {o.day} no longer matches the copy on disk; the new download was saved as {o.rev_path.name if o.rev_path else '?'} ({o.note}).")
        for o in r.download.failures:
            odd.append(f"{o.day}: {o.status} (expected {o.expected[:12] or 'none'}, actual {o.actual[:12] or 'none'}); the file is not in the normalized data.")
    if q.get("days_not_288"):
        odd.append(f"{len(q['days_not_288'])} day(s) do not have 288 rows: " + ", ".join(f"{d} ({n})" for d, n in list(q["days_not_288"].items())[:10]))
    if q.get("missing_slots"):
        odd.append(f"{q['missing_slots']} five-minute slot(s) are missing inside the date range.")
    if q.get("duplicates"):
        odd.append(f"{q['duplicates']} duplicate bulk labels.")
    if q.get("oi_non_positive"):
        odd.append(f"{q['oi_non_positive']} rows with open interest at or below zero.")
    if q.get("oi_non_positive_days"):
        odd.append("Zero open interest sits on: " + ", ".join(f"{d} ({n})" for d, n in list(q["oi_non_positive_days"].items())[:10]) + ".")
    if q.get("oi_jumps"):
        odd.append(f"{len(q['oi_jumps'])} one-step open-interest jump(s) above 50%.")
    for c, v in (q.get("ratio_ranges") or {}).items():
        if v["non_positive"] or v["nan"]:
            odd.append(f"{c}: {v['nan']} not-a-number and {v['non_positive']} zero-or-negative value(s); range {v['min']:.6g} to {v['max']:.6g}.")
    for date, br in r.breaks.items():
        for c, v in br.items():
            b, a = v["before"], v["after"]
            if not b["n"] or not a["n"] or not b["median"] or not a["median"]:
                continue
            wb, wa = b["p95"] - b["p5"], a["p95"] - a["p5"]
            med = a["median"] / b["median"]
            wid = (wa / wb) if wb else None
            if med > 1.5 or med < 2 / 3 or (wid is not None and (wid > 3 or wid < 1 / 3)):
                odd.append(f"Around {date} (14 days either side) {c}: median {b['median']:.6g} to {a['median']:.6g}, "
                           f"5th-95th percentile range {b['p5']:.6g}-{b['p95']:.6g} to {a['p5']:.6g}-{a['p95']:.6g}.")
    if r.recheck and r.recheck.get("equal") is not None and r.recheck["equal"] < 0.999999:
        odd.append(f"The label convention recheck: open interest equals the recorder in only {pct(r.recheck['equal'])} of rows.")
    if r.normalized.get("out_of_order_days"):
        odd.append(f"{r.normalized['out_of_order_days']} day(s) were appended after later days, so the file is not in time order.")
    return odd


def render_report(r: Report) -> str:
    L = ["# Bulk metrics history (TACUSDT USD-M futures)", "",
         f"Written {datetime.now(timezone.utc).strftime('%Y-%m-%d')} (UTC). Facts and what could not be shown; no rule is changed and no feature or model was built. "
         "The rules used to build the normalized file are the user's decisions of 2026-11-21 in docs/bulk_equivalence_report.md.", ""]
    L += ["## Download", ""]
    d = r.download
    if d:
        ok = sum(1 for o in d.outcomes if o.verified)
        reused = sum(1 for o in d.outcomes if o.reused)
        L += [f"- Days processed: {len(d.outcomes)}; verified against the published checksum: **{ok}**; already on disk and checked again against the published checksum (not downloaded again): {reused}.",
              f"- Revisions (an archive file differing from the copy on disk): **{len(d.revisions)}**. Other failures (mismatch, no checksum, 404): **{len(d.failures)}**.",
              f"- Stopped by a refusal: {d.stopped or 'no'}.",
              f"- Pinned manifest `data/static/bulk_metrics_manifest.csv`: {r.manifest_rows} rows. LastModified per file comes from {r.lag_source}."]
    if r.history:
        L += ["", "Run history (one line per run; the first line was recorded from the console output of the first run):", ""] + [f"- {h}" for h in r.history]
    L += ["", "## Normalized file", ""]
    n = r.normalized
    if n:
        L += [f"- Rows added this run: {n.get('rows_added', 0):,} from {n.get('days_added', 0)} days; days already present: {n.get('days_already_present', 0)}."]
    if r.first_last:
        L += [f"- Bulk labels from {iso(r.first_last[0])} to {iso(r.first_last[1])} UTC; total rows {r.quality.get('rows', 0):,}."]
    L += ["- Rules: ts_ours_ms = label + 5 min before 2026-11-16 00:00 UTC, the label from then on; known_at_oi_ms = ts_ours_ms + 10 min from 2026-10-19 on, otherwise the "
          "later of UTC day end of the file date + 24 h and LastModified; known_at_other_ms always the later of those two; unverified_era = true before 2026-07-12. "
          "Rows between 2026-10-19 00:00 and our first recorder row (17:25) are covered by the 2026-10-19 rule as decided, although the recorder cannot check them.", ""]
    q = r.quality
    L += ["## Quality checks", ""]
    if q.get("rows"):
        L += [f"- Rows: {q['rows']:,} over {q['days']} days; days without exactly 288 rows: {len(q['days_not_288'])}"
              + (f" ({', '.join(f'{k}: {v}' for k, v in list(q['days_not_288'].items())[:8])})" if q["days_not_288"] else "") + ".",
              f"- Missing 5-minute slots inside the range: {q['missing_slots']}" + (f" (first: {', '.join(q['missing_examples'][:5])})" if q["missing_slots"] else "") + ".",
              f"- Duplicate labels: {q['duplicates']}. Rows in time order: {'yes' if q['in_order'] else 'NO'} ({q['out_of_order_steps']} backward steps).",
              f"- Open interest at or below zero: {q['oi_non_positive']}; not a number: {q['oi_nan']}.",
              f"- One-step open-interest jumps above 50%: {len(q['oi_jumps'])}" + (": " + "; ".join(f"{iso(t)} ({100 * c:+.0f}%)" for t, c in q["oi_jumps"][:10]) if q["oi_jumps"] else "")
              + f" (jumps after a gap in the labels: {q['oi_jumps_after_gap']}).",
              f"- Symbols: {', '.join(q['symbols'])}.", "",
              "| Ratio column | Min | Max | At or below zero | Not a number |", "|---|---|---|---|---|"]
        L += [f"| {c} | {v['min']:.6g} | {v['max']:.6g} | {v['non_positive']} | {v['nan']} |" for c, v in q["ratio_ranges"].items()]
    L += ["", "### Monthly distributions (median, 5th and 95th percentile)", ""]
    for c, rows in r.monthly.items():
        L += [f"**{c}**", "", "| Month | Rows | Median | 5th pct | 95th pct |", "|---|---|---|---|---|"]
        L += [f"| {x['month']} | {x['n']:,} | {x['median']:.6g} | {x['p5']:.6g} | {x['p95']:.6g} |" for x in rows]
        L.append("")
    for date, br in r.breaks.items():
        L += [f"### The 14 days before and after {date}", "", "| Column | Median before | Median after | 5th-95th pct before | 5th-95th pct after |", "|---|---|---|---|---|"]
        for c, v in br.items():
            b, a = v["before"], v["after"]
            fmt = lambda x: "n/a" if x is None else f"{x:.6g}"
            L.append(f"| {c} | {fmt(b['median'])} | {fmt(a['median'])} | {fmt(b['p5'])} to {fmt(b['p95'])} | {fmt(a['p5'])} to {fmt(a['p95'])} |")
        L.append("")
    L += ["### Label convention recheck against the recorder (decision 5)", ""]
    if r.recheck:
        L += [f"Open interest at ts_ours_ms equals our recorder's value in {pct(r.recheck['equal'])} of {r.recheck['rows_compared']:,} compared rows"
              + (f"; first mismatches at labels {', '.join(r.recheck['first_mismatch_labels'])}" if r.recheck["first_mismatch_labels"] else "") + ".", ""]
    L += ["## Taker ratio against our 1m klines", "",
          "Derived ratio = taker_buy_base_volume divided by (volume minus taker_buy_base_volume), summed over the five 1m candles of a 5-minute window "
          "(base units); windows with fewer than five candles are dropped.", ""]
    if r.taker_align:
        L += ["Which alignment fits best (bulk taker ratio vs the derived ratio, whole history):", "",
              "| Alignment | Rows | Within 0.1% | Within 1% | Median abs. diff | 95th pct abs. diff |", "|---|---|---|---|---|---|"]
        for name, v in r.taker_align["by_alignment"].items():
            if v.get("rows"):
                L.append(f"| {name} | {v['rows']:,} | {pct(v['within_0_1pct'])} | {pct(v['within_1pct'])} | {v['median_abs']:.5f} | {v['p95_abs']:.5f} |")
        L += ["", f"**Best fit: {r.taker_align['best']}.**", ""]
    if r.taker_monthly:
        L += ["Per month, using the best alignment:", "", "| Month | Rows | Within 0.1% | Within 1% | Median abs. diff | 95th pct abs. diff |", "|---|---|---|---|---|---|"]
        L += [f"| {m['month']} | {m['rows']:,} | {pct(m['within_0_1pct'])} | {pct(m['within_1pct'])} | {m['median_abs']:.5f} | {m['p95_abs']:.5f} |" for m in r.taker_monthly["months"] if m.get("rows")]
        L += ["", "By era:", "", "| Era | Rows | Within 0.1% | Within 1% | Median abs. diff | 95th pct abs. diff |", "|---|---|---|---|---|---|"]
        L += [f"| {e} | {v['rows']:,} | {pct(v['within_0_1pct'])} | {pct(v['within_1pct'])} | {v['median_abs']:.5f} | {v['p95_abs']:.5f} |" for e, v in r.taker_monthly["eras"].items() if v.get("rows")]
        L.append("")
    if r.recorder_cmp:
        c = r.recorder_cmp
        L += [f"### Recorder window only: API ratio vs bulk ratio, each against the klines-derived ratio ({c['periods']:,} common periods)", "",
              "| Source | Rows | Within 0.1% | Within 1% | Median abs. diff | 95th pct abs. diff |", "|---|---|---|---|---|---|"]
        for name, v in (("Our recorder (API ratio, 4 decimals)", c["api"]), ("Bulk ratio", c["bulk"])):
            if v.get("rows"):
                L.append(f"| {name} | {v['rows']:,} | {pct(v['within_0_1pct'])} | {pct(v['within_1pct'])} | {v['median_abs']:.5f} | {v['p95_abs']:.5f} |")
        L += ["", f"**Which agrees better with the klines: {better_source(c)}.**", ""]
    L += ["## Anything odd", ""]
    L += [f"- {x}" for x in r.odd] or ["- Nothing in the checks above was flagged."]
    L += ["", "## What could not be shown", "",
          "- Whether bulk values before 2026-10-19 equal what the API showed at the time: our recorder starts then, so only the klines cross-check (taker ratio) reaches earlier.",
          "- Why the bulk and API taker ratios differ slightly where they do; this report gives no cause.",
          "- The exact LastModified of each file: it is rebuilt from the cached publish lag (accurate to the second), not read again from the archive.",
          "- Nothing from this archive has been used as a feature or in any model.", ""]
    L += decisions_lines()
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------------ run ---

def run(session, data_dir: Path, report_path: Path, sleep: Callable[[float], None] = time.sleep, last_day: str | None = None,
        on_progress: Callable[[str], None] | None = print) -> Report:
    data_dir = Path(data_dir)
    rep = Report()
    cache = data_dir / "bulk_window" / "_listing_lags.json"
    if cache.exists():
        lags, rep.lag_source = load_lags(cache), "the cached listing of the earlier bulk_equivalence run"
    else:
        lags, rep.lag_source = fetch_lags_listing(session, sleep), "ONE new metrics listing request (the cache was missing)"
    days = sorted(d for d in lags if d <= (last_day or "9999"))
    zips = data_dir / "bulk_metrics" / "zips"
    reuse = tuple(data_dir / p for p in ("bulk_window/metrics", "bulk_window/metrics_format", "bulk_sample/metrics"))
    manifest = MANIFEST_PATH if data_dir.resolve() == DEFAULT_DATA_DIR.resolve() else data_dir.parent / "static" / MANIFEST_PATH.name
    rep.download = download_all(session, days, zips, manifest, lags, reuse, sleep, on_progress)
    rep.manifest_rows = len(read_manifest(manifest))
    out_path = data_dir / "binance_bulk_metrics_TACUSDT_5m.csv"
    rep.normalized = append_normalized(out_path, rep.download.outcomes, lags)
    df = load_normalized(out_path)
    if df.empty:
        rep.odd = collect_odd(rep)
        report_path.write_text(render_report(rep), encoding="utf-8")
        return rep
    rep.first_last = (int(df["bulk_label_ms"].min()), int(df["bulk_label_ms"].max()))
    rep.quality = quality_checks(df)
    rep.monthly = monthly_distribution(df)
    rep.breaks = {"2026-07-12": break_check(df, "2026-07-12"), "2026-11-16": break_check(df, "2026-11-16")}
    oi_path = next(d for d in be.RECORDER_DATASETS if d.name == "open_interest").csv_path(data_dir)
    tk_path = next(d for d in be.RECORDER_DATASETS if d.name == "taker_buy_sell").csv_path(data_dir)
    rec = df[df["ts_ours_ms"] >= OI_VERIFIED_FROM_MS]
    rep.recheck = label_convention_recheck(rec, ba.read_complete(oi_path)) if len(rec) and oi_path.exists() else None
    kl_path = data_dir / bk.DEFAULT_OUT.name
    if kl_path.exists():
        derived = derived_taker_ratio(ba.read_complete(kl_path))
        rep.taker_align = taker_alignment(df, derived)
        off = ALIGNMENTS[rep.taker_align["best"]]
        rep.taker_monthly = taker_by_month_and_era(df, derived, off)
        if tk_path.exists():
            rep.recorder_cmp = recorder_taker_comparison(rec, derived, ba.read_complete(tk_path), off)
    rep.odd = collect_odd(rep)
    write_run_log(data_dir, rep)
    rep.history = read_run_log(data_dir)
    Path(report_path).write_text(render_report(rep), encoding="utf-8")
    return rep


def run_log_path(data_dir: Path) -> Path:
    return Path(data_dir) / "bulk_metrics" / "run_log.txt"


def write_run_log(data_dir: Path, rep: "Report") -> None:
    """One line per run, appended (a record of what each run downloaded, reused and found)."""
    d = rep.download
    if not d:
        return
    p = run_log_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = (f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC: days {len(d.outcomes)}, verified {sum(1 for o in d.outcomes if o.verified)}, "
            f"reused from disk {sum(1 for o in d.outcomes if o.reused)}, revisions {len(d.revisions)}, failures {len(d.failures)}, stopped: {d.stopped or 'no'}, "
            f"normalized rows added {rep.normalized.get('rows_added', 0)}")
    with p.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_run_log(data_dir: Path) -> list[str]:
    p = run_log_path(data_dir)
    return p.read_text(encoding="utf-8").splitlines() if p.exists() else []


def console_summary(rep: Report, report: Path) -> str:
    d = rep.download
    out = ["Bulk metrics history"]
    if d:
        out.append(f"  days processed {len(d.outcomes)}, verified {sum(1 for o in d.outcomes if o.verified)}, reused {sum(1 for o in d.outcomes if o.reused)}, "
                   f"revisions {len(d.revisions)}, failures {len(d.failures)}; stopped: {d.stopped or 'no'}")
    if rep.first_last:
        out.append(f"  normalized rows {rep.quality['rows']:,}, {iso(rep.first_last[0])} to {iso(rep.first_last[1])}")
    if rep.taker_align:
        out.append(f"  taker best alignment: {rep.taker_align['best']}")
    out += [f"  odd: {len(rep.odd)}", f"  report: {report}"]
    return "\n".join(out)


def decisions_lines() -> list[str]:
    """The decisions taken by the user on 2026-11-21 after reading this report (fixed text; the script adopts nothing by itself)."""
    return [
        "## Decisions", "",
        "**Decided by the user on 2026-11-21.**", "",
        "1. The bulk taker ratio is not used as a feature. Taker flow will be derived from our own 1m klines (known at candle close), because over the "
        "recorder window the API ratio matches the klines-derived ratio in 92.49 percent of rows within 0.1 percent while the bulk ratio does so in 60.61 "
        "percent, and the bulk ratio differs from the klines in both eras.",
        "2. Bad rows are flagged missing by the loader and never filled from neighbours: open interest at or below zero or not-a-number, any ratio at or "
        "below zero or not-a-number, and rows inside the 24 open-interest jumps above 50 percent. The raw normalized file stays unchanged.",
        "3. Open interest and the ratio columns are regime-sensitive. Levels shift around 2026-07-12 (this cannot be checked against the recorder, which starts "
        "2026-10-19) and around 2026-11-16 (also present in our recorder's API values, which match the bulk values on both sides, so it is not an archive "
        "artifact; the cause is unknown). Phase 2 must test stability per regime before any such feature is used.",
        "4. Nothing from this file has been used as a feature.", ""]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Download the bulk metrics history for TACUSDT, normalize it, check it, cross-check the taker ratio.")
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    args = ap.parse_args(argv)
    data_dir, report = Path(args.data_dir), Path(args.report)
    r_res, d_res = report.resolve(), data_dir.resolve()
    if r_res == d_res or d_res in r_res.parents:
        print(f"Refusing: --report must not be inside the data directory {data_dir}.")
        return 2
    rep = run(requests.Session(), data_dir, report)
    print(console_summary(rep, report))
    return 2 if (rep.download and rep.download.stopped) else 0


if __name__ == "__main__":
    raise SystemExit(main())
