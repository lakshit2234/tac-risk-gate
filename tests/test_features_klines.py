"""Tests for the Phase 2 price-based features: known answers on hand-made klines, truncation, gaps, warm-up, known_at, bounds. No labels anywhere."""
import math
import statistics

import numpy as np
import pandas as pd
import pytest

from tacgate.phase2 import features_klines as fk

MIN = 60_000
GRID = 5 * MIN
T0 = (1_700_000_000_000 // GRID) * GRID  # first candle opens on a 5-minute boundary
LONG = 11_700  # > 7 days + 24 h of candles, so every feature can be valid
W = dict(fk.WINDOWS)


def klines(n, close=None, high=None, low=None, vol=None, taker=None, missing=(), offset=0):
    """n one-minute candles opening at T0 + (offset + i) minutes. Defaults: flat price 100, volume 10, taker buy 4."""
    i = np.arange(n)
    c = np.full(n, 100.0) if close is None else np.asarray(close, dtype=float)
    h = c.copy() if high is None else np.asarray(high, dtype=float)
    lo = c.copy() if low is None else np.asarray(low, dtype=float)
    v = np.full(n, 10.0) if vol is None else np.asarray(vol, dtype=float)
    tk = np.full(n, 4.0) if taker is None else np.asarray(taker, dtype=float)
    keep = np.array([k not in set(missing) for k in i])
    return pd.DataFrame({"ts_ms": T0 + (offset + i[keep]) * MIN, "high": h[keep], "low": lo[keep], "close": c[keep], "volume": v[keep], "taker_buy_base_volume": tk[keep]})


def row(f, j):
    """The feature row at decision time T0 + j minutes (the candle that closed then is candle j - 1)."""
    return f[f["decision_ms"] == T0 + j * MIN].iloc[0]


def rnd(n, seed, missing=(), offset=0):
    r = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(r.normal(0, 0.003, n)))
    h, lo = c * (1 + r.uniform(0, 0.004, n)), c * (1 - r.uniform(0, 0.004, n))
    v = r.integers(0, 1000, n).astype(float)
    tk = np.floor(v * r.uniform(0, 1, n))
    return klines(n, close=c, high=h, low=lo, vol=v, taker=tk, missing=missing, offset=offset)


def cut(df, t_ms):
    """Only the candles known at t: open + 60 s <= t."""
    return df[df["ts_ms"] + MIN <= t_ms]


# ------------------------------------------------------------ known answers ---

def test_windows_are_the_fixed_list():
    assert fk.WINDOWS == (("15m", 15), ("1h", 60), ("4h", 240), ("24h", 1440)) and fk.BASELINE_DAYS == 7
    assert len(fk.FEATURE_COLUMNS) == 7 * 4 + 2


def test_known_answers_15m():
    n = 40
    c = 100.0 + np.arange(n)
    h, lo = c + 1, c - 1
    h[30], lo[35] = 150.0, 60.0
    v, tk = np.full(n, 10.0), np.full(n, 4.0)
    v[35], tk[35] = 30.0, 30.0
    r = row(fk.build_features(klines(n, close=c, high=h, low=lo, vol=v, taker=tk)), 40)  # window = candles 25..39, C_t = close of candle 39 = 139
    assert r["ret_15m"] == pytest.approx(139 / 124 - 1)  # close of candle 24, which closed at t - 15 min
    assert r["rv_15m"] == pytest.approx(statistics.stdev([math.log(c[i] / c[i - 1]) for i in range(25, 40)]))
    assert r["drawdown_15m"] == pytest.approx(139 / 150 - 1)
    assert r["runup_15m"] == pytest.approx(139 / 60 - 1)
    assert r["range_15m"] == pytest.approx((150 - 60) / 139)
    assert r["taker_buy_share_15m"] == pytest.approx((14 * 4 + 30) / (14 * 10 + 30))
    # one hour needs 61 closes: not there yet
    assert np.isnan(r["ret_1h"]) and np.isnan(r["volume_ratio_15m"])


def test_flat_series_values():
    f = fk.build_features(klines(LONG), klines(LONG))
    r = row(f, LONG)
    for lab, _ in fk.WINDOWS:
        assert r[f"ret_{lab}"] == 0 and r[f"rv_{lab}"] == 0 and r[f"drawdown_{lab}"] == 0 and r[f"runup_{lab}"] == 0 and r[f"range_{lab}"] == 0
        assert r[f"taker_buy_share_{lab}"] == pytest.approx(0.4) and r[f"volume_ratio_{lab}"] == pytest.approx(1.0)
    assert r["bybit_gap"] == 0 and r["bybit_gap_abs_max_1h"] == 0


def test_volume_ratio_known_answers_and_baseline_span():
    j = 10_400
    v = np.full(j, 10.0)
    v[j - 15:] = 20.0  # the 15-minute window just ended has double volume
    r = row(fk.build_features(klines(j, vol=v)), j)
    assert r["volume_ratio_15m"] == pytest.approx(300 / 150)  # baseline = 672 windows of 150
    assert r["volume_ratio_1h"] == pytest.approx((45 * 10 + 15 * 20) / 600)  # the 7 days BEFORE the window: the current window is not in its own baseline
    assert r["volume_ratio_4h"] == pytest.approx((225 * 10 + 15 * 20) / 2400)
    assert np.isnan(r["volume_ratio_24h"])  # warm-up: 7 days + 24 h of history needed
    # a heavy window inside the baseline span moves the baseline by one window out of 672; a spike just before the span does not
    v2 = v.copy()
    v2[j - 30:j - 15] = 40.0  # baseline window k = 1 for 15 m
    assert row(fk.build_features(klines(j, vol=v2)), j)["volume_ratio_15m"] == pytest.approx(300 / ((671 * 150 + 600) / 672))
    v3 = v.copy()
    v3[j - 10_096] = 1000.0  # the candle just before the oldest baseline window (candles j - 10095 ... j - 16)
    assert row(fk.build_features(klines(j, vol=v3)), j)["volume_ratio_15m"] == pytest.approx(2.0)


def test_bybit_gap_and_abs_max():
    n = 200
    yb = np.full(n, 101.0)
    yb[n - 30] = 105.0  # inside the last hour
    yb[n - 80] = 150.0  # outside the last hour
    f = fk.build_features(klines(n), klines(n, close=yb, high=yb, low=yb))
    r = row(f, n)
    assert r["bybit_gap"] == pytest.approx((100 - 101) / 100)
    assert r["bybit_gap_abs_max_1h"] == pytest.approx(0.05)
    # a missing Bybit minute in the last hour makes the 1h maximum NaN, not the gap at t
    f2 = fk.build_features(klines(n), klines(n, missing={n - 10}))
    assert np.isnan(row(f2, n)["bybit_gap_abs_max_1h"]) and not np.isnan(row(f2, n)["bybit_gap"])
    # a missing Bybit candle at t itself makes the gap NaN
    f3 = fk.build_features(klines(n), klines(n, missing={n - 1}))
    assert np.isnan(row(f3, n)["bybit_gap"])
    # no Bybit data at all: NaN, nothing else changes
    f4 = fk.build_features(klines(n))
    assert f4[list(fk.SINGLE)].isna().all().all() and f4["ret_15m"].equals(f["ret_15m"])


# ---------------------------------------------------------------- truncation ---

def test_truncation_every_feature():
    b, y = rnd(12_000, 1, missing={3_000, 9_000, 11_000}), rnd(11_990, 2, missing={3_002, 10_500}, offset=30)
    full = fk.build_features(b, y)
    for j in (1_440, 3_000, 3_005, 3_010, 9_000, 9_005, 10_100, 11_005, 11_530, 11_990):  # includes decision times at and right after a gap
        t = T0 + j * MIN
        part = fk.build_features(cut(b, t), cut(y, t))
        a, p = full[full["decision_ms"] == t], part[part["decision_ms"] == t]
        assert len(a) == 1 and len(p) == 1, j
        for c in fk.FEATURE_COLUMNS:
            np.testing.assert_array_equal(a[c].to_numpy(), p[c].to_numpy(), err_msg=f"{c} at j={j}")


def test_known_at_candle_closing_at_t_is_used_and_later_ones_are_not():
    j = 600
    base = fk.build_features(klines(j + 5), klines(j + 5))
    c = np.full(j + 5, 100.0)
    c[j - 1] = 110.0  # the candle that closes at exactly t
    used = fk.build_features(klines(j + 5, close=c, high=c, low=c), klines(j + 5))
    assert row(used, j)["ret_15m"] == pytest.approx(0.10) and row(used, j)["bybit_gap"] == pytest.approx(10 / 110)
    # the candle that closes at t + 1 minute (opens at t) and the next ones: wild values, the row at t must not change
    h, lo, cc = np.full(j + 5, 100.0), np.full(j + 5, 100.0), np.full(j + 5, 100.0)
    cc[j:], h[j:], lo[j:] = 500.0, 900.0, 1.0
    future = fk.build_features(klines(j + 5, close=cc, high=h, low=lo, vol=np.full(j + 5, 10.0) * np.r_[np.ones(j), np.full(5, 99.0)]),
                               klines(j + 5, close=cc, high=h, low=lo))
    for col in fk.FEATURE_COLUMNS:
        np.testing.assert_array_equal(row(future, j)[col], row(base, j)[col], err_msg=col)
    # the next decision time (t + 5 min) does use them
    assert row(future, j + 5)["ret_15m"] == pytest.approx(4.0)
    # and the last decision time of a table is the one whose newest candle just closed: no row exists for a time whose candle is not in the data
    assert fk.build_features(klines(j))["decision_ms"].max() == T0 + j * MIN


# ----------------------------------------------------------------------- gaps ---

def test_one_missing_minute_makes_exactly_the_affected_features_nan():
    j, m = 11_620, 11_600  # the missing candle is candle j - 20: inside 1 h, 4 h, 24 h, outside 15 m
    f = fk.build_features(rnd(LONG, 3, missing={m}), rnd(LONG, 4))
    r, clean = row(f, j), row(fk.build_features(rnd(LONG, 3), rnd(LONG, 4)), j)
    expect_nan = {c for c in fk.FEATURE_COLUMNS if c.rsplit("_", 1)[1] in ("1h", "4h", "24h") and not c.startswith("bybit")}
    expect_nan |= {"volume_ratio_15m", "bybit_gap_abs_max_1h"}  # candle m is inside the 15 m baseline window k = 1 and inside the last hour
    assert {c for c in fk.FEATURE_COLUMNS if np.isnan(r[c])} == expect_nan
    for c in set(fk.FEATURE_COLUMNS) - expect_nan:  # and the others are the values the clean data give
        assert r[c] == clean[c], c
    # a decision time before the gap is not affected at all
    before = row(f, 11_540)
    assert before[list(fk.FEATURE_COLUMNS)].notna().all()
    assert (before[list(fk.FEATURE_COLUMNS)] == row(fk.build_features(rnd(LONG, 3), rnd(LONG, 4)), 11_540)[list(fk.FEATURE_COLUMNS)]).all()
    # the window moves past the gap: 15 m features are NaN only while the gap is inside (candles j - 16 .. j - 1)
    assert np.isnan(row(f, 11_605)["ret_15m"]) and np.isnan(row(f, 11_615)["ret_15m"]) and not np.isnan(row(f, 11_620)["ret_15m"])
    # nothing is filled: no value is invented for the missing minute
    assert np.isnan(row(f, 11_605)["drawdown_15m"])


# --------------------------------------------------------------------- warm-up ---

def test_warm_up_is_nan_until_enough_history():
    f = fk.build_features(klines(LONG), klines(LONG, offset=30)[:LONG - 30])
    first = {"ret_15m": 20, "rv_15m": 20, "drawdown_15m": 15, "runup_15m": 15, "range_15m": 15, "taker_buy_share_15m": 15, "volume_ratio_15m": 10_095,
             "ret_1h": 65, "drawdown_1h": 60, "volume_ratio_1h": 10_140, "ret_4h": 245, "volume_ratio_4h": 10_320, "ret_24h": 1_445, "drawdown_24h": 1_440,
             "volume_ratio_24h": 11_520, "bybit_gap": 35, "bybit_gap_abs_max_1h": 90}
    js = np.arange(5, LONG + 1, 5)
    for col, j0 in first.items():
        valid = f.set_index("decision_ms").loc[T0 + js * MIN, col].notna().to_numpy()
        assert not valid[js < j0].any(), (col, "valid too early")
        assert valid[js >= j0].all(), (col, "NaN after warm-up")


# ----------------------------------------------------------------- invariants ---

def test_bounds_on_random_data():
    f = fk.build_features(rnd(LONG, 5), rnd(LONG, 6))
    for lab, _ in fk.WINDOWS:
        t = f[f"taker_buy_share_{lab}"].dropna()
        assert len(t) > 0 and t.between(0, 1).all()
        assert (f[f"drawdown_{lab}"].dropna() <= 0).all() and (f[f"runup_{lab}"].dropna() >= 0).all()
        assert (f[f"range_{lab}"].dropna() >= 0).all() and (f[f"rv_{lab}"].dropna() >= 0).all() and (f[f"volume_ratio_{lab}"].dropna() >= 0).all()
    assert (f["bybit_gap_abs_max_1h"].dropna() >= 0).all()


def test_zero_volume_window_taker_share_is_nan_not_zero():
    r = row(fk.build_features(klines(40, vol=np.zeros(40), taker=np.zeros(40))), 40)
    assert np.isnan(r["taker_buy_share_15m"]) and r["range_15m"] == 0


def test_inputs_and_no_label_code():
    with pytest.raises(ValueError):
        fk.build_features(klines(50, close=np.r_[np.full(49, 100.0), 0.0], high=np.full(50, 100.0), low=np.full(50, 100.0)))
    with pytest.raises(ValueError):
        fk.build_features(klines(50).drop(columns=["volume"]))
    with pytest.raises(ValueError):
        fk.build_features(pd.concat([klines(10), klines(10)]))
    assert not hasattr(fk, "build_labels") and "label" not in "".join(fk.FEATURE_COLUMNS)


def test_development_rows_cut():
    from tacgate.phase2 import labels as lb
    d = pd.DataFrame({"decision_ms": [lb.DEVELOPMENT_END_MS - GRID, lb.DEVELOPMENT_END_MS, lb.DEVELOPMENT_END_MS + GRID, lb.HOLDOUT_START_MS]})
    assert list(fk.development_rows(d)["decision_ms"]) == [lb.DEVELOPMENT_END_MS - GRID, lb.DEVELOPMENT_END_MS]


def test_gap_runs():
    assert fk.gap_runs(klines(20, missing={5, 6, 12})) == [(T0 + 5 * MIN, 2), (T0 + 12 * MIN, 1)]
    assert fk.gap_runs(klines(20)) == []
