"""Fetch TAC chain TVL and TAC coin price history from DeFiLlama's free public API (no key).

Two subcommands, both verified live on 2026-11-20 (see docs/phase0_sources.md):

  tvl    GET https://api.llama.fi/v2/historicalChainTvl/TAC
         -> [{"date": <unix SECONDS>, "tvl": <number>}, ...], one point per UTC midnight.
  price  GET https://coins.llama.fi/chart/coingecko:tac?start=<unix s>&span=<n>&period=1d
         -> {"coins": {"coingecko:tac": {"symbol": "TAC", "confidence": 0.99,
                                         "prices": [{"timestamp": <unix SECONDS>, "price": <number>}, ...]}}}
         Price timestamps are NOT midnight aligned: they jitter within seconds of a UTC midnight
         (for example 23:59:42 on one day, 00:00:23 on another). They are stored exactly as returned.

Same rules as the CoinGecko fetcher (docs/phase0_sources.md, "Decisions (approved)"):
- RAW fields only, plus fetched_at_ms (local UTC clock when the response arrived): no look-ahead, no
  derived columns. timestamp_ms is the API's seconds value x 1000 (the API uses seconds, our files use ms).
- Append-only. Existing rows are never rewritten or deleted. Dedupe by timestamp_ms.
- Points on the current UTC day are skipped (the newest point is a live, still-changing value).
- Revision check: stored days are only COMPARED with the new value, never overwritten; the number of
  changed days, the largest relative change and up to 10 changed days are printed, logged and appended
  to <out>_revisions.log.
- Missing days are NOT filled. They are counted and listed as gaps.

Run: python -m tacgate.data.defillama tvl   [--out PATH]
     python -m tacgate.data.defillama price [--out PATH]
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
from tacgate.data.coingecko_market_chart import DAY_MS, MAX_LISTED_REVISIONS, Revision, rel_change, utc_date

CHAIN = "TAC"
COIN_ID = "coingecko:tac"
TVL_BASE_URL = "https://api.llama.fi"
TVL_PATH = f"/v2/historicalChainTvl/{CHAIN}"
PRICE_BASE_URL = "https://coins.llama.fi"
PRICE_PATH = f"/chart/{COIN_ID}"
# 2025-07-15 00:00:00 UTC, the day the token launched. The API's first point is on 2025-07-16, so this
# start covers "the first available date"; anything earlier returns nothing.
PRICE_START_S = 1_752_537_600
MAX_RETRIES = 5
BACKOFF_BASE = 2.0  # 2, 4, 8, 16, 32 s unless Retry-After asks for more (no limits are documented)
SECONDS_LIMIT = 10**11  # a seconds timestamp is below this (year 5138); a milliseconds one is not
MAX_LISTED_GAPS = 30

FATAL_STATUS = {
    401: "HTTP 401 from DeFiLlama: a key is now required for this endpoint. Not retried.",
    402: "HTTP 402 from DeFiLlama: this endpoint is on the paid plan. Not retried.",
    403: "HTTP 403 from DeFiLlama: access denied. Not retried.",
}

log = logging.getLogger(__name__)


class ShapeError(ValueError):
    """The response is not the layout verified live. Fail loudly, never guess."""


def _number(v, where: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ShapeError(f"Unexpected value {v!r} in {where}; expected a finite number.")
    return float(v)


def _seconds_to_ms(v, where: str) -> int:
    """The API's timestamps are unix SECONDS; our files store milliseconds (x 1000)."""
    s = _number(v, where)
    if not s.is_integer() or s <= 0:
        raise ShapeError(f"{where}: {v!r} is not a positive whole number of seconds")
    if s >= SECONDS_LIMIT:
        raise ShapeError(f"{where}: {v!r} looks like milliseconds, expected seconds. The API changed units?")
    return int(s) * 1000


def _check_order(stamps: list[int], where: str) -> None:
    if len(set(stamps)) != len(stamps):
        raise ShapeError(f"{where}: duplicate timestamps in one response")
    if stamps != sorted(stamps):
        raise ShapeError(f"{where}: timestamps are not ascending")


# A parsed point: (timestamp_ms, {column name: value}) for every column except timestamp_ms/fetched_at_ms.
Point = tuple[int, dict]


def parse_tvl(payload) -> list[Point]:
    if not isinstance(payload, list) or not payload:
        raise ShapeError(f"Expected a non-empty list, got {str(payload)[:200]}")
    out: list[Point] = []
    for item in payload:
        if not isinstance(item, dict) or set(item) != {"date", "tvl"}:
            raise ShapeError(f"Unexpected TVL point {str(item)[:150]}; expected exactly keys date and tvl.")
        out.append((_seconds_to_ms(item["date"], "tvl date"), {"tvl": _number(item["tvl"], "tvl")}))
    _check_order([p[0] for p in out], "tvl")
    return out


def parse_price(payload) -> list[Point]:
    if not isinstance(payload, dict) or set(payload) != {"coins"}:
        raise ShapeError(f"Expected an object with only the key 'coins', got {str(payload)[:200]}")
    coins = payload["coins"]
    if not isinstance(coins, dict) or set(coins) != {COIN_ID}:
        raise ShapeError(f"Expected exactly the coin {COIN_ID}, got {str(coins)[:200]}")
    coin = coins[COIN_ID]
    if not isinstance(coin, dict) or not {"symbol", "prices"} <= set(coin) <= {"symbol", "prices", "confidence"}:
        raise ShapeError(f"Unexpected coin object keys {sorted(coin) if isinstance(coin, dict) else coin!r}; "
                         "expected symbol, prices and optionally confidence.")
    if coin["symbol"] != "TAC":
        raise ShapeError(f"Unexpected symbol {coin['symbol']!r}; expected 'TAC'.")
    # confidence is one value for the whole chart (not per point); stored on every row, blank if absent.
    confidence = _number(coin["confidence"], "confidence") if "confidence" in coin else ""
    prices = coin["prices"]
    if not isinstance(prices, list) or not prices:
        raise ShapeError("prices must be a non-empty list")
    out: list[Point] = []
    for item in prices:
        if not isinstance(item, dict) or set(item) != {"timestamp", "price"}:
            raise ShapeError(f"Unexpected price point {str(item)[:150]}; expected exactly keys timestamp and price.")
        out.append((_seconds_to_ms(item["timestamp"], "price timestamp"),
                    {"price": _number(item["price"], "price"), "confidence": confidence}))
    _check_order([p[0] for p in out], "price")
    return out


@dataclass(frozen=True)
class Spec:
    name: str
    base_url: str
    path: str
    columns: list[str]  # first is timestamp_ms, last is fetched_at_ms
    value_fields: tuple[str, ...]  # compared in the revision check
    default_out: Path
    parse: Callable[[object], list[Point]]
    build_params: Callable[[int], dict]  # fetched-at clock (ms) is not known yet, so uses a pre-request clock

    @property
    def data_columns(self) -> list[str]:
        return self.columns[1:-1]


def _price_params(now: int) -> dict:
    span = (now // 1000 - PRICE_START_S) // 86_400 + 2  # one point per day from the start through today
    return {"start": PRICE_START_S, "span": span, "period": "1d"}


TVL = Spec("tvl", TVL_BASE_URL, TVL_PATH, ["timestamp_ms", "tvl", "fetched_at_ms"], ("tvl",),
           Path("data/raw/defillama_TAC_chain_tvl_daily.csv"), parse_tvl, lambda now: {})
PRICE = Spec("price", PRICE_BASE_URL, PRICE_PATH, ["timestamp_ms", "price", "confidence", "fetched_at_ms"],
             ("price",), Path("data/raw/defillama_TAC_price_daily.csv"), parse_price, _price_params)
SPECS = {"tvl": TVL, "price": PRICE}


@dataclass
class Result:
    spec: str = ""
    added: int = 0
    skipped_current_day: int = 0
    revisions: list[Revision] = field(default_factory=list)
    compared: int = 0
    out_of_order: int = 0
    total_rows: int = 0
    first_ts: int | None = None
    last_ts: int | None = None
    missing_days: list[int] = field(default_factory=list)  # nominal UTC day starts (ms) with no point


def nominal_day(ts_ms: int) -> int:
    """UTC day number of the nearest midnight. Price timestamps sit a few seconds either side of midnight,
    so floor() would put 23:59:42 on one day and 00:00:23 on the next and invent false gaps."""
    return round(ts_ms / DAY_MS)


def read_stored(path: Path, spec: Spec) -> dict[int, tuple]:
    """Stored rows by timestamp_ms -> tuple of the spec's value_fields (read-only; repair_csv first)."""
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return {}
    idx = [spec.columns.index(f) for f in spec.value_fields]
    with path.open(newline="") as f:
        reader = csv.reader(f)
        next(reader, None)  # header (checked by repair_csv)
        return {int(r[0]): tuple(float(r[i]) for i in idx) for r in reader if r}


def gaps(missing_days: list[int]) -> list[tuple[int, int]]:
    """Group missing nominal days into consecutive runs: [(first_day_ms, last_day_ms), ...]."""
    runs: list[tuple[int, int]] = []
    for d in missing_days:
        if runs and d - runs[-1][1] == DAY_MS:
            runs[-1] = (runs[-1][0], d)
        else:
            runs.append((d, d))
    return runs


def summarize_file(path: Path, spec: Spec, res: Result) -> None:
    stored = read_stored(path, spec)
    res.total_rows = len(stored)
    if not stored:
        return
    res.first_ts, res.last_ts = min(stored), max(stored)
    days = {nominal_day(ts) for ts in stored}
    res.missing_days = [d * DAY_MS for d in range(min(days), max(days) + 1) if d not in days]


def fetch(
    spec: Spec,
    out_path: Path | None = None,
    session: requests.Session | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], int] = now_ms,
) -> Result:
    """One request, then append the new complete-day rows to out_path. Returns a Result."""
    out_path = Path(out_path or spec.default_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    session = session or requests.Session()

    repair_csv(out_path, spec.columns)  # drop a partial last line from a crash; refuses a wrong header
    stored = read_stored(out_path, spec)

    payload = get_with_retry(
        session, spec.build_params(clock()), sleep=sleep, max_retries=MAX_RETRIES, backoff_base=BACKOFF_BASE,
        path=spec.path, base_url=spec.base_url, fatal_status=FATAL_STATUS,
    )
    fetched_at = clock()  # when the response arrived
    points = spec.parse(payload)
    today = fetched_at // DAY_MS

    res = Result(spec=spec.name)
    last_stored = max(stored) if stored else None
    new_rows = []
    for ts, values in points:
        if ts // DAY_MS >= today:
            res.skipped_current_day += 1  # still-changing value for the current UTC day
            continue
        if ts in stored:
            res.compared += 1
            changes = {
                f: rel_change(old, values[f])
                for f, old in zip(spec.value_fields, stored[ts])
                if old != values[f]
            }
            if changes:
                res.revisions.append(Revision(ts, changes))
            continue  # never overwrite
        if last_stored is not None and ts < last_stored:
            res.out_of_order += 1
        new_rows.append([ts] + [values[c] for c in spec.data_columns] + [fetched_at])

    need_header = not out_path.exists() or out_path.stat().st_size == 0
    if new_rows or need_header:
        with out_path.open("a", newline="") as f:
            writer = csv.writer(f)
            if need_header:
                writer.writerow(spec.columns)
            writer.writerows(new_rows)
            f.flush()
    res.added = len(new_rows)
    summarize_file(out_path, spec, res)
    if res.revisions:
        log_revisions(out_path, spec, res, fetched_at)
    return res


def revision_log_path(out_path: Path) -> Path:
    return out_path.with_name(out_path.stem + "_revisions.log")


def revision_lines(spec: Spec, res: Result) -> list[str]:
    lines = [f"revisions: {len(res.revisions)} of {res.compared} already-stored days changed"]
    if not res.revisions:
        return lines
    for f in spec.value_fields:
        biggest = max((r.changes.get(f, 0.0) for r in res.revisions), default=0.0)
        lines.append(f"  largest relative change in {f}: {biggest:.6g}")
    ranked = sorted(res.revisions, key=lambda r: max(r.changes.values()), reverse=True)
    lines.append(f"  changed days (largest first, up to {MAX_LISTED_REVISIONS}):")
    for r in ranked[:MAX_LISTED_REVISIONS]:
        parts = ", ".join(f"{k} {v:.6g}" for k, v in r.changes.items())
        lines.append(f"    {utc_date(r.timestamp_ms)} ({r.timestamp_ms}): {parts}")
    return lines


def log_revisions(out_path: Path, spec: Spec, res: Result, fetched_at: int) -> None:
    """Log the revision report and append it to <out>_revisions.log. The CSV itself is never touched."""
    lines = revision_lines(spec, res)
    for line in lines:
        log.warning(line)
    stamp = datetime.fromtimestamp(fetched_at / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with revision_log_path(out_path).open("a", encoding="utf-8") as f:
        f.write(f"{stamp} UTC fetched_at_ms={fetched_at}\n" + "\n".join(lines) + "\n")


def gap_text(missing_days: list[int]) -> str:
    runs = gaps(missing_days)
    shown = [utc_date(a) if a == b else f"{utc_date(a)}..{utc_date(b)}" for a, b in runs[:MAX_LISTED_GAPS]]
    more = f", and {len(runs) - MAX_LISTED_GAPS} more" if len(runs) > MAX_LISTED_GAPS else ""
    return ", ".join(shown) + more


def summary_lines(spec: Spec, res: Result, out_path: Path) -> list[str]:
    lines = [f"[{spec.name}] Rows added: {res.added} (skipped {res.skipped_current_day} point(s) on the current UTC day)"]
    if res.first_ts is not None:
        lines.append(f"Stored dates: {utc_date(res.first_ts)} to {utc_date(res.last_ts)}")
    else:
        lines.append("Stored dates: none")
    lines.append(f"Total rows: {res.total_rows} in {out_path}")
    lines.append(f"Days missing inside the range: {len(res.missing_days)}")
    if res.missing_days:
        lines.append(f"Gaps (not filled): {gap_text(res.missing_days)}")
    if res.out_of_order:
        lines.append(f"Note: {res.out_of_order} new row(s) are older than the last stored row (a gap filled late); "
                     "sort by timestamp_ms when reading.")
    lines += revision_lines(spec, res)
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch TAC chain TVL / coin price from DeFiLlama (public, no key).")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, spec in SPECS.items():
        p = sub.add_parser(name, help=f"fetch {name} history")
        p.add_argument("--out", default=str(spec.default_out), help="output CSV path (default %(default)s)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    spec = SPECS[args.command]
    try:
        res = fetch(spec, Path(args.out))
    except (RuntimeError, ValueError, requests.RequestException) as exc:
        print(f"ERROR: {exc}")
        return 1
    print("\n".join(summary_lines(spec, res, Path(args.out))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
