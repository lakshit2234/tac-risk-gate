"""Tests for the Phase 2 label count table (synthetic klines only, no real data, no network)."""
import numpy as np
import pytest

from tacgate.data import binance_klines as bk
from tacgate.phase2 import label_counts as lc

T0 = lc.utc_ms("2026-01-30")  # a 5-minute boundary, 2 days before the month end so a month change is inside 3 days of data
MIN = lc.MIN_MS


def flat(n, price=100.0):
    return np.full(n, price), np.full(n, price), np.full(n, price)


def minutes(n=4320, drop_at=None, drop_to=70.0, spike_at=None, spike_to=130.0, first=T0):
    high, low, close = flat(n)
    if drop_at is not None:
        low[drop_at], close[drop_at:] = drop_to, drop_to
        low[drop_at:], high[drop_at:] = drop_to, np.maximum(high[drop_at:], drop_to)
        high[drop_at:] = drop_to
        high[drop_at] = 100.0
    if spike_at is not None:
        high[spike_at], close[spike_at:] = spike_to, spike_to
        high[spike_at:], low[spike_at:] = spike_to, spike_to
        low[spike_at] = 100.0
    return lc.Minutes(first, high, low, close)


# --------------------------------------------------------- primitives ---

def test_forward_extreme_window_and_missing_values():
    v = np.array([5.0, 3.0, 4.0, 1.0, 9.0, 8.0])
    assert list(lc.forward_extreme(v, 3, "min")[:4]) == [3.0, 1.0, 1.0, 1.0]
    assert list(lc.forward_extreme(v, 3, "max")[:4]) == [5.0, 4.0, 9.0, 9.0]
    assert np.isnan(lc.forward_extreme(v, 3, "min")[-1]) and np.isnan(lc.forward_extreme(v, 3, "min")[-2])  # the window runs past the end
    w = np.array([5.0, np.nan, 4.0, 1.0, 9.0, 8.0])
    out = lc.forward_extreme(w, 3, "min")
    assert np.isnan(out[0]) and np.isnan(out[1]) and out[2] == 1.0  # a window with a missing minute is not used


def test_adverse_moves_find_the_crash_for_a_long_and_nothing_for_a_short():
    k, h = 1000, 1  # the crash candle (index 1000 = a multiple of 5) and a 1-hour horizon
    a = lc.adverse_moves(minutes(drop_at=k), h)
    assert (a.t_ms % lc.GRID_MS == 0).all()
    pos = lc.positives(a, "long", 0.25)
    expected = [T0 + j * MIN for j in range(945, 1001, 5)]  # windows that contain the crash candle: j in (k - 60, k]
    assert list(pos) == expected and len(pos) == 12
    assert len(lc.positives(a, "long", 0.35)) == 0  # a 30% fall is not a 35% fall
    assert len(lc.positives(a, "short", 0.10)) == 0
    assert a.adverse_long.min() == pytest.approx(-0.30) and a.adverse_short.max() == pytest.approx(0.0)


def test_adverse_moves_for_a_spike_hit_the_short_only():
    a = lc.adverse_moves(minutes(spike_at=2000), 4)
    assert len(lc.positives(a, "short", 0.25)) == 4 * 12 and len(lc.positives(a, "long", 0.05)) == 0


def test_the_close_at_t_is_the_candle_that_ended_at_t_and_the_window_starts_at_t():
    # a fall that happened IN the candle that ends at t must not count for t (it is already in the close); one in the candle opening at t must
    high, low, close = flat(600)
    low[300], close[300:] = 50.0, 50.0  # candle 300 opens at a decision time
    m = lc.Minutes(T0, high, low, close)
    a = lc.adverse_moves(m, 1)
    t300 = T0 + 300 * MIN
    assert t300 in set(lc.positives(a, "long", 0.4))  # the fall is in the candle opening at t: counts
    assert (T0 + 305 * MIN) not in set(lc.positives(a, "long", 0.4))  # the close at that t is already 50: nothing further


def test_incomplete_forward_windows_and_gaps_are_excluded():
    m = minutes(n=300)
    a = lc.adverse_moves(m, 1)
    assert a.t_ms.max() <= T0 + (300 - 60) * MIN
    m2 = minutes(n=300)
    m2.low[100] = np.nan  # a missing minute
    t2 = lc.adverse_moves(m2, 1).t_ms
    assert not any(T0 + 41 * MIN <= t <= T0 + 100 * MIN for t in t2 if t % lc.GRID_MS == 0 and T0 + 40 * MIN < t <= T0 + 100 * MIN)


# ------------------------------------------------------------ episodes ---

def test_episodes_merge_when_closer_than_the_horizon():
    h = lc.HOUR_MS
    t = np.array([0, 5 * 60_000, 10 * 60_000, 3 * h, 3 * h + 5 * 60_000])
    assert lc.episodes(t, 1) == [(0, 10 * 60_000, 3), (3 * h, 3 * h + 5 * 60_000, 2)]
    assert len(lc.episodes(t, 4)) == 1  # 3 hours apart is closer than 4 hours: one episode
    assert len(lc.episodes(np.array([0, h]), 1)) == 2 and len(lc.episodes(np.array([0, h - 1]), 1)) == 1  # exactly H apart is separate
    assert lc.episodes(np.array([]), 1) == []
    assert lc.episodes(np.array([9, 3, 5]), 24) == [(3, 9, 3)]  # unsorted input


def test_overlapping_positive_times_are_one_episode_not_many():
    a = lc.adverse_moves(minutes(drop_at=1000), 1)
    pos = lc.positives(a, "long", 0.25)
    assert len(pos) == 12 and len(lc.episodes(pos, 1)) == 1


# ------------------------------------------------------------ counting ---

def two_crashes(gap_minutes):
    high, low, close = flat(4320)
    for k in (1000, 1000 + gap_minutes):
        new = close[k] * 0.7
        low[k:], close[k:], high[k:] = new, new, new
        low[k], high[k] = new, close[k - 1]
    return lc.Minutes(T0, high, low, close)


def test_count_table_overall_and_months_add_up():
    t = lc.count_table(minutes(drop_at=3000), horizons=(1, 4), thresholds=(0.25,))
    h1 = t["horizons"][1]
    cell = h1["cells"][(0.25, "long")]
    assert cell["positive"] == 12 and len(cell["episodes"]) == 1 and cell["episodes_by_month"] == {"2026-02": 1}
    assert sum(h1["valid_by_month"].values()) == h1["valid_decision_times"]
    assert set(h1["valid_by_month"]) == {"2026-01", "2026-02"}  # the 3 days of data cross the month end
    assert sum(cell["positive_by_month"].values()) == cell["positive"]
    assert t["horizons"][4]["cells"][(0.25, "long")]["positive"] == 4 * 12
    assert h1["cells"][(0.25, "short")]["positive"] == 0


def test_two_crashes_are_one_or_two_episodes_depending_on_the_horizon():
    m = two_crashes(gap_minutes=180)  # 3 hours apart
    t = lc.count_table(m, horizons=(1, 4), thresholds=(0.2,))
    assert len(t["horizons"][1]["cells"][(0.2, "long")]["episodes"]) == 2
    assert len(t["horizons"][4]["cells"][(0.2, "long")]["episodes"]) == 1


def test_window_counts_use_the_episode_start():
    t = lc.count_table(minutes(drop_at=3000), horizons=(1,), thresholds=(0.25,))
    start = lc.utc_ms("2026-02-01")
    inside = lc.window_counts(t, {"w": ("2026-02-01", "2026-03-01")})["w"]
    assert inside[(1, 0.25, "long")] == 1
    before = lc.window_counts(t, {"w": ("2026-01-01", "2026-02-01")})["w"]
    assert before[(1, 0.25, "long")] == 0
    assert start > T0


def test_proposed_windows_and_horizons_are_marked_as_proposals_in_the_report():
    t = lc.count_table(minutes(drop_at=3000), horizons=(1,), thresholds=(0.25,))
    text = lc.render(t, lc.window_counts(t, {"w": ("2026-02-01", "2026-03-01")}))
    assert "PROPOSALS" in text and "Episodes that START" in text and "NOT independent" in text
    assert set(lc.PROPOSED_WINDOWS) and lc.HORIZONS_H == (1, 4, 24) and lc.THRESHOLDS == (0.10, 0.20, 0.30)


# ------------------------------------------------------------- loading ---

def write_klines(path, n=600, skip=(), partial=False):
    rows = []
    for i in range(n):
        if i in skip:
            continue
        t = T0 + i * MIN
        rows.append(f"{t},100,101,99,100,1,{t + 59_999},1,1,1,1,0")
    text = ",".join(bk.COLUMNS) + "\n" + "\n".join(rows) + "\n"
    if partial:
        text += f"{T0 + n * MIN},100,10"
    path.write_text(text)


def test_load_minutes_puts_a_missing_minute_at_nan_and_ignores_a_partial_line(tmp_path):
    p = tmp_path / bk.DEFAULT_OUT.name
    write_klines(p, n=10, skip=(4,), partial=True)
    m = lc.load_minutes(p)
    assert m.n == 10 and np.isnan(m.low[4]) and m.low[3] == 99 and m.high[0] == 101 and m.first_open == T0


def test_main_is_read_only_and_refuses_a_report_inside_the_data_dir(tmp_path, capsys):
    data = tmp_path / "raw"
    data.mkdir()
    write_klines(data / bk.DEFAULT_OUT.name, n=2000)
    before = (data / bk.DEFAULT_OUT.name).read_bytes()
    assert lc.main(["--data-dir", str(data), "--report", str(data / "r.md")]) == 2
    assert "Refusing" in capsys.readouterr().out
    report = tmp_path / "docs" / "r.md"
    assert lc.main(["--data-dir", str(data), "--report", str(report)]) == 0
    assert report.exists() and (data / bk.DEFAULT_OUT.name).read_bytes() == before
    assert lc.main(["--data-dir", str(tmp_path / "nope"), "--report", str(report)]) == 2
