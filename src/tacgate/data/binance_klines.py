"""Fetch raw 1-minute klines for the TACUSDT perpetual from Binance USD-M futures.

Read-only public endpoint (no API key). Raw data only: timestamps stay as UTC
milliseconds, no cleaning, no gap filling.

Run: python -m tacgate.data.binance_klines [--start YYYY-MM-DD] [--end YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import csv
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests

BASE_URL = "https://fapi.binance.com"
KLINES_PATH = "/fapi/v1/klines"
SYMBOL = "TACUSDT"
INTERVAL = "1m"
INTERVAL_MS = 60_000
MAX_LIMIT = 1500  # maximum accepted by /fapi/v1/klines (1501 is rejected)
DEFAULT_START = "2025-07-15"
REQUEST_SLEEP = 0.5  # seconds between requests (limit=1500 costs more weight)
MAX_RETRIES = 6
BACKOFF_BASE = 1.0  # seconds; doubles each retry
RETRY_STATUS = {429, 500, 502, 503, 504}  # 418 (IP ban) is deliberately NOT retried
TIMEOUT = 30

COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trades",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore",
]

DEFAULT_OUT = Path("data/raw/binance_TACUSDT_1m.csv")

log = logging.getLogger(__name__)


def parse_utc_ms(text: str) -> int:
    """Parse 'YYYY-MM-DD' or ISO datetime (assumed UTC if naive) to epoch ms."""
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def now_ms() -> int:
    return int(time.time() * 1000)


def get_with_retry(
    session: requests.Session,
    params: dict,
    sleep: Callable[[float], None] = time.sleep,
    max_retries: int = MAX_RETRIES,
    backoff_base: float = BACKOFF_BASE,
) -> list:
    """GET klines with exponential backoff on network errors, 429/418 and 5xx."""
    url = BASE_URL + KLINES_PATH
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        wait = backoff_base * (2**attempt)
        try:
            resp = session.get(url, params=params, timeout=TIMEOUT)
        except requests.RequestException as exc:
            last_err = exc
        else:
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 418:
                retry_after = resp.headers.get("Retry-After")
                detail = f" Retry-After: {retry_after}." if retry_after else ""
                raise RuntimeError(
                    "HTTP 418: this IP has been banned by Binance for sending too many "
                    f"requests after rate limiting. Stop and wait; do not retry.{detail}"
                )
            if resp.status_code not in RETRY_STATUS:
                resp.raise_for_status()
                raise RuntimeError(f"Unexpected HTTP {resp.status_code}")
            last_err = RuntimeError(f"HTTP {resp.status_code}")
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    wait = max(wait, float(retry_after))
                except ValueError:
                    pass
        if attempt < max_retries:
            log.warning("Request failed (%s); retry %d in %.1fs", last_err, attempt + 1, wait)
            sleep(wait)
    raise RuntimeError(f"Giving up after {max_retries} retries: {last_err}")


def _complete_lines(data: bytes) -> list[tuple[int, int]]:
    """(start, end) byte offsets of each newline-terminated line in data."""
    spans, pos = [], 0
    while True:
        nl = data.find(b"\n", pos)
        if nl == -1:
            return spans
        spans.append((pos, nl + 1))
        pos = nl + 1


def _row(data: bytes, span: tuple[int, int]) -> list[str]:
    return next(csv.reader([data[span[0] : span[1]].decode("utf-8", errors="replace")]), [])


def repair_csv(path: Path) -> bool:
    """Truncate a partial trailing line (crash mid-write). Returns True if repaired.

    A line is kept only if it ends with a newline and has exactly len(COLUMNS)
    columns. The header must be complete and correct, otherwise we refuse.
    """
    path = Path(path)
    if not path.exists():
        return False
    data = path.read_bytes()
    spans = _complete_lines(data)
    if spans:
        if _row(data, spans[0]) != COLUMNS:
            raise ValueError(f"{path} has an unexpected header; refusing to resume")
    keep = 0
    for i, span in enumerate(spans):
        if i == 0 or len(_row(data, span)) == len(COLUMNS):
            keep = span[1]
        else:
            break  # first bad line: drop it and everything after
    if keep == len(data):
        return False
    with path.open("r+b") as f:
        f.truncate(keep)
    log.warning(
        "Partial/corrupt tail in %s: truncated %d bytes back to last complete line",
        path,
        len(data) - keep,
    )
    return True


def last_saved_open_time(path: Path) -> int | None:
    """open_time of the last COMPLETE row (newline-terminated, right column count).

    Never returns a value from a partial row. Does not modify the file.
    """
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return None
    data = path.read_bytes()
    last = None
    for i, span in enumerate(_complete_lines(data)):
        if i == 0:
            continue  # header
        row = _row(data, span)
        if len(row) != len(COLUMNS):
            break
        last = row[0]
    return int(last) if last is not None else None


def fetch_klines(
    out_path: Path = DEFAULT_OUT,
    start_ms: int | None = None,
    end_ms: int | None = None,
    session: requests.Session | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], int] = now_ms,
    limit: int = MAX_LIMIT,
) -> int:
    """Download klines into out_path, resuming if it exists. Returns rows written.

    Only fully closed candles are saved (close_time < now), so a partial
    in-progress candle is never stored. Rows are appended page by page.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    session = session or requests.Session()
    start_ms = parse_utc_ms(DEFAULT_START) if start_ms is None else start_ms
    end_ms = clock() if end_ms is None else end_ms

    repair_csv(out_path)  # drop any partial last line left by a crash
    last = last_saved_open_time(out_path)
    cursor = start_ms if last is None else max(start_ms, last + INTERVAL_MS)
    last_written = last if last is not None else -1
    need_header = not out_path.exists() or out_path.stat().st_size == 0
    written = 0

    with out_path.open("a", newline="") as f:
        writer = csv.writer(f)
        if need_header:
            writer.writerow(COLUMNS)
        while cursor <= end_ms:
            params = {
                "symbol": SYMBOL,
                "interval": INTERVAL,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": limit,
            }
            page = get_with_retry(session, params, sleep=sleep)
            if not page:
                break
            now = clock()
            rows = [
                r
                for r in page
                if int(r[0]) > last_written and int(r[6]) < now and int(r[0]) <= end_ms
            ]
            for r in rows:
                writer.writerow(r)
            f.flush()
            if rows:
                last_written = int(rows[-1][0])
                written += len(rows)
            page_last = int(page[-1][0])
            if page_last < cursor:  # no forward progress; avoid infinite loop
                break
            cursor = page_last + INTERVAL_MS
            log.info("Saved through %d (%d rows total this run)", page_last, written)
            sleep(REQUEST_SLEEP)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch Binance TACUSDT 1m klines (public, read-only).")
    parser.add_argument("--start", default=DEFAULT_START, help="UTC start, YYYY-MM-DD or ISO (default %(default)s)")
    parser.add_argument("--end", default=None, help="UTC end, YYYY-MM-DD or ISO (default: now)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output CSV path (default %(default)s)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    start_ms = parse_utc_ms(args.start)
    end_ms = parse_utc_ms(args.end) if args.end else None
    n = fetch_klines(Path(args.out), start_ms=start_ms, end_ms=end_ms)
    print(f"Wrote {n} new rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
