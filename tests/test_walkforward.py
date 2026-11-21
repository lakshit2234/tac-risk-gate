"""Tests for the Phase 2 walk-forward harness. Synthetic data only; temporary trial-log, lock and results paths only."""
import json
import math

import numpy as np
import pandas as pd
import pytest

from tacgate.phase2 import labels as lb
from tacgate.phase2 import walkforward as wf

MIN = 60_000
T = lambda s: wf.utc_ms(s)  # noqa: E731
START = T("2025-08-30T00:00:00")
DAYS = 40
CRASHES = [T(x) for x in ("2025-09-03T12:03:00", "2025-09-06T12:03:00", "2025-09-09T12:03:00", "2025-09-12T12:03:00", "2025-09-15T12:03:00", "2025-10-01T06:03:00")]
SPIKES = [T("2025-09-05T06:07:00"), T("2025-09-10T18:07:00")]
HOLDOUT_CRASHES = [T("2025-10-05T12:03:00"), T("2025-10-07T12:03:00")]
PK = wf.view_key(wf.PRIMARY_VIEW)


@pytest.fixture(autouse=True)
def synthetic_dates(monkeypatch):
    monkeypatch.setattr(lb, "DEVELOPMENT_END_MS", T("2025-10-03T00:00:00"))
    monkeypatch.setattr(lb, "HOLDOUT_START_MS", T("2025-10-04T00:00:00"))


def klines(crashes=(), spikes=()):
    n = DAYS * 1440
    ts = START + np.arange(n) * MIN
    c = np.full(n, 100.0)
    lo, hi = c.copy(), c.copy()
    for b in crashes:
        lo[(b - START) // MIN] = 60.0  # a 40 percent fall inside one candle; the close is back at 100
    for b in spikes:
        hi[(b - START) // MIN] = 150.0
    return pd.DataFrame({"ts_ms": ts, "high": hi, "low": lo, "close": c, "volume": np.full(n, 10.0), "taker_buy_base_volume": np.full(n, 4.0)})


def all_klines():
    return klines(CRASHES + HOLDOUT_CRASHES, SPIKES)


def dev_klines():
    k = all_klines()
    return k[k["ts_ms"] < lb.HOLDOUT_START_MS]


def features_for(k, lead_from=30, lead_to=5):
    """Synthetic features incl. a CHEATING pair (danger_*), used only to build a perfect-foresight rule."""
    grid = lb.build_labels(k, 1, 0.30)["decision_ms"].to_numpy()
    danger_l, danger_s = np.zeros(len(grid)), np.zeros(len(grid))
    for b in CRASHES + HOLDOUT_CRASHES:
        danger_l[(grid >= b - lead_from * MIN) & (grid <= b - lead_to * MIN)] = 1
    for b in SPIKES:
        danger_s[(grid >= b - lead_from * MIN) & (grid <= b - lead_to * MIN)] = 1
    return pd.DataFrame({"decision_ms": grid, "known_at_ms": grid, "x": 0.0, "danger_long": danger_l, "danger_short": danger_s})


@pytest.fixture
def ds():
    k = dev_klines()
    return wf.make_dataset(features_for(k), k)


class Perfect:
    name = "perfect"

    def __call__(self, row):
        return (2 if row["danger_long"] else 0), (2 if row["danger_short"] else 0)


@pytest.fixture
def log(tmp_path):
    return tmp_path / "trial_log.csv"


def trial(log, name="t"):
    return wf.append_trial("test", name, 24, 0.30, "none", path=log)


def ev(rule, ds, log, tmp_path):
    return wf.evaluate(rule, trial(log), ds, trial_log=log, results_dir=tmp_path / "res")


def cell(res, side="long", lead="60min", alarm="stay_out", part="all", view=PK):
    return res["metrics"]["views"][view][side][lead][alarm][part]


# ------------------------------------------------------------- gate results ---

def test_perfect_foresight_captures_everything(ds, log, tmp_path):
    r = ev(Perfect(), ds, log, tmp_path)
    c = cell(r, "long")
    assert (c["episodes"], c["captured"], c["rate"]) == (6, 6, 1.0)
    assert c["lead_count"] == 6 and 25 <= c["lead_min"] <= c["lead_max"] <= 35  # the alarm run starts 30 minutes before the event
    for lead in ("15min", "60min", "240min"):
        assert cell(r, "long", lead)["captured"] == 6
    s = cell(r, "short")
    assert (s["episodes"], s["captured"]) == (2, 2)
    for v in wf.VIEWS:
        assert cell(r, "long", view=wf.view_key(v))["rate"] == 1.0
    assert r["metrics"]["shares"]["long"]["all"]["stay_out"] < 0.01
    assert (tmp_path / "res" / f"{r['trial_id']}.json").exists()


def test_always_stay_out_and_never(ds, log, tmp_path):
    a = ev(wf.AlwaysStayOut(), ds, log, tmp_path)
    n = ev(wf.NeverGate(), ds, log, tmp_path)
    for side in wf.SIDES:
        sh = a["metrics"]["shares"][side]["all"]
        assert sh["stay_out"] == 1.0 and sh["caution"] == 0.0
        assert cell(a, side)["rate"] == 1.0 and cell(a, side)["random_median"] == 1.0
        assert cell(n, side)["captured"] == 0 and cell(n, side)["rate"] == 0.0 and cell(n, side)["random_median"] == 0.0
        assert n["metrics"]["shares"][side]["all"]["stay_out"] == 0.0 and n["metrics"]["shares"][side]["all"]["caution_or_stay_out"] == 0.0
    assert cell(a, "long")["lead_count"] == 6


def test_random_gate_shares_and_band(ds, log, tmp_path):
    r = ev(wf.RandomGate(), ds, log, tmp_path)
    sh = r["metrics"]["shares"]["long"]["all"]
    assert 0.07 < sh["stay_out"] < 0.13 and 0.07 < sh["caution"] < 0.13
    c = cell(r, "long")
    assert 0 <= c["random_p2_5"] <= c["random_median"] <= c["random_p97_5"] <= 1
    assert cell(r, "long", alarm="caution_or_stay_out")["random_median"] >= c["random_median"] - 1e-9


def test_event_time_is_the_crossing_candle(ds):
    eps = wf.build_episodes(ds, wf.PRIMARY_VIEW, "long", T("2025-09-01T00:00:00"), lb.DEVELOPMENT_END_MS)
    assert [e.event_ms for e in eps] == [b for b in CRASHES]
    assert all(e.start_ms < e.event_ms for e in eps)
    eps_s = wf.build_episodes(ds, wf.PRIMARY_VIEW, "short", T("2025-09-01T00:00:00"), lb.DEVELOPMENT_END_MS)
    assert [e.event_ms for e in eps_s] == SPIKES
    # two crossing candles: the first one is the event
    k = klines(crashes=[T("2025-09-03T12:03:00"), T("2025-09-03T12:40:00")])
    d2 = wf.make_dataset(features_for(k), k[k["ts_ms"] < lb.HOLDOUT_START_MS])
    e = wf.build_episodes(d2, wf.PRIMARY_VIEW, "long", T("2025-09-01T00:00:00"), lb.DEVELOPMENT_END_MS)
    assert len(e) == 1 and e[0].event_ms == T("2025-09-03T12:03:00")


def test_too_few_flag_below_four_episodes(ds, log, tmp_path):
    r = ev(Perfect(), ds, log, tmp_path)
    assert cell(r, "short")["verdict"] == "TOO FEW"  # 2 episodes
    assert cell(r, "long")["verdict"] not in ("", "TOO FEW")  # 6 episodes: a descriptive position, not a significance claim
    assert "significan" not in cell(r, "long")["verdict"].lower()
    assert cell(r, "long", part="after the cliff (2026-07-15)")["verdict"] == "TOO FEW"  # no episodes there at all
    assert cell(r, "long", part="after the cliff (2026-07-15)")["rate"] is None
    # exactly 4 episodes is enough, 3 is not
    assert wf.MIN_EPISODES == 4


def test_splits_by_cliff_and_listing(ds, log, tmp_path):
    r = ev(wf.NeverGate(), ds, log, tmp_path)
    allc, pre, post, free = (cell(r, "long", part=p) for p in ("all", "before the cliff (2026-07-15)", "after the cliff (2026-07-15)", "without the first 7 days after listing"))
    assert pre["episodes"] == allc["episodes"] and post["episodes"] == 0 and free["episodes"] == allc["episodes"]  # synthetic data are 2025: before the cliff and after listing week
    assert r["metrics"]["shares"]["long"]["after the cliff (2026-07-15)"]["rows"] == 0


# ------------------------------------------------------------------ embargo ---

class Spy:
    name = "spy"

    def __init__(self):
        self.fits = []

    def fit(self, train):
        self.fits.append(train)

    def __call__(self, row):
        return 0, 0


def test_embargo_training_rows_known_before_each_test_month(ds, log, tmp_path):
    spy = Spy()
    r = ev(spy, ds, log, tmp_path)
    assert r["test_months"] == ["2025-09", "2025-10"] and len(spy.fits) == 2
    for (month, start, _), tr in zip(wf.month_blocks(ds), spy.fits):
        assert len(tr) > 0
        assert (tr["label_known_at_ms"] <= start).all()
        assert (tr["decision_ms"] + 24 * 3_600_000 <= start).all()  # 24 h horizon: nothing from the last day before the month
        assert tr["label_long"].notna().all() and "complete" not in tr.columns
    assert spy.fits[1]["decision_ms"].max() > spy.fits[0]["decision_ms"].max()  # expanding window


def test_embargo_violation_raises(ds):
    start = T("2025-09-01T00:00:00")
    good = wf.train_rows(ds, start)
    wf.check_training_rows(good, start)
    bad = good.copy()
    bad.loc[bad.index[-1], "label_known_at_ms"] = start + 1
    with pytest.raises(wf.EmbargoError):
        wf.check_training_rows(bad, start)
    late = good.copy()
    late.loc[late.index[-1], "decision_ms"] = lb.DEVELOPMENT_END_MS + MIN
    with pytest.raises(wf.HoldoutError):
        wf.check_training_rows(late, start)


def test_embargo_violation_inside_a_run_raises(ds, monkeypatch):
    real = wf.train_rows

    def leaky(d, start):
        t = real(d, start)
        t.loc[t.index[-1], "label_known_at_ms"] = start + 1
        return t
    monkeypatch.setattr(wf, "train_rows", leaky)
    with pytest.raises(wf.EmbargoError):
        wf.run_gate(Spy(), ds, wf.month_blocks(ds))


def test_rule_input_has_no_label_columns(ds, log, tmp_path):
    seen = []

    class Look:
        name = "look"

        def __call__(self, row):
            seen.append(set(row))
            return 0, 0
    ev(Look(), ds, log, tmp_path)
    keys = set().union(*seen)
    assert keys == {"decision_ms", "known_at_ms", "x", "danger_long", "danger_short"}
    assert not [k for k in keys if k.startswith(wf.FORBIDDEN_FEATURE_PREFIXES)]
    bad = features_for(dev_klines()).assign(label_long=0.0)
    with pytest.raises(ValueError):
        wf.make_dataset(bad, dev_klines())


def test_rule_rows_come_one_at_a_time_and_only_up_to_t(ds):
    calls = []

    class Check:
        name = "check"

        def __call__(self, row):
            calls.append(row["decision_ms"])
            return 0, 0
    g = wf.run_gate(Check(), ds, wf.month_blocks(ds))
    assert calls == sorted(calls) and len(calls) == len(g.times) and calls[-1] <= lb.DEVELOPMENT_END_MS
    with pytest.raises(ValueError):
        wf.run_gate(lambda row: (3, 0), ds, wf.month_blocks(ds)[:1])
    with pytest.raises(ValueError):
        wf.run_gate(lambda row: 1, ds, wf.month_blocks(ds)[:1])


# ------------------------------------------------------------------ holdout ---

def test_development_run_never_reads_holdout_rows(tmp_path, log):
    b = all_klines()
    d = wf.build_dataset(b)  # klines are cut at the holdout start before anything is built
    assert d.features["decision_ms"].max() <= lb.DEVELOPMENT_END_MS
    assert d.minutes.first_open + (d.minutes.n - 1) * MIN < lb.HOLDOUT_START_MS
    assert not d.includes_holdout
    # a dataset with holdout rows is refused by the guard and by the development run
    full = wf.build_dataset(b, include_holdout=True)
    assert full.features["decision_ms"].max() > lb.DEVELOPMENT_END_MS
    with pytest.raises(wf.HoldoutError):
        wf.assert_development_only(wf.Dataset(full.features, full.labels, full.minutes, False))
    with pytest.raises(wf.HoldoutError):
        wf.evaluate(wf.NeverGate(), trial(log), full, trial_log=log, results_dir=tmp_path / "res")
    assert not (tmp_path / "res").exists()


def test_holdout_lock_works_once_then_refuses(tmp_path, log):
    lock = tmp_path / "holdout_used.txt"
    tid = trial(log)
    b = all_klines()
    r = wf.evaluate_holdout(wf.NeverGate(), tid, b, None, lock_path=lock, trial_log=log, results_dir=tmp_path / "res")
    assert lock.exists() and f"trial_id: {tid}" in lock.read_text() and "used_utc:" in lock.read_text()
    assert r["period"] == "holdout" and (tmp_path / "res" / f"{tid}_holdout.json").exists()
    h = cell(r, "long")
    assert h["episodes"] == 2 and h["captured"] == 0 and h["verdict"] == "TOO FEW"
    before = lock.read_text()
    with pytest.raises(wf.HoldoutError):
        wf.evaluate_holdout(wf.NeverGate(), tid, b, None, lock_path=lock, trial_log=log, results_dir=tmp_path / "res")
    assert lock.read_text() == before  # untouched


def test_holdout_needs_a_logged_trial_and_makes_no_lock_otherwise(tmp_path, log):
    lock = tmp_path / "holdout_used.txt"
    with pytest.raises(wf.UnknownTrialError):
        wf.evaluate_holdout(wf.NeverGate(), "T9999", all_klines(), None, lock_path=lock, trial_log=log)
    assert not lock.exists()


def test_holdout_trains_only_on_development_rows(tmp_path, log):
    spy = Spy()
    tid = trial(log)
    wf.evaluate_holdout(spy, tid, all_klines(), None, lock_path=tmp_path / "l.txt", trial_log=log, results_dir=tmp_path / "res")
    (tr,) = spy.fits
    assert (tr["label_known_at_ms"] <= lb.HOLDOUT_START_MS).all() and (tr["decision_ms"] <= lb.DEVELOPMENT_END_MS).all()


# ---------------------------------------------------------------- trial log ---

def test_evaluate_refuses_an_unknown_trial_id(ds, log, tmp_path):
    trial(log)
    with pytest.raises(wf.UnknownTrialError):
        wf.evaluate(wf.NeverGate(), "T0002", ds, trial_log=log, results_dir=tmp_path / "res")
    with pytest.raises(wf.UnknownTrialError):
        wf.evaluate(wf.NeverGate(), "T0001", ds, trial_log=tmp_path / "missing.csv", results_dir=tmp_path / "res")
    assert not (tmp_path / "res").exists()


def test_trial_log_is_append_only_and_keeps_its_line_endings(tmp_path):
    p = tmp_path / "trial_log.csv"
    header = ",".join(wf.TRIAL_COLUMNS) + "\r\n"
    p.write_bytes(header.encode())
    t1 = wf.append_trial("a", "first", 24, 0.3, "none", path=p)
    snap = p.read_bytes()
    t2 = wf.append_trial("b", "second, with a comma", 4, 0.2, "x", notes="n", path=p)
    after = p.read_bytes()
    assert (t1, t2) == ("T0001", "T0002")
    assert after.startswith(snap) and len(after) > len(snap)  # old bytes never touched
    assert after.count(b"\r\n") == 3 and b"\n" not in after.replace(b"\r\n", b"")
    df = pd.read_csv(p, dtype=str)
    assert list(df.columns) == wf.TRIAL_COLUMNS and list(df["trial_id"]) == ["T0001", "T0002"]
    assert df.loc[1, "description"] == "second, with a comma" and df.loc[0, "development_result_reference"] == "data/processed/trials/T0001.json"
    # a file that lacks its final newline is still appended to, not rewritten
    p.write_bytes(snap.rstrip(b"\r\n"))
    wf.append_trial("c", "third", 1, 0.2, "none", path=p)
    assert p.read_bytes().startswith(snap.rstrip(b"\r\n")) and len(pd.read_csv(p)) == 2
    # no file yet: header is written
    q = tmp_path / "new.csv"
    assert wf.append_trial("a", "d", 24, 0.3, "none", path=q) == "T0001" and q.read_text().startswith("trial_id,")


def test_warning_above_fifty_trials(ds, tmp_path, capsys):
    p = tmp_path / "log.csv"
    for i in range(51):
        wf.append_trial("t", f"v{i}", 24, 0.3, "none", path=p)
    r = wf.evaluate(wf.NeverGate(), "T0051", ds, trial_log=p, results_dir=tmp_path / "res")
    assert r["trials_so_far"] == 51 and "exploratory only" in r["warnings"][0]
    assert "exploratory only" in capsys.readouterr().out
    r2 = wf.evaluate(wf.NeverGate(), "T0001", ds, trial_log=p, results_dir=tmp_path / "res2", write=False)
    assert r2["trials_so_far"] == 51
    q = tmp_path / "few.csv"
    wf.append_trial("t", "v", 24, 0.3, "none", path=q)
    assert wf.evaluate(wf.NeverGate(), "T0001", ds, trial_log=q, write=False)["warnings"] == []


def test_result_json_is_valid(ds, log, tmp_path):
    r = ev(wf.RandomGate(), ds, log, tmp_path)
    data = json.loads((tmp_path / "res" / f"{r['trial_id']}.json").read_text())
    assert data["trial_id"] == r["trial_id"] and data["fixed"]["shift_seed"] == 20261121 and data["fixed"]["n_shifts"] == 1000


# ------------------------------------------------------------------- stats ---

def test_circular_shift_keeps_share_and_spells():
    a = np.zeros(200, bool)
    a[10:25] = True
    a[60:62] = True
    a[100:130] = True  # spells of 15, 2 and 30 away from both ends
    def spells(x):
        d = np.diff(np.r_[False, x, False].astype(int))
        return sorted(np.flatnonzero(d == -1) - np.flatnonzero(d == 1))
    for k in (1, 37, 99, 150, 199):
        s = wf.circular_shift(a, k)
        assert s.sum() == a.sum() and s.mean() == a.mean()
        if not (s[0] or s[-1]):  # no spell cut by the array ends
            assert spells(s) == spells(a) == [2, 15, 30]


def test_clopper_pearson_known_values():
    lo, hi = wf.clopper_pearson(0, 4)  # two-sided 95 percent: each tail 2.5 percent
    assert lo == 0.0 and hi == pytest.approx(1 - 0.025 ** 0.25, abs=1e-6) and hi == pytest.approx(0.6023, abs=1e-3)
    lo, hi = wf.clopper_pearson(4, 4)
    assert hi == 1.0 and lo == pytest.approx(0.025 ** 0.25, abs=1e-6) and lo == pytest.approx(0.3977, abs=1e-3)
    assert wf.clopper_pearson(5, 5)[0] == pytest.approx(0.478, abs=1e-3)  # the plan: 0.025^(1/5)
    assert wf.clopper_pearson(11, 11)[0] == pytest.approx(0.7151, abs=1e-3) and wf.clopper_pearson(28, 28)[0] == pytest.approx(0.8766, abs=1e-3)
    # 0.527 and 0.473 are the ONE-sided 95 percent limits (= a two-sided 90 percent interval)
    assert wf.clopper_pearson(0, 4, alpha=0.10)[1] == pytest.approx(0.527, abs=1e-3)
    assert wf.clopper_pearson(4, 4, alpha=0.10)[0] == pytest.approx(0.473, abs=1e-3)
    lo, hi = wf.clopper_pearson(3, 10)
    assert lo == pytest.approx(0.0667, abs=1e-3) and hi == pytest.approx(0.6525, abs=1e-3)
    assert math.isnan(wf.clopper_pearson(0, 0)[0])
    with pytest.raises(ValueError):
        wf.clopper_pearson(5, 4)


def test_fixed_values_are_named_constants():
    assert (wf.FIRST_TEST_MONTH, wf.PRIMARY_VIEW, wf.REPORTED_VIEWS) == ("2025-09", (24, 0.30), ((4, 0.20), (1, 0.20)))
    assert (wf.PRIMARY_LEAD_MIN, wf.REPORTED_LEADS_MIN, wf.N_SHIFTS, wf.SHIFT_SEED, wf.MIN_EPISODES, wf.TRIAL_WARN_AFTER) == (60, (15, 240), 1000, 20261121, 4, 50)
    assert (wf.CLEAR, wf.CAUTION, wf.STAY_OUT) == (0, 1, 2)
    assert str(wf.HOLDOUT_LOCK).replace("\\", "/") == "docs/holdout_used.txt" and str(wf.RESULTS_DIR).replace("\\", "/") == "data/processed/trials"
