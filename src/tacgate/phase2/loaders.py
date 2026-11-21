"""Phase 2 loaders: read every source we have and apply the already decided known-time and bad-row rules, and nothing else.

No features, no labels, no models, no downloads. Read-only: no file is written except the check report of the CLI. All times are UTC
milliseconds (int64). Every loader returns a pandas DataFrame with at least

    ts_ms        the period or event time as the source states it,
    known_at_ms  when the row may first be used (see the rules below),
    the source columns, and flag columns (booleans).

Nothing is forward-filled, imputed or interpolated: a bad value is FLAGGED, and the `masked_*` helpers return a copy with the flagged entries set
to missing, leaving the raw values untouched.

Known-time rules (docs/gate1_summary.md, bulk_equivalence_report.md, bulk_metrics_history_report.md, phase2_plan.md):
  * Binance and Bybit 1m klines: at the candle close (open time + 60 s).
  * Binance funding: at its fundingTime, never earlier.
  * CoinGecko, DeFiLlama price and DeFiLlama TVL daily rows: at timestamp + 24 h. A price more than 2% from the Binance price is flagged
    (the method of quality_daily_external.py: the Binance 1m OPEN at the minute nearest to the external timestamp).
  * Bulk metrics (the normalized file): open interest at known_at_oi_ms, the ratio columns at known_at_other_ms; the taker column is dropped
    (decided: not used); unverified_era is carried.
  * Recorder files: live rows at fetched_at_ms, backfilled rows (fetched more than 15 minutes after the timestamp) at timestamp + 10 minutes.
  * Static events: known_at_utc of the row; a row with an empty known_at_utc is never usable.

Bulk bad-row rule (decision of 2026-11-21, docs/bulk_metrics_history_report.md):
  * open interest at or below zero, or not a number, is bad;
  * any ratio at or below zero, or not a number, is bad (per column);
  * a ONE-STEP OPEN-INTEREST JUMP is a change of more than 50% (|OI_t / OI_{t-1} - 1| > 0.5, a division by zero counts) between two rows whose labels are
    exactly 5 minutes apart. The documented count is 24. "Rows inside the jumps" are the rows of each EXCURSION: from the row of a DOWN jump (OI fell by
    more than 50%) up to, but not including, the row of the next UP jump (OI rose by more than 50%). An up jump with no open excursion flags its own
    row; an excursion still open at the end of the data runs to the end.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from tacgate.data import binance_funding as bf
from tacgate.data import binance_klines as bk
from tacgate.data import bulk_metrics_history as bm
from tacgate.data import bybit_klines as by
from tacgate.data import coingecko_market_chart as cgm
from tacgate.data import defillama as dl
from tacgate.data import quality_daily_external as qde
from tacgate.data import quality_recorder as qr
from tacgate.data import static_events as se
from tacgate.data.bulk_availability import read_complete
from tacgate.data.recorder import DATASETS as RECORDER_DATASETS
from tacgate.data.recorder import SNAPSHOT_COLUMNS, snapshot_path

MIN_MS = 60_000
HOUR_MS = 3_600_000
DAY_MS = 86_400_000
FIVE_MIN_MS = 300_000
PRICE_GAP_LIMIT = 0.02  # a daily external price more than 2% from the Binance price is flagged
OI_JUMP_LIMIT = 0.5  # a one-step open-interest change above this is a jump
RECORDER_BACKFILL_DELAY_MS = 10 * MIN_MS  # backfilled recorder rows are known at timestamp + 10 minutes
BACKFILL_LAG_MS = qr.BACKFILL_LAG_MS  # fetched more than this after the timestamp = backfilled (the recorder rule used in the Gate 1 checks)
KLINE_DELAY_MS = MIN_MS
DAILY_DELAY_MS = DAY_MS

DEFAULT_DATA_DIR = Path("data/raw")
DEFAULT_STATIC_DIR = Path("data/static")
BULK_NAME = "binance_bulk_metrics_TACUSDT_5m.csv"
BULK_RATIO_COLS = ["count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio", "count_long_short_ratio"]
BULK_TAKER_COL = "sum_taker_long_short_vol_ratio"
BULK_OI_COLS = ["sum_open_interest", "sum_open_interest_value"]
DEFAULT_REPORT = Path("docs/phase2_loaders_check.md")


class KnownTimeError(ValueError):
    """A loader produced a row that would be known before the time it describes (a look-ahead problem)."""


def utc_ms(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp() * 1000)


TGE_MS = utc_ms("2025-07-15")  # token generation event (data/static/tokenomics.csv, tge_date)


# --------------------------------------------------------- generic helpers ---

def check_known_after_ts(df: pd.DataFrame, ts_col: str = "ts_ms", known_col: str = "known_at_ms", allow: pd.Series | None = None) -> int:
    """Number of rows whose known time is before their own time. `allow` (boolean, same index) marks documented exceptions, which are not counted.
    Rows with a missing known time are not usable and are not counted."""
    k = df[known_col]
    bad = (k.notna()) & (k.astype("float64") < df[ts_col].astype("float64"))
    if allow is not None:
        bad &= ~allow.reindex(df.index, fill_value=False)
    return int(bad.sum())


def enforce_known_after_ts(df: pd.DataFrame, name: str, allow: pd.Series | None = None, **kw) -> pd.DataFrame:
    n = check_known_after_ts(df, allow=allow, **kw)
    if n:
        raise KnownTimeError(f"{name}: {n} row(s) would be known before their own time (known_at_ms < ts_ms)")
    return df


def asof(table: pd.DataFrame, t_ms: int, known_col: str = "known_at_ms") -> pd.DataFrame:
    """Only the rows that may be used at time t_ms: known_at_ms at or before t_ms. A row with a missing known time is never returned."""
    k = table[known_col]
    return table[k.notna() & (k.astype("float64") <= t_ms)]


def assert_no_lookahead(table: pd.DataFrame, t_ms: int, fn: Callable[[pd.DataFrame, int], pd.DataFrame] = asof, known_col: str = "known_at_ms") -> None:
    """The look-ahead test utility (docs/phase2_plan.md, section 7): the result of fn at t must be identical when every row with a known time
    after t is removed first. Raises AssertionError if it is not."""
    full = fn(table, t_ms)
    k = table[known_col]
    cut = table[k.notna() & (k.astype("float64") <= t_ms)]
    truncated = fn(cut, t_ms)
    pd.testing.assert_frame_equal(full.reset_index(drop=True), truncated.reset_index(drop=True), check_dtype=True)


def missing_slots(label_ms: np.ndarray, step_ms: int = FIVE_MIN_MS) -> int:
    """How many slots of a regular grid are absent between the first and last label (nothing is added)."""
    t = np.asarray(label_ms, dtype="int64")
    if len(t) == 0:
        return 0
    return int(len(np.setdiff1d(np.arange(t.min(), t.max() + 1, step_ms), t)))


def _to_num(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for c in cols:
        out[c] = pd.to_numeric(df[c], errors="coerce")
    return out


def _read(path: Path, columns: list[str], label: str) -> pd.DataFrame:
    """Read a source CSV once (a partial last line is ignored) and check its header against the fetcher's columns."""
    df = read_complete(Path(path))
    if list(df.columns) != columns:
        raise ValueError(f"{label}: expected columns {columns}, got {list(df.columns)}")
    return df


# ------------------------------------------------------------------ klines ---

def load_klines(path: Path, venue: str = "binance") -> pd.DataFrame:
    """1m klines. ts_ms = open time; known_at_ms = open time + 60 s (the candle close). No missing minute is added.

    Columns: ts_ms, known_at_ms, open, high, low, close, volume, plus quote_volume, trades, taker_buy_base_volume, taker_buy_quote_volume
    (Binance) or turnover (Bybit); flag: zero_volume."""
    if venue not in ("binance", "bybit"):
        raise ValueError("venue must be 'binance' or 'bybit'")
    cols = bk.COLUMNS if venue == "binance" else by.COLUMNS
    df = _read(path, cols, f"{venue} klines")
    keep = [c for c in cols if c not in ("open_time", "close_time", "ignore")]
    out = _to_num(df, keep)
    out.insert(0, "ts_ms", pd.to_numeric(df["open_time"]).astype("int64"))
    out.insert(1, "known_at_ms", out["ts_ms"] + KLINE_DELAY_MS)
    out["zero_volume"] = out["volume"] == 0
    return enforce_known_after_ts(out, f"{venue} klines")


# ------------------------------------------------------------------ funding ---

def load_funding(path: Path) -> pd.DataFrame:
    """Funding rates. ts_ms = fundingTime = known_at_ms (never earlier). Flag: bad_value (a missing rate or mark price)."""
    df = _read(path, bf.FUNDING_COLUMNS, "funding")
    out = pd.DataFrame({"ts_ms": pd.to_numeric(df["fundingTime"]).astype("int64")})
    out["known_at_ms"] = out["ts_ms"]
    out["symbol"], out["rateType"] = df["symbol"].values, df["rateType"].values
    out["fundingRate"] = pd.to_numeric(df["fundingRate"], errors="coerce")
    out["markPrice"] = pd.to_numeric(df["markPrice"], errors="coerce")
    out["bad_value"] = out["fundingRate"].isna() | out["markPrice"].isna()
    return enforce_known_after_ts(out, "funding")


# --------------------------------------------------- daily external sources ---

def binance_open_series(path: Path) -> pd.Series:
    """The Binance 1m open by open_time (the reference of the 2% rule; the reader of quality_daily_external.py)."""
    s = qde.load_klines_open(Path(path), qde.Result(str(path), 0))
    if s is None:
        raise ValueError(f"cannot read the Binance klines in {path}")
    return s


def price_gap(ts_ms: np.ndarray, price: np.ndarray, binance_open: pd.Series | None) -> pd.DataFrame:
    """Relative gap of an external price to the Binance 1m open at the minute NEAREST to the external timestamp (method of quality_daily_external.py).

    Columns: binance_gap (price / binance - 1, NaN where there is no Binance minute), has_binance, off_2pct (|gap| > 2%, strict)."""
    ts = pd.Series(np.asarray(ts_ms, dtype="int64"))
    if binance_open is None:
        bn = pd.Series(np.nan, index=ts.index)
    else:
        bn = (ts / MIN_MS).round().astype("int64").mul(MIN_MS).map(binance_open)
    gap = pd.Series(np.asarray(price, dtype="float64"), index=ts.index) / bn - 1
    return pd.DataFrame({"binance_gap": gap.values, "has_binance": bn.notna().values, "off_2pct": (gap.abs() > PRICE_GAP_LIMIT).values})


def load_coingecko(path: Path, binance_open: pd.Series | None = None) -> pd.DataFrame:
    """CoinGecko daily rows, known at timestamp + 24 h. The price is flagged against Binance (never use it unflagged: see masked_prices);
    market cap and volume stay usable. Columns: ts_ms, known_at_ms, price, market_cap, total_volume, fetched_at_ms, binance_gap, has_binance, off_2pct."""
    df = _read(path, cgm.COLUMNS, "coingecko")
    out = pd.DataFrame({"ts_ms": pd.to_numeric(df["timestamp_ms"]).astype("int64")})
    out["known_at_ms"] = out["ts_ms"] + DAILY_DELAY_MS
    for c in ("price", "market_cap", "total_volume"):
        out[c] = pd.to_numeric(df[c], errors="coerce")
    out["fetched_at_ms"] = pd.to_numeric(df["fetched_at_ms"]).astype("int64")
    out = pd.concat([out, price_gap(out["ts_ms"].values, out["price"].values, binance_open)], axis=1)
    return enforce_known_after_ts(out, "coingecko")


def load_defillama_price(path: Path, binance_open: pd.Series | None = None) -> pd.DataFrame:
    """DeFiLlama price, known at timestamp + 24 h, flagged against Binance. Columns: ts_ms, known_at_ms, price, confidence, fetched_at_ms and the gap flags."""
    df = _read(path, dl.PRICE.columns, "defillama price")
    out = pd.DataFrame({"ts_ms": pd.to_numeric(df["timestamp_ms"]).astype("int64")})
    out["known_at_ms"] = out["ts_ms"] + DAILY_DELAY_MS
    out["price"] = pd.to_numeric(df["price"], errors="coerce")
    out["confidence"] = pd.to_numeric(df["confidence"], errors="coerce")
    out["fetched_at_ms"] = pd.to_numeric(df["fetched_at_ms"]).astype("int64")
    out = pd.concat([out, price_gap(out["ts_ms"].values, out["price"].values, binance_open)], axis=1)
    return enforce_known_after_ts(out, "defillama price")


def load_defillama_tvl(path: Path) -> pd.DataFrame:
    """DeFiLlama chain TVL, known at timestamp + 24 h. Columns: ts_ms, known_at_ms, tvl, fetched_at_ms; flag: bad_value."""
    df = _read(path, dl.TVL.columns, "defillama tvl")
    out = pd.DataFrame({"ts_ms": pd.to_numeric(df["timestamp_ms"]).astype("int64")})
    out["known_at_ms"] = out["ts_ms"] + DAILY_DELAY_MS
    out["tvl"] = pd.to_numeric(df["tvl"], errors="coerce")
    out["fetched_at_ms"] = pd.to_numeric(df["fetched_at_ms"]).astype("int64")
    out["bad_value"] = out["tvl"].isna()
    return enforce_known_after_ts(out, "defillama tvl")


def masked_prices(df: pd.DataFrame) -> pd.DataFrame:
    """A copy where the price is missing wherever it is flagged more than 2% off Binance, or has no Binance minute to be checked against.
    Market cap, volume and every other column are left as they are; the input is not modified."""
    out = df.copy()
    out.loc[out["off_2pct"] | ~out["has_binance"], "price"] = np.nan
    return out


# ------------------------------------------------------- bulk metrics (5 min) ---

def oi_jump_flags(label_ms: np.ndarray, oi: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(jump_step, inside_jump) boolean arrays, one entry per row, for rows sorted by label. See the module docstring for the exact rule."""
    label = np.asarray(label_ms, dtype="int64")
    v = np.asarray(oi, dtype="float64")
    n = len(v)
    with np.errstate(divide="ignore", invalid="ignore"):
        chg = np.full(n, np.nan)
        chg[1:] = v[1:] / v[:-1] - 1.0
    consecutive = np.zeros(n, dtype=bool)
    consecutive[1:] = np.diff(label) == FIVE_MIN_MS
    step = consecutive & (np.abs(chg) > OI_JUMP_LIMIT)
    inside = np.zeros(n, dtype=bool)
    open_at = None
    for i in np.flatnonzero(step):
        if chg[i] < 0:
            if open_at is None:
                open_at = i
        else:  # an up jump (including +inf from zero) closes the excursion; without one it flags only its own row
            if open_at is not None:
                inside[open_at:i] = True
                open_at = None
            else:
                inside[i] = True
    if open_at is not None:
        inside[open_at:] = True
    return step, inside


def load_bulk_metrics(path: Path, keep_taker: bool = False) -> pd.DataFrame:
    """The normalized bulk metrics file with the decided bad-row flags. The taker column is dropped unless keep_taker (only the check uses it).

    Columns: ts_ms (= ts_ours_ms), bulk_label_ms, known_at_oi_ms, known_at_other_ms, known_at_ms (= known_at_other_ms, the later of the two for every row),
    file_date, last_modified_ms, unverified_era, the open interest columns, the three ratio columns [and the taker ratio], and flags oi_bad, oi_jump_step,
    oi_inside_jump and bad_<ratio column> (at or below zero, or not a number). The raw values are not changed."""
    df = _read(path, bm.OUT_COLUMNS, "bulk metrics")
    out = pd.DataFrame({"ts_ms": pd.to_numeric(df["ts_ours_ms"]).astype("int64"), "bulk_label_ms": pd.to_numeric(df["bulk_label_ms"]).astype("int64")})
    out["known_at_oi_ms"] = pd.to_numeric(df["known_at_oi_ms"]).astype("int64")
    out["known_at_other_ms"] = pd.to_numeric(df["known_at_other_ms"]).astype("int64")
    out["known_at_ms"] = out["known_at_other_ms"]
    out["file_date"] = df["file_date"].values
    out["last_modified_ms"] = pd.to_numeric(df["last_modified_ms"]).astype("int64")
    out["unverified_era"] = (df["unverified_era"].str.lower() == "true").values
    value_cols = BULK_OI_COLS + BULK_RATIO_COLS + ([BULK_TAKER_COL] if keep_taker else [])
    out = pd.concat([out, _to_num(df, value_cols)], axis=1)
    out = out.sort_values("bulk_label_ms", kind="stable").reset_index(drop=True)
    oi = out["sum_open_interest"]
    out["oi_bad"] = oi.isna() | (oi <= 0)
    step, inside = oi_jump_flags(out["bulk_label_ms"].to_numpy(), oi.to_numpy())
    out["oi_jump_step"], out["oi_inside_jump"] = step, inside
    for c in BULK_RATIO_COLS + ([BULK_TAKER_COL] if keep_taker else []):
        out[f"bad_{c}"] = out[c].isna() | (out[c] <= 0)
    enforce_known_after_ts(out, "bulk metrics", known_col="known_at_oi_ms")
    return enforce_known_after_ts(out, "bulk metrics", known_col="known_at_other_ms")


def bulk_masked(df: pd.DataFrame) -> pd.DataFrame:
    """A copy with the flagged entries set to missing (never filled): the open interest columns where oi_bad or oi_inside_jump, each ratio column
    where its own bad flag is set. Flags and the input are left untouched."""
    out = df.copy()
    oi_mask = out["oi_bad"] | out["oi_inside_jump"]
    for c in BULK_OI_COLS:
        out.loc[oi_mask, c] = np.nan
    for c in BULK_RATIO_COLS:
        out.loc[out[f"bad_{c}"], c] = np.nan
    return out


def load_bulk_open_interest(path: Path) -> pd.DataFrame:
    """The open-interest part of the bulk metrics, with known_at_ms = known_at_oi_ms (our timestamp + 10 minutes from 2026-10-19 on, otherwise the day rule)."""
    b = load_bulk_metrics(path)
    cols = ["ts_ms", "known_at_ms", "bulk_label_ms", "file_date", "unverified_era"] + BULK_OI_COLS + ["oi_bad", "oi_jump_step", "oi_inside_jump"]
    out = b.assign(known_at_ms=b["known_at_oi_ms"])[cols]
    return out


def load_bulk_ratios(path: Path) -> pd.DataFrame:
    """The ratio part of the bulk metrics (taker dropped), with known_at_ms = known_at_other_ms (UTC day end + 24 h or LastModified if later)."""
    b = load_bulk_metrics(path)
    cols = ["ts_ms", "known_at_ms", "bulk_label_ms", "file_date", "unverified_era"] + BULK_RATIO_COLS + [f"bad_{c}" for c in BULK_RATIO_COLS]
    return b[cols]


# ----------------------------------------------------------------- recorder ---

def load_recorder(name: str, data_dir: Path = DEFAULT_DATA_DIR) -> pd.DataFrame:
    """One recorder history file (open_interest, global_long_short, top_position_long_short or taker_buy_sell), read once; a partial last line is ignored.

    ts_ms = the API timestamp; is_backfilled = fetched more than 15 minutes after the timestamp; known_at_ms = fetched_at_ms for live rows and
    timestamp + 10 minutes for backfilled rows. The numeric source columns follow."""
    ds = next((d for d in RECORDER_DATASETS if d.name == name), None)
    if ds is None:
        raise ValueError(f"unknown recorder dataset {name!r}")
    df = _read(ds.csv_path(Path(data_dir)), ds.columns, f"recorder {name}")
    out = pd.DataFrame({"ts_ms": pd.to_numeric(df["timestamp"]).astype("int64"), "fetched_at_ms": pd.to_numeric(df["fetched_at_ms"]).astype("int64")})
    out["is_backfilled"] = (out["fetched_at_ms"] - out["ts_ms"]) > BACKFILL_LAG_MS
    out["known_at_ms"] = np.where(out["is_backfilled"], out["ts_ms"] + RECORDER_BACKFILL_DELAY_MS, out["fetched_at_ms"])
    for c in ds.columns:
        if c in ("timestamp", "fetched_at_ms", "symbol"):
            continue
        out[c] = pd.to_numeric(df[c], errors="coerce")
    return enforce_known_after_ts(out, f"recorder {name}")


def load_recorder_snapshot(data_dir: Path = DEFAULT_DATA_DIR) -> pd.DataFrame:
    """The recorder's depth/premium snapshot. Documented choice: ts_ms = known_at_ms = fetched_at_ms (the real fetch time stamps the snapshot, so it
    cannot be known before it was taken); server_time_ms stays a column. Blank slippage cells stay missing."""
    df = _read(snapshot_path(Path(data_dir)), SNAPSHOT_COLUMNS, "recorder snapshot")
    out = pd.DataFrame({"ts_ms": pd.to_numeric(df["fetched_at_ms"]).astype("int64")})
    out["known_at_ms"] = out["ts_ms"]
    for c in SNAPSHOT_COLUMNS:
        if c != "fetched_at_ms":
            out[c] = pd.to_numeric(df[c], errors="coerce")
    out["filled_ok"] = out["filled_ok"] == 1
    return enforce_known_after_ts(out, "recorder snapshot")


# ------------------------------------------------------------------- static ---

def load_events(path: Path) -> pd.DataFrame:
    """data/static/events.csv. ts_ms = event_date_utc; known_at_ms = known_at_utc (missing when the cell is empty: such a row is never usable).

    Documented exception: a known time before the event time is allowed only when the notes explain it (static_events.validate_events); it is flagged
    in known_before_event. Columns: ts_ms, known_at_ms (nullable Int64), event_type, description, cause_status, source_url, price_evidence, notes, usable."""
    rows = se.load_rows(Path(path), se.EVENT_COLUMNS)
    ts = [se.parse_utc(r["event_date_utc"]) for r in rows]
    known = [se.parse_utc(r["known_at_utc"]) if r["known_at_utc"] else None for r in rows]
    out = pd.DataFrame({"ts_ms": pd.array(ts, dtype="Int64"), "known_at_ms": pd.array(known, dtype="Int64")})
    for c in ("event_type", "description", "cause_status", "source_url", "price_evidence", "notes"):
        out[c] = [r[c] for r in rows]
    out["usable"] = out["known_at_ms"].notna()
    out["known_before_event"] = out["usable"] & (out["known_at_ms"].astype("float64") < out["ts_ms"].astype("float64"))
    explained = out["known_before_event"] & (out["notes"] != "")
    out["ts_ms"] = out["ts_ms"].astype("int64")
    return enforce_known_after_ts(out, "events", allow=explained)


def events_known(path: Path, t_ms: int) -> pd.DataFrame:
    """The events usable at t_ms, through static_events.known_events (rows with an empty known_at_utc are never returned)."""
    rows = se.load_rows(Path(path), se.EVENT_COLUMNS)
    got = se.known_events(rows, t_ms)
    return pd.DataFrame(got, columns=se.EVENT_COLUMNS)


def time_since_tge_ms(t_ms: int) -> int:
    """Milliseconds from the token generation event (2025-07-15 00:00 UTC) to t_ms (negative before it)."""
    return int(t_ms) - TGE_MS


def _add_months(ms: int, months: int) -> int:
    d = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    y, m = divmod(d.month - 1 + months, 12)
    return int(d.replace(year=d.year + y, month=m + 1).timestamp() * 1000)


CLIFF_TERMS = {  # category -> text that must appear in its vesting_terms (data/static/tokenomics.csv); both terms are relative to TGE only
    "investors": "12-month cliff from TGE",
    "advisors": "12-month cliff from TGE",
    "early_contributors_team": "locked for 1 year from TGE",
}


def cliff_dates(tokenomics_path: Path | None = None) -> dict[str, int]:
    """Cliff (lock) end dates derived from the TGE-relative terms: investors and advisors, 12-month cliff; team, locked for 1 year (then linear).
    TGE + 12 months = 2026-07-15 for all three. With a path, the terms in tokenomics.csv are checked first and a change raises ValueError."""
    if tokenomics_path is not None:
        rows = {r["category"]: r["vesting_terms"] for r in se.load_rows(Path(tokenomics_path), se.TOKENOMICS_COLUMNS)}
        for cat, phrase in CLIFF_TERMS.items():
            if phrase.lower() not in rows.get(cat, "").lower():
                raise ValueError(f"tokenomics.csv terms for {cat} no longer say {phrase!r}")
    end = _add_months(TGE_MS, 12)
    return {cat: end for cat in CLIFF_TERMS}


# ---------------------------------------------------------------- the check ---

@dataclass
class Check:
    name: str
    loader: str
    documented: str
    source: str
    status: str  # yes / no / info


def _cmp(name: str, loader, documented, source: str, info: bool = False) -> Check:
    ok = "info" if info else ("yes" if str(loader) == str(documented) else "no")
    return Check(name, str(loader), str(documented), source, ok)


def ms_str(ms: int) -> str:
    return pd.Timestamp(int(ms), unit="ms", tz="UTC").strftime("%Y-%m-%d %H:%M")


# why a documented value may differ from today's loader value (filled in only after a mismatch has been looked at; an unexplained one is shown as such)
EXPLANATIONS: dict[str, str] = {}


def run_checks(data_dir: Path, static_dir: Path) -> tuple[list[Check], dict]:
    data_dir, static_dir = Path(data_dir), Path(static_dir)
    checks: list[Check] = []
    extra: dict = {}
    bn = load_klines(data_dir / bk.DEFAULT_OUT.name, "binance")
    by_ = load_klines(data_dir / by.DEFAULT_OUT.name, "bybit")
    checks += [
        _cmp("Binance 1m klines: rows", f"{len(bn):,}", "707,389", "quality_klines_report.md"),
        _cmp("Binance 1m klines: first open", ms_str(bn.ts_ms.min()), "2025-07-15 10:30", "quality_klines_report.md"),
        _cmp("Binance 1m klines: last open", ms_str(bn.ts_ms.max()), "2026-11-18 16:18", "quality_klines_report.md"),
        _cmp("Binance 1m klines: zero-volume candles", f"{int(bn.zero_volume.sum()):,}", "5,814", "quality_klines_report.md"),
        _cmp("Bybit 1m klines: rows", f"{len(by_):,}", "707,404", "crosscheck_klines_report.md"),
        _cmp("Bybit 1m klines: first open", ms_str(by_.ts_ms.min()), "2025-07-15 11:00", "crosscheck_klines_report.md"),
        _cmp("Bybit 1m klines: last open", ms_str(by_.ts_ms.max()), "2026-11-18 17:03", "crosscheck_klines_report.md"),
        _cmp("Bybit 1m klines: zero-volume candles", f"{int(by_.zero_volume.sum()):,}", "123,561", "crosscheck_klines_report.md"),
    ]
    fu = load_funding(data_dir / bf.DEFAULT_OUT.name)
    checks += [
        _cmp("Funding: rows", f"{len(fu):,}", "2,947", "quality_funding_report.md"),
        _cmp("Funding: first fundingTime", ms_str(fu.ts_ms.min()), "2025-07-15 12:00", "quality_funding_report.md"),
        _cmp("Funding: last fundingTime", ms_str(fu.ts_ms.max()), "2026-11-18 16:00", "quality_funding_report.md"),
    ]
    bopen = binance_open_series(data_dir / bk.DEFAULT_OUT.name)
    cg = load_coingecko(data_dir / cgm.DEFAULT_OUT.name, bopen)
    cg_cmp = cg[cg.has_binance]
    checks += [
        _cmp("CoinGecko: rows", f"{len(cg):,}", "364", "quality_daily_external_report.md"),
        _cmp("CoinGecko: days compared with Binance", f"{len(cg_cmp):,}", "363", "quality_daily_external_report.md"),
        _cmp("CoinGecko: days more than 2% off Binance", f"{int(cg_cmp.off_2pct.sum())}", "73", "quality_daily_external_report.md"),
    ]
    dp = load_defillama_price(data_dir / dl.PRICE.default_out.name, bopen)
    dp_cmp = dp[dp.has_binance]
    within1 = float((dp_cmp.binance_gap.abs() <= 0.01).mean())
    checks += [
        _cmp("DeFiLlama price: rows", f"{len(dp):,}", "493", "quality_daily_external_report.md"),
        _cmp("DeFiLlama price: days compared with Binance", f"{len(dp_cmp):,}", "491", "quality_daily_external_report.md"),
        _cmp("DeFiLlama price: share within 1% of Binance", f"{100 * within1:.1f}%", "97.6%", "quality_daily_external_report.md"),
        _cmp("DeFiLlama price: days more than 2% off Binance", f"{int(dp_cmp.off_2pct.sum())}", "3", "quality_daily_external_report.md"),
    ]
    tv = load_defillama_tvl(data_dir / dl.TVL.default_out.name)
    checks.append(_cmp("DeFiLlama TVL: rows", f"{len(tv):,}", "490", "quality_daily_external_report.md"))

    bulk = load_bulk_metrics(data_dir / BULK_NAME, keep_taker=True)
    checks += [
        _cmp("Bulk metrics normalized: rows", f"{len(bulk):,}", "141,855", "bulk_metrics_history_report.md"),
        _cmp("Bulk metrics: first bulk label", ms_str(bulk.bulk_label_ms.min()), "2025-07-15 10:30", "bulk_metrics_history_report.md"),
        _cmp("Bulk metrics: last bulk label", ms_str(bulk.bulk_label_ms.max()), "2026-11-19 23:55", "bulk_metrics_history_report.md"),
        _cmp("Bulk metrics: missing 5-minute slots", f"{missing_slots(bulk.bulk_label_ms.to_numpy())}", "3", "bulk_metrics_history_report.md"),
        _cmp("Bulk metrics: open interest at or below zero (rows)", f"{int(bulk.oi_bad.sum())}", "25", "bulk_metrics_history_report.md"),
        _cmp("Bulk metrics: one-step open-interest jumps above 50%", f"{int(bulk.oi_jump_step.sum())}", "24", "bulk_metrics_history_report.md"),
        _cmp("Bulk metrics: rows inside the jump excursions (the rule defined in this module)", f"{int(bulk.oi_inside_jump.sum())}", "no documented value", "loaders.py docstring", info=True),
        _cmp("Bulk metrics: not-a-number count_toptrader_long_short_ratio", f"{int(bulk.count_toptrader_long_short_ratio.isna().sum())}", "41", "bulk_metrics_history_report.md"),
        _cmp("Bulk metrics: not-a-number sum_toptrader_long_short_ratio", f"{int(bulk.sum_toptrader_long_short_ratio.isna().sum())}", "12", "bulk_metrics_history_report.md"),
        _cmp("Bulk metrics: not-a-number count_long_short_ratio", f"{int(bulk.count_long_short_ratio.isna().sum())}", "13", "bulk_metrics_history_report.md"),
        _cmp("Bulk metrics: not-a-number sum_taker_long_short_vol_ratio (column dropped by the loader)", f"{int(bulk[BULK_TAKER_COL].isna().sum())}", "27", "bulk_metrics_history_report.md"),
        _cmp("Bulk metrics: unverified-era rows (before 2026-07-12)", f"{int(bulk.unverified_era.sum()):,}", "104,127", "gate1_summary.md"),
    ]
    taker_in_output = BULK_TAKER_COL in load_bulk_metrics(data_dir / BULK_NAME).columns
    checks.append(_cmp("Bulk metrics: taker column absent from the loader output (decided: not used)", "yes" if not taker_in_output else "no", "yes", "bulk_metrics_history_report.md"))

    ev = load_events(static_dir / se.EVENTS_NAME)
    checks += [
        _cmp("Static events: rows", f"{len(ev)}", "25", "gate1_summary.md"),
        _cmp("Static events: sourced rows", f"{int((ev.cause_status == 'sourced').sum())}", "6", "gate1_summary.md"),
        _cmp("Static events: rows with an empty known_at_utc (never usable)", f"{int((~ev.usable).sum())}", "3", "gate1_summary.md"),
    ]
    cliffs = cliff_dates(static_dir / se.TOKENOMICS_NAME)
    checks.append(_cmp("Static tokenomics: cliff date derived from the TGE-relative terms", ms_str(cliffs["investors"]), "2026-07-15 (TGE + 12 months)", "tokenomics.csv terms; phase2_plan.md", info=True))

    rec_info = []
    for ds in RECORDER_DATASETS:
        r = load_recorder(ds.name, data_dir)
        live, back = int((~r.is_backfilled).sum()), int(r.is_backfilled.sum())
        checks.append(_cmp(f"Recorder {ds.name}: rows (live / backfilled), first, last", f"{len(r):,} ({live:,} / {back:,}), {ms_str(r.ts_ms.min())} to {ms_str(r.ts_ms.max())}",
                           "grows while the recorder runs", "quality_recorder_report.md (2026-11-19)", info=True))
        rec_info.append((ds.name, len(r), live, back))
    snap = load_recorder_snapshot(data_dir)
    checks.append(_cmp("Recorder snapshot: rows, first, last", f"{len(snap):,}, {ms_str(snap.ts_ms.min())} to {ms_str(snap.ts_ms.max())}",
                       "grows while the recorder runs", "quality_recorder_report.md (2026-11-19)", info=True))
    extra["recorder"] = rec_info
    return checks, extra


def decisions_lines() -> list[str]:
    """The decision taken by the user on 2026-11-21 after reading this check (fixed text; it is part of every generated report)."""
    return [
        "## Decisions", "",
        "**Decided by the user on 2026-11-21.**", "",
        "1. The open-interest jump rule is accepted as implemented. A jump is a one-step change in open interest of more than 50 percent between two rows "
        "whose labels are 5 minutes apart. The rows inside a jump are the whole excursion, from the row of a down jump up to, but not including, the row of the "
        "next up jump.",
        "2. The rule applies only to the bulk archive file, never to the live recorder. A real fall of more than 50 percent in open interest during a "
        "liquidation cascade must not be masked as a data glitch.", ""]


def render_check(checks: list[Check], extra: dict) -> str:
    n_yes = sum(1 for c in checks if c.status == "yes")
    n_no = sum(1 for c in checks if c.status == "no")
    n_info = sum(1 for c in checks if c.status == "info")
    L = ["# Phase 2 loaders: check against the documented numbers", "",
         f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC by `python -m tacgate.phase2.loaders --check`. The loaders read the real files read-only "
         "(nothing is written to data/ and the recorder is not touched). The recorder files keep growing, so their numbers are information, not pass or fail.", "",
         f"Result: {n_yes} match, {n_no} mismatch, {n_info} information only.", "",
         "| Check | Loader value | Documented value | Source doc | Match |", "|---|---|---|---|---|"]
    for c in checks:
        L.append(f"| {c.name} | {c.loader} | {c.documented} | {c.source} | {c.status} |")
    mism = [c for c in checks if c.status == "no"]
    L += ["", "## Mismatches", ""]
    if not mism:
        L.append("None.")
    for c in mism:
        L.append(f"- **{c.name}**: loader {c.loader}, documented {c.documented} ({c.source}). " + EXPLANATIONS.get(c.name, "UNEXPLAINED: this mismatch has not been looked at yet."))
    L += ["", "## Rules applied", "",
          "- Klines known at open + 60 s; funding at fundingTime; CoinGecko, DeFiLlama price and TVL at timestamp + 24 h; prices flagged when more than 2% from the Binance 1m open at the nearest minute.",
          "- Bulk metrics: open interest at known_at_oi_ms, ratios at known_at_other_ms, taker dropped, unverified era carried; bad rows flagged (open interest at or below zero or not a number, "
          "ratios at or below zero or not a number, the excursion rows of the 24 one-step open-interest jumps above 50%), never filled.",
          "- Recorder: live rows at fetched_at_ms, backfilled rows (fetched more than 15 minutes after the timestamp) at timestamp + 10 minutes. Static events: known_at_utc, never when empty.", ""]
    L += decisions_lines()
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 2 loaders. With --check: load the real files read-only and write the check report.")
    ap.add_argument("--check", action="store_true", help="run the check against the documented numbers")
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    ap.add_argument("--static-dir", default=str(DEFAULT_STATIC_DIR))
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    args = ap.parse_args(argv)
    if not args.check:
        ap.print_help()
        return 0
    data_dir, report = Path(args.data_dir), Path(args.report)
    r_res, d_res = report.resolve(), data_dir.resolve()
    if r_res == d_res or d_res in r_res.parents:
        print(f"Refusing: --report must not be inside the data directory {data_dir}.")
        return 2
    try:
        checks, extra = run_checks(data_dir, Path(args.static_dir))
    except (OSError, ValueError) as exc:
        print(f"Check failed to run: {exc}")
        return 2
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_check(checks, extra), encoding="utf-8")
    for c in checks:
        print(f"{c.status:4s} {c.name}: {c.loader} (documented {c.documented})")
    print(f"report: {report}")
    return 1 if any(c.status == "no" for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
