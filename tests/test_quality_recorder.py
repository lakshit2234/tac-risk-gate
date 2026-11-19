import csv
import hashlib

import pytest

from tacgate.data import quality_recorder as qr
from tacgate.data.recorder import DATASETS, SNAPSHOT_COLUMNS, snapshot_path

P = 300_000
T0 = 1_795_023_000_000  # multiple of 5 minutes
N = 12
NOW = T0 + N * P + 60_000  # one minute after the 12th period label
LIVE_LAG = 6 * 60_000  # fetched 6 min after the label: live by the 15 min rule

DS = {d.name: d for d in DATASETS}
OI, GLS, TOP, TAKER = (DS[n] for n in ("open_interest", "global_long_short", "top_position_long_short", "taker_buy_sell"))


def hist_values(ds, i=0):
    if ds.name == "open_interest":
        return {"symbol": "TACUSDT", "sumOpenInterest": 1000.0 + i, "sumOpenInterestValue": 50.0, "CMCCirculatingSupply": 9.0}
    if ds.name == "taker_buy_sell":
        return {"buySellRatio": 2.0, "buyVol": 200.0, "sellVol": 100.0}
    return {"symbol": "TACUSDT", "longShortRatio": 1.5, "longAccount": 0.6, "shortAccount": 0.4}


def hist_row(ds, ts, fetched, i=0, **over):
    vals = {**hist_values(ds, i), "timestamp": ts, "fetched_at_ms": fetched, **over}
    return [vals[c] for c in ds.columns]


def hist_rows(ds, n=N, lag=LIVE_LAG):
    return [hist_row(ds, T0 + i * P, T0 + i * P + lag, i) for i in range(n)]


def snap_row(i, **over):
    f = T0 + i * P + 30_000
    vals = {
        "fetched_at_ms": f, "server_time_ms": f - 400, "mark": 1.0, "index": 1.0, "lastFundingRate": 0.0001,
        "nextFundingTime": f + 3_600_000, "best_bid": 0.99, "best_ask": 1.01, "spread_bps": 200.0,
        "bid_depth_usd_0p5pct": 100, "bid_depth_usd_1pct": 200, "bid_depth_usd_2pct": 300,
        "ask_depth_usd_0p5pct": 100, "ask_depth_usd_1pct": 200, "ask_depth_usd_2pct": 300,
        "slippage_bps_buy_1000": 5.0, "slippage_bps_buy_5000": 9.0, "slippage_bps_sell_1000": 5.0,
        "slippage_bps_sell_5000": 9.0, "filled_ok": 1,
    }
    vals.update(over)
    return [vals[c] for c in SNAPSHOT_COLUMNS]


def snap_rows(n=N):
    return [snap_row(i) for i in range(n)]


def write(path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def make_dir(tmp_path, **overrides):
    """A clean recorder directory. overrides: name -> rows (history) or 'snapshot' -> rows."""
    d = tmp_path / "raw"
    d.mkdir()
    for ds in DATASETS:
        write(ds.csv_path(d), ds.columns, overrides.get(ds.name, hist_rows(ds)))
    write(snapshot_path(d), SNAPSHOT_COLUMNS, overrides.get("snapshot", snap_rows()))
    return d


def check(d, now=NOW):
    return qr.run_checks(d, now=now)


def has(res, text):
    return any(text in m for m in res.hard_failures)


def warned(res, text):
    return any(text in m for m in res.warnings)


# ------------------------------------------------------------- pass / fail ---

def test_clean_directory_passes_with_no_warnings(tmp_path):
    res = check(make_dir(tmp_path))
    assert res.passed and not res.warnings
    for name, d in res.datasets.items():
        assert d["rows"] == N and d["coverage"] == pytest.approx(100.0) and d["gaps"] == []
        assert d["lookahead_violations"] == 0
    assert res.snapshot["rows"] == N and res.snapshot["filled_ok_share"] == 100.0
    assert res.running["ok"]


def test_duplicate_timestamp_fails(tmp_path):
    rows = hist_rows(OI)
    rows.insert(5, list(rows[4]))
    res = check(make_dir(tmp_path, open_interest=rows))
    assert not res.passed and has(res, "duplicate timestamp")


def test_unsorted_timestamps_fail(tmp_path):
    rows = hist_rows(GLS)
    rows[4], rows[5] = rows[5], rows[4]
    res = check(make_dir(tmp_path, global_long_short=rows))
    assert not res.passed and has(res, "not monotonic")


@pytest.mark.parametrize("bad", ["", "nan", "abc"])
def test_nan_fails(tmp_path, bad):
    rows = hist_rows(TOP)
    rows[3][TOP.columns.index("longAccount")] = bad
    res = check(make_dir(tmp_path, top_position_long_short=rows))
    assert not res.passed and has(res, "NaN")


def test_snapshot_nan_fails_but_blank_slippage_is_allowed(tmp_path):
    rows = snap_rows()
    rows[2][SNAPSHOT_COLUMNS.index("mark")] = ""
    res = check(make_dir(tmp_path, snapshot=rows))
    assert not res.passed and has(res, "NaN")
    rows = snap_rows()
    for c in ("slippage_bps_buy_5000", "slippage_bps_sell_5000"):
        rows[2][SNAPSHOT_COLUMNS.index(c)] = ""
    rows[2][SNAPSHOT_COLUMNS.index("filled_ok")] = 0
    (tmp_path / "b").mkdir()
    res = check(make_dir(tmp_path / "b", snapshot=rows))
    assert res.passed and res.snapshot["blank_slippage_cells"] == 2
    assert res.snapshot["filled_ok_share"] == pytest.approx(100 * (N - 1) / N)


def test_missing_column_fails(tmp_path):
    d = make_dir(tmp_path)
    cols = [c for c in TAKER.columns if c != "buyVol"]
    write(TAKER.csv_path(d), cols, [[r[TAKER.columns.index(c)] for c in cols] for r in hist_rows(TAKER)])
    res = check(d)
    assert not res.passed and has(res, "taker_buy_sell schema")


def test_snapshot_missing_column_fails(tmp_path):
    d = make_dir(tmp_path)
    cols = SNAPSHOT_COLUMNS[:-1]
    write(snapshot_path(d), cols, [r[:-1] for r in snap_rows()])
    assert has(check(d), "snapshot schema")


def test_malformed_row_fails(tmp_path):
    d = make_dir(tmp_path)
    with open(OI.csv_path(d), "ab") as f:
        f.write(b"TACUSDT,1,2,3,4,5,6,7,8\r\n")  # complete line, too many columns
    assert has(check(d), "malformed")


# -------------------------------------------------------------------- gaps ---

def test_gap_is_listed_and_warned_but_not_failed(tmp_path):
    rows = [r for i, r in enumerate(hist_rows(OI)) if i not in (4, 5, 6)]  # 3 slots missing
    res = check(make_dir(tmp_path, open_interest=rows))
    assert res.passed
    d = res.datasets["open_interest"]
    assert d["gaps"] == [(T0 + 3 * P, T0 + 7 * P, 3)]
    assert d["missing_slots"] == 3 and d["expected"] == N
    assert d["coverage"] == pytest.approx(100 * 9 / 12)
    assert d["distribution"].to_dict() == {5.0: 7, 20.0: 1}  # 9 rows: 8 steps, one of them 20 min
    assert warned(res, "1 gap(s) above 5 min, 3 slot(s) missing")


def test_snapshot_gap_over_10_minutes_listed(tmp_path):
    rows = [r for i, r in enumerate(snap_rows()) if i not in (4, 5)]  # a 15 min hole
    res = check(make_dir(tmp_path, snapshot=rows))
    assert res.passed and len(res.snapshot["gaps"]) == 1
    assert warned(res, "snapshot: 1 gap(s) above 10 min")
    assert res.snapshot["coverage"] == pytest.approx(100 * 10 / 12)
    assert res.snapshot["covered_hours"] == pytest.approx(8 * P / 3_600_000)  # 8 steps of 5 min; the 15 min step is not covered


def test_snapshot_gap_of_exactly_10_min_is_not_listed(tmp_path):
    rows = [r for i, r in enumerate(snap_rows()) if i != 5]  # 10 min step, not above
    assert check(make_dir(tmp_path, snapshot=rows)).snapshot["gaps"] == []


# ------------------------------------------------- look-ahead / live split ---

def test_lookahead_violation_fails(tmp_path):
    rows = hist_rows(TAKER)
    rows[6] = hist_row(TAKER, T0 + 6 * P, T0 + 6 * P - 1_000, 6)  # fetched before the timestamp
    res = check(make_dir(tmp_path, taker_buy_sell=rows))
    assert not res.passed and has(res, "look-ahead")
    assert res.datasets["taker_buy_sell"]["lookahead_violations"] == 1


def test_fetched_exactly_at_timestamp_is_allowed(tmp_path):
    rows = hist_rows(OI)
    rows[3] = hist_row(OI, T0 + 3 * P, T0 + 3 * P, 3)
    assert check(make_dir(tmp_path, open_interest=rows)).passed


def test_backfilled_vs_live_split(tmp_path):
    late = T0 + 100 * P  # a later backfill run fetched the first 8 rows hours afterwards
    rows = []
    for i in range(20):
        ts = T0 + i * P
        fetched = late if i < 8 else ts + 2 * 60_000
        rows.append(hist_row(OI, ts, fetched, i))
    d = make_dir(tmp_path, open_interest=rows)
    res = check(d, now=T0 + 20 * P + 60_000)
    info = res.datasets["open_interest"]
    assert info["backfilled"] == {"count": 8, "first": T0, "last": T0 + 7 * P}
    assert info["live"] == {"count": 12, "first": T0 + 8 * P, "last": T0 + 19 * P}
    assert info["live_coverage_to_last"] == pytest.approx(100.0)  # 12 live rows of 12 slots
    assert info["coverage"] == pytest.approx(100.0)
    assert info["live_median_lag_min"] == pytest.approx(2.0)
    assert res.passed  # fetched late for old timestamps is fine; only fetched-before-timestamp is a violation


def test_live_coverage_counts_only_live_rows_when_gap_was_backfilled(tmp_path):
    rows = []
    for i in range(10):
        ts = T0 + i * P
        late = 4 <= i <= 6  # these slots only exist because a later backfill filled the hole
        rows.append(hist_row(OI, ts, ts + (5 * 3_600_000 if late else 120_000), i))
    res = check(make_dir(tmp_path, open_interest=rows), now=T0 + 10 * P)
    info = res.datasets["open_interest"]
    assert info["coverage"] == pytest.approx(100.0) and info["gaps"] == []
    assert info["live"]["count"] == 7 and info["backfilled"]["count"] == 3
    assert info["live_coverage_to_last"] == pytest.approx(100 * 7 / 10)


def test_live_coverage_to_now_penalises_a_stopped_recorder(tmp_path):
    d = make_dir(tmp_path)
    info = check(d, now=T0 + (N + 48) * P).datasets["open_interest"]  # 4 hours later, nothing recorded
    assert info["live_coverage_to_last"] == pytest.approx(100.0)
    assert info["live_coverage_to_now"] == pytest.approx(100 * N / (N + 48 + 1), rel=0.01)


def test_taker_median_lag_reported_in_minutes(tmp_path):
    rows = [hist_row(TAKER, T0 + i * P, T0 + i * P + 6 * 60_000 + (i % 3) * 1000, i) for i in range(N)]
    info = check(make_dir(tmp_path, taker_buy_sell=rows)).datasets["taker_buy_sell"]
    assert info["live_median_lag_min"] == pytest.approx(6.0, abs=0.05)
    assert info["median_lag_min_all"] == pytest.approx(6.0, abs=0.05)


# ----------------------------------------------------------- partial lines ---

def test_partial_last_line_is_ignored_and_file_untouched(tmp_path):
    d = make_dir(tmp_path)
    paths = [ds.csv_path(d) for ds in DATASETS] + [snapshot_path(d)]
    for p in paths:
        with open(p, "ab") as f:
            f.write(b"TACUSDT,1.5,1.5,9")  # the recorder is mid-write
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    res = check(d)
    assert res.passed
    assert res.datasets["open_interest"]["rows"] == N and res.snapshot["rows"] == N
    assert warned(res, "ignored a partial last line")
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths] == before


def test_file_without_any_newline_is_a_schema_failure(tmp_path):
    d = make_dir(tmp_path)
    OI.csv_path(d).write_bytes(b"symbol,sumOpen")
    assert has(check(d), "open_interest schema")


# --------------------------------------------------------------- consistency ---

def test_long_short_share_and_ratio_inconsistency_flagged_not_failed(tmp_path):
    rows = hist_rows(GLS)
    rows[2] = hist_row(GLS, T0 + 2 * P, T0 + 2 * P + LIVE_LAG, 2, longAccount=0.7, shortAccount=0.4)  # sums to 1.1
    rows[3] = hist_row(GLS, T0 + 3 * P, T0 + 3 * P + LIVE_LAG, 3, longShortRatio=3.0)  # 0.6/0.4 = 1.5
    res = check(make_dir(tmp_path, global_long_short=rows))
    assert res.passed
    flags = dict(res.datasets["global_long_short"]["flags"])
    assert flags[f"where longAccount + shortAccount is not within {qr.SHARE_TOL} of 1"] == 1
    assert flags["where longShortRatio differs from longAccount / shortAccount"] >= 1
    assert warned(res, "global_long_short: flag")
    assert res.datasets["global_long_short"]["rows"] == N  # not clipped


def test_taker_ratio_inconsistency_flagged(tmp_path):
    rows = hist_rows(TAKER)
    rows[4] = hist_row(TAKER, T0 + 4 * P, T0 + 4 * P + LIVE_LAG, 4, buySellRatio=5.0)
    res = check(make_dir(tmp_path, taker_buy_sell=rows))
    assert res.passed and dict(res.datasets["taker_buy_sell"]["flags"])["where buySellRatio differs from buyVol / sellVol"] == 1


def test_taker_sell_volume_zero_is_flagged_not_a_crash(tmp_path):
    rows = hist_rows(TAKER)
    rows[1] = hist_row(TAKER, T0 + P, T0 + P + LIVE_LAG, 1, sellVol=0.0, buySellRatio=0.0)
    assert check(make_dir(tmp_path, taker_buy_sell=rows)).passed


def test_open_interest_not_positive_flagged_not_failed(tmp_path):
    rows = hist_rows(OI)
    rows[2] = hist_row(OI, T0 + 2 * P, T0 + 2 * P + LIVE_LAG, 2, sumOpenInterest=0.0)
    res = check(make_dir(tmp_path, open_interest=rows))
    assert res.passed and dict(res.datasets["open_interest"]["flags"])["where sumOpenInterest is not > 0"] == 1


def test_stats_and_extremes_flagged_not_clipped(tmp_path):
    rows = hist_rows(OI)
    rows[7] = hist_row(OI, T0 + 7 * P, T0 + 7 * P + LIVE_LAG, 7, sumOpenInterest=999_999.0)
    s = check(make_dir(tmp_path, open_interest=rows)).datasets["open_interest"]["stats"]
    assert s["max"] == 999_999.0 and s["col"] == "sumOpenInterest"
    assert int(s["extremes"].iloc[0]["timestamp"]) == T0 + 7 * P
    assert len(s["extremes"]) == 5
    assert s["min"] <= s["median"] <= s["max"]


# ------------------------------------------------------------ snapshot rules ---

def test_crossed_book_fails(tmp_path):
    rows = snap_rows()
    rows[3] = snap_row(3, best_bid=1.02, best_ask=1.01)
    res = check(make_dir(tmp_path, snapshot=rows))
    assert not res.passed and has(res, "crossed book")


def test_locked_book_also_fails(tmp_path):
    rows = snap_rows()
    rows[3] = snap_row(3, best_bid=1.0, best_ask=1.0)
    assert has(check(make_dir(tmp_path, snapshot=rows)), "crossed book")


def test_snapshot_duplicates_and_unsorted_fail(tmp_path):
    rows = snap_rows()
    rows.insert(4, list(rows[3]))
    assert has(check(make_dir(tmp_path, snapshot=rows)), "duplicate fetched_at_ms")
    rows = snap_rows()
    rows[4], rows[5] = rows[5], rows[4]
    (tmp_path / "x").mkdir()
    assert has(check(make_dir(tmp_path / "x", snapshot=rows)), "not monotonic")


def test_snapshot_flags_do_not_fail(tmp_path):
    rows = snap_rows()
    rows[1] = snap_row(1, spread_bps=0.0)
    rows[2] = snap_row(2, slippage_bps_buy_1000=20.0, slippage_bps_buy_5000=10.0)  # 5000 cheaper than 1000
    rows[3] = snap_row(3, mark=1.1, index=1.0)  # 10% apart
    rows[4] = snap_row(4, nextFundingTime=T0)  # already in the past
    rows[5] = snap_row(5, bid_depth_usd_1pct=-1)
    rows[6] = snap_row(6, server_time_ms=T0 + 6 * P + 30_000 + 10_000)  # local clock 10 s behind the server
    res = check(make_dir(tmp_path, snapshot=rows))
    assert res.passed
    flags = dict(res.snapshot["flags"])
    assert flags["with spread_bps <= 0"] == 1
    assert flags["where buy slippage for 5000 is below 1000"] == 1
    assert flags["where sell slippage for 5000 is below 1000"] == 0
    assert flags["where mark and index differ by more than 5%"] == 1
    assert flags["where nextFundingTime is not after fetched_at_ms"] == 1
    assert flags["with a negative depth value"] == 1
    assert flags["where the local clock is more than 2s behind server_time_ms"] == 1


def test_snapshot_spacing_distribution_and_hours(tmp_path):
    s = check(make_dir(tmp_path)).snapshot
    assert s["distribution"].to_dict() == {300.0: N - 1}
    assert s["span_hours"] == pytest.approx((N - 1) * P / 3_600_000)
    assert s["covered_hours"] == pytest.approx((N - 1) * P / 3_600_000)
    assert s["coverage"] == pytest.approx(100.0)


# ----------------------------------------------------------- recorder running ---

def test_fresh_snapshot_means_running(tmp_path):
    res = check(make_dir(tmp_path), now=T0 + (N - 1) * P + 30_000 + 4 * 60_000)
    assert res.running["ok"] and not warned(res, "Recorder may be stopped")


def test_old_snapshot_warns_recorder_may_be_stopped_but_does_not_fail(tmp_path):
    res = check(make_dir(tmp_path), now=T0 + (N - 1) * P + 30_000 + 16 * 60_000)
    assert res.passed and not res.running["ok"] and res.running["age_min"] == pytest.approx(16.0)
    assert warned(res, "Recorder may be stopped")


def test_error_log_is_summarised_not_modified(tmp_path):
    d = make_dir(tmp_path)
    log = d / "recorder_errors.log"
    log.write_text(
        "2026-11-18 18:01:27 UTC | GAP | restart: ...\n2026-11-18 18:10:00 UTC | ERROR | snapshot: boom\n", encoding="utf-8"
    )
    before = log.read_bytes()
    res = check(d)
    assert res.log_summary["lines"] == 2 and res.log_summary["kinds"] == {"GAP": 1, "ERROR": 1}
    assert log.read_bytes() == before


# ------------------------------------------------------------------- CLI ---

def test_report_written_and_inputs_never_modified(tmp_path):
    d = make_dir(tmp_path)
    files = sorted(d.iterdir())
    before = {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in files}
    rep = tmp_path / "out" / "r.md"
    assert qr.main(["--dir", str(d), "--report", str(rep)]) == 0
    text = rep.read_text(encoding="utf-8")
    assert "PASS" in text and "Is the recorder running?" in text and "BACKFILLED" in text
    assert {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in files} == before
    assert sorted(d.iterdir()) == files  # no new files in the data directory


def test_failure_gives_exit_1(tmp_path):
    rows = hist_rows(OI)
    rows.insert(5, list(rows[4]))
    d = make_dir(tmp_path, open_interest=rows)
    rep = tmp_path / "r.md"
    assert qr.main(["--dir", str(d), "--report", str(rep)]) == 1
    assert "FAIL" in rep.read_text(encoding="utf-8")


def test_report_inside_data_dir_is_refused(tmp_path):
    d = make_dir(tmp_path)
    before = sorted(p.name for p in d.iterdir())
    assert qr.main(["--dir", str(d), "--report", str(d / "report.md")]) == 2
    assert qr.main(["--dir", str(d), "--report", str(d / "sub" / "report.md")]) == 2
    assert sorted(p.name for p in d.iterdir()) == before


def test_missing_file_or_directory_exit_2(tmp_path):
    d = make_dir(tmp_path)
    snapshot_path(d).unlink()
    assert qr.main(["--dir", str(d), "--report", str(tmp_path / "r.md")]) == 2
    assert qr.main(["--dir", str(tmp_path / "nope"), "--report", str(tmp_path / "r.md")]) == 2
