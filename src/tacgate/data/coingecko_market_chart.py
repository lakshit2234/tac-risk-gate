"""Fetch the daily TAC market chart (price, market cap, volume) from CoinGecko's public API.

Read-only public endpoint, no API key:
    GET https://api.coingecko.com/api/v3/coins/tac/market_chart?vs_currency=usd&days=365&interval=daily
(coin id "tac", verified live 2026-11-20, see docs/phase0_sources.md).

Why this exists: the free tier only serves the LAST 365 days and the window moves forward every
day, so this run must be repeated at least every few weeks. Days before the first stored date are
unrecoverable on the free tier.

Rules (docs/phase0_sources.md, "Decisions (approved)"):
- RAW fields only: timestamp_ms, price, market_cap, total_volume, fetched_at_ms. No derived columns.
- Never used as a price: CoinGecko's price disagreed with Binance by more than 2% on 73 of 363 days.
  Use it for market cap and volume only, and exclude the mismatch days.
- Only complete past days are stored. The last point CoinGecko returns is a live partial day
  (its timestamp is "now", not midnight), so any point on the current UTC day is skipped.
- Append-only. Existing rows are never rewritten or deleted. For timestamps already stored, the new
  value is only COMPARED (revision check) and the difference is reported, never applied.
- fetched_at_ms (local UTC clock when the response arrived) is stored on every row: no look-ahead.

Timestamp meaning (observed, not documented): a point stamped D 00:00 UTC is the value at that
instant, so on the free tier the newest stored row is the previous midnight.

Run: python -m tacgate.data.coingecko_market_chart [--days 365] [--out PATH]
"""
from __future__ import annotations

import argparse
import csv
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests

from tacgate.data.binance_klines import get_with_retry, now_ms, repair_csv

BASE_URL = "https://api.coingecko.com"
PATH = "/api/v3/coins/tac/market_chart"
COIN_ID = "tac"
VS_CURRENCY = "usd"
MAX_DAYS = 365  # free tier: older data is refused (HTTP 401, error 10012)
DAY_MS = 86_400_000
# CoinGecko's free tier throttles quickly (HTTP 429 after a few requests), so wait longer than the default.
MAX_RETRIES = 5
BACKOFF_BASE = 5.0  # 5, 10, 20, 40, 80 s unless Retry-After asks for more

RESPONSE_KEYS = ("prices", "market_caps", "total_volumes")
COLUMNS = ["timestamp_ms", "price", "market_cap", "total_volume", "fetched_at_ms"]
VALUE_FIELDS = ("price", "market_cap", "total_volume")  # compared in the revision check
MAX_LISTED_REVISIONS = 10

DEFAULT_OUT = Path("data/raw/coingecko_TAC_market_chart_daily.csv")

FATAL_STATUS = {
    401: (
        "HTTP 401 from CoinGecko: the request was refused (free-tier limit such as error 10012 "
        '"public API users are limited to the past 365 days", or a key is now required). Not retried.'
    ),
    403: "HTTP 403 from CoinGecko: access denied (plan or terms). Not retried.",
}

log = logging.getLogger(__name__)


class ShapeError(ValueError):
    """The response is not the expected market_chart layout. Fail loudly, never guess."""


@dataclass
class Revision:
    timestamp_ms: int
    changes: dict[str, float]  # field -> relative change (new vs stored); only fields that changed


@dataclass
class Result:
    added: int = 0
    skipped_current_day: int = 0
    revisions: list[Revision] = field(default_factory=list)
    compared: int = 0  # timestamps already stored that were compared
    out_of_order: int = 0  # new rows older than the last stored row (late fill of a gap)
    total_rows: int = 0
    first_ts: int | None = None
    last_ts: int | None = None
    missing_days: list[int] = field(default_factory=list)  # UTC day start (ms) inside the range with no row


def utc_date(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _number(v, where: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ShapeError(f"Unexpected value {v!r} in {where}; expected a finite number.")
    return float(v)


def parse_market_chart(payload) -> list[tuple[int, float, float, float]]:
    """Validate the response and return (timestamp_ms, price, market_cap, total_volume), ascending.

    Raises ShapeError on any difference from the layout verified live: exactly the keys prices,
    market_caps and total_volumes, each a non-empty list of [timestamp_ms, number] pairs, all three
    with the same timestamps in the same order.
    """
    if not isinstance(payload, dict):
        raise ShapeError(f"Expected a JSON object, got {type(payload).__name__}: {str(payload)[:200]}")
    if set(payload) != set(RESPONSE_KEYS):
        raise ShapeError(f"Unexpected response keys {sorted(payload)}; expected {sorted(RESPONSE_KEYS)}. "
                         "Refusing to save a changed layout.")
    series: dict[str, list[tuple[int, float]]] = {}
    for key in RESPONSE_KEYS:
        raw = payload[key]
        if not isinstance(raw, list) or not raw:
            raise ShapeError(f"{key} must be a non-empty list, got {str(raw)[:100]!r}")
        pairs = []
        for item in raw:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise ShapeError(f"{key}: expected [timestamp_ms, value] pairs, got {str(item)[:100]!r}")
            ts = _number(item[0], f"{key} timestamp")
            if not ts.is_integer() or ts <= 0:
                raise ShapeError(f"{key}: timestamp {item[0]!r} is not a positive integer in milliseconds")
            pairs.append((int(ts), _number(item[1], key)))
        stamps = [p[0] for p in pairs]
        if len(set(stamps)) != len(stamps):
            raise ShapeError(f"{key}: duplicate timestamps in one response")
        if stamps != sorted(stamps):
            raise ShapeError(f"{key}: timestamps are not ascending")
        series[key] = pairs
    base = [p[0] for p in series["prices"]]
    for key in ("market_caps", "total_volumes"):
        if [p[0] for p in series[key]] != base:
            raise ShapeError(f"{key} timestamps differ from prices timestamps")
    return [
        (ts, series["prices"][i][1], series["market_caps"][i][1], series["total_volumes"][i][1])
        for i, ts in enumerate(base)
    ]


def read_stored(path: Path) -> dict[int, tuple[float, float, float]]:
    """Stored rows by timestamp (read-only). Call repair_csv first so only complete rows remain."""
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return {}
    with path.open(newline="") as f:
        reader = csv.reader(f)
        next(reader, None)  # header (checked by repair_csv)
        return {int(r[0]): (float(r[1]), float(r[2]), float(r[3])) for r in reader if r}


def rel_change(old: float, new: float) -> float:
    if old == new:
        return 0.0
    if old == 0:
        return math.inf
    return abs(new - old) / abs(old)


def compare(stored: tuple[float, float, float], new: tuple[float, float, float]) -> dict[str, float]:
    return {f: rel_change(o, n) for f, o, n in zip(VALUE_FIELDS, stored, new) if o != n}


def summarize_file(path: Path, res: Result) -> None:
    stored = read_stored(path)
    res.total_rows = len(stored)
    if not stored:
        return
    res.first_ts, res.last_ts = min(stored), max(stored)
    days = {ts // DAY_MS for ts in stored}
    res.missing_days = [d * DAY_MS for d in range(min(days), max(days) + 1) if d not in days]


def fetch_market_chart(
    out_path: Path = DEFAULT_OUT,
    days: int = MAX_DAYS,
    session: requests.Session | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], int] = now_ms,
) -> Result:
    """One request, then append the new complete-day rows to out_path. Returns a Result."""
    if not 1 <= days <= MAX_DAYS:
        raise ValueError(f"--days must be between 1 and {MAX_DAYS} (the free tier refuses older data)")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    session = session or requests.Session()

    repair_csv(out_path, COLUMNS)  # drop any partial last line left by a crash; refuses a wrong header
    stored = read_stored(out_path)

    params = {"vs_currency": VS_CURRENCY, "days": days, "interval": "daily"}
    payload = get_with_retry(
        session, params, sleep=sleep, max_retries=MAX_RETRIES, backoff_base=BACKOFF_BASE,
        path=PATH, base_url=BASE_URL, fatal_status=FATAL_STATUS,
    )
    fetched_at = clock()  # when the response arrived
    points = parse_market_chart(payload)
    today = fetched_at // DAY_MS

    res = Result()
    last_stored = max(stored) if stored else None
    new_rows = []
    for ts, price, mcap, vol in points:
        if ts // DAY_MS >= today:
            res.skipped_current_day += 1  # live partial day: not a complete past day
            continue
        if ts in stored:
            res.compared += 1
            changes = compare(stored[ts], (price, mcap, vol))
            if changes:
                res.revisions.append(Revision(ts, changes))
            continue  # never overwrite
        if last_stored is not None and ts < last_stored:
            res.out_of_order += 1
        new_rows.append((ts, price, mcap, vol))

    need_header = not out_path.exists() or out_path.stat().st_size == 0
    if new_rows or need_header:
        with out_path.open("a", newline="") as f:
            writer = csv.writer(f)
            if need_header:
                writer.writerow(COLUMNS)
            for ts, price, mcap, vol in new_rows:
                writer.writerow([ts, price, mcap, vol, fetched_at])
            f.flush()
    res.added = len(new_rows)
    summarize_file(out_path, res)
    if res.revisions:
        log_revisions(out_path, res, fetched_at)
    return res


def revision_log_path(out_path: Path) -> Path:
    return out_path.with_name(out_path.stem + "_revisions.log")


def revision_lines(res: Result) -> list[str]:
    """Plain-text revision report: count, largest relative change per field, up to 10 changed days."""
    lines = [f"revisions: {len(res.revisions)} of {res.compared} already-stored days changed"]
    if not res.revisions:
        return lines
    for f in VALUE_FIELDS:
        biggest = max((r.changes.get(f, 0.0) for r in res.revisions), default=0.0)
        lines.append(f"  largest relative change in {f}: {biggest:.6g}")
    ranked = sorted(res.revisions, key=lambda r: max(r.changes.values()), reverse=True)
    lines.append(f"  changed days (largest first, up to {MAX_LISTED_REVISIONS}):")
    for r in ranked[:MAX_LISTED_REVISIONS]:
        parts = ", ".join(f"{k} {v:.6g}" for k, v in r.changes.items())
        lines.append(f"    {utc_date(r.timestamp_ms)} ({r.timestamp_ms}): {parts}")
    return lines


def log_revisions(out_path: Path, res: Result, fetched_at: int) -> None:
    """Log the revision report and append it to <out>_revisions.log. The CSV itself is never touched."""
    lines = revision_lines(res)
    for line in lines:
        log.warning(line)
    stamp = datetime.fromtimestamp(fetched_at / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with revision_log_path(out_path).open("a", encoding="utf-8") as f:
        f.write(f"{stamp} UTC fetched_at_ms={fetched_at}\n" + "\n".join(lines) + "\n")


def summary_lines(res: Result, out_path: Path) -> list[str]:
    lines = [f"Rows added: {res.added} (skipped {res.skipped_current_day} point(s) on the current UTC day)"]
    if res.first_ts is not None:
        lines.append(f"Stored dates: {utc_date(res.first_ts)} to {utc_date(res.last_ts)}")
    else:
        lines.append("Stored dates: none")
    lines.append(f"Total rows: {res.total_rows} in {out_path}")
    miss = [utc_date(m) for m in res.missing_days]
    lines.append(f"Days missing inside the range: {len(miss)}" + (f" ({', '.join(miss[:10])})" if miss else ""))
    if res.out_of_order:
        lines.append(f"Note: {res.out_of_order} new row(s) are older than the last stored row (a gap filled late); "
                     "sort by timestamp_ms when reading.")
    lines += revision_lines(res)
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch CoinGecko TAC daily market chart (public, no key).")
    parser.add_argument("--days", type=int, default=MAX_DAYS, help=f"days back, 1-{MAX_DAYS} (default %(default)s)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output CSV path (default %(default)s)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        res = fetch_market_chart(Path(args.out), days=args.days)
    except (RuntimeError, ValueError, requests.RequestException) as exc:
        print(f"ERROR: {exc}")
        return 1
    print("\n".join(summary_lines(res, Path(args.out))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
