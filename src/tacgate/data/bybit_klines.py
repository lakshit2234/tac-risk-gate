"""Fetch raw 1-minute klines for the TACUSDT linear perpetual from Bybit (public, read-only).

GET https://api.bybit.com/v5/market/kline, no API key. Used only for a
cross-exchange price check against the Binance data. Raw data only: no
cleaning, no gap filling. Only fully closed candles are saved (no look-ahead).

Bybit returns each page NEWEST FIRST as string lists
[startTime, open, high, low, close, volume, turnover]; rows are sorted
ascending and de-duplicated by startTime before saving. The close of a candle
that is still open is just the last traded price, so open candles are dropped.

Run: python -m tacgate.data.bybit_klines [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--out PATH]
Default start: the first kline Bybit has for TACUSDT (detected, not assumed).
"""
from __future__ import annotations

import argparse
import csv
import logging
import time
from pathlib import Path
from typing import Callable

import requests

from tacgate.data.binance_klines import (
    INTERVAL_MS,
    get_with_retry,
    last_saved_open_time,
    now_ms,
    parse_utc_ms,
    repair_csv,
)

BASE_URL = "https://api.bybit.com"
KLINE_PATH = "/v5/market/kline"
INSTRUMENTS_PATH = "/v5/market/instruments-info"
CATEGORY = "linear"
SYMBOL = "TACUSDT"
INTERVAL = "1"
MAX_LIMIT = 1000  # documented range 1..1000 (default 200)
REQUEST_SLEEP = 0.5
DETECT_MAX_WINDOWS = 5

COLUMNS = ["open_time", "open", "high", "low", "close", "volume", "turnover"]
DEFAULT_OUT = Path("data/raw/bybit_TACUSDT_1m.csv")

FATAL_STATUS = {
    403: (
        "HTTP 403 from Bybit: the request was blocked (region/IP block, or 'access too "
        "frequent' from too many requests). Do not retry. Stop all sessions and wait at "
        "least 10 minutes; if it persists, this IP or region may be blocked."
    )
}

log = logging.getLogger(__name__)


def _get(session, path, params, sleep):
    return get_with_retry(
        session, params, sleep=sleep, path=path, base_url=BASE_URL, fatal_status=FATAL_STATUS
    )


def _check_envelope(payload) -> dict:
    """Fail loudly on a non-zero retCode or an unexpected response shape."""
    if not isinstance(payload, dict) or "retCode" not in payload:
        raise ValueError(f"Bybit response shape changed: no retCode in {str(payload)[:200]!r}")
    if payload["retCode"] != 0:
        raise RuntimeError(f"Bybit error retCode {payload['retCode']}: {payload.get('retMsg')}")
    result = payload.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("list"), list):
        raise ValueError("Bybit response shape changed: expected result.list")
    return result


def parse_kline_response(payload) -> list[list[str]]:
    """Validate a kline response and return rows sorted ascending, de-duplicated by startTime."""
    result = _check_envelope(payload)
    if result.get("symbol") != SYMBOL or result.get("category") != CATEGORY:
        raise ValueError(
            f"Bybit response shape changed: got symbol={result.get('symbol')!r} "
            f"category={result.get('category')!r}, expected {SYMBOL}/{CATEGORY}"
        )
    by_time: dict[int, list[str]] = {}
    for item in result["list"]:
        if not (isinstance(item, list) and len(item) == len(COLUMNS) and all(isinstance(x, str) for x in item)):
            raise ValueError(f"Bybit response shape changed: bad kline entry {item!r}")
        by_time[int(item[0])] = item
    return [by_time[t] for t in sorted(by_time)]


def fetch_window(session, start_ms: int, end_ms: int, sleep=time.sleep, limit: int = MAX_LIMIT) -> list[list[str]]:
    params = {
        "category": CATEGORY,
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "start": start_ms,
        "end": end_ms,
        "limit": limit,
    }
    return parse_kline_response(_get(session, KLINE_PATH, params, sleep))


def detect_first_kline(session, sleep=time.sleep) -> int:
    """Find the first 1m kline Bybit has for TACUSDT, using the instrument's launchTime as a hint."""
    payload = _get(
        session, INSTRUMENTS_PATH, {"category": CATEGORY, "symbol": SYMBOL}, sleep
    )
    result = _check_envelope(payload)
    try:
        launch = int(result["list"][0]["launchTime"])
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Bybit response shape changed: no launchTime ({exc!r})") from exc
    cursor = launch - launch % INTERVAL_MS - 60 * INTERVAL_MS  # one hour before launch
    for _ in range(DETECT_MAX_WINDOWS):
        rows = fetch_window(session, cursor, cursor + (MAX_LIMIT - 1) * INTERVAL_MS, sleep)
        if rows:
            return int(rows[0][0])
        sleep(REQUEST_SLEEP)
        cursor += MAX_LIMIT * INTERVAL_MS
    raise RuntimeError("Could not detect the first kline near launchTime; pass --start explicitly")


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

    Walks forward in fixed windows of `limit` one-minute slots, so an empty or
    short page never ends the download early. Only closed candles are saved.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    session = session or requests.Session()

    repair_csv(out_path, COLUMNS)  # drop any partial last line left by a crash
    last = last_saved_open_time(out_path, COLUMNS, 0)
    if start_ms is None:
        start_ms = (last + INTERVAL_MS) if last is not None else detect_first_kline(session, sleep)
        if last is None:
            sleep(REQUEST_SLEEP)
    start_ms -= start_ms % INTERVAL_MS
    end_ms = clock() if end_ms is None else end_ms
    cursor = start_ms if last is None else max(start_ms, last + INTERVAL_MS)
    last_written = last if last is not None else -1
    need_header = not out_path.exists() or out_path.stat().st_size == 0
    written = 0

    with out_path.open("a", newline="") as f:
        writer = csv.writer(f)
        if need_header:
            writer.writerow(COLUMNS)
        while cursor <= end_ms and cursor + INTERVAL_MS <= clock():
            window_end = min(cursor + (limit - 1) * INTERVAL_MS, end_ms)
            page = fetch_window(session, cursor, window_end, sleep, limit)
            now = clock()
            rows = [
                r
                for r in page
                if int(r[0]) > last_written and int(r[0]) + INTERVAL_MS <= now and int(r[0]) <= end_ms
            ]
            for r in rows:
                writer.writerow(r)
            f.flush()
            if rows:
                last_written = int(rows[-1][0])
                written += len(rows)
            log.info("Window %d..%d: %d rows (%d total this run)", cursor, window_end, len(rows), written)
            cursor += limit * INTERVAL_MS
            sleep(REQUEST_SLEEP)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch Bybit TACUSDT 1m klines (public, read-only).")
    parser.add_argument("--start", default=None, help="UTC start, YYYY-MM-DD or ISO (default: first Bybit kline, detected)")
    parser.add_argument("--end", default=None, help="UTC end, YYYY-MM-DD or ISO (default: now)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output CSV path (default %(default)s)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    start_ms = parse_utc_ms(args.start) if args.start else None
    end_ms = parse_utc_ms(args.end) if args.end else None
    n = fetch_klines(Path(args.out), start_ms=start_ms, end_ms=end_ms)
    print(f"Wrote {n} new rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
