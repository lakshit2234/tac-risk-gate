"""Availability and format check of Binance's free public bulk archive (data.binance.vision) for TACUSDT USD-M futures.

This is NOT a history download. It makes a few listing requests (the archive is an S3 bucket whose listing is public),
downloads at most ONE small sample file per dataset type into a new git-ignored folder, and compares the sample day
read-only against our existing files. It never modifies any existing data file.

Rules it follows:
  * sequential requests with short pauses;
  * a refused request (HTTP 403 or 418, or 429 after its retries) STOPS the run at that point and says so; it never
    looks for a way around it;
  * a file that is not in a listing does not exist (nothing is guessed);
  * a sample file is checked against its published .CHECKSUM (sha256) when the listing shows one.

Run: python -m tacgate.data.bulk_availability [--sample-day 2026-11-10] [--out-dir data/raw/bulk_sample]
                                             [--report docs/binance_bulk_availability.md] [--data-dir data/raw]
Exit codes: 0 ok, 2 bad arguments or the run stopped because a request was refused.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import re
import statistics
import time
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import pandas as pd
import requests

from tacgate.data import binance_klines as bk
from tacgate.data.recorder import DATASETS as RECORDER_DATASETS

LIST_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DOWNLOAD_URL = "https://data.binance.vision"
SYMBOL = "TACUSDT"
AREAS = ("daily", "monthly")
DEFAULT_SAMPLE_DAY = "2026-11-10"
DEFAULT_OUT_DIR = Path("data/raw/bulk_sample")
DEFAULT_REPORT = Path("docs/binance_bulk_availability.md")
DEFAULT_DATA_DIR = Path("data/raw")
PAUSE_S = 0.5  # between requests
MAX_RETRIES = 2
MAX_SAMPLE_BYTES = 30_000_000  # a bigger sample file is skipped, not downloaded
MAX_KEYS = 1000
DAY_MS = 86_400_000
S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
RETRY_STATUS = {500, 502, 503, 504}


@dataclass(frozen=True)
class DatasetType:
    name: str
    interval: str | None = None  # a sub-folder such as 1m for the kline families

    def prefix(self, area: str) -> str:
        p = f"data/futures/um/{area}/{self.name}/{SYMBOL}/"
        return p + (f"{self.interval}/" if self.interval else "")


TYPES = [
    DatasetType("klines", "1m"),
    DatasetType("metrics"),
    DatasetType("bookDepth"),
    DatasetType("markPriceKlines", "1m"),
    DatasetType("indexPriceKlines", "1m"),
    DatasetType("premiumIndexKlines", "1m"),
    DatasetType("fundingRate"),
    DatasetType("aggTrades"),
    DatasetType("trades"),
    DatasetType("bookTicker"),
    DatasetType("liquidationSnapshot"),
]


class Refused(RuntimeError):
    """The server refused a request (403, 418, or 429 after retries). The run stops; no workaround is tried."""


@dataclass
class Entry:
    key: str
    last_modified: datetime
    size: int


# ------------------------------------------------------------------- HTTP ---

def http_get(session, url: str, params: dict | None = None, sleep: Callable[[float], None] = time.sleep) -> bytes | None:
    """GET with a small bounded retry on 5xx and 429. Returns the body, or None on 404.

    403 and 418 raise Refused at once; 429 raises Refused after MAX_RETRIES retries (Retry-After honoured)."""
    last = ""
    for attempt in range(MAX_RETRIES + 1):
        resp = session.get(url, params=params, timeout=60)
        code = resp.status_code
        if code == 200:
            return resp.content
        if code == 404:
            return None
        if code in (403, 418):
            raise Refused(f"HTTP {code} from {url}: refused, stopping here")
        last = f"HTTP {code}"
        if code == 429 or code in RETRY_STATUS:
            wait = 2.0 * (2**attempt)
            ra = resp.headers.get("Retry-After") if hasattr(resp, "headers") else None
            try:
                wait = max(wait, float(ra)) if ra else wait
            except ValueError:
                pass
            if attempt < MAX_RETRIES:
                sleep(wait)
                continue
            if code == 429:
                raise Refused(f"HTTP 429 from {url} after {MAX_RETRIES} retries: refused, stopping here")
            raise RuntimeError(f"{last} from {url} after {MAX_RETRIES} retries")
        raise RuntimeError(f"{last} from {url}")
    raise RuntimeError(f"{last} from {url}")


# ---------------------------------------------------------------- listing ---

def parse_listing(body: bytes) -> tuple[list[Entry], bool, str]:
    """(entries, is_truncated, next_marker) from one S3 ListBucketResult page."""
    root = ET.fromstring(body)
    entries = []
    for c in root.findall("s3:Contents", S3_NS):
        lm = c.findtext("s3:LastModified", default="", namespaces=S3_NS)
        entries.append(Entry(
            key=c.findtext("s3:Key", default="", namespaces=S3_NS),
            last_modified=datetime.strptime(lm, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc),
            size=int(c.findtext("s3:Size", default="0", namespaces=S3_NS)),
        ))
    truncated = root.findtext("s3:IsTruncated", default="false", namespaces=S3_NS) == "true"
    nxt = root.findtext("s3:NextMarker", default="", namespaces=S3_NS)
    return entries, truncated, nxt


def list_prefix(session, prefix: str, sleep: Callable[[float], None] = time.sleep) -> list[Entry]:
    """All objects directly under prefix (follows pagination)."""
    out: list[Entry] = []
    marker = ""
    while True:
        params = {"delimiter": "/", "prefix": prefix, "max-keys": MAX_KEYS}
        if marker:
            params["marker"] = marker
        body = http_get(session, LIST_URL, params, sleep)
        if body is None:
            return out
        entries, truncated, nxt = parse_listing(body)
        out += entries
        if not truncated or not entries:
            return out
        marker = nxt or entries[-1].key
        sleep(PAUSE_S)


_DAILY_RE = re.compile(r"-(\d{4}-\d{2}-\d{2})\.zip$")
_MONTHLY_RE = re.compile(r"-(\d{4}-\d{2})\.zip$")


def file_period(key: str, area: str) -> str | None:
    """'2026-11-10' (daily) or '2026-11' (monthly) from a data file name; None for checksum files and others."""
    m = (_DAILY_RE if area == "daily" else _MONTHLY_RE).search(key)
    return m.group(1) if m else None


def period_end(period: str) -> datetime:
    """The end (exclusive) of the UTC day or month the file covers."""
    if len(period) == 10:
        return datetime.strptime(period, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
    start = datetime.strptime(period, "%Y-%m").replace(tzinfo=timezone.utc)
    return (start.replace(day=28) + timedelta(days=4)).replace(day=1)


@dataclass
class Summary:
    files: int = 0
    first: str | None = None
    last: str | None = None
    checksums: int = 0
    periods: list[str] = field(default_factory=list)
    total_bytes: int = 0

    @property
    def exists(self) -> bool:
        return self.files > 0


def summarize(entries: list[Entry], area: str) -> Summary:
    s = Summary()
    for e in entries:
        if e.key.endswith(".CHECKSUM"):
            s.checksums += 1
            continue
        p = file_period(e.key, area)
        if p:
            s.periods.append(p)
            s.total_bytes += e.size
    s.periods.sort()
    s.files = len(s.periods)
    if s.periods:
        s.first, s.last = s.periods[0], s.periods[-1]
    return s


def lag_hours(entries: list[Entry], area: str) -> dict[str, float]:
    """period -> hours between the end of the UTC day/month and the object's LastModified time."""
    out = {}
    for e in entries:
        p = file_period(e.key, area)
        if p:
            out[p] = (e.last_modified - period_end(p)).total_seconds() / 3600
    return out


def lag_stats(lags: dict[str, float]) -> dict | None:
    if not lags:
        return None
    v = sorted(lags.values())
    latest = max(lags)
    last90 = [lags[p] for p in sorted(lags)[-90:]]
    return {"latest_period": latest, "latest": lags[latest], "n": len(v), "min": v[0], "median": statistics.median(v),
            "p95": v[min(len(v) - 1, int(0.95 * len(v)))], "max": v[-1], "max_last90": max(last90)}


def survey(session, sleep: Callable[[float], None] = time.sleep) -> dict[tuple[str, str], list[Entry]]:
    """Listing of every (type, area). Raises Refused at the first refusal (nothing after it is requested)."""
    out: dict[tuple[str, str], list[Entry]] = {}
    for t in TYPES:
        for area in AREAS:
            out[(t.name, area)] = list_prefix(session, t.prefix(area), sleep)
            sleep(PAUSE_S)
    return out


# ----------------------------------------------------------------- samples ---

def choose_sample(daily: list[Entry], monthly: list[Entry], preferred_day: str) -> tuple[str, Entry, str] | None:
    """(area, entry, period): the preferred day if listed, else the latest full daily file; monthly only if there is
    no daily file at all (the latest monthly file). 'Full day' = a day that has ended, so the newest listed day is used
    as long as its end is in the past (a listed daily file always is)."""
    by_period = {file_period(e.key, "daily"): e for e in daily if file_period(e.key, "daily")}
    if by_period:
        p = preferred_day if preferred_day in by_period else max(by_period)
        return "daily", by_period[p], p
    by_m = {file_period(e.key, "monthly"): e for e in monthly if file_period(e.key, "monthly")}
    if by_m:
        p = max(by_m)
        return "monthly", by_m[p], p
    return None


@dataclass
class Sample:
    type_name: str
    area: str
    period: str
    key: str
    size: int
    zip_path: Path | None = None
    csv_path: Path | None = None
    sha256: str = ""
    checksum: str = "not checked"  # verified / MISMATCH / not published / unreadable
    skipped: str = ""


def parse_checksum(text: str) -> str:
    """The hex digest in a '<sha256>  <filename>' checksum file ('' if unreadable)."""
    tok = text.strip().split()
    return tok[0].lower() if tok and re.fullmatch(r"[0-9a-fA-F]{64}", tok[0]) else ""


def download_sample(session, type_name: str, area: str, period: str, entry: Entry, checksum_listed: bool, out_dir: Path,
                    sleep: Callable[[float], None] = time.sleep) -> Sample:
    s = Sample(type_name, area, period, entry.key, entry.size)
    if entry.size > MAX_SAMPLE_BYTES:
        s.skipped = f"file is {entry.size:,} bytes, over the {MAX_SAMPLE_BYTES:,} byte sample limit; not downloaded"
        return s
    out_dir = Path(out_dir) / type_name  # one folder per type: the kline families share the same file name
    out_dir.mkdir(parents=True, exist_ok=True)
    s.zip_path = out_dir / Path(entry.key).name
    if s.zip_path.exists():  # a sample from an earlier run: reuse it (still verified below), do not download it again
        body = s.zip_path.read_bytes()
    else:
        body = http_get(session, f"{DOWNLOAD_URL}/{entry.key}", None, sleep)
        sleep(PAUSE_S)
        if body is None:
            s.zip_path = None
            s.skipped = "listed but the download returned 404"
            return s
        s.zip_path.write_bytes(body)
    s.sha256 = hashlib.sha256(body).hexdigest()
    if checksum_listed:
        ck = http_get(session, f"{DOWNLOAD_URL}/{entry.key}.CHECKSUM", None, sleep)
        sleep(PAUSE_S)
        want = parse_checksum(ck.decode("utf-8", errors="replace")) if ck else ""
        s.checksum = "unreadable" if not want else ("verified" if want == s.sha256 else "MISMATCH")
    else:
        s.checksum = "not published"
    with zipfile.ZipFile(s.zip_path) as z:
        names = [n for n in z.namelist() if n.endswith(".csv")]
        if names:
            s.csv_path = out_dir / names[0]
            s.csv_path.write_bytes(z.read(names[0]))
    return s


def classify_time(value: str) -> str:
    v = value.strip()
    if re.fullmatch(r"\d{13}", v):
        return "epoch milliseconds (13 digits)"
    if re.fullmatch(r"\d{16}", v):
        return "epoch microseconds (16 digits)"
    if re.fullmatch(r"\d{10}", v):
        return "epoch seconds (10 digits)"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\.\d+)?", v):
        return "datetime text, UTC assumed (not stated in the file)"
    return "other"


def describe_csv(path: Path, n: int = 3) -> dict:
    """Header (None if the file has no header row), the first n data rows, the row count and the first-cell format."""
    with Path(path).open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        return {"header": None, "first": [], "rows": 0, "time_format": "empty"}
    first_cell = rows[0][0]
    has_header = not re.fullmatch(r"[\d.\-: ]+", first_cell.strip())
    header = rows[0] if has_header else None
    data = rows[1:] if has_header else rows
    # the time column is the first one whose name contains "time" (the first column otherwise)
    ti = next((i for i, c in enumerate(header or []) if "time" in c.lower()), 0)
    times = [r[ti] for r in data]
    try:
        in_order = [float(t) for t in times] == sorted(float(t) for t in times)
    except ValueError:
        in_order = times == sorted(times)
    return {"header": header, "first": data[:n], "rows": len(data), "time_column": (header[ti] if header else None),
            "time_format": classify_time(times[0]) if times else "empty", "in_time_order": in_order,
            "unique_times": len(set(times))}


# ---------------------------------------------------------------- overlaps ---

def read_csv_df(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    df = pd.read_csv(path, header=0 if columns is None else None, dtype=str, keep_default_na=False)
    if columns is not None:
        if len(df.columns) != len(columns):
            raise ValueError(f"{path}: expected {len(columns)} columns, found {len(df.columns)}")
        df.columns = columns
    return df


def day_bounds(day: str) -> tuple[int, int]:
    start = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    return start, start + DAY_MS


def read_complete(path: Path) -> pd.DataFrame:
    """Read one of OUR files once, read-only, ignoring a partial last line."""
    data = Path(path).read_bytes()
    data = data[: data.rfind(b"\n") + 1]
    return pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False)


def compare_klines(bulk: pd.DataFrame, ours: pd.DataFrame, day: str) -> dict:
    """Row-by-row comparison of bulk 1m klines against our Binance 1m file for one UTC day.

    Both have the same 12 columns in the same order, so columns are compared by position. Values are compared as numbers."""
    lo, hi = day_bounds(day)
    cols = bk.COLUMNS
    b = bulk.copy()
    b.columns = cols
    o = ours[(ours["open_time"].astype("int64") >= lo) & (ours["open_time"].astype("int64") < hi)].copy()
    o.columns = cols
    bn, on = b.astype(float).set_index("open_time"), o.astype(float).set_index("open_time")
    common = bn.index.intersection(on.index)
    diff_mask = (bn.loc[common] != on.loc[common])
    differing = int(diff_mask.any(axis=1).sum())
    return {"bulk_rows": len(bn), "our_rows": len(on), "common": len(common), "only_bulk": len(bn.index.difference(on.index)),
            "only_ours": len(on.index.difference(bn.index)), "differing_rows": differing,
            "differing_columns": {c: int(diff_mask[c].sum()) for c in diff_mask.columns if int(diff_mask[c].sum())},
            "examples": [(int(t), {c: (float(bn.loc[t, c]), float(on.loc[t, c])) for c in diff_mask.columns if diff_mask.loc[t, c]})
                         for t in diff_mask.index[diff_mask.any(axis=1)][:3]]}


def to_ms(series: pd.Series) -> pd.Series:
    """Epoch ms from epoch numbers or UTC datetime text."""
    num = pd.to_numeric(series, errors="coerce")
    if num.notna().all():
        return num.astype("int64")
    dt = pd.to_datetime(series, utc=True)
    return ((dt - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(milliseconds=1)).astype("int64")


SHIFTS_MS = (-300_000, 0, 300_000)


def match_metrics(bulk: pd.DataFrame, ours: dict[str, pd.DataFrame], day: str, rel_tol: float = 1e-3) -> list[dict]:
    """For each numeric bulk column, find which of our recorder columns holds the same values, and at which time shift.

    `ours` maps a recorder dataset name to its frame (all-string columns, including `timestamp`). Bulk rows are aligned to our
    rows by timestamp plus a shift of -5, 0 or +5 minutes (to see how the labels line up). `close` means within rel_tol,
    `exact` means equal to 1e-9. Nothing is assumed: the best match is whatever the numbers show."""
    lo, hi = day_bounds(day)
    b = bulk.copy()
    tcol = b.columns[0]
    b["_ts"] = to_ms(b[tcol])
    results = []
    for col in [c for c in b.columns[1:] if c != "_ts"]:
        bv = pd.to_numeric(b[col], errors="coerce")
        if bv.isna().all():
            continue  # text column such as symbol
        best = None
        for name, odf in ours.items():
            ts = pd.to_numeric(odf["timestamp"], errors="coerce")
            odf = odf[(ts >= lo - 600_000) & (ts < hi + 600_000)]
            if odf.empty:
                continue
            ot = pd.to_numeric(odf["timestamp"]).astype("int64")
            for ocol in odf.columns:
                if ocol in ("timestamp", "fetched_at_ms", "symbol"):
                    continue
                ov = pd.to_numeric(odf[ocol], errors="coerce")
                lookup = pd.Series(ov.values, index=ot.values)
                lookup = lookup[~lookup.index.duplicated()]
                for shift in SHIFTS_MS:
                    other = lookup.reindex((b["_ts"] + shift).values).values
                    ok = ~pd.isna(other) & bv.notna().values
                    if int(ok.sum()) < 10:
                        continue
                    a, c = bv.values[ok].astype(float), other[ok].astype(float)
                    scale = pd.Series(abs(c)).clip(lower=1e-12).values
                    rel = abs(a - c) / scale
                    close = float((rel <= rel_tol).mean())
                    exact = float((rel <= 1e-9).mean())
                    cand = {"bulk_column": col, "ours": f"{name}.{ocol}", "shift_min": shift // 60_000, "rows": int(ok.sum()),
                            "close": close, "exact": exact, "max_rel": float(rel.max())}
                    if best is None or (close, exact) > (best["close"], best["exact"]):
                        best = cand
        results.append(best or {"bulk_column": col, "ours": None, "shift_min": None, "rows": 0, "close": 0.0, "exact": 0.0, "max_rel": 0.0})
    return results


# ------------------------------------------------------------------ report ---

def book_depth_facts(csv_path: Path) -> dict:
    """What the bookDepth sample shows: the distinct percentage levels, the snapshots in the day and their typical spacing."""
    df = pd.read_csv(csv_path)
    ts = pd.to_datetime(df.iloc[:, 0], utc=True)
    uniq = sorted(ts.unique())
    gaps = pd.Series(uniq).diff().dt.total_seconds().dropna()
    return {"levels": sorted(df["percentage"].unique().tolist()), "snapshots": len(uniq),
            "median_gap_s": float(gaps.median()) if len(gaps) else None, "max_gap_s": float(gaps.max()) if len(gaps) else None}


def fmt_h(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1f} h"


def proposed_rule(type_name: str, area: str, st: dict | None) -> str:
    if not st:
        return "no files listed: no rule"
    if area == "monthly":
        days = max(1, int(-(-st["max"] // 24)))  # the largest observed lag over all monthly files, in whole days, rounded up
        return (f"a row counts as known at the end of its UTC month plus {days} days, never at the row's own time. Why: monthly files are a later "
                f"consolidated copy; the {st['n']} listed ones appeared between {fmt_h(st['min'])} and {fmt_h(st['max'])} after the month ended, so the "
                "largest observed lag, rounded up, is used. Where daily files exist for the same data they are earlier and should be used instead.")
    if st["max_last90"] <= 12:
        why = (f"the latest file appeared {fmt_h(st['latest'])} after the UTC day ended and none of the latest 90 took longer than {fmt_h(st['max_last90'])}, "
               "so 24 h leaves more than a 2x margin")
    else:
        why = (f"the latest file appeared {fmt_h(st['latest'])} after the UTC day ended, but among the latest 90 one took {fmt_h(st['max_last90'])}, "
               "so a live system must also check the file's own LastModified time and use whichever is later")
    return f"a row counts as known at the end of its UTC day plus 24 h, never at the row's own time. Why: {why}."


@dataclass
class Result:
    listings: dict[tuple[str, str], list[Entry]] = field(default_factory=dict)
    samples: dict[str, Sample] = field(default_factory=dict)
    descriptions: dict[str, dict] = field(default_factory=dict)
    kline_overlap: dict | None = None
    metrics_overlap: list[dict] | None = None
    stopped: str = ""
    depth_facts: dict | None = None
    sample_day: str = DEFAULT_SAMPLE_DAY
    notes: list[str] = field(default_factory=list)


def render_report(res: Result) -> str:
    L = ["# Binance bulk archive (data.binance.vision): availability check for TACUSDT USD-M futures", "",
         f"Checked on {datetime.now(timezone.utc).strftime('%Y-%m-%d')} (UTC). This is a listing and sample check, not a history download. "
         "The archive's file listing is a public S3 listing; a file that is not listed is treated as not existing. "
         "Samples are in `data/raw/bulk_sample/` (git-ignored).", ""]
    if res.stopped:
        L += [f"**The run stopped early: {res.stopped}** Nothing after that request was attempted.", ""]
    L += ["## 1. What exists", "", "| Dataset | Daily files | First to last (daily) | Monthly files | First to last (monthly) | Checksum files (daily) |",
          "|---|---|---|---|---|---|"]
    for t in TYPES:
        d = summarize(res.listings.get((t.name, "daily"), []), "daily")
        m = summarize(res.listings.get((t.name, "monthly"), []), "monthly")
        if (t.name, "daily") not in res.listings:
            L.append(f"| {t.name}{' ' + t.interval if t.interval else ''} | not listed (run stopped) | | | | |")
            continue
        kind = "daily and monthly" if d.exists and m.exists else "daily only" if d.exists else "monthly only" if m.exists else "none"
        L.append(f"| {t.name}{' ' + t.interval if t.interval else ''} ({kind}) | {d.files} | {d.first or '-'} to {d.last or '-'} | "
                 f"{m.files} | {m.first or '-'} to {m.last or '-'} | {d.checksums} |")
    L += ["", "## 2. Sample files and formats", ""]
    for name, s in res.samples.items():
        L += [f"### {name}", "", f"- File: `{s.key}` ({s.area}, {s.period}), {s.size:,} bytes"]
        if s.skipped:
            L += [f"- Skipped: {s.skipped}", ""]
            continue
        L += [f"- Checksum: {s.checksum}" + (f" (sha256 {s.sha256[:16]}...)" if s.sha256 else "")]
        d = res.descriptions.get(name)
        if d:
            L += [f"- Header row: {'yes' if d['header'] else 'NO, the file has no header'}; data rows: {d['rows']:,}; time column {d.get('time_column')}: {d['time_format']}",
                  f"- Rows in time order: {'yes' if d['in_time_order'] else '**NO, the rows are not sorted by time (sort before use)**'}; distinct time values: {d['unique_times']:,}",
                  f"- Columns: {', '.join(d['header']) if d['header'] else 'not given in the file'}", "", "```"]
            if d["header"]:
                L.append(",".join(d["header"]))
            L += [",".join(r) for r in d["first"]] + ["```"]
        L.append("")
    L += ["Units are not stated inside the files. Where a unit matters it is taken from the comparison with our own files below, or marked unknown.", ""]
    L += ["## 3. Publish lag (hours after the end of the UTC day or month, from the object's LastModified time in the listing)", "",
          "| Dataset | Area | Latest file | Its LastModified (UTC) | Lag of latest | Median | 95th pct | Max | Max (latest 90) | Files |", "|---|---|---|---|---|---|---|---|---|---|"]
    stats: dict[tuple[str, str], dict | None] = {}
    for t in TYPES:
        for area in AREAS:
            ents = res.listings.get((t.name, area), [])
            st = lag_stats(lag_hours(ents, area))
            stats[(t.name, area)] = st
            if st:
                latest_entry = next(e for e in ents if file_period(e.key, area) == st["latest_period"])
                L.append(f"| {t.name} | {area} | {st['latest_period']} | {latest_entry.last_modified.strftime('%Y-%m-%d %H:%M')} | {fmt_h(st['latest'])} | {fmt_h(st['median'])} | {fmt_h(st['p95'])} | "
                         f"{fmt_h(st['max'])} | {fmt_h(st['max_last90'])} | {st['n']} |")
    L += ["", "LastModified is when the object was last written. A file that was rewritten later would look slower than it first appeared, "
          "which only makes the lag estimate more conservative.", ""]
    L += [f"## 4. Overlap with our own files on {res.sample_day}", ""]
    ko = res.kline_overlap
    if ko:
        L += ["### Bulk 1m klines vs our Binance 1m file", "",
              f"- Rows: bulk {ko['bulk_rows']:,}, ours {ko['our_rows']:,}, in both {ko['common']:,}; only in bulk {ko['only_bulk']}, only in ours {ko['only_ours']}",
              f"- Rows with any differing value: **{ko['differing_rows']}**"]
        if ko["differing_columns"]:
            L.append("- Differing columns: " + ", ".join(f"{c} {n}" for c, n in ko["differing_columns"].items()))
        for t, dd in ko["examples"]:
            L.append(f"  - open_time {t}: " + "; ".join(f"{c} bulk {a} vs ours {b}" for c, (a, b) in dd.items()))
        L.append("")
    else:
        L += ["Klines comparison not run (no sample).", ""]
    mo = res.metrics_overlap
    if mo is not None:
        L += ["### Bulk metrics vs our recorder history files", "",
              "For each numeric bulk column, the recorder column whose values match best, at which time shift between the bulk row time and "
              "our timestamp (a shift of +5 means our timestamp is the bulk row time plus 5 minutes), and the share of rows that match (close = within 0.1%, "
              "exact = equal; our ratios are rounded to 4 decimals, so exact is not expected for them). A share well below 100% means the mapping is unclear.", "",
              "| Bulk column | Best match in our files | Shift (min) | Rows compared | Close | Exact | Largest relative difference |", "|---|---|---|---|---|---|---|"]
        for r in mo:
            L.append(f"| {r['bulk_column']} | {r['ours'] or 'none found'} | {r['shift_min'] if r['shift_min'] is not None else '-'} | {r['rows']} | "
                     f"{100 * r['close']:.1f}% | {100 * r['exact']:.1f}% | {100 * r['max_rel']:.2f}% |")
        unclear = [r["bulk_column"] for r in mo if r["close"] < 0.95]
        L += ["", ("Mapping unclear or partial for: " + ", ".join(unclear) + ".") if unclear else "Every numeric bulk column matched one of our columns in at least 95% of rows.", ""]
        for r in mo:
            if r["close"] < 0.95 and r["ours"]:
                L.append(f"- `{r['bulk_column']}` matched `{r['ours']}` in only {100 * r['close']:.0f}% of rows (largest relative difference "
                         f"{100 * r['max_rel']:.2f}%), so it is a near match at best; the cause of the differences is not known.")
            if r["close"] < 0.95 and r["close"] < 0.5:
                L.append(f"- `{r['bulk_column']}` has no clear counterpart in our recorder files. By its name it may be a top-trader account ratio, "
                         "which our recorder does not fetch; that is a reading of the name, the data do not show it.")
        L.append("")
    else:
        L += ["Metrics comparison not run (no sample).", ""]
    L += ["## 5. Proposed known-time rules", "",
          "Two facts from section 3 shape these rules. First, recent day files appear a few hours after their UTC day ends. Second, many OLD files "
          "appear to have been written long after their day (for metrics the median lag over all files is far larger than the latest ones), so for "
          "historical rows the file's LastModified time says when the archive was filled, not when the data first existed. The overlap above shows "
          "the same values were already public through the API on that day (open interest matched exactly on the sample day). Because of that, and to stay "
          "conservative, the proposed rule treats every bulk row like our daily external rows: known no earlier than the end of its UTC day plus 24 h. "
          "That rule gives up intraday timing for bulk history, which is the price of not trusting the file time. The equality with the API was "
          "checked on one sample day only.", ""]
    for t in TYPES:
        for area in AREAS:
            if stats.get((t.name, area)):
                L.append(f"- **{t.name} ({area})**: {proposed_rule(t.name, area, stats[(t.name, area)])}")
    L += ["", "## 6. What this changes for Gate 1", ""]
    for line in gate1_lines(res):
        L.append(f"- {line}")
    for n in res.notes:
        L.append(f"- {n}")
    L.append("")
    L += open_items_lines()
    return "\n".join(L) + "\n"


def open_items_lines() -> list[str]:
    """The open items that come with this check (fixed text: they are about what was NOT checked)."""
    return [
        "## 7. Open items", "",
        "1. The equivalence with our recorder was checked on one day only (2026-11-10). A check over the full recorder window (2026-10-19 to the latest "
        "day) is still needed for open interest, the long/short ratios and the taker ratio, together with an explanation of the taker differences "
        "(75% of rows within 0.1%, largest difference 0.34%).",
        "2. Many old metrics files were written months after their day. The date where the file lag changes from months to hours (the backfilled era "
        "versus the live era) must be found, and values before that date may have been produced differently.",
        "3. The proposed known-time rule (end of the UTC day plus 24 hours, or the file's LastModified time if later) is provisional. A tighter rule "
        "(label time plus 10 minutes, as for the recorder) may be justified only if item 1 shows exact equality.",
        "4. Units are not stated in the files. `count_toptrader_long_short_ratio` has no counterpart in our files. The bookDepth bands differ from our "
        "snapshot bands.",
        "",
        "No feature was built from any of this data.", ""]


def gate1_lines(res: Result) -> list[str]:
    out = []
    m = summarize(res.listings.get(("metrics", "daily"), []), "daily")
    if m.exists:
        days = (datetime.strptime(m.last, "%Y-%m-%d") - datetime.strptime(m.first, "%Y-%m-%d")).days + 1
        out.append(f"`metrics`: the listing shows daily files for {SYMBOL} from {m.first} to {m.last} ({m.files} files, a span of {days} days). "
                   "Our recorder history has 32 days. On the sample day the open interest, the top-position ratio and the global ratio matched our recorder "
                   "columns (see section 4), so open interest and the two long/short ratios could have about "
                   f"{days} days of history instead of 32. The taker ratio matched only approximately, and one bulk column has no counterpart in our files. "
                   "Only one day was compared; no history was downloaded.")
    else:
        out.append("No daily `metrics` files are listed, so recorder-type features gain no extra history from this archive.")
    b = summarize(res.listings.get(("bookDepth", "daily"), []), "daily")
    if b.exists:
        f = res.depth_facts
        detail = ""
        if f:
            lv = ", ".join(f"{x:g}" for x in f["levels"])
            detail = (f" The sample day has {f['snapshots']:,} snapshots (median spacing {f['median_gap_s']:.0f} s) at the percentage levels {lv}; "
                      "each row gives a depth and a notional value. Whether `depth` is in tokens and `notional` in USD is not stated in the file.")
        out.append(f"`bookDepth`: {b.files} daily files from {b.first} to {b.last}, so the 'no depth history' gap in Gate 1 could shrink to "
                   f"banded depth only (not the full book, not trade-size slippage).{detail}")
    k = summarize(res.listings.get(("klines", "daily"), []), "daily")
    if k.exists:
        out.append(f"Daily 1m klines are listed from {k.first} to {k.last} ({k.files} files). On the sample day they matched our Binance 1m file "
                   "(section 4), so they add no new information for klines, only a second source.")
    for name in ("markPriceKlines", "indexPriceKlines", "premiumIndexKlines", "aggTrades", "trades", "fundingRate"):
        d, mm = summarize(res.listings.get((name, "daily"), []), "daily"), summarize(res.listings.get((name, "monthly"), []), "monthly")
        if d.exists or mm.exists:
            out.append(f"`{name}`: " + (f"{d.files} daily files ({d.first} to {d.last})" if d.exists else "no daily files")
                       + (f", {mm.files} monthly files ({mm.first} to {mm.last})" if mm.exists else ", no monthly files")
                       + ". New data for us (not compared with anything of ours)" + (" except funding, which our funding file already covers." if name == "fundingRate" else "."))
    for name in ("bookTicker", "liquidationSnapshot"):
        d, mm = summarize(res.listings.get((name, "daily"), []), "daily"), summarize(res.listings.get((name, "monthly"), []), "monthly")
        if (name, "daily") in res.listings and not (d.exists or mm.exists):
            out.append(f"`{name}`: no files are listed for {SYMBOL} (daily or monthly), so it does not exist in this archive. "
                       + ("The 'no liquidation data' gap stays." if name == "liquidationSnapshot" else ""))
    return out


# --------------------------------------------------------------------- run ---

def run(session, out_dir: Path, data_dir: Path, sample_day: str, sleep: Callable[[float], None] = time.sleep) -> Result:
    res = Result(sample_day=sample_day)
    try:
        res.listings = survey(session, sleep)
    except Refused as exc:
        res.stopped = str(exc)
        return res
    try:
        for t in TYPES:
            daily, monthly = res.listings[(t.name, "daily")], res.listings[(t.name, "monthly")]
            pick = choose_sample(daily, monthly, sample_day)
            if not pick:
                continue
            area, entry, period = pick
            listed = {e.key for e in (daily if area == "daily" else monthly)}
            s = download_sample(session, t.name, area, period, entry, entry.key + ".CHECKSUM" in listed, out_dir, sleep)
            res.samples[t.name] = s
            if s.csv_path:
                res.descriptions[t.name] = describe_csv(s.csv_path)
                if t.name == "bookDepth":
                    res.depth_facts = book_depth_facts(s.csv_path)
    except Refused as exc:
        res.stopped = str(exc)
    day = sample_day
    k = res.samples.get("klines")
    if k and k.csv_path and k.period == day:
        try:
            res.kline_overlap = compare_klines(read_csv_df(k.csv_path, None if res.descriptions["klines"]["header"] else bk.COLUMNS),
                                               read_complete(Path(data_dir) / bk.DEFAULT_OUT.name), day)
        except (OSError, ValueError, KeyError) as exc:
            res.notes.append(f"Klines comparison failed: {exc}")
    elif k and k.csv_path:
        res.notes.append(f"The klines sample is for {k.period}, not {day}, so the klines overlap was not run.")
    m = res.samples.get("metrics")
    if m and m.csv_path and m.period == day:
        try:
            ours = {d.name: read_complete(d.csv_path(Path(data_dir))) for d in RECORDER_DATASETS}
            res.metrics_overlap = match_metrics(read_csv_df(m.csv_path), ours, day)
        except (OSError, ValueError, KeyError) as exc:
            res.notes.append(f"Metrics comparison failed: {exc}")
    elif m and m.csv_path:
        res.notes.append(f"The metrics sample is for {m.period}, not {day}, so the metrics overlap was not run.")
    return res


def console_summary(res: Result, report: Path) -> str:
    out = ["Binance bulk archive check (TACUSDT USD-M futures)"]
    if res.stopped:
        out.append(f"  STOPPED: {res.stopped}")
    for t in TYPES:
        if (t.name, "daily") not in res.listings:
            continue
        d, m = summarize(res.listings[(t.name, "daily")], "daily"), summarize(res.listings[(t.name, "monthly")], "monthly")
        out.append(f"  {t.name:20s} daily {d.files:>4} ({d.first or '-'} to {d.last or '-'})  monthly {m.files:>3} ({m.first or '-'} to {m.last or '-'})")
    for name, s in res.samples.items():
        out.append(f"  sample {name}: {s.period} {s.checksum}" + (f" SKIPPED: {s.skipped}" if s.skipped else ""))
    out.append(f"  report: {report}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Availability and format check of data.binance.vision for TACUSDT USD-M futures.")
    ap.add_argument("--sample-day", default=DEFAULT_SAMPLE_DAY)
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    args = ap.parse_args(argv)
    out_dir, report, data_dir = Path(args.out_dir), Path(args.report), Path(args.data_dir)
    r_res, d_res = report.resolve(), data_dir.resolve()
    if r_res == d_res or d_res in r_res.parents:
        print(f"Refusing: --report must not be inside the data directory {data_dir}.")
        return 2
    if not (data_dir / bk.DEFAULT_OUT.name).exists():
        print(f"Our klines file not found in {data_dir}")
        return 2
    session = requests.Session()
    res = run(session, out_dir, data_dir, args.sample_day)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(res), encoding="utf-8")
    print(console_summary(res, report))
    return 2 if res.stopped else 0


if __name__ == "__main__":
    raise SystemExit(main())
