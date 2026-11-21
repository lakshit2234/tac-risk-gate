"""Tests for the Phase 2 label builder: synthetic klines with known answers, no look-ahead, NaN not 0, long/short separate, and a reproduction of docs/label_counts.md."""
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tacgate.phase2 import label_counts as lc
from tacgate.phase2 import labels as lb

MIN = 60_000
HOUR = 3_600_000
T0 = 1_700_000_040_000  # a minute boundary; arbitrary (used only with step_min=1 where the grid does not matter)
ROOT = Path(__file__).resolve().parents[1]


def klines(n, base=100.0, lows=None, highs=None, closes=None, missing=(), t0=T0):
    """n one-minute candles opening at t0 + i minutes. Every candle is flat at `base` unless overridden by {index: value}."""
    rows = []
    for i in range(n):
        if i in missing:
            continue
        c = (closes or {}).get(i, base)
        rows.append({"ts_ms": t0 + i * MIN, "high": (highs or {}).get(i, max(base, c)), "low": (lows or {}).get(i, min(base, c)), "close": c})
    return pd.DataFrame(rows)


def row_at(df, minute_index, t0=T0):
    """The row whose decision time is the open of candle `minute_index` (its reference close is candle minute_index - 1)."""
    return df[df["decision_ms"] == t0 + minute_index * MIN].iloc[0]


# ----------------------------------------------------------- known answers ---

def test_clean_drop_hits_long_only():
    k = klines(130, lows={30: 60.0})  # a fall to 60 (-40%) in the hour after candle 1
    df = lb.build_labels(k, 1, 0.30, step_min=1)
    r = row_at(df, 1)
    assert r["complete"] and r["ref_price"] == 100.0
    assert r["adverse_long"] == pytest.approx(-0.40) and r["adverse_short"] == 0.0
    assert r["label_long"] == 1.0 and r["label_short"] == 0.0


def test_clean_spike_hits_short_only():
    k = klines(130, highs={30: 140.0})
    r = row_at(lb.build_labels(k, 1, 0.30, step_min=1), 1)
    assert r["adverse_short"] == pytest.approx(0.40) and r["adverse_long"] == 0.0
    assert r["label_short"] == 1.0 and r["label_long"] == 0.0


def test_flat_series_has_no_events():
    df = lb.build_labels(klines(200), 1, 0.10, step_min=1)
    c = df[df["complete"]]
    assert len(c) > 0
    assert (c["adverse_long"] == 0).all() and (c["adverse_short"] == 0).all()
    assert (c["label_long"] == 0).all() and (c["label_short"] == 0).all()


def test_drop_just_under_and_just_over_the_threshold():
    under = lb.build_labels(klines(130, lows={30: 75.5}), 1, 0.25, step_min=1)  # -24.5%
    over = lb.build_labels(klines(130, lows={30: 74.5}), 1, 0.25, step_min=1)  # -25.5%
    assert row_at(under, 1)["label_long"] == 0.0
    assert row_at(over, 1)["label_long"] == 1.0


def test_move_of_exactly_the_threshold_counts():
    exact = lb.build_labels(klines(130, lows={30: 75.0}), 1, 0.25, step_min=1)  # 75/100 - 1 = -0.25 exactly
    assert row_at(exact, 1)["label_long"] == 1.0


def test_drop_exactly_at_the_window_edge():
    # H = 1 h = 60 candles. Decision time = open of candle 10. The window is candles 10..69 (opening in [t, t + 1 h)).
    last_inside = lb.build_labels(klines(130, lows={69: 60.0}), 1, 0.30, step_min=1)
    first_outside = lb.build_labels(klines(130, lows={70: 60.0}), 1, 0.30, step_min=1)
    assert row_at(last_inside, 10)["label_long"] == 1.0  # candle 69 opens at t + 59 min: inside
    assert row_at(first_outside, 10)["label_long"] == 0.0  # candle 70 opens at t + 60 min: outside
    # a low in the reference candle (the one that ends at t) is not in the window either
    ref_candle = lb.build_labels(klines(130, lows={9: 60.0}), 1, 0.30, step_min=1)
    assert row_at(ref_candle, 10)["label_long"] == 0.0


def test_reference_price_is_the_close_of_the_candle_ending_at_t():
    k = klines(130, closes={9: 110.0})  # candle 9 closes at 110 -> C_t for t = open of candle 10
    r = row_at(lb.build_labels(k, 1, 0.10, step_min=1), 10)
    assert r["ref_price"] == 110.0
    assert r["adverse_long"] == pytest.approx(100.0 / 110.0 - 1)


def test_columns_and_known_at():
    df = lb.build_labels(klines(130), 4, 0.1, step_min=1)
    assert list(df.columns) == ["decision_ms", "ref_price", "adverse_long", "adverse_short", "label_long", "label_short", "label_known_at_ms", "complete"]
    assert (df["label_known_at_ms"] - df["decision_ms"] == 4 * HOUR).all()


def test_step_grid_is_five_minutes_by_default():
    t0 = 1_700_000_100_000  # divisible by 5 minutes? make it so explicitly
    t0 -= t0 % (5 * MIN)
    df = lb.build_labels(klines(400, t0=t0), 1, 0.1)
    assert (df["decision_ms"] % (5 * MIN) == 0).all()
    assert df["decision_ms"].diff().dropna().eq(5 * MIN).all()


# --------------------------------------------------------------- NaN not 0 ---

def test_window_past_the_end_is_nan_not_zero():
    df = lb.build_labels(klines(130), 1, 0.10, step_min=1)
    tail = df[df["decision_ms"] > T0 + 70 * MIN]
    assert len(tail) > 0 and not tail["complete"].any()
    assert tail[["label_long", "label_short", "adverse_long", "adverse_short"]].isna().all().all()


def test_missing_minute_makes_every_containing_window_nan():
    df = lb.build_labels(klines(200, missing={50}), 1, 0.10, step_min=1)
    inside = df[(df["decision_ms"] > T0 + (50 - 60) * MIN) & (df["decision_ms"] <= T0 + 50 * MIN)]  # windows that contain candle 50
    assert len(inside) > 0 and inside["label_long"].isna().all() and inside["label_short"].isna().all()
    assert not inside["complete"].any()
    # a window after the gap is fine, and a missing reference close (t = open of candle 51) gives NaN too
    assert row_at(df, 51)["label_long"] != row_at(df, 51)["label_long"]
    assert row_at(df, 52)["complete"] and row_at(df, 52)["label_long"] == 0.0


def test_nothing_is_filled():
    df = lb.build_labels(klines(200, missing={50}), 1, 0.10, step_min=1)
    assert not df["label_long"].isin([0.0, 1.0]).all()  # NaN rows exist and stay NaN
    assert df.loc[~df["complete"], ["ref_price", "adverse_long", "adverse_short", "label_long", "label_short"]].isna().all().all()


# ------------------------------------------------------------ no look-ahead ---

def test_truncation_after_decision_time_plus_h_gives_the_same_label():
    k = klines(400, lows={200: 60.0, 300: 50.0}, highs={150: 135.0})
    full = lb.build_labels(k, 1, 0.30, step_min=1)
    for minute in (10, 100, 150, 250):
        t = T0 + minute * MIN
        cut = k[k["ts_ms"] < t + HOUR]  # keep only data up to decision time + H
        part = lb.build_labels(cut, 1, 0.30, step_min=1)
        a, b = full[full["decision_ms"] == t].iloc[0], part[part["decision_ms"] == t].iloc[0]
        assert b["complete"] and a["complete"]
        for c in ("ref_price", "adverse_long", "adverse_short", "label_long", "label_short", "label_known_at_ms"):
            assert a[c] == b[c], (minute, c)


def test_label_known_at_nothing_used_before_it():
    df = lb.build_labels(klines(400, lows={200: 60.0}), 1, 0.30, step_min=1)
    for as_of in (T0 + 30 * MIN, T0 + 100 * MIN, T0 + 250 * MIN):
        used = lb.known_labels(df, as_of)
        assert (used["label_known_at_ms"] <= as_of).all()
        assert (used["decision_ms"] + HOUR <= as_of).all()
        assert used["complete"].all() and used["label_long"].notna().all()
    # the row whose window contains the drop is not usable until its window has passed
    t = T0 + 150 * MIN  # window candles 150..209 contains candle 200
    assert t not in lb.known_labels(df, t + HOUR - MIN)["decision_ms"].to_numpy()
    assert t in lb.known_labels(df, t + HOUR)["decision_ms"].to_numpy()


def test_known_labels_is_look_ahead_free():
    from tacgate.phase2 import loaders as ld
    df = lb.build_labels(klines(400, lows={200: 60.0}), 1, 0.30, step_min=1)
    ld.assert_no_lookahead(df, T0 + 220 * MIN, fn=lb.known_labels, known_col="label_known_at_ms")


# ------------------------------------------------------ long / short apart ---

def test_long_and_short_never_mix():
    k = klines(300, lows={30: 60.0}, highs={200: 150.0})
    df = lb.build_labels(k, 1, 0.30, step_min=1)
    long_t, short_t = lb.positive_times(df, "long"), lb.positive_times(df, "short")
    assert len(long_t) > 0 and len(short_t) > 0
    assert set(long_t).isdisjoint(short_t)
    assert long_t.max() < T0 + 31 * MIN and short_t.min() > T0 + 130 * MIN
    # a fall never sets the short label and a spike never sets the long label
    assert (df.loc[df["label_long"] == 1.0, "label_short"] == 0.0).all()
    assert (df.loc[df["label_short"] == 1.0, "label_long"] == 0.0).all()
    # episodes are per side
    assert len(lb.label_episodes(df, "long", 1)) == 1 and len(lb.label_episodes(df, "short", 1)) == 1
    with pytest.raises(ValueError):
        lb.positive_times(df, "both")


def test_episodes_gap_rule():
    h = 1
    t = np.array([0, 5, 10, 70, 75, 135]) * MIN  # gap 60 -> new episode (gap >= H); gap 60 again -> new
    eps = lb.episodes(t, h)
    assert [(a // MIN, b // MIN, n) for a, b, n in eps] == [(0, 10, 3), (70, 75, 2), (135, 135, 1)]
    assert lb.episodes(np.array([0, 59 * MIN]), 1) == [(0, 59 * MIN, 2)]  # closer than H: one episode
    assert lb.episodes(np.array([]), 1) == []


def test_bad_arguments():
    with pytest.raises(ValueError):
        lb.build_labels(klines(100), 0, 0.1)
    with pytest.raises(ValueError):
        lb.build_labels(klines(100), 1, 0.0)
    with pytest.raises(ValueError):
        lb.build_labels(klines(100), 1, 0.1, step_min=0)
    with pytest.raises(ValueError):
        lb.build_labels(pd.DataFrame({"ts_ms": [1], "high": [1], "low": [1]}), 1, 0.1)


# ------------------------------------------------------------ split_periods ---

def test_split_periods():
    ms = lambda s: lb.utc_ms(s)  # noqa: E731
    d = pd.DataFrame({"decision_ms": [ms("2026-07-14T23:55:00"), ms("2026-07-15T00:00:00"), ms("2026-07-31T00:00:00"), ms("2026-07-31T00:05:00"),
                                      ms("2026-07-31T23:55:00"), ms("2026-08-01T00:00:00")]})
    p = lb.split_periods(d)
    assert p.cliff_ms == ms("2026-07-15T00:00:00")
    assert list(p.development["decision_ms"]) == list(d["decision_ms"][:3])  # up to and including 2026-07-31 00:00
    assert list(p.embargo["decision_ms"]) == list(d["decision_ms"][3:5])
    assert list(p.holdout["decision_ms"]) == [ms("2026-08-01T00:00:00")]
    assert list(p.pre_cliff["decision_ms"]) == [d["decision_ms"][0]]
    assert len(p.post_cliff) == 5
    assert len(p.development) + len(p.embargo) + len(p.holdout) == len(d) and len(p.pre_cliff) + len(p.post_cliff) == len(d)


# ------------------------------------------------------- one implementation ---

def test_label_counts_uses_the_builder():
    assert lc.Minutes is lb.Minutes and lc.episodes is lb.episodes and lc.forward_extreme is lb.forward_extreme
    k = klines(300, lows={30: 60.0}, highs={200: 150.0}, t0=T0 - T0 % (5 * MIN))
    m = lb.minutes_from_klines(k)
    a = lc.adverse_moves(m, 1)
    f = lb.adverse_frame(m, 1)
    f = f[f["complete"]]
    assert np.array_equal(a.t_ms, f["decision_ms"].to_numpy()) and np.array_equal(a.adverse_long, f["adverse_long"].to_numpy())


# ----------------------------------------------------------- reproduction ---

CELLS = [(24, 30), (4, 30), (1, 30), (24, 20), (24, 10)]  # (horizon h, threshold %) named by the task; the whole table is checked
KLINES_FILE = ROOT / "data" / "raw" / "binance_TACUSDT_1m.csv"
DOC = ROOT / "docs" / "label_counts.md"


def doc_overall():
    rx = re.compile(r"^\| (\d+) h \| (\d+)% \| (long|short) \| ([\d,]+) \| [\d.]+% \| (\d+) \|$")
    cells = {}
    for line in DOC.read_text(encoding="utf-8").splitlines():
        m = rx.match(line)
        if m:
            cells[(int(m.group(1)), int(m.group(2)), m.group(3))] = (int(m.group(4).replace(",", "")), int(m.group(5)))
    valid = {int(h): int(n.replace(",", "")) for h, n in re.findall(r"(\d+) h: ([\d,]+)", re.search(r"Valid decision times.*", DOC.read_text(encoding="utf-8")).group(0))}
    return cells, valid


@pytest.mark.skipif(not (KLINES_FILE.exists() and DOC.exists()), reason="needs the downloaded klines file and docs/label_counts.md")
def test_reproduces_every_number_in_label_counts_md():
    cells, valid = doc_overall()
    assert len(cells) == 18 and set(valid) == {1, 4, 24}
    m = lc.load_minutes(KLINES_FILE)
    for h in (1, 4, 24):
        df = lb.build_labels(m, h, 0.30)  # thresholds applied below from the adverse columns, one build per horizon
        assert int(df["complete"].sum()) == valid[h]
        for x in (10, 20, 30):
            d = lb.build_labels(m, h, x / 100)
            for side in ("long", "short"):
                pos = lb.positive_times(d, side)
                eps = lb.label_episodes(d, side, h)
                assert (len(pos), len(eps)) == cells[(h, x, side)], (h, x, side, len(pos), len(eps), cells[(h, x, side)])
    for h, x in CELLS:
        assert (h, x, "long") in cells and (h, x, "short") in cells
