"""Tests for the bulk metrics history download, normalization, quality checks and taker cross-check (mocked HTTP, tiny synthetic data)."""
import csv
import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tacgate.data import bulk_availability as ba
from tacgate.data import bulk_equivalence as be
from tacgate.data import bulk_metrics_history as bm
from tacgate.data import binance_klines as bk
from tacgate.data.recorder import DATASETS

DAY = bm.DAY_MS
D0 = bm.utc_ms("2026-10-19")


class Resp:
    def __init__(self, status=200, content=b"", headers=None):
        self.status_code, self.content, self.headers = status, content, headers or {}


class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        r = self.routes.get(url, Resp(404))
        return r.pop(0) if isinstance(r, list) and len(r) > 1 else (r[0] if isinstance(r, list) else r)


def zip_of(name, text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, text)
    return buf.getvalue()


def served(day, text, published=None):
    key = be.metrics_key(day)
    z = zip_of(Path(key).name.replace(".zip", ".csv"), text)
    sha = published or hashlib.sha256(z).hexdigest()
    return {f"{ba.DOWNLOAD_URL}/{key}": Resp(200, z), f"{ba.DOWNLOAD_URL}/{key}.CHECKSUM": Resp(200, f"{sha}  x.zip\n".encode())}, z


def label(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def metrics_csv(day, n=288, shuffle=False, oi=lambda i: 1000.0 + i, taker=lambda i: 0.5 + i * 0.001):
    ms0 = bm.utc_ms(day)
    rows = [f"{label(ms0 + i * 300_000)},TACUSDT,{oi(i):.16f},{oi(i) * 2:.16f},3.0,{1.5 + i * 0.001:.8f},{1.6 + i * 0.001:.8f},{taker(i):.8f}" for i in range(n)]
    if shuffle:
        rows = rows[::-1]
    return ",".join(bm.METRIC_COLS) + "\n" + "\n".join(rows) + "\n"


# --------------------------------------------------------- rules ---

def test_last_modified_ms_is_day_end_plus_lag():
    assert bm.last_modified_ms("2026-11-19", 6.5) == bm.utc_ms("2026-11-20") + int(6.5 * 3_600_000)


def test_ts_ours_changes_convention_on_2026_11_16():
    before = bm.utc_ms("2026-11-15") + 23 * 3_600_000 + 55 * 60_000
    assert bm.ts_ours(before) == before + 300_000 == bm.utc_ms("2026-11-16")
    t = bm.utc_ms("2026-11-16")
    assert bm.ts_ours(t) == t and bm.ts_ours(t + 300_000) == t + 300_000


def test_day_rows_known_at_rules_and_flags():
    lm = bm.utc_ms("2026-10-20") + 8 * 3_600_000  # earlier than day end + 24 h (2026-10-21 00:00)
    rows = bm.day_rows(metrics_csv("2026-10-19", n=3, shuffle=True), "2026-10-19", lm)
    assert [int(r[0]) for r in rows] == sorted(int(r[0]) for r in rows)  # sorted by time
    cols = {c: i for i, c in enumerate(bm.OUT_COLUMNS)}
    r0 = rows[0]
    assert int(r0[cols["bulk_label_ms"]]) == D0 and int(r0[cols["ts_ours_ms"]]) == D0 + 300_000
    assert int(r0[cols["known_at_oi_ms"]]) == D0 + 300_000 + 600_000  # ts_ours + 10 min, from 2026-10-19 on
    assert int(r0[cols["known_at_other_ms"]]) == bm.utc_ms("2026-10-21")  # day end of the file date + 24 h
    assert r0[cols["unverified_era"]] == "false" and r0[cols["sum_open_interest"]] == "1000.0000000000000000"  # original text kept
    # a later LastModified wins for the other columns
    late = bm.utc_ms("2026-12-01")
    assert int(bm.day_rows(metrics_csv("2026-10-19", n=1), "2026-10-19", late)[0][cols["known_at_other_ms"]]) == late


def test_open_interest_known_time_before_2026_10_19_uses_the_day_rule_and_flags_the_unverified_era():
    lm = bm.utc_ms("2026-06-10")
    r = bm.day_rows(metrics_csv("2026-07-11", n=1), "2026-07-11", lm)[0]
    cols = {c: i for i, c in enumerate(bm.OUT_COLUMNS)}
    assert int(r[cols["known_at_oi_ms"]]) == int(r[cols["known_at_other_ms"]]) == bm.utc_ms("2026-07-13")
    assert r[cols["unverified_era"]] == "true"
    r2 = bm.day_rows(metrics_csv("2026-07-12", n=1), "2026-07-12", lm)[0]
    assert r2[cols["unverified_era"]] == "false"
    # the label change: from 2026-11-16 the timestamp is the label, and OI is known 10 minutes later
    r3 = bm.day_rows(metrics_csv("2026-11-16", n=1), "2026-11-16", lm)[0]
    assert int(r3[cols["ts_ours_ms"]]) == int(r3[cols["bulk_label_ms"]]) and int(r3[cols["known_at_oi_ms"]]) == int(r3[cols["ts_ours_ms"]]) + 600_000


def test_day_rows_rejects_an_unexpected_header():
    with pytest.raises(ValueError):
        bm.day_rows("a,b\n1,2\n", "2026-10-19", 0)


# ------------------------------------------------------ downloads ---

def test_ensure_file_downloads_and_verifies(tmp_path):
    routes, z = served("2026-10-19", metrics_csv("2026-10-19", n=2))
    o = bm.ensure_file(FakeSession(routes), "2026-10-19", tmp_path / "zips", sleep=lambda x: None)
    assert o.status == "verified" and o.verified and (tmp_path / "zips" / Path(be.metrics_key("2026-10-19")).name).read_bytes() == z and not o.reused


def test_ensure_file_skips_an_existing_verified_file_and_reuses_other_folders(tmp_path):
    routes, z = served("2026-10-19", metrics_csv("2026-10-19", n=2))
    other = tmp_path / "old"
    other.mkdir()
    name = Path(be.metrics_key("2026-10-19")).name
    (other / name).write_bytes(z)
    s = FakeSession(routes)
    o = bm.ensure_file(s, "2026-10-19", tmp_path / "zips", (other,), sleep=lambda x: None)
    assert o.verified and o.reused and [c[0] for c in s.calls] == [f"{ba.DOWNLOAD_URL}/{be.metrics_key('2026-10-19')}.CHECKSUM"]  # no zip request
    s2 = FakeSession(routes)
    bm.ensure_file(s2, "2026-10-19", tmp_path / "zips", sleep=lambda x: None)
    assert len(s2.calls) == 1  # already in zips: only the checksum was requested


def test_ensure_file_never_overwrites_and_keeps_a_revision_beside_it(tmp_path):
    routes, z_old = served("2026-10-19", metrics_csv("2026-10-19", n=2))
    bm.ensure_file(FakeSession(routes), "2026-10-19", tmp_path / "zips", sleep=lambda x: None)
    routes2, z_new = served("2026-10-19", metrics_csv("2026-10-19", n=3))  # the archive file changed
    o = bm.ensure_file(FakeSession(routes2), "2026-10-19", tmp_path / "zips", sleep=lambda x: None)
    name = Path(be.metrics_key("2026-10-19")).name
    assert o.status == "revision" and o.rev_path.name == name + ".rev" and o.rev_path.read_bytes() == z_new
    assert (tmp_path / "zips" / name).read_bytes() == z_old  # the original is untouched
    assert "matches the published checksum" in o.note
    # a second rerun does not create a second copy of the same revision
    o2 = bm.ensure_file(FakeSession(routes2), "2026-10-19", tmp_path / "zips", sleep=lambda x: None)
    assert o2.rev_path == o.rev_path and not (tmp_path / "zips" / (name + ".rev2")).exists()


def test_ensure_file_flags_mismatch_missing_and_no_checksum(tmp_path):
    routes, z = served("2026-10-19", metrics_csv("2026-10-19", n=1), published="0" * 64)
    o = bm.ensure_file(FakeSession(routes), "2026-10-19", tmp_path / "1", sleep=lambda x: None)
    assert o.status == "mismatch" and not o.verified and o.path.exists()
    assert bm.ensure_file(FakeSession({}), "2026-10-19", tmp_path / "2", sleep=lambda x: None).status == "missing"
    key = be.metrics_key("2026-10-19")
    only_zip = {f"{ba.DOWNLOAD_URL}/{key}": Resp(200, z)}
    assert bm.ensure_file(FakeSession(only_zip), "2026-10-19", tmp_path / "3", sleep=lambda x: None).status == "no checksum"


def test_ensure_file_notes_a_changed_pinned_checksum_and_raises_on_refusal(tmp_path):
    routes, _ = served("2026-10-19", metrics_csv("2026-10-19", n=1))
    o = bm.ensure_file(FakeSession(routes), "2026-10-19", tmp_path / "1", pinned="a" * 64, sleep=lambda x: None)
    assert "differs from the pinned" in o.note
    with pytest.raises(ba.Refused):
        bm.ensure_file(FakeSession({f"{ba.DOWNLOAD_URL}/{be.metrics_key('2026-10-19')}.CHECKSUM": Resp(403)}), "2026-10-19", tmp_path / "2", sleep=lambda x: None)


def test_download_all_manifest_is_append_only_and_resume_safe(tmp_path):
    routes = {}
    for d in ("2026-10-19", "2026-10-20"):
        r, _ = served(d, metrics_csv(d, n=2))
        routes.update(r)
    lags = {"2026-10-19": 8.0, "2026-10-20": 9.0}
    man = tmp_path / "static" / "m.csv"
    r1 = bm.download_all(FakeSession(routes), ["2026-10-19", "2026-10-20"], tmp_path / "zips", man, lags, sleep=lambda x: None)
    assert [o.status for o in r1.outcomes] == ["verified", "verified"] and not r1.revisions and not r1.failures
    rows = bm.read_manifest(man)
    assert [r["file_date"] for r in rows] == ["2026-10-19", "2026-10-20"] and rows[0]["verified"] == "yes" and rows[0]["revision"] == "0"
    assert rows[0]["last_modified_utc"] == "2026-10-20 08:00:00" and int(rows[0]["size"]) > 0
    before = man.read_bytes()
    s = FakeSession(routes)
    bm.download_all(s, ["2026-10-19", "2026-10-20"], tmp_path / "zips", man, lags, sleep=lambda x: None)
    assert man.read_bytes() == before  # no row rewritten or added
    assert all(c[0].endswith(".CHECKSUM") for c in s.calls)  # no file downloaded again


def test_download_all_records_a_revision_once(tmp_path):
    r, _ = served("2026-10-19", metrics_csv("2026-10-19", n=2))
    man, lags = tmp_path / "m.csv", {"2026-10-19": 8.0}
    bm.download_all(FakeSession(r), ["2026-10-19"], tmp_path / "zips", man, lags, sleep=lambda x: None)
    r2, _ = served("2026-10-19", metrics_csv("2026-10-19", n=5))
    res = bm.download_all(FakeSession(r2), ["2026-10-19"], tmp_path / "zips", man, lags, sleep=lambda x: None)
    assert len(res.revisions) == 1
    rows = bm.read_manifest(man)
    assert [x["revision"] for x in rows] == ["0", "1"] and rows[1]["verified"] == "yes"
    bm.download_all(FakeSession(r2), ["2026-10-19"], tmp_path / "zips", man, lags, sleep=lambda x: None)
    assert len(bm.read_manifest(man)) == 2  # the same revision is not recorded twice


def test_download_all_stops_at_a_refusal_and_keeps_earlier_days(tmp_path):
    routes, _ = served("2026-10-19", metrics_csv("2026-10-19", n=2))
    routes[f"{ba.DOWNLOAD_URL}/{be.metrics_key('2026-10-20')}.CHECKSUM"] = Resp(429)
    s = FakeSession(routes)
    res = bm.download_all(s, ["2026-10-19", "2026-10-20", "2026-10-21"], tmp_path / "zips", tmp_path / "m.csv", {"2026-10-19": 8.0}, sleep=lambda x: None)
    assert [o.day for o in res.outcomes] == ["2026-10-19"] and "429" in res.stopped and "2026-10-20" in res.stopped
    assert not any("2026-10-21" in c[0] for c in s.calls)  # nothing requested after the refusal
    assert [r["file_date"] for r in bm.read_manifest(tmp_path / "m.csv")] == ["2026-10-19"]


# ------------------------------------------------------- normalized ---

def outcome_for(day, tmp_path, n=3, verified=True):
    routes, z = served(day, metrics_csv(day, n=n))
    p = tmp_path / f"{day}.zip"
    p.write_bytes(z)
    return bm.Outcome(day, "u", "e", "a", "verified" if verified else "mismatch", verified, len(z), p)


def test_append_normalized_is_append_only(tmp_path):
    out = tmp_path / "n.csv"
    lags = {"2026-10-19": 8.0, "2026-10-20": 8.0, "2026-10-21": 8.0}
    o1, o2 = outcome_for("2026-10-19", tmp_path), outcome_for("2026-10-20", tmp_path)
    r = bm.append_normalized(out, [o1, o2], lags)
    assert r["days_added"] == 2 and r["rows_added"] == 6
    first = out.read_bytes()
    r2 = bm.append_normalized(out, [o1, o2], lags)
    assert r2["days_added"] == 0 and out.read_bytes() == first  # nothing rewritten
    o3 = outcome_for("2026-10-21", tmp_path)
    bm.append_normalized(out, [o1, o2, o3], lags)
    assert out.read_bytes().startswith(first) and len(pd.read_csv(out)) == 9
    df = pd.read_csv(out)
    assert list(df.columns) == bm.OUT_COLUMNS and df["bulk_label_ms"].is_monotonic_increasing


def test_append_normalized_skips_unverified_and_counts_out_of_order(tmp_path):
    out = tmp_path / "n.csv"
    lags = {d: 8.0 for d in ("2026-10-19", "2026-10-20", "2026-10-21")}
    bad = outcome_for("2026-10-20", tmp_path, verified=False)
    r = bm.append_normalized(out, [outcome_for("2026-10-19", tmp_path), bad, outcome_for("2026-10-21", tmp_path)], lags)
    assert r["days_added"] == 2 and set(pd.read_csv(out)["file_date"]) == {"2026-10-19", "2026-10-21"}
    late = bm.append_normalized(out, [outcome_for("2026-10-20", tmp_path)], lags)  # an older day arriving later
    assert late["days_added"] == 1 and late["out_of_order_days"] == 1
    assert not pd.read_csv(out)["bulk_label_ms"].is_monotonic_increasing  # appended, never inserted


# ------------------------------------------------------------ quality ---

def normalized_df(tmp_path, days, **kw):
    lags = {d: 8.0 for d in days}
    out = tmp_path / "n.csv"
    bm.append_normalized(out, [outcome_for(d, tmp_path, n=288) for d in days], lags)
    return bm.load_normalized(out)


def test_quality_checks_clean_data(tmp_path):
    q = bm.quality_checks(normalized_df(tmp_path, ["2026-10-19", "2026-10-20"]))
    assert q["rows"] == 576 and q["days"] == 2 and q["days_not_288"] == {} and q["missing_slots"] == 0 and q["duplicates"] == 0
    assert q["in_order"] and q["oi_non_positive"] == 0 and q["oi_jumps"] == [] and q["symbols"] == ["TACUSDT"]
    assert q["ratio_ranges"]["sum_taker_long_short_vol_ratio"]["min"] == pytest.approx(0.5)


def test_quality_checks_find_gaps_duplicates_order_zero_oi_and_jumps(tmp_path):
    df = normalized_df(tmp_path, ["2026-10-19"])
    df = df.drop(index=[10, 11]).reset_index(drop=True)  # two missing slots
    df = pd.concat([df, df.iloc[[5]]], ignore_index=True)  # a duplicate label, appended out of order
    df.loc[20, "sum_open_interest"] = 0.0
    df.loc[40, "sum_open_interest"] = df.loc[39, "sum_open_interest"] * 2.0  # +100% in one step
    q = bm.quality_checks(df)
    assert q["missing_slots"] == 2 and q["duplicates"] == 1 and not q["in_order"] and q["out_of_order_steps"] == 1
    assert q["oi_non_positive"] == 1 and len(q["days_not_288"]) == 1
    assert any(abs(c) > 0.5 for _, c in q["oi_jumps"])


def test_monthly_distribution_and_break_check(tmp_path):
    df = normalized_df(tmp_path, ["2026-10-19", "2026-10-20"])
    m = bm.monthly_distribution(df)
    assert m["sum_open_interest"][0]["month"] == "2026-10" and m["sum_open_interest"][0]["n"] == 576
    assert m["sum_open_interest"][0]["p5"] < m["sum_open_interest"][0]["median"] < m["sum_open_interest"][0]["p95"]
    b = bm.break_check(df, "2026-10-20", days=1)
    assert b["sum_open_interest"]["before"]["n"] == 288 and b["sum_open_interest"]["after"]["n"] == 288
    assert b["sum_open_interest"]["before"]["median"] == b["sum_open_interest"]["after"]["median"]


def recorder_oi(df, shift=0):
    return pd.DataFrame({"sumOpenInterest": df["sum_open_interest"].astype(str), "timestamp": (df["ts_ours_ms"] + shift).astype(str)})


def test_label_convention_recheck(tmp_path):
    df = normalized_df(tmp_path, ["2026-10-19"])
    assert bm.label_convention_recheck(df, recorder_oi(df))["equal"] == 1.0
    bad = bm.label_convention_recheck(df, recorder_oi(df, shift=300_000))
    assert bad["equal"] is not None and bad["equal"] < 0.1 and len(bad["first_mismatch_labels"]) == 5


# --------------------------------------------------------------- taker ---

def klines_frame(n_windows, start=D0):
    rows = []
    for i in range(n_windows * 5):
        vol = 100.0 + (i % 7)
        buy = 40.0 + (i % 5)
        rows.append({"open_time": str(start + i * 60_000), "volume": str(vol), "taker_buy_base_volume": str(buy)})
    return pd.DataFrame(rows)


def test_derived_taker_ratio_sums_five_candles_and_drops_partial_windows():
    kl = klines_frame(3).iloc[:-1]  # the last window has 4 candles
    d = bm.derived_taker_ratio(kl)
    assert len(d) == 2 and list(d.index) == [D0, D0 + 300_000]
    first = klines_frame(3).iloc[:5]
    buy, vol = first["taker_buy_base_volume"].astype(float).sum(), first["volume"].astype(float).sum()
    assert d.loc[D0, "ratio"] == pytest.approx(buy / (vol - buy))


def taker_setup(n=40, ending=True, noise=None):
    """Bulk rows whose taker ratio equals the klines-derived ratio of the window ending at ts_ours_ms (ending=True) or starting at it."""
    kl = klines_frame(n + 4)
    d = bm.derived_taker_ratio(kl)
    ts = np.array([D0 + 300_000 * (i + 1) for i in range(n)])
    ref = d["ratio"].reindex(ts - (300_000 if ending else 0)).values
    if noise is not None:
        ref = ref * noise
    df = pd.DataFrame({"ts_ours_ms": ts, "bulk_label_ms": ts - 300_000, "sum_taker_long_short_vol_ratio": ref, "unverified_era": "false"})
    return df, d


def test_taker_alignment_picks_the_window_ending_at_ts_ours():
    df, d = taker_setup(ending=True)
    a = bm.taker_alignment(df, d)
    assert a["best"].startswith("window ending at ts_ours_ms") and a["by_alignment"][a["best"]]["within_0_1pct"] == 1.0
    df2, d2 = taker_setup(ending=False)
    assert bm.taker_alignment(df2, d2)["best"] == "window starting at ts_ours_ms"


def test_taker_by_month_and_era_splits_the_eras():
    df, d = taker_setup()
    df.loc[:19, "unverified_era"] = "true"
    df.loc[:9, "sum_taker_long_short_vol_ratio"] = df.loc[:9, "sum_taker_long_short_vol_ratio"] * 1.05  # 5% off in the early era
    r = bm.taker_by_month_and_era(df, d, -300_000)
    assert r["eras"]["before 2026-07-12"]["within_1pct"] == pytest.approx(0.5) and r["eras"]["2026-07-12 and later"]["within_1pct"] == 1.0
    assert r["months"][0]["month"] == "2026-10" and r["months"][0]["rows"] == 40
    assert r["eras"]["before 2026-07-12"]["median_abs"] > 0


def test_agreement_statistics():
    a = np.array([1.0, 1.0005, 1.05, np.nan])
    b = np.array([1.0, 1.0, 1.0, 1.0])
    r = bm.agreement(a, b)
    assert r["rows"] == 3 and r["within_0_1pct"] == pytest.approx(2 / 3) and r["within_1pct"] == pytest.approx(2 / 3)
    assert r["median_abs"] == pytest.approx(0.0005) and bm.agreement(np.array([np.nan]), np.array([1.0])) == {"rows": 0}


def test_recorder_comparison_and_the_better_source():
    df, d = taker_setup(ending=True)
    periods = df["ts_ours_ms"].to_numpy() - 300_000
    exact = pd.DataFrame({"buySellRatio": [str(round(v, 4)) for v in d["ratio"].reindex(periods).values], "timestamp": periods.astype(str)})
    cmp = bm.recorder_taker_comparison(df, d, exact, -300_000)
    assert cmp["periods"] == 40 and cmp["api"]["within_0_1pct"] == 1.0 and cmp["bulk"]["within_0_1pct"] == 1.0
    assert "no clear difference" in bm.better_source(cmp)
    noisy = df.assign(sum_taker_long_short_vol_ratio=df["sum_taker_long_short_vol_ratio"] * (1 + 0.004 * (np.arange(40) % 2)))
    cmp2 = bm.recorder_taker_comparison(noisy, d, exact, -300_000)
    assert "API ratio" in bm.better_source(cmp2)
    cmp3 = bm.recorder_taker_comparison(df, d, exact.assign(buySellRatio=exact["buySellRatio"].astype(float) * (1 + 0.004 * (np.arange(40) % 2))), -300_000)
    assert "bulk ratio" in bm.better_source(cmp3)
    far = {"api": {"rows": 5, "within_0_1pct": 0.1, "within_1pct": 0.2}, "bulk": {"rows": 5, "within_0_1pct": 0.1, "within_1pct": 0.3}}
    assert bm.better_source(far).startswith("neither agrees")
    assert bm.better_source({"api": {"rows": 0}, "bulk": {"rows": 0}}).startswith("not shown")


# ----------------------------------------------------------- end to end ---

def build_world(tmp_path):
    """Two days of synthetic bulk files, recorder files and klines that agree with each other."""
    data = tmp_path / "raw"
    (data / "bulk_window").mkdir(parents=True)
    days = ["2026-10-19", "2026-10-20"]
    (data / "bulk_window" / "_listing_lags.json").write_text(json.dumps({"metrics": {d: 8.0 for d in days}}))
    kl = klines_frame(2 * 288 + 6)
    derived = bm.derived_taker_ratio(kl)
    full_kl = pd.DataFrame({c: ["0"] * len(kl) for c in bk.COLUMNS})
    full_kl["open_time"], full_kl["volume"], full_kl["taker_buy_base_volume"] = kl["open_time"], kl["volume"], kl["taker_buy_base_volume"]
    data.mkdir(exist_ok=True)
    full_kl.to_csv(data / bk.DEFAULT_OUT.name, index=False)
    routes, oi_rows, tk_rows = {}, [], []
    for d in days:
        ms0 = bm.utc_ms(d)
        text = [",".join(bm.METRIC_COLS)]
        for i in range(288):
            lab = ms0 + i * 300_000
            tk = derived["ratio"].reindex([lab]).values[0]  # the window [label, label+5) = ending at ts_ours (= label + 5 min)
            text.append(f"{label(lab)},TACUSDT,{1000.0 + i + (288 if d == days[1] else 0):.16f},5.0,3.0,1.5,1.6,{tk:.8f}")
            oi_rows.append(f"TACUSDT,{1000.0 + i + (288 if d == days[1] else 0):.8f},5.0,6000000000.0,{lab + 300_000},{lab + 10**9}")
            tk_rows.append(f"{round(tk, 4):.4f},1.0,1.0,{lab},{lab + 10**9}")
        r, _ = served(d, "\n".join(text) + "\n")
        routes.update(r)
    for ds, rows in (("open_interest", oi_rows), ("taker_buy_sell", tk_rows)):
        d_ = next(x for x in DATASETS if x.name == ds)
        d_.csv_path(data).write_text(",".join(d_.columns) + "\n" + "\n".join(rows) + "\n")
    return data, routes, days


def test_run_end_to_end_and_rerun_changes_nothing(tmp_path, monkeypatch):
    data, routes, days = build_world(tmp_path)
    monkeypatch.setattr(bm, "MANIFEST_PATH", tmp_path / "static" / "bulk_metrics_manifest.csv")
    report = tmp_path / "report.md"
    rep = bm.run(FakeSession(routes), data, report, sleep=lambda x: None, on_progress=None)
    assert [o.status for o in rep.download.outcomes] == ["verified", "verified"] and rep.quality["rows"] == 576 and rep.quality["missing_slots"] == 0
    assert rep.recheck["equal"] == 1.0
    assert rep.taker_align["best"].startswith("window ending at ts_ours_ms") and rep.taker_align["by_alignment"][rep.taker_align["best"]]["within_0_1pct"] > 0.99
    assert rep.recorder_cmp["api"]["within_0_1pct"] > 0.99 and rep.recorder_cmp["bulk"]["within_0_1pct"] > 0.99
    text = report.read_text(encoding="utf-8")
    assert "## Download" in text and "Best fit" in text and "Which agrees better with the klines" in text and "Anything odd" in text
    out = data / "binance_bulk_metrics_TACUSDT_5m.csv"
    manifest = tmp_path / "static" / "bulk_metrics_manifest.csv"
    snap = (out.read_bytes(), manifest.read_bytes())
    rep2 = bm.run(FakeSession(routes), data, report, sleep=lambda x: None, on_progress=None)
    assert rep2.normalized["days_added"] == 0 and (out.read_bytes(), manifest.read_bytes()) == snap  # nothing rewritten


def test_run_uses_one_listing_only_when_the_cache_is_missing(tmp_path, monkeypatch):
    data, routes, days = build_world(tmp_path)
    (data / "bulk_window" / "_listing_lags.json").unlink()
    prefix = be.LISTED[0][1].prefix("daily")
    xml = ('<?xml version="1.0"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>false</IsTruncated>'
           + "".join(f"<Contents><Key>{prefix}TACUSDT-metrics-{d}.zip</Key><LastModified>{(datetime.fromisoformat(d) + pd.Timedelta(days=1, hours=8)).strftime('%Y-%m-%dT%H:%M:%S')}.000Z</LastModified><Size>1</Size></Contents>" for d in days)
           + "</ListBucketResult>").encode()
    routes[(ba.LIST_URL)] = Resp(200, xml)
    monkeypatch.setattr(bm, "MANIFEST_PATH", tmp_path / "static" / "m.csv")
    s = FakeSession(routes)
    rep = bm.run(s, data, tmp_path / "r.md", sleep=lambda x: None, on_progress=None)
    assert sum(1 for c in s.calls if c[0] == ba.LIST_URL) == 1 and "ONE new metrics listing" in rep.lag_source
    assert rep.quality["rows"] == 576


def test_report_lists_revisions_and_failures_as_odd(tmp_path):
    rep = bm.Report()
    rep.download = bm.DownloadResult(stopped="2026-10-20: HTTP 429 refused")
    rep.download.revisions = [bm.Outcome("2026-10-19", "u", rev_path=Path("x.zip.rev"), note="changed")]
    rep.download.failures = [bm.Outcome("2026-10-21", "u", status="mismatch", expected="ab" * 32, actual="cd" * 32)]
    rep.quality = {"rows": 10, "days_not_288": {"2026-10-19": 5}, "missing_slots": 3, "duplicates": 1, "oi_non_positive": 1, "oi_jumps": [(0, 0.9)]}
    odd = bm.collect_odd(rep)
    text = "\n".join(odd)
    assert "stopped" in text and "REVISION" in text and "mismatch" in text and "288 rows" in text and "3 five-minute" in text and "jump" in text
    assert "Anything odd" in bm.render_report(bm.Report())


def test_main_refuses_report_inside_data_dir(tmp_path, capsys):
    assert bm.main(["--data-dir", str(tmp_path), "--report", str(tmp_path / "r.md")]) == 2
    assert "Refusing" in capsys.readouterr().out
    assert not (tmp_path / "r.md").exists()


# ------------------------------------------------ odd list and run log ---

def test_odd_list_reports_nan_and_zero_ratios_zero_open_interest_days_and_structural_breaks():
    rep = bm.Report()
    rep.quality = {"rows": 10, "days_not_288": {}, "missing_slots": 0, "duplicates": 0, "oi_non_positive": 2, "oi_jumps": [],
                   "oi_non_positive_days": {"2025-07-21": 2},
                   "ratio_ranges": {"sum_taker_long_short_vol_ratio": {"min": 0.0, "max": 9166.0, "non_positive": 3, "nan": 1},
                                    "count_long_short_ratio": {"min": 0.3, "max": 6.0, "non_positive": 0, "nan": 0}}}
    rep.breaks = {"2026-07-12": {"sum_open_interest": {"before": {"n": 10, "median": 100.0, "p5": 90.0, "p95": 400.0},
                                                       "after": {"n": 10, "median": 300.0, "p5": 280.0, "p95": 320.0}},
                                 "count_long_short_ratio": {"before": {"n": 10, "median": 1.0, "p5": 0.9, "p95": 1.1},
                                                            "after": {"n": 10, "median": 1.05, "p5": 0.95, "p95": 1.15}}}}
    text = "\n".join(bm.collect_odd(rep))
    assert "Zero open interest sits on: 2025-07-21 (2)" in text
    assert "sum_taker_long_short_vol_ratio: 1 not-a-number and 3 zero-or-negative" in text
    assert "Around 2026-07-12 (14 days either side) sum_open_interest: median 100 to 300" in text
    assert "count_long_short_ratio: median" not in text  # a small change is not flagged


def test_run_log_is_appended_and_shown_in_the_report(tmp_path, monkeypatch):
    data, routes, days = build_world(tmp_path)
    monkeypatch.setattr(bm, "MANIFEST_PATH", tmp_path / "static" / "m.csv")
    bm.run(FakeSession(routes), data, tmp_path / "r1.md", sleep=lambda x: None, on_progress=None)
    rep = bm.run(FakeSession(routes), data, tmp_path / "r2.md", sleep=lambda x: None, on_progress=None)
    lines = bm.read_run_log(data)
    assert len(lines) == 2 and "verified 2" in lines[0] and "reused from disk 2" in lines[1] and "normalized rows added 0" in lines[1]
    text = (tmp_path / "r2.md").read_text(encoding="utf-8")
    assert "Run history" in text and lines[0] in text and rep.history == lines


def test_report_ends_with_the_decisions():
    text = bm.render_report(bm.Report())
    assert "## Decisions" in text and "Decided by the user on 2026-11-21" in text
    assert "92.49 percent" in text and "60.61" in text and "never filled from neighbours" in text and "regime-sensitive" in text
    assert text.rstrip().endswith("4. Nothing from this file has been used as a feature.")
