"""Fetch raw funding-rate history for the TACUSDT perpetual from Binance USD-M futures.

Read-only public endpoint GET /fapi/v1/fundingRate (no API key). Raw data only:
fields are saved exactly as the API returns them, fundingTime stays as UTC
milliseconds, no cleaning. The funding interval is NOT assumed to be fixed (it
can change per symbol), so nothing here depends on a fixed spacing.

Run: python -m tacgate.data.binance_funding [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--out PATH]
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
    DEFAULT_START,
    get_with_retry,
    last_saved_open_time,
    now_ms,
    parse_utc_ms,
    repair_csv,
)

FUNDING_PATH = "/fapi/v1/fundingRate"
SYMBOL = "TACUSDT"
MAX_LIMIT = 1000  # documented maximum (default 100)
# fundingRate shares a 500 requests / 5 min / IP limit with /fapi/v1/fundingInfo,
# so stay at or below 1 request per second.
REQUEST_SLEEP = 1.0

# Exact fields the API returns, in the documented order.
FUNDING_COLUMNS = ["symbol", "fundingTime", "fundingRate", "markPrice", "rateType"]
TIME_INDEX = FUNDING_COLUMNS.index("fundingTime")

DEFAULT_OUT = Path("data/raw/binance_TACUSDT_funding.csv")

log = logging.getLogger(__name__)


def fetch_funding(
    out_path: Path = DEFAULT_OUT,
    start_ms: int | None = None,
    end_ms: int | None = None,
    session: requests.Session | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], int] = now_ms,
    limit: int = MAX_LIMIT,
) -> int:
    """Download funding history into out_path, resuming if it exists. Returns rows written.

    Pages forward: startTime is inclusive, results are ascending, so the cursor
    moves to last fundingTime + 1 ms. A short page is NOT treated as the end;
    only an empty page (or passing end_ms) stops the loop.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    session = session or requests.Session()
    start_ms = parse_utc_ms(DEFAULT_START) if start_ms is None else start_ms
    end_ms = clock() if end_ms is None else end_ms

    repair_csv(out_path, FUNDING_COLUMNS)  # drop any partial last line left by a crash
    last = last_saved_open_time(out_path, FUNDING_COLUMNS, TIME_INDEX)
    cursor = start_ms if last is None else max(start_ms, last + 1)
    last_written = last if last is not None else -1
    need_header = not out_path.exists() or out_path.stat().st_size == 0
    written = 0

    with out_path.open("a", newline="") as f:
        writer = csv.writer(f)
        if need_header:
            writer.writerow(FUNDING_COLUMNS)
        while cursor <= end_ms:
            params = {
                "symbol": SYMBOL,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": limit,
            }
            page = get_with_retry(session, params, sleep=sleep, path=FUNDING_PATH)
            if not page:
                break
            for rec in page:
                if set(rec) != set(FUNDING_COLUMNS):
                    raise ValueError(
                        f"Unexpected funding fields {sorted(rec)}; expected {FUNDING_COLUMNS}. "
                        "Refusing to save a changed layout."
                    )
            rows = [r for r in page if int(r["fundingTime"]) > last_written]
            for r in rows:
                writer.writerow([r[c] for c in FUNDING_COLUMNS])
            f.flush()
            if rows:
                last_written = int(rows[-1]["fundingTime"])
                written += len(rows)
            page_last = int(page[-1]["fundingTime"])
            if page_last < cursor:  # no forward progress; avoid infinite loop
                break
            cursor = page_last + 1
            log.info("Saved through %d (%d rows total this run)", page_last, written)
            sleep(REQUEST_SLEEP)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch Binance TACUSDT funding history (public, read-only).")
    parser.add_argument("--start", default=DEFAULT_START, help="UTC start, YYYY-MM-DD or ISO (default %(default)s)")
    parser.add_argument("--end", default=None, help="UTC end, YYYY-MM-DD or ISO (default: now)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output CSV path (default %(default)s)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    start_ms = parse_utc_ms(args.start)
    end_ms = parse_utc_ms(args.end) if args.end else None
    n = fetch_funding(Path(args.out), start_ms=start_ms, end_ms=end_ms)
    print(f"Wrote {n} new rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
