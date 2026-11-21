"""Tests for the Phase 2 loaders (tiny synthetic files only: no network, no real data)."""
import csv
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tacgate.data import binance_funding as bf
from tacgate.data import binance_klines as bk
from tacgate.data import bulk_metrics_history as bm
from tacgate.data import bybit_klines as by
from tacgate.data import coingecko_market_chart as cgm
from tacgate.data import defillama as dl
from tacgate.data import static_events as se
from tacgate.data.recorder import DATASETS, SNAPSHOT_COLUMNS, snapshot_path
from tacgate.phase2 import loaders as ld

MIN = 60_000
DAY = 86_400_000


def ms(text):
    return ld.utc_ms(text)


T0 = ms("2026-10-20")


def write_csv(path, columns, rows, partial=""):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(columns)
        w.writerows(rows)
    if partial:
        with open(path, "a", newline="") as f:
            f.write(partial)  # no trailing newline: a file being appended to
    return path


# ---------------------------------------------------------------- generic ---

def test_asof_returns_only_rows_known_at_or_before_t_and_never_missing_known_times():
    t = pd.DataFrame({"ts_ms": [1, 2, 3, 4], "known_at_ms": pd.array([10, 20, 30, None], dtype="Int64"), "v": [1, 2, 3, 4]})
    assert list(ld.asof(t, 20)["v"]) == [1, 2]
    assert list(ld.asof(t, 9)["v"]) == []
    assert list(ld.asof(t, 10**9)["v"]) == [1, 2, 3]  # the row with no known time is never returned
    assert list(ld.asof(t, 20, known_col="ts_ms")["v"]) == [1, 2, 3, 4]


def test_the_lookahead_utility_passes_for_asof_and_fails_for_a_leaky_function():
    t = pd.DataFrame({"ts_ms": np.arange(10), "known_at_ms": np.arange(10) * 10, "v": np.arange(10.0)})
    ld.assert_no_lookahead(t, 35)
    ld.assert_no_lookahead(t, 0)
    ld.assert_no_lookahead(t, 10**6)

    def leaky(table, t_ms):  # peeks at the whole table
        return table.assign(future_max=table["v"].max())[table["known_at_ms"] <= t_ms]

    with pytest.raises(AssertionError):
        ld.assert_no_lookahead(t, 35, fn=leaky)

    def mean_of_known(table, t_ms):  # an honest feature
        k = table[table["known_at_ms"] <= t_ms]
        return pd.DataFrame({"m": [k["v"].mean()]})

    ld.assert_no_lookahead(t, 35, fn=mean_of_known)


def test_known_after_ts_check_counts_and_allows_documented_exceptions():
    df = pd.DataFrame({"ts_ms": [10, 20, 30], "known_at_ms": [10, 15, 40]})
    assert ld.check_known_after_ts(df) == 1
    assert ld.check_known_after_ts(df, allow=pd.Series([False, True, False])) == 0
    with pytest.raises(ld.KnownTimeError):
        ld.enforce_known_after_ts(df, "x")
    ok = pd.DataFrame({"ts_ms": [10], "known_at_ms": pd.array([None], dtype="Int64")})
    assert ld.check_known_after_ts(ok) == 0  # a missing known time is "not usable", not a violation


def test_missing_slots_counts_gaps_without_adding_rows():
    assert ld.missing_slots(np.array([0, 300_000, 900_000, 1_200_000])) == 1
    assert ld.missing_slots(np.array([0, 300_000])) == 0 and ld.missing_slots(np.array([])) == 0


# ----------------------------------------------------------------- klines ---

def binance_rows(opens, vol=10):
    return [[t, 1, 2, 0.5, 1.5, vol, t + 59_999, 3, 4, 5, 6, 0] for t in opens]


def test_binance_klines_are_known_at_the_candle_close(tmp_path):
    p = write_csv(tmp_path / "k.csv", bk.COLUMNS, binance_rows([T0, T0 + MIN, T0 + 2 * MIN]))
    df = ld.load_klines(p, "binance")
    assert list(df["ts_ms"]) == [T0, T0 + MIN, T0 + 2 * MIN]
    assert list(df["known_at_ms"] - df["ts_ms"]) == [60_000] * 3
    assert {"open", "high", "low", "close", "volume", "quote_volume", "trades", "taker_buy_base_volume", "zero_volume"} <= set(df.columns)
    assert "close_time" not in df.columns and "ignore" not in df.columns
    assert df["ts_ms"].dtype == np.int64 and df["known_at_ms"].dtype == np.int64


def test_bybit_klines_known_at_close_zero_volume_flag_and_no_filling(tmp_path):
    rows = [[T0, 1, 2, 0.5, 1.5, 0, 0], [T0 + 3 * MIN, 1, 2, 0.5, 1.5, 7, 3]]  # a gap of two minutes between the rows
    p = write_csv(tmp_path / "b.csv", by.COLUMNS, rows)
    df = ld.load_klines(p, "bybit")
    assert len(df) == 2  # nothing was added for the missing minutes
    assert list(df["zero_volume"]) == [True, False] and list(df["known_at_ms"]) == [T0 + MIN, T0 + 4 * MIN]
    assert "turnover" in df.columns


def test_klines_ignore_a_partial_last_line_and_reject_a_wrong_header(tmp_path):
    p = write_csv(tmp_path / "k.csv", bk.COLUMNS, binance_rows([T0, T0 + MIN]), partial=f"{T0 + 2 * MIN},1,2,0.5")
    assert len(ld.load_klines(p)) == 2
    q = write_csv(tmp_path / "bad.csv", ["a", "b"], [[1, 2]])
    with pytest.raises(ValueError):
        ld.load_klines(q)
    with pytest.raises(ValueError):
        ld.load_klines(p, "kraken")


def test_loaders_only_read_files(tmp_path):
    p = write_csv(tmp_path / "k.csv", bk.COLUMNS, binance_rows([T0]))
    before = p.read_bytes()
    ld.load_klines(p)
    assert p.read_bytes() == before


# ---------------------------------------------------------------- funding ---

def test_funding_is_known_at_its_funding_time_even_with_millisecond_jitter(tmp_path):
    rows = [["TACUSDT", T0 + 5, "0.00005", "0.002", "Regular"], ["TACUSDT", T0 + 14_400_000 + 2, "", "0.002", "Regular"]]
    df = ld.load_funding(write_csv(tmp_path / "f.csv", bf.FUNDING_COLUMNS, rows))
    assert list(df["ts_ms"]) == [T0 + 5, T0 + 14_400_000 + 2] and list(df["known_at_ms"]) == list(df["ts_ms"])  # never earlier
    assert list(df["bad_value"]) == [False, True] and np.isnan(df["fundingRate"].iloc[1])  # missing stays missing


# ---------------------------------------------------------- daily external ---

def binance_open(minute_prices):
    return pd.Series(list(minute_prices.values()), index=list(minute_prices.keys()), dtype="float64")


def test_price_gap_uses_the_nearest_minute_open_and_a_strict_two_percent_limit():
    mid = ms("2026-10-20")
    bo = binance_open({mid: 100.0, mid - MIN: 50.0})
    ts = np.array([mid + 20_000, mid + 40_000, mid - 20_000])  # 20 s after, 40 s after (rounds to the next minute: no data), 20 s before (rounds to mid)
    g = ld.price_gap(ts, np.array([101.99, 100.0, 101.9]), bo)
    assert list(g["has_binance"]) == [True, False, True]  # mid + 40 s rounds to mid + 1 minute, which has no Binance candle
    assert g["binance_gap"].iloc[0] == pytest.approx(0.0199) and g["off_2pct"].iloc[0] == False  # noqa: E712  (the limit is strict: more than 2%, as in quality_daily_external.py)
    assert g["off_2pct"].iloc[2] == False and g["binance_gap"].iloc[2] == pytest.approx(0.019)  # noqa: E712
    g2 = ld.price_gap(np.array([mid]), np.array([102.1]), bo)
    assert bool(g2["off_2pct"].iloc[0]) is True
    none = ld.price_gap(np.array([mid]), np.array([1.0]), None)
    assert bool(none["has_binance"].iloc[0]) is False


def cg_rows(mid, prices, mc=8e6, vol=3e6):
    return [[mid + i * DAY, p, mc, vol, mid + (i + 2) * DAY] for i, p in enumerate(prices)]


def test_coingecko_known_at_plus_24h_flags_prices_and_keeps_market_cap_usable(tmp_path):
    mid = ms("2026-10-19")
    bo = binance_open({mid: 100.0, mid + DAY: 100.0, mid + 2 * DAY: 100.0})  # no candle for mid + 3 days
    p = write_csv(tmp_path / "cg.csv", cgm.COLUMNS, cg_rows(mid, [101.0, 103.0, 98.5, 100.0]))
    df = ld.load_coingecko(p, bo)
    assert list(df["known_at_ms"] - df["ts_ms"]) == [DAY] * 4
    assert list(df["off_2pct"]) == [False, True, False, False] and list(df["has_binance"]) == [True, True, True, False]
    m = ld.masked_prices(df)
    assert m["price"].isna().tolist() == [False, True, False, True]  # flagged, and the one that cannot be checked
    assert (m["market_cap"] == 8e6).all() and (m["total_volume"] == 3e6).all()  # still usable
    assert df["price"].notna().all()  # the input is untouched


def test_defillama_price_jitter_and_tvl(tmp_path):
    mid = ms("2026-10-19")
    ts = [mid + 1_000, mid + DAY - 18_000]  # seconds either side of a midnight
    bo = binance_open({mid: 100.0, mid + DAY: 100.0})
    p = write_csv(tmp_path / "dp.csv", dl.PRICE.columns, [[ts[0], 99.5, 0.99, mid + 3 * DAY], [ts[1], 104.0, 0.99, mid + 3 * DAY]])
    df = ld.load_defillama_price(p, bo)
    assert list(df["known_at_ms"]) == [ts[0] + DAY, ts[1] + DAY] and list(df["off_2pct"]) == [False, True] and list(df["has_binance"]) == [True, True]
    tv = ld.load_defillama_tvl(write_csv(tmp_path / "tv.csv", dl.TVL.columns, [[mid, 5e6, mid + 2 * DAY], [mid + DAY, "", mid + 3 * DAY]]))
    assert list(tv["known_at_ms"]) == [mid + DAY, mid + 2 * DAY] and list(tv["bad_value"]) == [False, True]


def test_a_row_fetched_before_its_known_time_is_fine_but_known_before_ts_is_an_error():
    df = pd.DataFrame({"ts_ms": [1000], "known_at_ms": [500]})
    with pytest.raises(ld.KnownTimeError):
        ld.enforce_known_after_ts(df, "x")


# ------------------------------------------------------------ bulk jumps ---

LAB = np.arange(8, dtype="int64") * 300_000


def test_jump_rule_flags_the_excursion_rows_between_a_down_and_an_up_jump():
    oi = np.array([100, 100, 10, 10, 100, 100, 100, 100], dtype=float)
    step, inside = ld.oi_jump_flags(LAB, oi)
    assert list(np.flatnonzero(step)) == [2, 4]  # the 2 jump steps (the rows that jumped)
    assert list(np.flatnonzero(inside)) == [2, 3]  # the rows from the down jump up to, not including, the up jump


def test_jump_rule_threshold_zero_and_unclosed_cases():
    exactly_half = np.array([100, 50, 50, 50, 50, 50, 50, 50], dtype=float)
    assert not ld.oi_jump_flags(LAB, exactly_half)[0].any()  # exactly 50% is not above 50%
    just_over = np.array([100, 49.9, 50, 50, 50, 50, 50, 50], dtype=float)
    assert ld.oi_jump_flags(LAB, just_over)[0][1]
    zero = np.array([100, 0, 0, 100, 100, 100, 100, 100], dtype=float)  # a drop to zero (-100%) and a rise from zero (+inf)
    step, inside = ld.oi_jump_flags(LAB, zero)
    assert list(np.flatnonzero(step)) == [1, 3] and list(np.flatnonzero(inside)) == [1, 2]
    up_only = np.array([10, 10, 100, 100, 100, 100, 100, 100], dtype=float)
    step, inside = ld.oi_jump_flags(LAB, up_only)
    assert list(np.flatnonzero(step)) == [2] and list(np.flatnonzero(inside)) == [2]  # an up jump with no open excursion flags only its own row
    unclosed = np.array([100, 100, 100, 10, 10, 10, 10, 10], dtype=float)
    step, inside = ld.oi_jump_flags(LAB, unclosed)
    assert list(np.flatnonzero(inside)) == [3, 4, 5, 6, 7]  # still open at the end of the data


def test_jump_steps_need_labels_exactly_five_minutes_apart():
    lab = np.array([0, 300_000, 900_000, 1_200_000], dtype="int64")  # a missing slot between rows 1 and 2
    step, inside = ld.oi_jump_flags(lab, np.array([100.0, 100.0, 10.0, 10.0]))
    assert not step.any() and not inside.any()


def test_the_documented_twenty_four_pattern_is_reproduced_by_twelve_excursions():
    # 12 excursions = 24 one-step jumps, like the documented count (2025-07-21 and 2026-10-15): drop to ~18% for two rows, then back
    oi, lab, t = [], [], 0
    for _ in range(12):
        for v in (100, 100, 18, 18, 100, 100):
            oi.append(float(v))
            lab.append(t)
            t += 300_000
    step, inside = ld.oi_jump_flags(np.array(lab), np.array(oi))
    assert int(step.sum()) == 24 and int(inside.sum()) == 24  # two interior rows per excursion


# -------------------------------------------------------------- bulk file ---

def bulk_rows(n, day="2026-10-19", oi=None, ratios=None, taker=None, start="2026-10-19 00:00:00"):
    lm = ms("2026-10-21") + 8 * 3_600_000
    text = [",".join(bm.METRIC_COLS)]
    t0 = datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp() * 1000
    for i in range(n):
        lab = datetime.fromtimestamp((t0 + i * 300_000) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        o = 1000.0 + i if oi is None else oi[i]
        r = [1.5, 1.2, 1.6] if ratios is None else ratios[i]
        tk = 0.9 if taker is None else taker[i]
        text.append(f"{lab},TACUSDT,{o},{o * 2},{r[0]},{r[1]},{r[2]},{tk}")
    return bm.day_rows("\n".join(text) + "\n", day, lm)


def write_bulk(path, rows):
    return write_csv(path, bm.OUT_COLUMNS, rows)


def test_bulk_loader_known_times_flags_and_dropped_taker(tmp_path):
    n = 12
    oi = [1000.0] * n
    oi[3] = 0.0  # open interest at zero
    ratios = [[1.5, 1.2, 1.6] for _ in range(n)]
    ratios[5] = [float("nan"), 1.2, 1.6]  # not a number
    ratios[6] = [1.5, -1.0, 1.6]  # at or below zero
    ratios[7] = [1.5, 1.2, 0.0]
    taker = [0.9] * n
    taker[2] = float("nan")
    rows = bulk_rows(n, oi=oi, ratios=ratios, taker=taker)
    p = write_bulk(tmp_path / "bulk.csv", rows)
    df = ld.load_bulk_metrics(p)
    assert ld.BULK_TAKER_COL not in df.columns and "bad_" + ld.BULK_TAKER_COL not in df.columns  # decided: not used
    assert ld.BULK_TAKER_COL in ld.load_bulk_metrics(p, keep_taker=True).columns
    # known times come from the normalized file: open interest 10 minutes after our timestamp (from 2026-10-19), the rest at the day rule
    assert list(df["known_at_oi_ms"] - df["ts_ms"]) == [600_000] * n
    assert (df["known_at_other_ms"] == ms("2026-10-21")).all() or (df["known_at_other_ms"] >= ms("2026-10-21")).all()
    assert (df["known_at_ms"] == df["known_at_other_ms"]).all()
    assert df["ts_ms"].iloc[0] == df["bulk_label_ms"].iloc[0] + 300_000  # label + 5 min before 2026-11-16
    assert list(np.flatnonzero(df["oi_bad"])) == [3]
    assert list(np.flatnonzero(df["bad_count_toptrader_long_short_ratio"])) == [5]
    assert list(np.flatnonzero(df["bad_sum_toptrader_long_short_ratio"])) == [6]
    assert list(np.flatnonzero(df["bad_count_long_short_ratio"])) == [7]
    k = ld.load_bulk_metrics(p, keep_taker=True)
    assert list(np.flatnonzero(k["bad_" + ld.BULK_TAKER_COL])) == [2]
    assert df["unverified_era"].dtype == bool and not df["unverified_era"].any()
    assert df["sum_open_interest"].iloc[3] == 0.0  # the raw value is kept


def test_bulk_masked_sets_only_flagged_entries_to_missing_and_never_fills(tmp_path):
    oi = [1000.0, 1000.0, 0.0, 1000.0, 1000.0, 1000.0]
    ratios = [[1.5, 1.2, 1.6]] * 6
    ratios = [list(r) for r in ratios]
    ratios[1][1] = -3.0
    rows = bulk_rows(6, oi=oi, ratios=ratios)
    raw = ld.load_bulk_metrics(write_bulk(tmp_path / "b.csv", rows))
    m = ld.bulk_masked(raw)
    assert m["sum_open_interest"].isna().tolist() == [False, False, True, False, False, False]
    assert m["sum_open_interest_value"].isna().tolist() == m["sum_open_interest"].isna().tolist()
    assert m["sum_toptrader_long_short_ratio"].isna().tolist() == [False, True, False, False, False, False]
    assert m["count_long_short_ratio"].notna().all()  # a bad value in one ratio column does not touch another
    assert m["sum_open_interest"].iloc[3] == 1000.0  # the next row is not filled from its neighbour or changed
    assert raw["sum_open_interest"].iloc[2] == 0.0 and raw["sum_toptrader_long_short_ratio"].iloc[1] == -3.0  # raw untouched
    assert raw["oi_bad"].iloc[2] and m["oi_bad"].iloc[2]  # the flags stay


def test_bulk_masked_also_removes_open_interest_inside_a_jump_excursion(tmp_path):
    oi = [100.0, 100.0, 10.0, 10.0, 100.0, 100.0, 100.0, 100.0]
    raw = ld.load_bulk_metrics(write_bulk(tmp_path / "b.csv", bulk_rows(8, oi=oi)))
    assert int(raw["oi_jump_step"].sum()) == 2 and list(np.flatnonzero(raw["oi_inside_jump"])) == [2, 3]
    m = ld.bulk_masked(raw)
    assert m["sum_open_interest"].isna().tolist() == [False, False, True, True, False, False, False, False]
    assert m["count_long_short_ratio"].notna().all()  # the ratios are not implicated by an open-interest jump


def test_bulk_split_loaders_use_their_own_known_times_and_drop_taker(tmp_path):
    p = write_bulk(tmp_path / "b.csv", bulk_rows(4))
    o, r = ld.load_bulk_open_interest(p), ld.load_bulk_ratios(p)
    assert list(o["known_at_ms"] - o["ts_ms"]) == [600_000] * 4  # open interest: our timestamp + 10 minutes
    assert (r["known_at_ms"] >= ms("2026-10-21")).all() and (r["known_at_ms"] > o["known_at_ms"]).all()  # ratios: the day rule, later
    assert ld.BULK_TAKER_COL not in r.columns and "sum_open_interest" not in r.columns and "count_long_short_ratio" not in o.columns
    assert {"oi_bad", "oi_jump_step", "oi_inside_jump"} <= set(o.columns) and "bad_count_long_short_ratio" in r.columns
    # the look-ahead rule holds for both tables
    for t in (o, r):
        ld.assert_no_lookahead(t, int(t["known_at_ms"].iloc[1]))


def test_bulk_unverified_era_and_the_label_change_come_from_the_file(tmp_path):
    early = bulk_rows(2, day="2026-07-10", start="2026-07-10 00:00:00")
    late = bulk_rows(2, day="2026-11-16", start="2026-11-16 00:00:00")
    df = ld.load_bulk_metrics(write_bulk(tmp_path / "b.csv", early + late))
    assert list(df["unverified_era"]) == [True, True, False, False]
    assert df["ts_ms"].iloc[0] == df["bulk_label_ms"].iloc[0] + 300_000 and df["ts_ms"].iloc[2] == df["bulk_label_ms"].iloc[2]
    assert df["known_at_oi_ms"].iloc[0] == df["known_at_other_ms"].iloc[0]


# --------------------------------------------------------------- recorder ---

def recorder_file(tmp_path, name, rows, partial=""):
    ds = next(d for d in DATASETS if d.name == name)
    return write_csv(ds.csv_path(tmp_path), ds.columns, rows, partial=partial)


def oi_row(ts, fetched, oi=1000.0):
    return ["TACUSDT", oi, oi * 2, 6e9, ts, fetched]


def test_recorder_live_rows_known_at_fetch_and_backfilled_rows_at_timestamp_plus_10_minutes(tmp_path):
    live_ts, back_ts = T0, T0 - DAY
    rows = [oi_row(back_ts, T0 + 3_600_000),  # fetched an hour later: backfilled
            oi_row(live_ts, live_ts + 400_000),  # 6.7 minutes: live
            oi_row(live_ts + 300_000, live_ts + 300_000 + 15 * MIN),  # exactly 15 minutes: live (the rule is "above 15 minutes")
            oi_row(live_ts + 600_000, live_ts + 600_000 + 15 * MIN + 1)]  # 1 ms over: backfilled
    df = ld.load_recorder("open_interest", recorder_file(tmp_path, "open_interest", rows).parent)
    assert list(df["is_backfilled"]) == [True, False, False, True]
    assert list(df["known_at_ms"]) == [back_ts + 10 * MIN, live_ts + 400_000, live_ts + 300_000 + 15 * MIN, live_ts + 600_000 + 10 * MIN]
    assert (df["known_at_ms"] >= df["ts_ms"]).all() and {"sumOpenInterest", "sumOpenInterestValue", "CMCCirculatingSupply"} <= set(df.columns)


def test_recorder_partial_last_line_is_ignored_and_the_file_is_not_changed(tmp_path):
    p = recorder_file(tmp_path, "open_interest", [oi_row(T0, T0 + 400_000)], partial=f"TACUSDT,1,2,3,{T0 + 300_000}")
    before = p.read_bytes()
    df = ld.load_recorder("open_interest", tmp_path)
    assert len(df) == 1 and p.read_bytes() == before


def test_recorder_row_fetched_before_its_timestamp_is_rejected(tmp_path):
    recorder_file(tmp_path, "open_interest", [oi_row(T0, T0 - 1000)])
    with pytest.raises(ld.KnownTimeError):
        ld.load_recorder("open_interest", tmp_path)


def test_recorder_taker_file_and_unknown_dataset(tmp_path):
    recorder_file(tmp_path, "taker_buy_sell", [[0.9, 100.0, 110.0, T0, T0 + 6 * MIN]])
    df = ld.load_recorder("taker_buy_sell", tmp_path)
    assert list(df["known_at_ms"]) == [T0 + 6 * MIN] and "buySellRatio" in df.columns
    with pytest.raises(ValueError):
        ld.load_recorder("nope", tmp_path)


def test_recorder_snapshot_is_stamped_by_its_fetch_time_and_blank_cells_stay_missing(tmp_path):
    row = {c: "" for c in SNAPSHOT_COLUMNS}
    row.update(fetched_at_ms=T0 + 5, server_time_ms=T0 + 9, mark="0.001", filled_ok="0")  # the server time is slightly AFTER our fetch time (clock skew)
    write_csv(snapshot_path(tmp_path), SNAPSHOT_COLUMNS, [[row[c] for c in SNAPSHOT_COLUMNS]])
    df = ld.load_recorder_snapshot(tmp_path)
    assert list(df["ts_ms"]) == [T0 + 5] and list(df["known_at_ms"]) == [T0 + 5] and df["server_time_ms"].iloc[0] == T0 + 9
    assert np.isnan(df["slippage_bps_buy_1000"].iloc[0]) and bool(df["filled_ok"].iloc[0]) is False


# ----------------------------------------------------------------- static ---

def event(date, known, typ="other", notes="", status="unverified", url="", evidence="", desc="x"):
    return [date, typ, desc, known, status, url, evidence, notes]


def test_events_with_an_empty_known_time_are_never_usable(tmp_path):
    rows = [event("2026-01-10T00:00:00Z", "2026-01-10T12:00:00Z", desc="a"),
            event("2026-01-11T00:00:00Z", "", desc="b", status="sourced", url="https://x.example/1"),
            event("2026-01-12T00:00:00Z", "2026-01-13T00:00:00Z", desc="c")]
    p = write_csv(tmp_path / "events.csv", se.EVENT_COLUMNS, rows)
    df = ld.load_events(p)
    assert list(df["usable"]) == [True, False, True] and df["known_at_ms"].isna().tolist() == [False, True, False]
    assert df["ts_ms"].dtype == np.int64
    late = ms("2027-01-01")
    assert list(ld.asof(df, late)["description"]) == ["a", "c"]  # the empty known_at row is never returned, however late
    assert list(ld.events_known(p, late)["description"]) == ["a", "c"]  # same through static_events.known_events
    assert list(ld.events_known(p, ms("2026-01-10T11:00:00Z".replace("T", " ").replace("Z", "")))["description"]) == []
    ld.assert_no_lookahead(df, ms("2026-01-12"))


def test_events_known_before_the_event_are_allowed_only_with_an_explanation(tmp_path):
    explained = [event("2026-01-10T00:00:00Z", "2026-01-09T00:00:00Z", notes="announced a day ahead by the source")]
    df = ld.load_events(write_csv(tmp_path / "e1.csv", se.EVENT_COLUMNS, explained))
    assert bool(df["known_before_event"].iloc[0]) is True and bool(df["usable"].iloc[0]) is True  # the documented exception
    with pytest.raises(ld.KnownTimeError):
        ld.load_events(write_csv(tmp_path / "e2.csv", se.EVENT_COLUMNS, [event("2026-01-10T00:00:00Z", "2026-01-09T00:00:00Z")]))


def test_time_since_tge_and_cliff_dates(tmp_path):
    assert ld.time_since_tge_ms(ld.TGE_MS) == 0 and ld.time_since_tge_ms(ms("2025-07-16")) == DAY and ld.time_since_tge_ms(ms("2025-07-14")) == -DAY
    assert ld.TGE_MS == ms("2025-07-15")
    cl = ld.cliff_dates()
    assert set(cl) == {"investors", "advisors", "early_contributors_team"} and set(cl.values()) == {ms("2026-07-15")}
    rows = [["investors", "16.6", "12-month cliff from TGE, then linear vesting over 24 months.", "https://x.example", "2026-11-20", "sourced"],
            ["advisors", "3.4", "Same terms as investors: 12-month cliff from TGE, then linear.", "https://x.example", "2026-11-20", "sourced"],
            ["early_contributors_team", "22.1", "Fully locked for 1 year from TGE, then linear.", "https://x.example", "2026-11-20", "sourced"]]
    good = write_csv(tmp_path / "t.csv", se.TOKENOMICS_COLUMNS, rows)
    assert ld.cliff_dates(good)["investors"] == ms("2026-07-15")
    rows[0][2] = "6-month cliff from TGE"
    with pytest.raises(ValueError):
        ld.cliff_dates(write_csv(tmp_path / "t2.csv", se.TOKENOMICS_COLUMNS, rows))  # the terms changed: refuse to derive a date


# -------------------------------------------------------------------- CLI ---

def test_cli_refuses_a_report_inside_the_data_dir_and_prints_help_without_check(tmp_path, capsys):
    assert ld.main(["--check", "--data-dir", str(tmp_path), "--report", str(tmp_path / "r.md")]) == 2
    assert "Refusing" in capsys.readouterr().out
    assert ld.main([]) == 0 and "--check" in capsys.readouterr().out
    assert ld.main(["--check", "--data-dir", str(tmp_path / "empty"), "--static-dir", str(tmp_path), "--report", str(tmp_path.parent / "r.md")]) == 2


def test_check_report_marks_a_mismatch_and_requires_an_explanation():
    checks = [ld.Check("a", "1", "2", "doc.md", "no"), ld.Check("b", "1", "1", "doc.md", "yes"), ld.Check("c", "5", "grows", "doc.md", "info")]
    text = ld.render_check(checks, {})
    assert "1 match, 1 mismatch, 1 information only" in text and "UNEXPLAINED" in text
    assert ld._cmp("x", "5", "5", "d").status == "yes" and ld._cmp("x", "5", "6", "d").status == "no" and ld._cmp("x", "5", "6", "d", info=True).status == "info"


def test_check_report_ends_with_the_jump_rule_decision():
    text = ld.render_check([], {})
    assert "## Decisions" in text and "Decided by the user on 2026-11-21" in text
    assert "whole excursion" in text and "never to the live recorder" in text and "must not be masked as a data glitch" in text
    assert text.rstrip().endswith("must not be masked as a data glitch.")


def test_the_recorder_loader_applies_no_jump_rule(tmp_path):
    # a real 90% fall in open interest in the live recorder file stays an ordinary, unflagged, unmasked value
    rows = [oi_row(T0 + i * 300_000, T0 + i * 300_000 + 400_000, oi=v) for i, v in enumerate([1000.0, 1000.0, 100.0, 100.0, 1000.0])]
    df = ld.load_recorder("open_interest", recorder_file(tmp_path, "open_interest", rows).parent)
    assert df["sumOpenInterest"].tolist() == [1000.0, 1000.0, 100.0, 100.0, 1000.0]
    assert not any(c.startswith("oi_") or c.startswith("bad_") for c in df.columns)
