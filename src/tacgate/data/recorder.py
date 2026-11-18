"""Forward recorder for TACUSDT data that Binance only keeps for about 30 days.

Public read-only endpoints, no API key. Raw data: every row carries
fetched_at_ms (this machine's UTC clock when the response arrived), so a row can
never be mistaken for data that was known earlier than it really was. Nothing is
ever back-dated, filled, or rewritten.

  python -m tacgate.data.recorder backfill
  python -m tacgate.data.recorder run [--interval 300]

Datasets (5m period, GET https://fapi.binance.com):
  /futures/data/openInterestHist, globalLongShortAccountRatio,
  topLongShortPositionRatio, takerlongshortRatio  -> data/raw/binance_TACUSDT_<name>_5m.csv
  /fapi/v1/premiumIndex + /fapi/v1/depth (limit 100) -> data/raw/binance_TACUSDT_snapshot.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import logging
import signal
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests

from tacgate.data.binance_klines import (
    IPBannedError,
    SYMBOL,
    get_with_retry,
    last_saved_open_time,
    now_ms,
    repair_csv,
)

PERIOD = "5m"
PERIOD_MS = 300_000
HIST_LIMIT = 500  # documented maximum for the /futures/data endpoints (the live API accepts more; not relied on)
RETENTION_DAYS = 30  # docs: "latest 30 days" / "latest 1 month"; live API rejects startTime older than ~31 days
RETENTION_MS = RETENTION_DAYS * 86_400_000
REQUEST_SLEEP = 0.3
CYCLE_OFFSET_MS = 5_000  # run this long after each boundary so the period is closed
MAX_CONSECUTIVE_FAILURES = 10
DEPTH_LIMIT = 100
DEPTH_BANDS_PCT = (0.5, 1.0, 2.0)
SLIPPAGE_NOTIONALS = (1000, 5000)
DEFAULT_DIR = Path("data/raw")

log = logging.getLogger(__name__)


class SchemaError(ValueError):
    """The API returned a different shape than expected. Fail loudly, never guess."""


@dataclass(frozen=True)
class Dataset:
    name: str  # used in the CSV file name
    path: str  # endpoint path
    fields: tuple[str, ...]  # exactly the fields the API returns, in file order

    @property
    def columns(self) -> list[str]:
        return list(self.fields) + ["fetched_at_ms"]

    @property
    def ts_index(self) -> int:
        return self.fields.index("timestamp")

    def csv_path(self, data_dir: Path) -> Path:
        return Path(data_dir) / f"binance_{SYMBOL}_{self.name}_{PERIOD}.csv"


DATASETS = [
    Dataset(
        "open_interest",
        "/futures/data/openInterestHist",
        ("symbol", "sumOpenInterest", "sumOpenInterestValue", "CMCCirculatingSupply", "timestamp"),
    ),
    Dataset(
        "global_long_short",
        "/futures/data/globalLongShortAccountRatio",
        ("symbol", "longShortRatio", "longAccount", "shortAccount", "timestamp"),
    ),
    Dataset(
        "top_position_long_short",
        "/futures/data/topLongShortPositionRatio",
        ("symbol", "longShortRatio", "longAccount", "shortAccount", "timestamp"),
    ),
    Dataset(
        "taker_buy_sell",
        "/futures/data/takerlongshortRatio",
        ("buySellRatio", "buyVol", "sellVol", "timestamp"),
    ),
]

SNAPSHOT_COLUMNS = (
    ["fetched_at_ms", "server_time_ms", "mark", "index", "lastFundingRate", "nextFundingTime",
     "best_bid", "best_ask", "spread_bps"]
    + [f"{side}_depth_usd_{b:g}".replace(".", "p") + "pct" for side in ("bid", "ask") for b in DEPTH_BANDS_PCT]
    + [f"slippage_bps_{side}_{n}" for side in ("buy", "sell") for n in SLIPPAGE_NOTIONALS]
    + ["filled_ok"]
)
PREMIUM_REQUIRED = ("symbol", "markPrice", "indexPrice", "lastFundingRate", "nextFundingTime", "time")
DEPTH_REQUIRED = ("lastUpdateId", "E", "T", "bids", "asks")


def snapshot_path(data_dir: Path) -> Path:
    return Path(data_dir) / f"binance_{SYMBOL}_snapshot.csv"


def errors_log_path(data_dir: Path) -> Path:
    return Path(data_dir) / "recorder_errors.log"


def utc_str(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ---------------------------------------------------------------- logging ---

def log_event(data_dir: Path, kind: str, message: str, clock: Callable[[], int] = now_ms) -> None:
    """Append one line to recorder_errors.log: time | KIND | message."""
    path = errors_log_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"{utc_str(clock())} | {kind} | {message}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()


# -------------------------------------------------------------- CSV append ---

def append_rows(path: Path, columns: list[str], rows: list[list]) -> None:
    """Append rows with ONE write call (header first if the file is new), so a line is never split by us."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    need_header = not path.exists() or path.stat().st_size == 0
    buf = io.StringIO()
    w = csv.writer(buf)
    if need_header:
        w.writerow(columns)
    w.writerows(rows)
    data = buf.getvalue()
    if not data:
        return
    with path.open("a", newline="", encoding="utf-8") as f:
        f.write(data)
        f.flush()


# ------------------------------------------------------- dataset fetching ---

def fetch_dataset_page(session, ds: Dataset, sleep=time.sleep, **extra) -> list[dict]:
    """One request for a history dataset. Validates the shape; returns rows ascending, de-duplicated."""
    params = {"symbol": SYMBOL, "period": PERIOD, "limit": HIST_LIMIT, **extra}
    payload = get_with_retry(session, params, sleep=sleep, path=ds.path)
    if not isinstance(payload, list):
        raise SchemaError(f"{ds.name}: expected a list, got {str(payload)[:200]!r}")
    by_ts: dict[int, dict] = {}
    for rec in payload:
        if not isinstance(rec, dict) or set(rec) != set(ds.fields):
            got = sorted(rec) if isinstance(rec, dict) else repr(rec)[:100]
            raise SchemaError(f"{ds.name}: fields changed. Expected {sorted(ds.fields)}, got {got}. Refusing to save.")
        by_ts[int(rec["timestamp"])] = rec
    return [by_ts[t] for t in sorted(by_ts)]


def _to_row(ds: Dataset, rec: dict, fetched_at_ms: int) -> list:
    return [rec[f] for f in ds.fields] + [fetched_at_ms]


def backfill_dataset(data_dir: Path, ds: Dataset, session, sleep=time.sleep, clock=now_ms) -> int:
    """Fetch everything Binance still holds for ds, appending after the last saved timestamp."""
    path = ds.csv_path(data_dir)
    repair_csv(path, ds.columns)
    last = last_saved_open_time(path, ds.columns, ds.ts_index)
    now = clock()
    start = now - RETENTION_MS
    start -= start % PERIOD_MS
    cursor = start if last is None else max(start, last + PERIOD_MS)
    last_written = last if last is not None else -1
    written = 0
    while cursor <= now:
        end = min(cursor + (HIST_LIMIT - 1) * PERIOD_MS, now)
        # startTime AND endTime are both required: with startTime alone the API returns the latest rows instead
        page = fetch_dataset_page(session, ds, sleep, startTime=cursor, endTime=end)
        fetched = clock()
        recs = [r for r in page if last_written < int(r["timestamp"]) <= now]
        append_rows(path, ds.columns, [_to_row(ds, r, fetched) for r in recs])
        if recs:
            last_written = int(recs[-1]["timestamp"])
            written += len(recs)
        log.info("%s: window %d..%d -> %d new rows", ds.name, cursor, end, len(recs))
        cursor += HIST_LIMIT * PERIOD_MS
        sleep(REQUEST_SLEEP)
    return written


def backfill(data_dir: Path = DEFAULT_DIR, session=None, sleep=time.sleep, clock=now_ms) -> dict[str, int]:
    session = session or requests.Session()
    return {ds.name: backfill_dataset(data_dir, ds, session, sleep, clock) for ds in DATASETS}


# ---------------------------------------------------------------- snapshot ---

def _levels(raw, label: str) -> list[tuple[float, float]]:
    try:
        out = [(float(p), float(q)) for p, q in raw]
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"depth {label}: bad level format ({exc})") from exc
    return [lv for lv in out if lv[1] > 0]


def depth_within(levels: list[tuple[float, float]], limit_price: float, side: str) -> float:
    """USD (price * qty) resting within the band. side 'bid': price >= limit; 'ask': price <= limit."""
    if side == "bid":
        return sum(p * q for p, q in levels if p >= limit_price)
    return sum(p * q for p, q in levels if p <= limit_price)


def slippage_bps(levels: list[tuple[float, float]], notional_usd: float, mid: float, side: str) -> float | None:
    """Walk the book for a market order worth notional_usd; slippage vs mid in bps, or None if the book is too thin.

    buy: walks asks (cheapest first), average price paid vs mid. sell: walks bids (best first),
    average price received vs mid. Positive = worse than mid (includes the half spread).
    """
    ordered = sorted(levels) if side == "buy" else sorted(levels, reverse=True)
    remaining, base = float(notional_usd), 0.0
    for price, qty in ordered:
        level_usd = price * qty
        if level_usd >= remaining:
            base += remaining / price
            remaining = 0.0
            break
        base += qty
        remaining -= level_usd
    if remaining > 1e-9 or base <= 0:
        return None
    avg = notional_usd / base
    return (avg / mid - 1.0) * 1e4 if side == "buy" else (1.0 - avg / mid) * 1e4


def build_snapshot(prem, depth, fetched_at_ms: int) -> list:
    """One snapshot row from a premiumIndex and a depth response (validated)."""
    if not isinstance(prem, dict) or any(k not in prem for k in PREMIUM_REQUIRED):
        raise SchemaError(f"premiumIndex: expected fields {PREMIUM_REQUIRED}, got {str(prem)[:200]!r}")
    if not isinstance(depth, dict) or any(k not in depth for k in DEPTH_REQUIRED):
        raise SchemaError(f"depth: expected fields {DEPTH_REQUIRED}, got {str(depth)[:200]!r}")
    bids, asks = _levels(depth["bids"], "bids"), _levels(depth["asks"], "asks")
    if not bids or not asks:
        raise SchemaError("depth: empty bid or ask side")
    best_bid, best_ask = max(p for p, _ in bids), min(p for p, _ in asks)
    mid = (best_bid + best_ask) / 2
    row = [
        fetched_at_ms, prem["time"], prem["markPrice"], prem["indexPrice"], prem["lastFundingRate"],
        prem["nextFundingTime"], best_bid, best_ask, f"{(best_ask - best_bid) / mid * 1e4:.6f}",
    ]
    for levels, side in ((bids, "bid"), (asks, "ask")):
        for pct in DEPTH_BANDS_PCT:
            edge = mid * (1 - pct / 100) if side == "bid" else mid * (1 + pct / 100)
            row.append(f"{depth_within(levels, edge, side):.4f}")
    filled_ok = 1
    for side, levels in (("buy", asks), ("sell", bids)):
        for n in SLIPPAGE_NOTIONALS:
            s = slippage_bps(levels, n, mid, side)
            if s is None:
                filled_ok = 0
                row.append("")
            else:
                row.append(f"{s:.6f}")
    row.append(filled_ok)
    return row


# --------------------------------------------------------------- run loop ---

def record_latest(data_dir: Path, ds: Dataset, session, sleep, clock) -> int:
    """Append the newest closed period(s). limit=2 so a period that appears a moment late is still caught."""
    path = ds.csv_path(data_dir)
    page = fetch_dataset_page(session, ds, sleep, limit=2)
    fetched = clock()
    last = last_saved_open_time(path, ds.columns, ds.ts_index)
    recs = [r for r in page if int(r["timestamp"]) > (last if last is not None else -1)]
    if last is not None and recs and int(recs[0]["timestamp"]) - last > PERIOD_MS:
        log_event(
            data_dir, "GAP",
            f"{ds.name}: no rows between {utc_str(last)} and {utc_str(int(recs[0]['timestamp']))} (not filled)", clock,
        )
    append_rows(path, ds.columns, [_to_row(ds, r, fetched) for r in recs])
    return len(recs)


def record_snapshot(data_dir: Path, session, sleep, clock) -> None:
    prem = get_with_retry(session, {"symbol": SYMBOL}, sleep=sleep, path="/fapi/v1/premiumIndex")
    sleep(0.2)
    depth = get_with_retry(session, {"symbol": SYMBOL, "limit": DEPTH_LIMIT}, sleep=sleep, path="/fapi/v1/depth")
    fetched = clock()  # after BOTH responses: everything in the row was known by this time
    row = build_snapshot(prem, depth, fetched)
    append_rows(snapshot_path(data_dir), SNAPSHOT_COLUMNS, [row])


def run_cycle(data_dir: Path, session, sleep=time.sleep, clock=now_ms) -> list[str]:
    """One recording cycle. Each task fails on its own; returns error strings (empty = clean cycle).

    An IP ban (418) is not caught here: it propagates so the loop can stop.
    """
    errors: list[str] = []
    for ds in DATASETS:
        try:
            record_latest(data_dir, ds, session, sleep, clock)
        except IPBannedError:
            raise
        except Exception as exc:
            errors.append(f"{ds.name}: {type(exc).__name__}: {exc}")
        sleep(REQUEST_SLEEP)
    try:
        record_snapshot(data_dir, session, sleep, clock)
    except IPBannedError:
        raise
    except Exception as exc:
        errors.append(f"snapshot: {type(exc).__name__}: {exc}")
    for e in errors:
        log_event(data_dir, "ERROR", e, clock)
    return errors


def next_target_ms(now: int, interval_s: int, offset_ms: int = CYCLE_OFFSET_MS) -> int:
    """Next wall-clock boundary of the interval, plus a few seconds so the period is closed."""
    iv = interval_s * 1000
    t = now - now % iv + offset_ms
    return t if t > now else t + iv


def prepare_files(data_dir: Path, interval_s: int, clock=now_ms, say=print) -> None:
    """Repair partial last lines left by a crash and log every gap since the last saved row (never filled)."""
    now = clock()
    for ds in DATASETS:
        path = ds.csv_path(data_dir)
        repair_csv(path, ds.columns)
        last = last_saved_open_time(path, ds.columns, ds.ts_index)
        if last is not None and now - last > 2 * PERIOD_MS:
            msg = f"{ds.name}: last saved period {utc_str(last)}, now {utc_str(now)} ({(now - last) // 60000} min). Gap is NOT filled."
            log_event(data_dir, "GAP", "restart: " + msg, clock)
            say("GAP on restart: " + msg)
    sp = snapshot_path(data_dir)
    repair_csv(sp, SNAPSHOT_COLUMNS)
    last = last_saved_open_time(sp, SNAPSHOT_COLUMNS, 0)
    if last is not None and now - last > 2 * interval_s * 1000:
        msg = f"snapshot: last row {utc_str(last)}, now {utc_str(now)} ({(now - last) // 60000} min). Gap is NOT filled."
        log_event(data_dir, "GAP", "restart: " + msg, clock)
        say("GAP on restart: " + msg)


def run_loop(
    data_dir: Path = DEFAULT_DIR,
    interval_s: int = 300,
    session=None,
    sleep=time.sleep,
    clock=now_ms,
    wait: Callable[[float], bool] | None = None,
    max_cycles: int | None = None,
    say=print,
) -> int:
    """Record forever (or max_cycles). Exit codes: 0 clean stop, 1 stopped on a 418 or repeated failures.

    `wait(seconds)` sleeps and returns True if a stop was requested (Ctrl+C).
    """
    session = session or requests.Session()
    wait = wait or (lambda s: (time.sleep(s), False)[1])
    prepare_files(data_dir, interval_s, clock, say)
    cycles = consecutive = 0
    while True:
        now = clock()
        if wait(max(0.0, (next_target_ms(now, interval_s) - now) / 1000)):
            say("Stopped cleanly.")
            return 0
        try:
            errors = run_cycle(data_dir, session, sleep, clock)
        except IPBannedError as exc:
            msg = f"STOPPED: {exc}"
            log_event(data_dir, "FATAL", msg, clock)
            say(msg)
            return 1
        cycles += 1
        if errors:
            consecutive += 1
            say(f"Cycle {cycles} had {len(errors)} error(s) (see recorder_errors.log); consecutive failed cycles: {consecutive}")
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                msg = f"STOPPED: {consecutive} consecutive failed cycles. Last errors: {errors}"
                log_event(data_dir, "FATAL", msg, clock)
                say(msg)
                return 1
        else:
            consecutive = 0
            say(f"Cycle {cycles} ok at {utc_str(clock())}")
        if max_cycles is not None and cycles >= max_cycles:
            return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Forward recorder for TACUSDT (public Binance futures data).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    bf = sub.add_parser("backfill", help="fetch the ~30 days Binance still holds for the 4 history datasets")
    bf.add_argument("--data-dir", default=str(DEFAULT_DIR))
    rn = sub.add_parser("run", help="record every --interval seconds until stopped")
    rn.add_argument("--interval", type=int, default=300)
    rn.add_argument("--max-cycles", type=int, default=None, help="stop after N cycles (for testing)")
    rn.add_argument("--data-dir", default=str(DEFAULT_DIR))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.cmd == "backfill":
        counts = backfill(Path(args.data_dir))
        for name, n in counts.items():
            print(f"{name}: {n} new rows")
        return 0

    stop = threading.Event()
    def on_sigint(*_):
        if stop.is_set():
            raise KeyboardInterrupt  # second Ctrl+C: stop now (the first one waits for the current cycle)
        stop.set()  # first Ctrl+C: finish the current write, then exit cleanly

    signal.signal(signal.SIGINT, on_sigint)
    return run_loop(Path(args.data_dir), args.interval, wait=stop.wait, max_cycles=args.max_cycles)


if __name__ == "__main__":
    raise SystemExit(main())
