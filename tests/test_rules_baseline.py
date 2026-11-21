"""Tests for the Phase 2 Gate 2 baseline rules. Synthetic data only; temporary trial-log and results paths only."""
import inspect

import numpy as np
import pandas as pd
import pytest

from tacgate.phase2 import features_klines as fk
from tacgate.phase2 import labels as lb
from tacgate.phase2 import rules_baseline as rb
from tacgate.phase2 import walkforward as wf

MIN = 60_000
T = lambda s: wf.utc_ms(s)  # noqa: E731
START = T("2025-08-30T00:00:00")
DAYS = 40
CRASHES = [T(x) for x in ("2025-09-03T12:03:00", "2025-09-09T12:03:00", "2025-09-15T12:03:00", "2025-10-01T06:03:00")]


@pytest.fixture(autouse=True)
def synthetic_dates(monkeypatch):
    monkeypatch.setattr(lb, "DEVELOPMENT_END_MS", T("2025-10-03T00:00:00"))
    monkeypatch.setattr(lb, "HOLDOUT_START_MS", T("2025-10-04T00:00:00"))


def klines(seed=0, n=DAYS * 1440, crashes=CRASHES):
    r = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(r.normal(0, 0.002, n)))
    hi, lo = c * (1 + r.uniform(0, 0.002, n)), c * (1 - r.uniform(0, 0.002, n))
    for b in crashes:
        lo[(b - START) // MIN] = c[(b - START) // MIN] * 0.6
    v = r.integers(1, 1000, n).astype(float)
    return pd.DataFrame({"ts_ms": START + np.arange(n) * MIN, "high": hi, "low": lo, "close": c, "volume": v, "taker_buy_base_volume": np.floor(v * 0.4)})


def funding(first="2025-08-30T08:00:00", days=DAYS, seed=1):
    r = np.random.default_rng(seed)
    t = np.arange(T(first), START + days * 1440 * MIN, 8 * 3_600_000)
    return pd.DataFrame({"ts_ms": t, "known_at_ms": t, "fundingRate": r.normal(0, 0.0005, len(t)), "markPrice": 100.0, "bad_value": False})


def train(**cols):
    n = len(next(iter(cols.values())))
    return pd.DataFrame({**cols, "label_known_at_ms": np.zeros(n, dtype="int64")})


def fitted(name, **cols):
    rule = {r.name: r for r in rb.make_rules()}[name]
    rule.fit(train(**cols))
    return rule


LIN = np.linspace(0, 1, 1001)  # percentiles: 5th 0.05, 10th 0.10, 90th 0.90, 95th 0.95


# ------------------------------------------------------------- the states ---

def test_fixed_constants():
    assert (rb.PCT_STAY_OUT_HIGH, rb.PCT_CAUTION_HIGH, rb.PCT_STAY_OUT_LOW, rb.PCT_CAUTION_LOW) == (95, 90, 5, 10)
    assert rb.RULE_NAMES == tuple(r.name for r in rb.make_rules()) and rb.TRIAL_FAMILY == "stage_a_baseline"


def test_r1_realized_volatility_states_and_same_for_both_sides():
    r = fitted("realized_volatility", rv_1h=LIN)
    assert r({"rv_1h": 0.96}) == (2, 2) and r({"rv_1h": r.cutoffs["long"][0]}) == (2, 2)  # at or beyond the 95th percentile (exactly at the cut-off counts)
    assert r({"rv_1h": 0.92}) == (1, 1) and r({"rv_1h": r.cutoffs["long"][1]}) == (1, 1)
    assert r({"rv_1h": 0.8999}) == (0, 0) and r({"rv_1h": 0.0}) == (0, 0)  # the low tail is not used
    assert r({"rv_1h": float("nan")}) == (0, 0) and r.n_nan == {"long": 1, "short": 1}


def test_r3_exchange_gap_states_and_same_for_both_sides():
    r = fitted("exchange_gap", bybit_gap_abs_max_1h=LIN)
    assert r({"bybit_gap_abs_max_1h": 0.99}) == (2, 2) and r({"bybit_gap_abs_max_1h": 0.93}) == (1, 1) and r({"bybit_gap_abs_max_1h": 0.2}) == (0, 0)
    assert r({"bybit_gap_abs_max_1h": float("nan")}) == (0, 0) and r.n_nan == {"long": 1, "short": 1}


def test_r2_funding_opposite_tails_for_long_and_short():
    r = fitted("funding_extreme", funding_rate=np.linspace(-1, 1, 2001))  # 5th -0.9, 10th -0.8, 90th 0.8, 95th 0.9
    assert r({"funding_rate": 0.95}) == (2, 0)  # high funding is risky for the long side only
    assert r({"funding_rate": 0.85}) == (1, 0)
    assert r({"funding_rate": -0.95}) == (0, 2)  # low funding is risky for the short side only
    assert r({"funding_rate": -0.85}) == (0, 1)
    assert r({"funding_rate": r.cutoffs["short"][0]}) == (0, 2) and r({"funding_rate": r.cutoffs["long"][0]}) == (2, 0)  # exactly at the cut-off
    assert r({"funding_rate": 0.0}) == (0, 0)
    assert r({"funding_rate": float("nan")}) == (0, 0) and r.n_nan == {"long": 1, "short": 1}


def test_r4_price_cascade_uses_drawdown_for_long_and_runup_for_short():
    r = fitted("price_cascade", drawdown_1h=-LIN, runup_1h=LIN)  # drawdown 5th = -0.95, 10th = -0.90; runup 90th 0.90, 95th 0.95
    assert r({"drawdown_1h": -0.97, "runup_1h": 0.0}) == (2, 0)
    assert r({"drawdown_1h": -0.92, "runup_1h": 0.0}) == (1, 0)
    assert r({"drawdown_1h": 0.0, "runup_1h": 0.97}) == (0, 2)
    assert r({"drawdown_1h": 0.0, "runup_1h": 0.92}) == (0, 1)
    assert r({"drawdown_1h": 0.0, "runup_1h": 0.0}) == (0, 0)
    # the opposite tails do nothing: a high drawdown value (near 0) and a low runup value never alarm
    assert r({"drawdown_1h": -0.01, "runup_1h": 0.01}) == (0, 0)
    assert r({"drawdown_1h": -0.97, "runup_1h": 0.97}) == (2, 2)


def test_long_and_short_never_mix_when_one_input_is_nan():
    r = fitted("price_cascade", drawdown_1h=-LIN, runup_1h=LIN)
    assert r({"drawdown_1h": -0.97, "runup_1h": float("nan")}) == (2, 0) and r.n_nan == {"long": 0, "short": 1}
    assert r({"drawdown_1h": float("nan"), "runup_1h": 0.97}) == (0, 2) and r.n_nan == {"long": 1, "short": 1}
    assert [x.spec for x in rb.make_rules() if x.name == "funding_extreme"][0] == {"long": (rb.FUNDING_COLUMN, "high"), "short": (rb.FUNDING_COLUMN, "low")}
    assert [x.spec for x in rb.make_rules() if x.name == "price_cascade"][0] == {"long": ("drawdown_1h", "low"), "short": ("runup_1h", "high")}


# ---------------------------------------------------------------------- fit ---

def test_fit_takes_cutoffs_from_the_given_training_rows_only():
    x = np.r_[np.linspace(0, 1, 501), [np.nan, np.nan, np.inf]]  # NaN and inf are not training values
    r = rb.make_rules()[0]
    r.fit(train(rv_1h=x))
    clean = x[np.isfinite(x)]
    assert r.cutoffs["long"] == (np.percentile(clean, 95), np.percentile(clean, 90)) and r.cutoffs["short"] == r.cutoffs["long"]
    before = dict(r.cutoffs)
    for v in (5.0, 0.0, 100.0):  # using the rule never moves the cut-offs
        r({"rv_1h": v})
    assert r.cutoffs == before
    r.fit(train(rv_1h=np.linspace(0, 10, 501)))  # the next month: new cut-offs from the new training rows
    assert r.cutoffs["long"][0] == pytest.approx(9.5) and len(r.history) == 2 and r.history[0]["n_train_rows"] == 504


def test_fit_and_call_errors():
    r = rb.make_rules()[0]
    with pytest.raises(RuntimeError):
        r({"rv_1h": 1.0})  # not fitted
    with pytest.raises(ValueError):
        r.fit(pd.DataFrame({"rv_1h": LIN}))  # not the harness's training rows
    with pytest.raises(KeyError):
        r.fit(train(other=LIN))
    r.fit(train(rv_1h=np.full(10, np.nan)))  # nothing usable: every state is 0, nothing is invented
    assert r({"rv_1h": 5.0}) == (0, 0)


@pytest.fixture
def small_ds():
    b = klines()
    return rb.add_funding(wf.build_dataset(b, b), funding())


def test_fit_with_a_leaking_training_set_raises_in_the_harness(small_ds, monkeypatch):
    real = wf.train_rows

    def leaky(d, start):
        t = real(d, start)
        t.loc[t.index[-1], "label_known_at_ms"] = start + 1
        return t
    monkeypatch.setattr(wf, "train_rows", leaky)
    for rule in rb.make_rules():
        with pytest.raises(wf.EmbargoError):
            wf.run_gate(rule, small_ds, wf.month_blocks(small_ds))


def test_training_rows_seen_by_fit_are_known_before_the_month(small_ds):
    seen = []

    class Spy(rb.PercentileRule):
        def fit(self, t):
            seen.append((t["label_known_at_ms"].max(), len(t)))
            super().fit(t)
    rule = Spy("spy", "rv_1h", rb.HIGH, "rv_1h", rb.HIGH)
    wf.run_gate(rule, small_ds, wf.month_blocks(small_ds))
    starts = [b[1] for b in wf.month_blocks(small_ds)]
    assert len(seen) == 2 and all(k <= s and n > 0 for (k, n), s in zip(seen, starts))


# ---------------------------------------------------------------- funding ---

def test_funding_known_time_never_uses_a_rate_stamped_after_t():
    t0 = T("2025-09-01T00:00:00")
    f = pd.DataFrame({"ts_ms": [t0 - 3_600_000, t0 + 10 * MIN], "known_at_ms": [t0 - 3_600_000, t0 + 10 * MIN], "fundingRate": [0.001, 0.5], "markPrice": 1.0, "bad_value": False})
    got = rb.latest_funding(np.array([t0, t0 + 5 * MIN, t0 + 10 * MIN, t0 + 15 * MIN]), f)
    assert list(got) == [0.001, 0.001, 0.5, 0.5]  # 0.5 only from its own time on, including exactly at fundingTime
    assert np.isnan(rb.latest_funding(np.array([t0 - 2 * 3_600_000]), f)[0])  # before the first funding row: NaN, not filled
    # the known time wins over the stamp
    f2 = f.assign(known_at_ms=[t0 - 3_600_000, t0 + 30 * MIN])
    assert list(rb.latest_funding(np.array([t0 + 10 * MIN, t0 + 30 * MIN]), f2)) == [0.001, 0.5]
    # a row with a bad value is skipped: the previous good rate stays
    f3 = f.assign(bad_value=[False, True])
    assert list(rb.latest_funding(np.array([t0 + 15 * MIN]), f3)) == [0.001]
    # the order of the decision times does not matter
    assert list(rb.latest_funding(np.array([t0 + 15 * MIN, t0, t0 + 10 * MIN]), f)) == [0.5, 0.001, 0.5]


def test_add_funding_keeps_rows_and_adds_no_label_column(small_ds):
    assert rb.FUNDING_COLUMN in small_ds.features.columns and not small_ds.includes_holdout
    assert not [c for c in small_ds.features.columns if c.startswith(wf.FORBIDDEN_FEATURE_PREFIXES)]
    base = wf.build_dataset(klines(), klines())
    assert len(base.features) == len(small_ds.features) and (base.features["decision_ms"] == small_ds.features["decision_ms"]).all()


# ------------------------------------------------------------- truncation ---

def test_truncation_state_at_t_is_the_same_if_later_data_is_cut():
    b, y, fu = klines(5, n=4000, crashes=[]), klines(6, n=4000, crashes=[]), funding(days=3)
    full = fk.build_features(b, y)
    full[rb.FUNDING_COLUMN] = rb.latest_funding(full["decision_ms"].to_numpy(), fu)
    rules = rb.make_rules()
    for rule in rules:
        rule.fit(train(**{c: full[c].to_numpy()[:1500] for c in ("rv_1h", "drawdown_1h", "runup_1h", "bybit_gap_abs_max_1h", rb.FUNDING_COLUMN)}))
    for j in (2000, 2005, 3000, 3995):
        t = START + j * MIN
        cut_b, cut_y = b[b["ts_ms"] + MIN <= t], y[y["ts_ms"] + MIN <= t]
        part = fk.build_features(cut_b, cut_y)
        for cut_funding in (fu[fu["known_at_ms"] <= t], fu):  # later funding rows removed, or present but not allowed to be used
            part[rb.FUNDING_COLUMN] = rb.latest_funding(part["decision_ms"].to_numpy(), cut_funding)
            for rule in rules:
                a = rule(full[full["decision_ms"] == t].iloc[0].to_dict())
                c = rule(part[part["decision_ms"] == t].iloc[0].to_dict())
                assert a == c, (rule.name, j)


# ----------------------------------------------------- the walk-forward run ---

def test_evaluate_all_four_rules_on_synthetic_data(small_ds, tmp_path):
    log = tmp_path / "log.csv"
    out = {}
    for rule in rb.make_rules():
        tid = wf.append_trial(rb.TRIAL_FAMILY, rule.name, 24, 0.3, "+".join(rule.features), path=log)
        res = wf.evaluate(rule, tid, small_ds, trial_log=log, results_dir=tmp_path / "res", write=False)
        res["rule_info"] = rule.info()
        out[rule.name] = res
        assert res["rule_info"]["n_decision_times"] == res["metrics"]["n_decision_times"] == rule.n_calls
        assert res["test_months"] == ["2025-09", "2025-10"] and len(res["rule_info"]["fits"]) == 2
    r1 = out["realized_volatility"]["metrics"]["shares"]
    assert r1["long"]["all"]["stay_out"] == r1["short"]["all"]["stay_out"]  # same state for both sides
    assert 0.005 < r1["long"]["all"]["stay_out"] < 0.15 and 0.005 < r1["long"]["all"]["caution"] < 0.15
    assert out["realized_volatility"]["rule_info"]["n_nan_state_clear"] == {"long": 0, "short": 0}
    c = out["price_cascade"]["metrics"]["views"][wf.view_key(wf.PRIMARY_VIEW)]
    assert c["long"]["60min"]["stay_out"]["all"]["episodes"] == 4
    assert wf.append_trial("x", "y", 1, 0.2, "z", path=log) == "T0005"  # four trials were logged before any evaluation


def test_nan_decision_times_are_counted(tmp_path):
    b = klines()
    ds = rb.add_funding(wf.build_dataset(b, b), funding(first="2025-09-02T08:00:00"))  # no usable funding for the first 32 hours of the test period
    rule = {r.name: r for r in rb.make_rules()}["funding_extreme"]
    log = tmp_path / "log.csv"
    wf.evaluate(rule, wf.append_trial("t", "d", 24, 0.3, "f", path=log), ds, trial_log=log, write=False)
    assert rule.n_nan == {"long": 384, "short": 384}  # 32 h of 5-minute decision times: state 0, counted
    assert rule.info()["n_nan_state_clear"] == {"long": 384, "short": 384}


def test_no_holdout_code_in_the_run():
    src = inspect.getsource(rb)
    assert "evaluate_holdout(" not in src and "HOLDOUT_LOCK" not in inspect.getsource(rb.run_baselines)


def test_the_four_trials_are_logged_once(tmp_path):
    log = tmp_path / "log.csv"
    assert not rb._baseline_logged(log)
    wf.append_trial("baseline", "anchor", 24, 0.3, "none", path=log)
    assert not rb._baseline_logged(log)
    wf.append_trial(rb.TRIAL_FAMILY, "R1", 24, 0.3, "rv_1h", path=log)
    assert rb._baseline_logged(log)
    with pytest.raises(wf.HarnessError):
        rb.run_baselines(tmp_path, trial_log=log)
