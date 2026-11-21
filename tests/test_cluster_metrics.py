"""Tests for the cluster-aware capture and remaining-move metrics. Synthetic data only."""
import numpy as np
import pandas as pd
import pytest

from tacgate.phase2 import cluster_metrics as cm
from tacgate.phase2 import labels as lb
from tacgate.phase2 import walkforward as wf

MIN = 60_000
H = 3_600_000
GRID = 5 * MIN
T0 = (1_700_000_000_000 // GRID) * GRID
N = 8000


def mins(close=None, high=None, low=None, n=N):
    c = np.full(n, 100.0) if close is None else np.array(close, dtype=float)
    hi = c.copy() if high is None else np.array(high, dtype=float)
    lo = c.copy() if low is None else np.array(low, dtype=float)
    return lb.minutes_from_klines(pd.DataFrame({"ts_ms": T0 + np.arange(n) * MIN, "high": hi, "low": lo, "close": c}))


def grid(n=N):
    t = T0 + np.arange(1, n + 1) * MIN
    return t[t % GRID == 0]


def alarm_on(T, *ranges_min):
    """Stay-out at the decision times T0 + a min .. T0 + b min (inclusive)."""
    a = np.zeros(len(T), bool)
    for lo, hi in ranges_min:
        a |= (T >= T0 + lo * MIN) & (T <= T0 + hi * MIN)
    return a


def ep(start_min, event_min):
    return wf.Episode(T0 + start_min * MIN, T0 + start_min * MIN + 5 * MIN, 2, T0 + event_min * MIN)


# ---------------------------------------------------------------- clusters ---

def test_cluster_grouping_chained_and_split():
    day = 24 * 60
    eps = [ep(h * 60, h * 60 + 60) for h in (0, 20, 40, 70)]
    assert cm.cluster_groups(eps) == [[0, 1, 2], [3]]  # 0-20 h and 20-40 h chain, 40-70 h (30 h) splits
    assert cm.cluster_groups([ep(0, 60), ep(day, day + 60), ep(2 * day, 2 * day + 60), ep(3 * day, 3 * day + 60)]) == [[0, 1, 2, 3]]  # exactly 24 h each: chained
    assert cm.cluster_groups([ep(0, 60), ep(day, day + 60)]) == [[0, 1]]  # the boundary: exactly 24 h is within
    assert cm.cluster_groups([ep(0, 60), ep(day + 5, day + 65)]) == [[0], [1]]  # 24 h and 5 minutes is not
    assert cm.cluster_groups([ep(3000, 3060), ep(0, 60), ep(100, 160)]) == [[1, 2], [0]]  # sorted by start, indexes into the input
    assert cm.cluster_groups([]) == [] and cm.cluster_groups([ep(0, 60)]) == [[0]]
    assert cm.CLUSTER_GAP_MS == 24 * H and cm.ALARM_LOOKBACK_MS == 24 * H and cm.REMAINING_HORIZON_MIN == 1440 and cm.MIN_CLUSTERS == 4


def test_first_episode_of_each_cluster_is_the_one_tested():
    T, m = grid(), mins()
    eps = [ep(10 * 60, 12 * 60), ep(30 * 60, 32 * 60), ep(50 * 60, 52 * 60), ep(90 * 60, 92 * 60)]  # clusters: [0, 1, 2] and [3]
    # the alarm covers the lead windows of the 2nd and 3rd episodes only (aftershocks): all-episode capture 2 of 4, cluster-aware 0 of 2
    a = alarm_on(T, (32 * 60 - 60, 32 * 60 - 5), (52 * 60 - 60, 52 * 60 - 5))
    s = cm.summarize(T, a, eps, m, "long")
    assert (s["episodes"], s["clusters"], s["captured_episodes"], s["cluster_captured"]) == (4, 2, 2, 0)
    assert s["cluster_verdict"] == "TOO FEW" and s["cluster_ci_low"] == 0.0
    # the alarm covers the first episode of each cluster: cluster-aware 2 of 2, all-episode 2 of 4
    a2 = alarm_on(T, (12 * 60 - 60, 12 * 60 - 5), (92 * 60 - 60, 92 * 60 - 5))
    s2 = cm.summarize(T, a2, eps, m, "long")
    assert (s2["captured_episodes"], s2["cluster_captured"], s2["clusters"]) == (2, 2, 2) and s2["cluster_rate"] == 1.0
    # an alarm one decision time before the lead window, or at the event time itself, does not capture
    a3 = alarm_on(T, (12 * 60 - 65, 12 * 60 - 65), (12 * 60, 12 * 60))
    assert not cm.episode_flags(T, a3, eps[:1])[0]
    # four clusters is enough for a verdict
    eps4 = [ep(h * 60, h * 60 + 120) for h in (10, 40, 70, 100)]
    s4 = cm.summarize(T, np.zeros(len(T), bool), eps4, m, "long")
    assert s4["clusters"] == 4 and s4["cluster_verdict"] == "" and s4["cluster_captured"] == 0
    assert s4["cluster_ci_high"] == pytest.approx(1 - 0.025 ** 0.25, abs=1e-6)


def test_cluster_capture_uses_the_harness_rule():
    T, m = grid(), mins()
    eps = [ep(h * 60, h * 60 + 90) for h in (10, 40, 80, 120, 160)]
    rng = np.random.default_rng(3)
    a = rng.random(len(T)) < 0.3
    flags = cm.episode_flags(T, a, eps)
    states = {"long": np.where(a, 2, 0).astype("int8"), "short": np.zeros(len(T), "int8")}
    metrics = wf.compute_metrics(T, states, {(v, s): eps for v in wf.VIEWS for s in wf.SIDES})
    c = metrics["views"][wf.view_key(wf.PRIMARY_VIEW)]["long"]["60min"]["stay_out"]["all"]
    assert (c["episodes"], c["captured"]) == (len(eps), int(flags.sum()))  # the same capture as the harness: existing metrics are unchanged
    assert metrics == wf.compute_metrics(T, states, {(v, s): eps for v in wf.VIEWS for s in wf.SIDES})  # and deterministic


# ----------------------------------------------------------- remaining move ---

def long_case(close_alarm=95.0):
    close = np.full(N, 100.0)
    low = close.copy()
    close[649] = close_alarm  # the reference price at the alarm time (decision time = minute 650)
    low[700] = 57.0  # the event candle
    low[900] = 47.5  # the lowest low in the 24 hours after the alarm
    low[2300] = 60.0  # the not-captured episode
    return mins(close=close, low=low)


def test_remaining_and_already_happened_move_hand_computed():
    m, T = long_case(), grid()
    eps = [ep(600, 700), ep(2200, 2300)]  # the second one is far away (> 24 h): its own cluster
    a = alarm_on(T, (650, 699))
    mv = cm.episode_moves(T, a, eps, m, "long")
    assert mv[0].captured and mv[0].alarm_ms == T0 + 650 * MIN
    assert mv[0].remaining == pytest.approx(1 - 47.5 / 95.0) == pytest.approx(0.5)  # lowest low in [650, 650 + 24 h) against the close at minute 649
    assert mv[0].already == pytest.approx(1 - 95.0 / 100.0)  # from the reference price of the episode's first positive decision time (100) to the one at the alarm (95)
    assert not mv[1].captured and mv[1].alarm_ms is None and np.isnan(mv[1].already)
    assert mv[1].remaining == pytest.approx(0.4) == pytest.approx(mv[1].whole)  # nothing protected: the whole move
    s = cm.summarize(T, a, eps, m, "long")
    assert s["remaining_captured"] == {"n": 1, "median": pytest.approx(0.5), "min": pytest.approx(0.5), "max": pytest.approx(0.5)}
    assert s["already_captured"]["median"] == pytest.approx(0.05) and s["whole_not_captured"]["median"] == pytest.approx(0.4)
    assert s["remaining_all_episodes"]["median"] == pytest.approx(0.45) and (s["clusters"], s["captured_episodes"], s["not_measurable"]) == (2, 1, 0)
    # the price went the other way before the alarm: the already-happened move is negative
    up = cm.episode_moves(T, a, eps[:1], long_case(close_alarm=105.0), "long")[0]
    assert up.already == pytest.approx(-0.05)


def test_short_side_uses_the_highs_and_the_rise():
    close, high = np.full(N, 100.0), np.full(N, 100.0)
    close[649] = 104.0
    high[700], high[1000] = 130.0, 156.0
    m, T = mins(close=close, high=high), grid()
    mv = cm.episode_moves(T, alarm_on(T, (650, 699)), [ep(600, 700)], m, "short")[0]
    assert mv.remaining == pytest.approx(156.0 / 104.0 - 1) == pytest.approx(0.5) and mv.already == pytest.approx(104.0 / 100.0 - 1)
    with pytest.raises(ValueError):
        cm.episode_moves(T, alarm_on(T, (650, 699)), [ep(600, 700)], m, "both")


def test_alarm_lookback_is_capped_at_24_hours_before_the_event():
    close, low = np.full(N, 100.0), np.full(N, 100.0)
    close[559] = 90.0  # the close at minute 560 = event (2000) - 24 h
    low[700] = 54.0
    m, T = mins(close=close, low=low), grid()
    e = [ep(1900, 2000)]
    a = alarm_on(T, (100, 2100))  # the spell began long before the cap
    mv = cm.episode_moves(T, a, e, m, "long")[0]
    assert mv.captured and mv.alarm_ms == e[0].event_ms - 24 * H == T0 + 560 * MIN
    assert mv.remaining == pytest.approx(1 - 54.0 / 90.0) == pytest.approx(0.4)
    # a spell that only starts inside the lead window: the alarm time is its first decision time
    mv2 = cm.episode_moves(T, alarm_on(T, (1950, 2100)), e, m, "long")[0]
    assert mv2.alarm_ms == T0 + 1950 * MIN
    # a spell that ended before the lead window: no such spell, not captured
    mv3 = cm.episode_moves(T, alarm_on(T, (100, 500)), e, m, "long")[0]
    assert not mv3.captured and mv3.alarm_ms is None
    # an earlier, separate spell is not the one that covers the lead window
    mv4 = cm.episode_moves(T, alarm_on(T, (600, 700), (1980, 1995)), e, m, "long")[0]
    assert mv4.alarm_ms == T0 + 1980 * MIN


def test_a_window_past_the_end_of_the_data_is_not_measurable_and_not_invented():
    m, T = mins(n=2000), grid(2000)
    mv = cm.episode_moves(T, alarm_on(T, (1090, 1190)), [ep(1000, 1200)], m, "long")[0]
    assert mv.captured and np.isnan(mv.remaining)  # 1090 + 24 h is past the data
    s = cm.summarize(T, alarm_on(T, (1090, 1190)), [ep(1000, 1200)], m, "long")
    assert s["not_measurable"] == 1 and s["remaining_captured"]["n"] == 0 and s["remaining_captured"]["median"] is None


def test_long_and_short_never_mix():
    close, low, high = np.full(N, 100.0), np.full(N, 100.0), np.full(N, 100.0)
    low[700], high[3000] = 60.0, 150.0
    m, T = mins(close=close, low=low, high=high), grid()
    long_eps, short_eps = [ep(600, 700)], [ep(2900, 3000)]
    long_alarm = alarm_on(T, (650, 699))
    none = np.zeros(len(T), bool)
    sl, ss = cm.summarize(T, long_alarm, long_eps, m, "long"), cm.summarize(T, none, short_eps, m, "short")
    assert sl["captured_episodes"] == 1 and sl["remaining_captured"]["median"] == pytest.approx(0.4)  # the fall, from the lows
    assert ss["captured_episodes"] == 0 and ss["whole_not_captured"]["median"] == pytest.approx(0.5)  # the rise, from the highs
    # the long alarm series does not capture the short episode and the short series does not capture the long one
    assert cm.summarize(T, long_alarm, short_eps, m, "short")["captured_episodes"] == 0
    assert cm.summarize(T, alarm_on(T, (2950, 2999)), long_eps, m, "long")["captured_episodes"] == 0
    # a fall never counts as a short move and a rise never as a long move
    assert cm.episode_moves(T, none, [ep(600, 700)], m, "short")[0].whole == pytest.approx(0.0)
    assert cm.episode_moves(T, none, short_eps, m, "long")[0].whole == pytest.approx(0.0)


# ---------------------------------------------------------- regression ---

def test_diff_finds_any_difference_and_counts_values():
    a = {"x": [1, 2.5, None], "y": {"z": "t", "k": 0.1}}
    assert cm.diff(a, {"x": [1, 2.5, None], "y": {"z": "t", "k": 0.1}}) == ([], 5)
    d, n = cm.diff(a, {"x": [1, 2.5000000000000004, None], "y": {"z": "t", "k": 0.1}})
    assert len(d) == 1 and "x[1]" in d[0] and n == 5
    assert cm.diff({"a": 1}, {"b": 1})[0] and cm.diff([1], [1, 2])[0]


def test_existing_harness_values_are_unchanged():
    fx = wf.fixed_values()
    assert (fx["n_shifts"], fx["shift_seed"], fx["min_episodes"], fx["primary_lead_min"], fx["first_test_month"]) == (1000, 20261121, 4, 60, "2025-09")
    assert wf.clopper_pearson(0, 4)[1] == pytest.approx(0.6023, abs=1e-3) and cm.LEAD_MIN == wf.PRIMARY_LEAD_MIN
    # the harness functions used here are the harness's own (nothing re-implemented)
    assert cm.wf is wf
