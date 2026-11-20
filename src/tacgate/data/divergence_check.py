"""Investigate the 2026-08-21 to 2026-08-25 price divergence (read-only analysis plus one small spot fetch).

Question: on 2026-08-23 00:00 UTC the Binance and Bybit perpetuals were both near 0.00165, but the CoinGecko
and DeFiLlama daily prices were about 0.00102 (about 38 percent lower). Did the SPOT price crash while the
perps held (spot crashed, perp held), or are the aggregator prices wrong (spot and perp agree)?

What this does:
  * Reads (never writes) the Binance perp 1m, Bybit perp 1m, DeFiLlama daily, CoinGecko daily and funding files.
  * `--fetch-spot` makes ONE public request for Binance SPOT TACUSDT 1h klines for the window and saves them to a NEW
    file (never overwrites). If the symbol does not exist or the request is refused, it says so and stops.
  * Writes a plain-words report. The verdict is exactly one of the three strings in VERDICTS. Causes are never
    asserted: everything about WHY is "unverified" unless a source is given.

Verdict rules (thresholds are constants below, chosen before looking at the spot data):
  "spot crashed, perp held"                   spot sits more than FAR_PCT below perp in some hour, AND on the days
                                              where an aggregator disagrees with perp, it sits closer to spot than to perp.
  "aggregators wrong, spot and perp agree"    spot stays within AGREE_PCT of perp in every hour, while an aggregator is
                                              more than FAR_PCT away from perp on some day.
  "cannot tell, <reason>"                     anything else, including no spot data.

Run: python -m tacgate.data.divergence_check [--dir data/raw] [--report docs/aug_2026_divergence_report.md] [--fetch-spot]
Exit codes: 0 ok, 2 bad arguments or file problem.
"""
from __future__ import annotations

import argparse
import csv
import io
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd
import requests

from tacgate.data import binance_klines as bk
from tacgate.data import bybit_klines as by
from tacgate.data import defillama as dl
from tacgate.data import binance_funding as bf
from tacgate.data import coingecko_market_chart as cgm

SPOT_BASE_URL = "https://api.binance.com"
SPOT_PATH = "/api/v3/klines"
SPOT_SYMBOL = "TACUSDT"
SPOT_INTERVAL = "1h"
SPOT_OUT_NAME = "binance_spot_TACUSDT_1h_aug2026.csv"
SPOT_ERROR_SUFFIX = ".fetch_error.txt"  # written next to the spot file when the one request is refused, so reruns can say why
HOUR_MS = 3_600_000
DAY_MS = 86_400_000

WINDOW_START = "2026-08-20"  # inclusive, UTC
WINDOW_END = "2026-08-27"  # exclusive: the window covers 2026-08-20 to 2026-08-26 inclusive
AGREE_PCT = 2.0  # spot within this of perp in every hour = "agree"
FAR_PCT = 5.0  # more than this = "far"
SPOT_MAX_RETRIES = 2  # the helper's own bounded backoff; there is no loop around it

DEFAULT_DIR = Path("data/raw")
DEFAULT_REPORT = Path("docs/aug_2026_divergence_report.md")

VERDICT_SPOT = "spot crashed, perp held"
VERDICT_AGG = "aggregators wrong, spot and perp agree"
VERDICT_UNKNOWN_PREFIX = "cannot tell"

log = logging.getLogger(__name__)


class FileProblem(Exception):
    """A required file is missing or unreadable (exit code 2)."""


def to_ms(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp() * 1000)


def utc(ms: int | float) -> str:
    return pd.Timestamp(int(ms), unit="ms", tz="UTC").strftime("%Y-%m-%d %H:%M")


def day_str(ms: int | float) -> str:
    return pd.Timestamp(int(ms), unit="ms", tz="UTC").strftime("%Y-%m-%d")


def nominal_day(ts_ms: int | float) -> int:
    """Nearest UTC midnight, for daily rows whose timestamps jitter by seconds."""
    return int(round(ts_ms / DAY_MS)) * DAY_MS


# ----------------------------------------------------------------- reading ---

def read_window(path: Path, columns: list[str], key: str, start: int, end: int) -> pd.DataFrame:
    """Read a CSV once (read-only), keep rows with start <= key < end, numeric. Ignores a partial last line."""
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise FileProblem(f"Cannot read {path}: {exc}") from exc
    data = data[: data.rfind(b"\n") + 1]
    if not data:
        raise FileProblem(f"{path}: empty")
    df = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False)
    if list(df.columns) != columns:
        raise FileProblem(f"{path}: expected columns {columns}, got {list(df.columns)}")
    for c in df.columns:
        if c not in ("symbol", "rateType"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[(df[key] >= start) & (df[key] < end)].reset_index(drop=True)
    return df


# --------------------------------------------------------------- spot fetch ---

@dataclass
class SpotFetch:
    ok: bool
    message: str
    rows: int = 0


def spot_error_path(spot_path: Path) -> Path:
    return Path(str(spot_path) + SPOT_ERROR_SUFFIX)


def _write_spot_error(spot_path: Path, message: str) -> None:
    p = spot_error_path(spot_path)
    spot_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with p.open("a", encoding="utf-8") as f:  # append: a record of every refused attempt
        f.write(f"{stamp} UTC {message}\n")


def fetch_spot(out_path: Path, start: int, end: int, session: requests.Session | None = None,
               sleep: Callable[[float], None] = time.sleep) -> SpotFetch:
    """ONE request for Binance SPOT 1h klines in [start, end). Saves a NEW file; never overwrites an existing one.

    A refused request (for example an unknown symbol, HTTP 400, or a region block, HTTP 451) is reported plainly and
    nothing is written."""
    out_path = Path(out_path)
    if out_path.exists():
        return SpotFetch(False, f"{out_path} already exists; not overwriting it. Delete it yourself to fetch again.")
    session = session or requests.Session()
    params = {"symbol": SPOT_SYMBOL, "interval": SPOT_INTERVAL, "startTime": start, "endTime": end - 1,
              "limit": (end - start) // HOUR_MS}
    try:
        page = bk.get_with_retry(session, params, sleep=sleep, max_retries=SPOT_MAX_RETRIES, path=SPOT_PATH,
                                 base_url=SPOT_BASE_URL)
    except (requests.RequestException, RuntimeError) as exc:
        msg = f"Spot request failed or was refused: {exc}"
        _write_spot_error(out_path, msg)
        return SpotFetch(False, msg)
    if not isinstance(page, list) or not page:
        return SpotFetch(False, f"Spot request returned no candles: {str(page)[:200]}")
    for r in page:
        if not isinstance(r, list) or len(r) != len(bk.COLUMNS):
            return SpotFetch(False, f"Unexpected spot kline layout: {str(r)[:200]}")
    rows = [r for r in page if start <= int(r[0]) < end]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("x", newline="") as f:  # "x": fail rather than overwrite
        w = csv.writer(f)
        w.writerow(bk.COLUMNS)
        w.writerows(rows)
    return SpotFetch(True, f"Saved {len(rows)} hourly spot candles to {out_path}", len(rows))


# ---------------------------------------------------------------- analysis ---

def perp_day_table(binance: pd.DataFrame, bybit: pd.DataFrame, start: int, end: int) -> pd.DataFrame:
    """One row per UTC day: Binance perp and Bybit perp 1m open/high/low/close/volume, plus the min and max of the
    Binance-minus-Bybit 1m close difference in bps (matched on open_time)."""
    rows = []
    merged = binance[["open_time", "close"]].merge(bybit[["open_time", "close"]], on="open_time", suffixes=("_bn", "_by"))
    merged["bps"] = (merged["close_bn"] / merged["close_by"] - 1) * 1e4
    for d in range(start, end, DAY_MS):
        b = binance[(binance.open_time >= d) & (binance.open_time < d + DAY_MS)]
        y = bybit[(bybit.open_time >= d) & (bybit.open_time < d + DAY_MS)]
        m = merged[(merged.open_time >= d) & (merged.open_time < d + DAY_MS)]
        row = {"day": d}
        for tag, x in (("bn", b), ("by", y)):
            if len(x):
                row.update({f"{tag}_open": float(x["open"].iloc[0]), f"{tag}_high": float(x["high"].max()),
                            f"{tag}_low": float(x["low"].min()), f"{tag}_close": float(x["close"].iloc[-1]),
                            f"{tag}_volume": float(x["volume"].sum()), f"{tag}_minutes": len(x)})
        row.update({"bps_min": float(m["bps"].min()) if len(m) else None,
                    "bps_max": float(m["bps"].max()) if len(m) else None, "bps_minutes": len(m)})
        rows.append(row)
    return pd.DataFrame(rows)


def daily_external(df: pd.DataFrame, price_col: str, start: int, end: int) -> dict[int, float]:
    """External daily price by nominal UTC midnight (the value stamped at the start of that day)."""
    out: dict[int, float] = {}
    for ts, p in zip(df["timestamp_ms"], df[price_col]):
        n = nominal_day(ts)
        if start <= n < end:
            out[n] = float(p)
    return out


def funding_by_day(funding: pd.DataFrame, start: int, end: int) -> pd.DataFrame:
    f = funding[(funding.fundingTime >= start) & (funding.fundingTime < end)].copy()
    f["day"] = (f.fundingTime // DAY_MS) * DAY_MS
    return f


def perp_low(df: pd.DataFrame) -> tuple[float, int] | None:
    """Lowest 1m low in df and the open_time of that minute."""
    if df.empty:
        return None
    i = df["low"].idxmin()
    return float(df.loc[i, "low"]), int(df.loc[i, "open_time"])


def perp_hourly(df: pd.DataFrame, start: int, end: int) -> pd.DataFrame:
    """Hourly open/high/low/close/volume from 1m candles with start <= open_time < end."""
    w = df[(df.open_time >= start) & (df.open_time < end)].copy()
    if w.empty:
        return w
    w["hour"] = (w["open_time"] // HOUR_MS) * HOUR_MS
    g = w.groupby("hour")
    return pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                         "close": g["close"].last(), "volume": g["volume"].sum()}).reset_index()


def spot_vs_perp(spot: pd.DataFrame, binance: pd.DataFrame) -> pd.DataFrame:
    """Per spot hour: spot close vs the Binance perp 1m close of the LAST minute of that hour (same instant),
    percent = spot / perp - 1. Hours with no matching perp minute are dropped."""
    s = spot[["open_time", "close"]].rename(columns={"close": "spot_close"}).copy()
    s["perp_minute"] = s["open_time"] + HOUR_MS - 60_000
    p = binance[["open_time", "close"]].rename(columns={"open_time": "perp_minute", "close": "perp_close"})
    j = s.merge(p, on="perp_minute")
    j["pct"] = (j["spot_close"] / j["perp_close"] - 1) * 100
    return j


@dataclass
class Analysis:
    start: int
    end: int
    days: pd.DataFrame
    dl: dict[int, float]
    cg: dict[int, float]
    funding: pd.DataFrame
    spot_status: str = "not fetched"
    spot: pd.DataFrame | None = None
    hourly: pd.DataFrame | None = None
    agg_gaps: list[dict] = field(default_factory=list)  # per day and aggregator: vs perp and vs spot
    verdict: str = ""
    verdict_reason: str = ""
    spot_message: str = ""  # last recorded refusal of the spot request, if any
    lows: dict = field(default_factory=dict)  # "Binance perp"/"Bybit perp" -> (lowest 1m low, open_time) in the window
    around_low: dict = field(default_factory=dict)  # same keys -> hourly frame around the lowest low


def aggregator_gaps(a: Analysis) -> None:
    """For each day and each aggregator that has a price: percent vs the Binance perp 1m open at 00:00, and (if
    spot exists) percent vs the spot 1h OPEN of the 00:00 hour, which is the same instant."""
    spot_open = {}
    if a.spot is not None and len(a.spot):
        spot_open = dict(zip(a.spot["open_time"].astype("int64"), a.spot["open"]))
    perp_open = {int(r.day): r.bn_open for r in a.days.itertuples() if hasattr(r, "bn_open") and pd.notna(r.bn_open)}
    for name, series in (("DeFiLlama", a.dl), ("CoinGecko", a.cg)):
        for d, price in sorted(series.items()):
            if d not in perp_open:
                continue
            row = {"day": d, "source": name, "price": price, "perp": perp_open[d],
                   "vs_perp_pct": (price / perp_open[d] - 1) * 100}
            sp = spot_open.get(d)
            row["spot"] = sp
            low = a.lows.get("Binance perp")
            row["vs_perp_low_pct"] = (price / low[0] - 1) * 100 if low else None
            row["vs_spot_pct"] = (price / sp - 1) * 100 if sp else None
            a.agg_gaps.append(row)


def decide(a: Analysis) -> None:
    if a.hourly is None or a.hourly.empty:
        a.verdict = f"{VERDICT_UNKNOWN_PREFIX}, no spot data was fetched ({a.spot_status})"
        a.verdict_reason = "Without spot candles the hypothesis about spot cannot be tested."
        low = a.lows.get("Binance perp")
        if low:
            a.verdict_reason += (f" What the perps do show: they did not hold. The Binance perp itself traded down to {low[0]:.6g} at "
                                 f"{utc(low[1])} UTC inside the window.")
            near = [g for g in a.agg_gaps if g.get("vs_perp_low_pct") is not None and abs(g["vs_perp_low_pct"]) <= AGREE_PCT
                    and g["vs_perp_pct"] < -FAR_PCT]
            if near:
                a.verdict_reason += (" The aggregator prices that sit far below the perp open on "
                                     + ", ".join(sorted({day_str(g['day']) for g in near}))
                                     + f" are within {AGREE_PCT:g}% of that perp low, so they look like the crash-minute price, not a spot "
                                     "price that stayed low (unverified: this only compares numbers).")
        return
    h = a.hourly
    min_pct, max_abs = float(h["pct"].min()), float(h["pct"].abs().max())
    far_hours = int((h["pct"] < -FAR_PCT).sum())
    agg_far = [g for g in a.agg_gaps if abs(g["vs_perp_pct"]) > FAR_PCT]
    if far_hours and agg_far:
        closer_to_spot = [g for g in agg_far if g["vs_spot_pct"] is not None and abs(g["vs_spot_pct"]) < abs(g["vs_perp_pct"])]
        if len(closer_to_spot) == len(agg_far):
            a.verdict = VERDICT_SPOT
            a.verdict_reason = (f"Spot closed more than {FAR_PCT:g}% below the perp in {far_hours} hour(s) (lowest {min_pct:.1f}%), and on "
                                f"every aggregator day that disagrees with the perp the aggregator is closer to spot than to the perp.")
            return
    if max_abs <= AGREE_PCT and agg_far:
        a.verdict = VERDICT_AGG
        a.verdict_reason = (f"Spot stayed within {AGREE_PCT:g}% of the perp in every hour (largest {max_abs:.2f}%), while "
                            f"{len(agg_far)} aggregator day(s) were more than {FAR_PCT:g}% away from the perp.")
        return
    if not agg_far:
        why = f"no aggregator price is more than {FAR_PCT:g}% away from the perp inside the window"
    elif far_hours and not all(g["vs_spot_pct"] is not None and abs(g["vs_spot_pct"]) < abs(g["vs_perp_pct"]) for g in agg_far):
        why = "spot was far below the perp in some hours, but the aggregator prices are not closer to spot than to the perp"
    else:
        why = (f"spot and perp differ by up to {max_abs:.1f}% (between the {AGREE_PCT:g}% agree and {FAR_PCT:g}% far thresholds), "
               "so neither pattern is clean")
    a.verdict = f"{VERDICT_UNKNOWN_PREFIX}, {why}"
    a.verdict_reason = a.verdict


def analyse(directory: Path, spot_path: Path | None = None, start: int | None = None, end: int | None = None) -> Analysis:
    directory = Path(directory)
    start = to_ms(WINDOW_START) if start is None else start
    end = to_ms(WINDOW_END) if end is None else end
    binance = read_window(directory / bk.DEFAULT_OUT.name, bk.COLUMNS, "open_time", start, end)
    bybit = read_window(directory / by.DEFAULT_OUT.name, by.COLUMNS, "open_time", start, end)
    cg = read_window(directory / cgm.DEFAULT_OUT.name, cgm.COLUMNS, "timestamp_ms", start - DAY_MS, end + DAY_MS)
    dlp = read_window(directory / dl.PRICE.default_out.name, dl.PRICE.columns, "timestamp_ms", start - DAY_MS, end + DAY_MS)
    funding = read_window(directory / bf.DEFAULT_OUT.name, bf.FUNDING_COLUMNS, "fundingTime", start, end)
    a = Analysis(start, end, perp_day_table(binance, bybit, start, end), daily_external(dlp, "price", start, end),
                 daily_external(cg, "price", start, end), funding_by_day(funding, start, end))
    for name, df in (("Binance perp", binance), ("Bybit perp", bybit)):
        low = perp_low(df)
        if low:
            a.lows[name] = low
            a.around_low[name] = perp_hourly(df, (low[1] // HOUR_MS) * HOUR_MS - 2 * HOUR_MS, (low[1] // HOUR_MS) * HOUR_MS + 10 * HOUR_MS)
    spot_path = Path(spot_path) if spot_path else directory / SPOT_OUT_NAME
    if spot_path.exists():
        spot = read_window(spot_path, bk.COLUMNS, "open_time", start, end)
        if len(spot):
            a.spot, a.spot_status = spot, f"read {len(spot)} hourly candles from {spot_path.name}"
            a.hourly = spot_vs_perp(spot, binance)
        else:
            a.spot_status = f"{spot_path.name} has no candles in the window"
    else:
        a.spot_status = f"{spot_path.name} does not exist"
        err = spot_error_path(spot_path)
        if err.exists():
            a.spot_message = err.read_text(encoding="utf-8").strip().splitlines()[-1]
    aggregator_gaps(a)
    decide(a)
    return a


# ------------------------------------------------------------------ report ---

def _f(x, digits=6):
    return "n/a" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x:.{digits}g}"


def render_report(a: Analysis, spot_message: str = "") -> str:
    spot_message = spot_message or a.spot_message
    L = ["# Aug 2026 price divergence report", "",
         f"Window: {day_str(a.start)} to {day_str(a.end - 1)} UTC. Read-only analysis of local files"
         + (" plus one small Binance spot request." if a.spot is not None else "."),
         "", "## Verdict", "", f"**{a.verdict}**", "", a.verdict_reason, "",
         "Why it happened is **unverified**: this report compares prices only. It does not establish any cause, "
         "including anything about the 2026-08-22 exploit.", ""]
    L += ["## Spot data", "", f"- {a.spot_status}" + (f"\n- Fetch: {spot_message}" if spot_message else "")]
    if "Spot request failed" in spot_message:
        L += ["- Only one request was made and it was not retried. The shared request helper does not keep the response body, so "
              "the reason for the refusal is not confirmed. HTTP 400 on this endpoint is what Binance returns for an unknown symbol, "
              "which would mean TACUSDT has no Binance spot market; the earlier source research (docs/phase0_sources.md) found only "
              "Binance Alpha and Futures listings for TAC. Both of these are unverified."]
    L += [""]
    L += ["## Per day: perpetuals (UTC day, 1m candles)", "",
          "| Day | Exchange | Open | High | Low | Close | Volume (tokens) | Minutes |", "|---|---|---|---|---|---|---|---|"]
    for r in a.days.to_dict("records"):
        for tag, name in (("bn", "Binance perp"), ("by", "Bybit perp")):
            if f"{tag}_open" in r and pd.notna(r.get(f"{tag}_open")):
                L.append(f"| {day_str(r['day'])} | {name} | {_f(r[f'{tag}_open'])} | {_f(r[f'{tag}_high'])} | {_f(r[f'{tag}_low'])} | "
                         f"{_f(r[f'{tag}_close'])} | {r[f'{tag}_volume']:,.0f} | {int(r[f'{tag}_minutes'])} |")
    L += ["", "## Binance minus Bybit 1m close (bps, per day)", "", "| Day | Min | Max | Minutes compared |", "|---|---|---|---|"]
    L += [f"| {day_str(r['day'])} | {_f(r['bps_min'], 4)} | {_f(r['bps_max'], 4)} | {int(r['bps_minutes'])} |" for r in a.days.to_dict("records")]
    L += ["", "## Daily aggregator prices (the value stamped at 00:00 UTC of the day)", "",
          "| Day | DeFiLlama | CoinGecko | Binance perp 1m open at 00:00 | DeFiLlama vs perp | CoinGecko vs perp |", "|---|---|---|---|---|---|"]
    perp_open = {int(r["day"]): r.get("bn_open") for r in a.days.to_dict("records")}
    for d in range(a.start, a.end, DAY_MS):
        po, dp, cp = perp_open.get(d), a.dl.get(d), a.cg.get(d)
        pct = lambda p: f"{(p / po - 1) * 100:+.1f}%" if p is not None and po else "n/a"
        L.append(f"| {day_str(d)} | {_f(dp)} | {_f(cp)} | {_f(po)} | {pct(dp)} | {pct(cp)} |")
    L += ["", "## Funding (Binance perp)", "", "| Time (UTC) | Funding rate | Mark price |", "|---|---|---|"]
    if a.funding.empty:
        L.append("| none in the window | | |")
    L += [f"| {utc(r.fundingTime)} | {r.fundingRate:.8f} | {_f(r.markPrice)} |" for r in a.funding.itertuples()]
    if a.lows:
        L += ["", "## Did the perpetuals hold? Lowest 1m low in the window", "", "| Exchange | Lowest 1m low | Minute (UTC) |", "|---|---|---|"]
        L += [f"| {n} | {_f(v[0])} | {utc(v[1])} |" for n, v in a.lows.items()]
        for n, h in a.around_low.items():
            if len(h):
                L += ["", f"{n}, hourly candles from 2 hours before to 10 hours after that hour:", "",
                      "| Hour (UTC) | Open | High | Low | Close | Volume (tokens) |", "|---|---|---|---|---|---|"]
                L += [f"| {utc(r.hour)} | {_f(r.open)} | {_f(r.high)} | {_f(r.low)} | {_f(r.close)} | {r.volume:,.0f} |" for r in h.itertuples()]
    far_low = [g for g in a.agg_gaps if g["vs_perp_pct"] < -FAR_PCT]
    if far_low:
        L += ["", "## Aggregator prices that sit far below the perp open", ""]
        low = a.lows.get("Binance perp")
        days_far = sorted({g["day"] for g in far_low})
        if low and low[1] < days_far[0]:
            hrs = (days_far[0] - low[1]) / HOUR_MS
            L += [f"These daily values are stamped at about 00:00 UTC, {hrs:.1f} hours after the perp low at {utc(low[1])} UTC. "
                  f"At 00:00 the Binance perp was at {_f(perp_open.get(days_far[0]))}, so a value equal to that low was not a price the perps were trading at that moment; "
                  "whether it is stale, lagging or from another venue is unverified.", ""]
        L += ["| Day | Source | Price | vs perp open at 00:00 | vs the lowest perp low in the window |", "|---|---|---|---|---|"]
        L += [f"| {day_str(g['day'])} | {g['source']} | {_f(g['price'])} | {g['vs_perp_pct']:+.1f}% | "
              f"{g['vs_perp_low_pct']:+.1f}% |" for g in far_low]
    if a.agg_gaps and a.spot is not None:
        L += ["", "## Aggregators vs perp vs spot at 00:00 UTC", "", "| Day | Source | Price | vs Binance perp open | vs spot 00:00 hour open |", "|---|---|---|---|---|"]
        for g in a.agg_gaps:
            vs = f"{g['vs_spot_pct']:+.1f}%" if g["vs_spot_pct"] is not None else "n/a"
            L.append(f"| {day_str(g['day'])} | {g['source']} | {_f(g['price'])} | {g['vs_perp_pct']:+.1f}% | {vs} |")
    if a.hourly is not None and not a.hourly.empty:
        h = a.hourly
        far = h[h["pct"] < -FAR_PCT]
        L += ["", "## Spot vs perp, per hour", "",
              f"Spot close vs the Binance perp close at the same instant (the hour's last minute), {len(h)} hours.", "",
              f"- Spot lowest vs perp: {h['pct'].min():+.2f}% at {utc(h.loc[h['pct'].idxmin(), 'open_time'])} UTC",
              f"- Spot highest vs perp: {h['pct'].max():+.2f}% at {utc(h.loc[h['pct'].idxmax(), 'open_time'])} UTC",
              f"- Largest absolute gap: {h['pct'].abs().max():.2f}% at {utc(h.loc[h['pct'].abs().idxmax(), 'open_time'])} UTC",
              f"- Hours with spot more than {FAR_PCT:g}% below the perp: {len(far)}",
              f"- Hours within {AGREE_PCT:g}%: {int((h['pct'].abs() <= AGREE_PCT).sum())} of {len(h)}",
              "", "The 10 largest absolute gaps:", "", "| Hour (UTC) | Spot close | Perp close | Spot vs perp |", "|---|---|---|---|"]
        top = h.reindex(h["pct"].abs().sort_values(ascending=False).index).head(10)
        L += [f"| {utc(r.open_time)} | {_f(r.spot_close)} | {_f(r.perp_close)} | {r.pct:+.2f}% |" for r in top.itertuples()]
    L += ["", "Thresholds (fixed before looking at spot data): agree = within "
          f"{AGREE_PCT:g}%, far = more than {FAR_PCT:g}%.", ""]
    return "\n".join(L)


def console_summary(a: Analysis, report: Path, spot_message: str = "") -> str:
    out = [f"Aug 2026 divergence check ({day_str(a.start)} to {day_str(a.end - 1)} UTC)",
           f"  spot: {spot_message or a.spot_message or a.spot_status}"]
    for r in a.days.to_dict("records"):
        out.append(f"  {day_str(r['day'])}  Binance {_f(r.get('bn_open'))}->{_f(r.get('bn_close'))}  Bybit {_f(r.get('by_open'))}->"
                   f"{_f(r.get('by_close'))}  BN-BY bps [{_f(r['bps_min'], 3)}, {_f(r['bps_max'], 3)}]  "
                   f"DeFiLlama {_f(a.dl.get(int(r['day'])))}  CoinGecko {_f(a.cg.get(int(r['day'])))}")
    if a.hourly is not None and not a.hourly.empty:
        h = a.hourly
        i = h["pct"].abs().idxmax()
        out.append(f"  largest spot-vs-perp gap: {h.loc[i, 'pct']:+.2f}% at {utc(h.loc[i, 'open_time'])} UTC (lowest {h['pct'].min():+.2f}%)")
    out += [f"  verdict: {a.verdict}", f"  report: {report}"]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Investigate the Aug 2026 price divergence (read-only + one optional spot fetch).")
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    ap.add_argument("--fetch-spot", action="store_true", help="make ONE request for Binance spot 1h klines (new file only)")
    args = ap.parse_args(argv)
    directory, report = Path(args.dir), Path(args.report)
    d_res, r_res = directory.resolve(), report.resolve()
    if r_res == d_res or d_res in r_res.parents:
        print(f"Refusing: --report must not be inside the data directory {directory}.")
        return 2
    if not directory.is_dir():
        print(f"Directory not found: {directory}")
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    spot_message = ""
    if args.fetch_spot:
        res = fetch_spot(directory / SPOT_OUT_NAME, to_ms(WINDOW_START), to_ms(WINDOW_END))
        spot_message = res.message
        print(spot_message)
    try:
        a = analyse(directory)
    except FileProblem as exc:
        print(str(exc))
        return 2
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(a, spot_message), encoding="utf-8")
    print(console_summary(a, report, spot_message))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
