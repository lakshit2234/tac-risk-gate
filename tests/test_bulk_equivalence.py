"""Tests for the bulk equivalence and cutover checks (mocked HTTP, tiny synthetic data, no network)."""
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
from tacgate.data.recorder import DATASETS, SNAPSHOT_COLUMNS

DAY = 86_400_000
D0 = int(datetime(2026, 10, 19, tzinfo=timezone.utc).timestamp() * 1000)


class Resp:
    def __init__(self, status=200, content=b"", headers=None):
        self.status_code, self.content, self.headers = status, content, headers or {}


class FakeSession:
    def __init__(self, routes, default=None):
        self.routes, self.calls, self.default = routes, [], default

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        key = url if url != ba.LIST_URL else (url, (params or {}).get("prefix"), (params or {}).get("marker", ""))
        r = self.routes.get(key, self.default if self.default is not None else Resp(404))
        return r.pop(0) if isinstance(r, list) and len(r) > 1 else (r[0] if isinstance(r, list) else r)


def zip_of(name, text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, text)
    return buf.getvalue()


def served(key, text):
    """Routes for one archive file and its checksum."""
    z = zip_of(Path(key).name.replace(".zip", ".csv"), text)
    return {f"{ba.DOWNLOAD_URL}/{key}": Resp(200, z),
            f"{ba.DOWNLOAD_URL}/{key}.CHECKSUM": Resp(200, f"{hashlib.sha256(z).hexdigest()}  {Path(key).name}\n".encode())}


def label(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


METRIC_COLS = "create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio"


def metrics_csv(day_ms, shift_min=5, n=288, ratio=lambda i: 1.5 + i * 0.001, taker=lambda i: 0.5 + i * 0.001, shuffle=False):
    """A bulk day file. Label = our timestamp - shift_min (shift 5 = the old convention, 0 = the new one)."""
    rows = []
    for i in range(n):
        ours_ts = day_ms + i * 300_000 + shift_min * 60_000
        rows.append(f"{label(ours_ts - shift_min * 60_000)},TACUSDT,{1000.0 + i:.16f},{2000.5 + i + 0.5:.16f},"
                    f"3.0,{ratio(i):.8f},{ratio(i):.8f},{taker(i):.8f}")
    if shuffle:
        rows = rows[::-1]
    return METRIC_COLS + "\n" + "\n".join(rows) + "\n"


def write_ours(data_dir, days, shift_for_day=lambda d: 5, live_from=None, taker_round=True, ratio_noise=0.0):
    """Our recorder files for the given day starts, consistent with metrics_csv. Our timestamp = label + shift."""
    data_dir.mkdir(parents=True, exist_ok=True)
    oi, gl, tp, tk = [], [], [], []
    for day in days:
        sh = shift_for_day(day)
        for i in range(288):
            ts = day + i * 300_000 + sh * 60_000
            fetched = (ts + 400_000) if (live_from is not None and ts >= live_from) else ts + 3_600_000 * 24
            oi.append(f"TACUSDT,{1000.0 + i:.8f},{2000.5 + i + 0.5:.8f},6000000000.00000000,{ts},{fetched}")
            r = round(1.5 + i * 0.001, 4)
            gl.append(f"TACUSDT,{r:.4f},0.6,0.4,{ts},{fetched}")
            tp.append(f"TACUSDT,{r:.4f},0.6,0.4,{ts},{fetched}")
            tk_ts = day + i * 300_000 + (sh - 5) * 60_000 + 0 * 0  # taker: old shift 0, new -5  (= sh - 5)
            tv = 0.5 + i * 0.001 + ratio_noise * (i % 3)
            buy, sell = 1000.0 * tv, 1000.0
            tk.append(f"{round(tv, 4):.4f},{buy:.4f},{sell:.4f},{tk_ts},{fetched}")
    hdr = {d.name: ",".join(d.columns) for d in DATASETS}
    for name, rows in (("open_interest", oi), ("global_long_short", gl), ("top_position_long_short", tp), ("taker_buy_sell", tk)):
        ds = next(d for d in DATASETS if d.name == name)
        ds.csv_path(data_dir).write_text(hdr[name] + "\n" + "\n".join(rows) + "\n")
    (data_dir / "binance_TACUSDT_snapshot.csv").write_text(",".join(SNAPSHOT_COLUMNS) + "\n")


# ----------------------------------------------------------- basics ---

def test_keys_and_day_list():
    assert be.metrics_key("2026-10-19") == "data/futures/um/daily/metrics/TACUSDT/TACUSDT-metrics-2026-10-19.zip"
    assert be.bookdepth_key("2026-11-18").endswith("bookDepth/TACUSDT/TACUSDT-bookDepth-2026-11-18.zip")
    assert be.day_list("2026-10-30", "2026-11-02") == ["2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02"]


def test_decimals_of():
    assert be.decimals_of(pd.Series(["1.5", "1.2345", "7"])) == 4
    assert be.decimals_of(pd.Series(["10", "20"])) == 0


# --------------------------------------------------------- downloads ---

KEY = be.metrics_key("2026-10-19")


def test_fetch_verified_downloads_and_checks_the_checksum(tmp_path):
    s = FakeSession(served(KEY, "a,b\n1,2\n"))
    f = be.fetch_verified(s, KEY, "2026-10-19", tmp_path, lambda x: None)
    assert f.checksum == "verified" and f.csv_path.read_text() == "a,b\n1,2\n" and not f.reused


def test_fetch_verified_flags_mismatch_missing_and_reuses(tmp_path):
    routes = served(KEY, "a,b\n1,2\n")
    routes[f"{ba.DOWNLOAD_URL}/{KEY}.CHECKSUM"] = Resp(200, b"0" * 64 + b"  f\n")
    assert be.fetch_verified(FakeSession(routes), KEY, "d", tmp_path / "1", lambda x: None).checksum == "MISMATCH"
    f404 = be.fetch_verified(FakeSession({}), KEY, "d", tmp_path / "2", lambda x: None)
    assert f404.checksum == "missing (404)" and f404.csv_path is None
    # an existing local copy is reused (only the small checksum file is requested)
    good = served(KEY, "a,b\n1,2\n")
    folder = tmp_path / "3"
    folder.mkdir()
    (folder / Path(KEY).name).write_bytes(good[f"{ba.DOWNLOAD_URL}/{KEY}"].content)
    s = FakeSession(good)
    f = be.fetch_verified(s, KEY, "d", folder, lambda x: None)
    assert f.reused and f.checksum == "verified" and [c[0] for c in s.calls] == [f"{ba.DOWNLOAD_URL}/{KEY}.CHECKSUM"]
    # ...and so is a copy in a reuse directory (the earlier sample folder)
    other = tmp_path / "sample"
    other.mkdir()
    (other / Path(KEY).name).write_bytes(good[f"{ba.DOWNLOAD_URL}/{KEY}"].content)
    s2 = FakeSession(good)
    f2 = be.fetch_verified(s2, KEY, "d", tmp_path / "4", lambda x: None, reuse_dirs=(other,))
    assert f2.reused and f2.checksum == "verified" and (tmp_path / "4" / Path(KEY).name).exists()


def test_refusal_raises(tmp_path):
    with pytest.raises(ba.Refused):
        be.fetch_verified(FakeSession({f"{ba.DOWNLOAD_URL}/{KEY}": Resp(403)}), KEY, "d", tmp_path, lambda x: None)


def test_download_window_builds_urls_stops_at_the_first_404_and_never_lists(tmp_path):
    routes = {}
    for day in ("2026-10-19", "2026-10-20"):
        routes.update(served(be.metrics_key(day), "a,b\n1,2\n"))
    s = FakeSession(routes)
    out = be.download_window(s, "2026-10-19", tmp_path, lambda x: None)
    assert [f.day for f in out] == ["2026-10-19", "2026-10-20"] and all(f.checksum == "verified" for f in out)
    assert all(c[0] != ba.LIST_URL for c in s.calls)  # the archive was not listed
    assert s.calls[-1][0].endswith("TACUSDT-metrics-2026-10-21.zip")  # the probe that returned 404


# ------------------------------------------------------- comparisons ---

def ours_frame(rows):
    df = pd.DataFrame(rows, columns=["ts", "v", "fetched"]).astype({"ts": "int64"})
    df["timestamp"], df["fetched_at_ms"] = df["ts"].astype(str), df["fetched"].astype(str)
    df["x"] = df["v"].map(lambda f: f"{f:.4f}")
    df["klass"] = np.where(df["fetched"] - df["ts"] > be.BACKFILL_LAG_MS, "backfilled", "live")
    return df


def bulk_frame(values, start=D0):
    return pd.DataFrame({"ms": [start + i * 300_000 for i in range(len(values))], "c": [str(v) for v in values]})


def test_compare_column_exact_precision_tolerances_and_mismatches():
    ours = ours_frame([(D0 + 300_000 + i * 300_000, v, D0 + 10**9) for i, v in enumerate([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])])
    bulk = bulk_frame([1.0, 2.00001, 3.0004, 4.0, 5.2, 6.0, 7.0, 8.0])  # our timestamp = bulk label + 5 min
    r = be.compare_column(bulk, ours, "c", "x", 5)
    assert r["rows"] == 8 and r["decimals"] == 4
    assert r["exact"] == pytest.approx(5 / 8)  # three rows differ at full precision
    assert r["at_our_precision"] == pytest.approx(6 / 8)  # 2.00001 rounds to 2.0 at four decimals
    assert r["within_0_1pct"] == pytest.approx(7 / 8) and r["within_1pct"] == pytest.approx(7 / 8)
    assert r["max_abs_diff"] == pytest.approx(0.2)
    assert [m[1:] for m in r["first_mismatches"]] == [(3.0004, 3.0), (5.2, 5.0)]
    assert r["first_mismatches"][0][0] == D0 + 3 * 300_000


def test_compare_column_first_mismatches_capped_at_five_and_live_split():
    n = 10
    ours = ours_frame([(D0 + i * 300_000, 1.0, (D0 + i * 300_000 + 60_000) if i < 4 else D0 + 10**9) for i in range(n)])
    r = be.compare_column(bulk_frame([9.0] * n), ours, "c", "x", 0)
    assert len(r["first_mismatches"]) == be.FIRST_MISMATCHES and r["exact"] == 0.0
    assert r["by_class"]["live"]["rows"] == 4 and r["by_class"]["backfilled"]["rows"] == 6


def test_compare_column_accepts_a_shift_per_row_and_handles_no_overlap():
    keys = [300_000, 600_000, 900_000, 1_200_000, 1_500_000, 1_800_000]
    ours = ours_frame([(D0 + k, float(i), D0 + 10**9) for i, k in enumerate(keys)])
    bulk = pd.DataFrame({"ms": [D0, D0 + 300_000, D0 + 600_000, D0 + 1_200_000, D0 + 1_500_000, D0 + 1_800_000], "c": [str(float(i)) for i in range(6)]})
    r = be.compare_column(bulk, ours, "c", "x", np.array([5, 5, 5, 0, 0, 0]))
    assert r["rows"] == 6 and r["exact"] == 1.0
    assert be.compare_column(bulk, ours, "c", "x", 5)["exact"] < 1.0  # a single fixed shift cannot fit both eras
    assert be.compare_column(bulk_frame([1]), ours_frame([(D0 + 10**12, 1.0, 1)]), "c", "x", 0) == {"rows": 0, "decimals": 4}


def test_era_shift():
    ms = np.array([10, 20, 30])
    assert list(be.era_shift(ms, 20, 5)) == [5, 0, 0]
    assert list(be.era_shift(ms, 20, 0)) == [0, -5, -5]
    assert be.era_shift(ms, None, 5) == 5


def two_era_data(tmp_path):
    day1, day2 = D0, D0 + DAY
    data = tmp_path / "raw"
    write_ours(data, [day1, day2], shift_for_day=lambda d: 5 if d == day1 else 0)
    bulk = be.load_bulk_metrics([_write(tmp_path / "a.csv", metrics_csv(day1, 5)), _write(tmp_path / "b.csv", metrics_csv(day2, 0, shuffle=True))])
    return data, bulk, day2


def _write(path, text):
    path.write_text(text)
    return path


def test_load_bulk_metrics_sorts_and_adds_ms(tmp_path):
    bulk = be.load_bulk_metrics([_write(tmp_path / "b.csv", metrics_csv(D0, 5, shuffle=True))])
    assert bulk["ms"].is_monotonic_increasing and bulk["ms"].iloc[0] == D0


def test_detect_label_change_finds_the_day_the_convention_changes(tmp_path):
    data, bulk, day2 = two_era_data(tmp_path)
    oi = be.load_ours(DATASETS[0].csv_path(data))
    lc = be.detect_label_change(bulk, oi)
    assert lc["boundary_ms"] in (day2, day2 + 300_000) and lc["clean_split"] and lc["old_rows"] > 280 and lc["new_rows"] > 280
    assert lc["by_day"]["2026-10-19"]["+5"] > 0.95 and lc["by_day"]["2026-10-20"]["+0"] > 0.95
    # fixed shift +5 everywhere is wrong on the second day; the era-aware shift is right on both
    fixed = be.compare_column(bulk, oi, "sum_open_interest", "sumOpenInterest", 5)
    aware = be.compare_column(bulk, oi, "sum_open_interest", "sumOpenInterest", be.era_shift(bulk["ms"].to_numpy(), day2, 5))
    assert fixed["exact"] < 0.6 and aware["exact"] > 0.99


def test_detect_label_change_counts_rows_without_a_counterpart(tmp_path):
    data = tmp_path / "raw"
    write_ours(data, [D0])
    bulk = be.load_bulk_metrics([_write(tmp_path / "a.csv", metrics_csv(D0, 5)), _write(tmp_path / "b.csv", metrics_csv(D0 - DAY, 5))])
    lc = be.detect_label_change(bulk, be.load_ours(DATASETS[0].csv_path(data)))
    assert lc["no_counterpart"] >= 280 and lc["new_rows"] == 0 and lc["boundary_ms"] is None


def test_label_offset_shares(tmp_path):
    data, bulk, _ = two_era_data(tmp_path)
    o = be.label_offset(bulk, be.load_ours(DATASETS[0].csv_path(data)))
    assert o["labels_on_5min"] is True
    assert o["by_shift"][5]["equal"] == pytest.approx(0.5, abs=0.02) and o["by_shift"][0]["equal"] == pytest.approx(0.5, abs=0.02)
    assert o["by_shift"][-5]["equal"] == 0.0 and o["by_shift"][10]["equal"] == 0.0


# ------------------------------------------------------------ taker ---

def taker_setup(tmp_path, noise=0.0):
    data = tmp_path / "raw"
    write_ours(data, [D0], ratio_noise=noise)
    bulk = be.load_bulk_metrics([_write(tmp_path / "a.csv", metrics_csv(D0, 5))])
    bulk["ms"] = bulk["ms"]  # taker label = our timestamp (old convention shift 0), so ms is already aligned
    return bulk, be.load_ours(DATASETS[3].csv_path(data))


def test_taker_rounding_is_supported_when_only_our_rounding_differs(tmp_path):
    bulk, taker = taker_setup(tmp_path)
    res = be.taker_explanations(bulk, taker)
    assert res["rounding: bulk equals our own buyVol / sellVol to 1e-6"][1] > 0.99
    assert res["internal: our buySellRatio equals our own buyVol / sellVol within 0.1% (no bulk data involved)"][1] > 0.99
    assert be.explanation_verdict(res).startswith("supported")


def test_taker_is_unexplained_when_bulk_volumes_really_differ(tmp_path):
    bulk, taker = taker_setup(tmp_path)
    bulk["sum_taker_long_short_vol_ratio"] = bulk["sum_taker_long_short_vol_ratio"] * (1 + 0.01 * (np.arange(len(bulk)) % 5))
    res = be.taker_explanations(bulk, taker)
    assert be.explanation_verdict(res).startswith("unexplained")
    assert res["_spread"]["max_rel"] > 0.03


def test_taker_alignment_error_is_visible_in_the_shift_tests(tmp_path):
    bulk, taker = taker_setup(tmp_path)
    shifted = bulk.assign(ms=bulk["ms"] + 300_000)  # pretend the bulk label is 5 minutes late
    res = be.taker_explanations(shifted, taker)
    assert res["alignment: our ratio -5 min from the aligned period, within 0.1%"][1] > 0.99
    assert res["baseline: our ratio, same period, within 0.1%"][1] < 0.1
    assert be.explanation_verdict(res).startswith("supported")


# ------------------------------------------------------------ depth ---

def test_bookdepth_vs_snapshot_compares_only_corresponding_bands():
    t0 = D0
    rows = []
    for k in range(4):
        for pct in (-5.0, -1.0, -0.2, 0.2, 1.0, 2.0, -2.0):
            rows.append([label(t0 + k * 30_000), pct, 100.0, 1000.0 * abs(pct) + k])
    bulk = pd.DataFrame(rows, columns=["timestamp", "percentage", "depth", "notional"])
    snap = pd.DataFrame({"fetched_at_ms": [str(t0 + 31_000)], "bid_depth_usd_1pct": ["1100.0"], "ask_depth_usd_1pct": ["1000.0"],
                         "bid_depth_usd_2pct": ["2000.0"], "ask_depth_usd_2pct": ["1900.0"], "bid_depth_usd_0p5pct": ["500.0"]})
    r = be.bookdepth_vs_snapshot(bulk, snap)
    assert r["snapshot_rows"] == 1 and set(r["pairs"]) == {"bid_depth_usd_1pct", "ask_depth_usd_1pct", "bid_depth_usd_2pct", "ask_depth_usd_2pct"}
    assert "bid_depth_usd_0p5pct" not in r["pairs"]  # the 0.5% band has no counterpart in the bulk file
    assert r["pairs"]["bid_depth_usd_1pct"]["median_ratio"] == pytest.approx(1100.0 / 1001.0)
    far = pd.DataFrame({"fetched_at_ms": [str(t0 + 10 * 60_000)], **{c: ["1"] for c in ("bid_depth_usd_1pct", "ask_depth_usd_1pct", "bid_depth_usd_2pct", "ask_depth_usd_2pct")}})
    assert be.bookdepth_vs_snapshot(bulk, far)["snapshot_rows"] == 0  # no bulk snapshot within 30 s


# ---------------------------------------------------------- cutover ---

def test_cutover_strict_and_ignoring_isolated_files():
    lags = {f"2026-07-{d:02d}": (500.0 if d < 10 else 8.0) for d in range(1, 20)}
    assert be.cutover(lags) == "2026-07-10" and be.cutover_ignoring_isolated(lags) == "2026-07-10"
    lags["2026-07-15"] = 700.0  # one re-written file
    assert be.cutover(lags) == "2026-07-16" and be.cutover_ignoring_isolated(lags) == "2026-07-10"
    assert be.cutover({"2026-07-01": 8.0, "2026-07-02": 60.0}) is None  # the latest file is slow
    assert be.cutover({}) is None
    assert be.cutover({"2026-07-01": 47.9, "2026-07-02": 48.0, "2026-07-03": 10.0}) == "2026-07-03"  # 48 h is not below 48 h


def test_lag_by_month():
    rows = be.lag_by_month({"2026-06-30": 100.0, "2026-07-01": 8.0, "2026-07-02": 10.0, "2026-07-03": 60.0})
    assert [r["month"] for r in rows] == ["2026-06", "2026-07"]
    assert rows[1]["files"] == 3 and rows[1]["median"] == 10.0 and rows[1]["max"] == 60.0 and rows[1]["over_limit"] == 1 and rows[0]["over_limit"] == 1


# ---------------------------------------------------------- formats ---

def test_format_profile_order_missing_slots_and_decimals(tmp_path):
    p = _write(tmp_path / "m.csv", metrics_csv(D0, 5, n=286, shuffle=True))
    pr = be.format_profile(p)
    assert pr["rows"] == 286 and pr["missing_slots"] == 2 and pr["sorted"] is False and pr["duplicates"] == 0
    assert pr["decimals"]["sum_open_interest"] == 16 and pr["decimals"]["sum_taker_long_short_vol_ratio"] == 8
    assert pr["symbols"] == ["TACUSDT"] and pr["label_format"].startswith("datetime text")
    ok = be.format_profile(_write(tmp_path / "n.csv", metrics_csv(D0, 5)))
    assert ok["sorted"] is True and ok["missing_slots"] == 0 and ok["slot_spacing_ok"] is True


# --------------------------------------------------------- runs ---

def listing_xml(names, lm="2026-10-20T08:00:00.000Z"):
    body = "".join(f"<Contents><Key>{n}</Key><LastModified>{lm}</LastModified><Size>1</Size></Contents>" for n in names)
    return (f'<?xml version="1.0"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>false</IsTruncated>{body}</ListBucketResult>').encode()


def listing_routes():
    routes = {}
    for name, t in be.LISTED:
        prefix = t.prefix("daily")
        routes[(ba.LIST_URL, prefix, "")] = Resp(200, listing_xml([f"{prefix}TACUSDT-{name}-2026-10-19.zip", f"{prefix}TACUSDT-{name}-2026-10-20.zip"]))
    return routes


def test_run_check2_lists_once_per_dataset_caches_and_reuses(tmp_path):
    s = FakeSession(listing_routes())
    res = be.Result()
    be.run_check2(s, tmp_path, res, lambda x: None)
    lists = [c for c in s.calls if c[0] == ba.LIST_URL]
    assert len(lists) == 4 and set(res.lags) == {"metrics", "bookDepth", "klines", "markPriceKlines"}  # at most 4 listing requests
    assert (tmp_path / "_listing_lags.json").exists() and res.cutovers["metrics"] == "2026-10-19"
    s2 = FakeSession({})
    res2 = be.Result()
    be.run_check2(s2, tmp_path, res2, lambda x: None, reuse_cache=True)
    assert s2.calls == [] or all(c[0] != ba.LIST_URL for c in s2.calls)  # no listing request on the cached run
    assert res2.lags == json.loads((tmp_path / "_listing_lags.json").read_text()) and "cache" in " ".join(res2.notes)


def test_run_check2_stops_at_a_refused_listing(tmp_path):
    routes = listing_routes()
    routes[(ba.LIST_URL, be.LISTED[1][1].prefix("daily"), "")] = Resp(403)
    s = FakeSession(routes)
    res = be.Result()
    be.run_check2(s, tmp_path, res, lambda x: None)
    assert "check 2 listing bookDepth" in res.stopped and "403" in res.stopped["check 2 listing bookDepth"]
    assert [c for c in s.calls if c[0] == ba.LIST_URL][-1][1]["prefix"] == be.LISTED[1][1].prefix("daily")  # nothing was requested after the refusal


def test_run_check2_downloads_exactly_four_metrics_files(tmp_path):
    routes = listing_routes()
    lags_days = {"2025-08-01": 9000.0, "2026-08-12": 700.0, "2026-08-13": 8.0, "2026-11-10": 8.0}
    cache = {"metrics": {"2025-08-01": 9000.0, "2026-08-12": 700.0, "2026-08-13": 8.0, "2026-08-14": 8.0, "2026-11-10": 8.0}}
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "_listing_lags.json").write_text(json.dumps(cache))
    for day in lags_days:
        routes.update(served(be.metrics_key(day), metrics_csv(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() and int(
            datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000), 5)))
    s = FakeSession(routes)
    res = be.Result()
    be.run_check2(s, tmp_path, res, lambda x: None, reuse_cache=True, sample_dir=tmp_path / "no_samples")
    assert res.cutovers["metrics"] == "2026-08-13"
    assert [f.day for _, f, _ in res.format_files] == ["2025-08-01", "2026-08-12", "2026-08-13", "2026-11-10"]
    assert all(pr and pr["rows"] == 288 for _, _, pr in res.format_files)
    assert sum(1 for c in s.calls if c[0].endswith(".zip")) == 4  # exactly four data files


def test_run_check1_end_to_end_with_a_label_change(tmp_path):
    day1, day2 = D0, D0 + DAY
    data = tmp_path / "raw"
    write_ours(data, [day1, day2], shift_for_day=lambda d: 5 if d == day1 else 0, live_from=day2)
    routes = {}
    routes.update(served(be.metrics_key("2026-10-19"), metrics_csv(day1, 5)))
    routes.update(served(be.metrics_key("2026-10-20"), metrics_csv(day2, 0, shuffle=True)))
    res = be.Result()
    be.run_check1(FakeSession(routes), tmp_path / "out", data, res, lambda x: None, sample_dir=tmp_path / "no_samples")
    assert res.window == ("2026-10-19", "2026-10-20") and [d.checksum for d in res.downloads] == ["verified", "verified"]
    assert res.label_change["boundary_ms"] in (day2, day2 + 300_000) and res.label_change["clean_split"]
    assert res.columns["sum_open_interest"]["exact"] < 0.6  # fixed +5 shift is wrong on the second day
    oi = res.aligned["sum_open_interest"]
    assert oi["rows"] == 576 and oi["exact"] > 0.99 and oi["by_class"]["live"]["rows"] > 0 and oi["by_class"]["backfilled"]["rows"] > 0
    assert res.aligned["count_long_short_ratio"]["at_our_precision"] > 0.99
    assert res.taker_verdict and "depth" not in res.stopped
    text = be.render_report(res)
    assert "**Answer: no.**" in text and "Live versus backfilled" in text and "recommendation only" in text


def test_run_check1_stops_when_a_download_is_refused(tmp_path):
    data = tmp_path / "raw"
    write_ours(data, [D0])
    res = be.Result()
    be.run_check1(FakeSession({f"{ba.DOWNLOAD_URL}/{be.metrics_key('2026-10-19')}": Resp(429, headers={"Retry-After": "1"})}), tmp_path / "out", data, res, lambda x: None, sample_dir=tmp_path / "no_samples")
    assert "check 1 downloads" in res.stopped and "429" in res.stopped["check 1 downloads"]
    assert res.columns == {}


# ----------------------------------------------------------- report ---

def test_recommendation_is_marked_and_depends_on_the_results():
    res = be.Result()
    res.cutovers = {"metrics": "2026-08-13"}
    res.cutovers_loose = {"metrics": "2026-07-12"}
    res.label_change = {"boundary_ms": D0 + DAY}
    res.aligned = {"sum_open_interest": {"rows": 100, "exact": 1.0},
                   "count_long_short_ratio": {"rows": 100, "within_0_1pct": 1.0, "at_our_precision": 0.03},
                   "sum_taker_long_short_vol_ratio": {"rows": 100, "within_0_1pct": 0.64, "at_our_precision": 0.04}}
    res.taker_verdict = "unexplained: no tested explanation reaches 99% of rows"
    text = "\n".join(be.recommendation(res))
    assert "recommendation only" in text and "No rule has been adopted" in text
    assert "2026-08-13" in text and "2026-07-12" in text and "label change" in text and "100.00%" in text
    assert "keep the day-end rule" in text.lower() or "Keep the day-end rule" in text
    res.aligned["sum_open_interest"]["exact"] = 0.8
    assert "no tighter rule is justified" in "\n".join(be.recommendation(res))


def test_report_mentions_the_listing_history_and_stops(tmp_path):
    res = be.Result()
    res.stopped = {"check 2 listing metrics": "HTTP 403 refused"}
    text = be.render_report(res)
    assert be.LISTING_NOTE in text and "Stopped: check 2 listing metrics" in text and "Not shown" in text


def test_main_refuses_report_inside_data_dir(tmp_path, capsys):
    assert be.main(["--data-dir", str(tmp_path), "--report", str(tmp_path / "r.md"), "--out-dir", str(tmp_path / "o")]) == 2
    assert "Refusing" in capsys.readouterr().out
    assert not (tmp_path / "r.md").exists()


def test_report_ends_with_the_decisions_and_the_open_item():
    text = be.render_report(be.Result())
    assert "## Decisions" in text and "Decided by the user on 2026-11-21" in text and "## Open item" in text
    assert "unverified era" in text and "taker_buy_volume" in text
    assert text.rstrip().endswith("Nothing from the bulk archive has been used as a feature.")
