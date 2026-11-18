import csv
import hashlib

import pytest

from tacgate.data import crosscheck_klines as cc
from tacgate.data.binance_klines import COLUMNS as BN_COLS
from tacgate.data.bybit_klines import COLUMNS as BY_COLS

MIN = 60_000
T0 = 1_752_577_200_000


def px(i):
    return round(1.0 + 0.01 * i, 4)


def bn_row(t, c, o=None, h=None, l=None, v=100):
    o = c if o is None else o
    h = max(o, c) + 0.001 if h is None else h
    l = min(o, c) - 0.001 if l is None else l
    return [t, o, h, l, c, v, t + MIN - 1, 1, 1, 1, 1, 0]


def by_row(t, c, o=None, h=None, l=None, v=100):
    o = c if o is None else o
    h = max(o, c) + 0.001 if h is None else h
    l = min(o, c) - 0.001 if l is None else l
    return [t, o, h, l, c, v, 1.5]


def bn_rows(times):
    return [bn_row(t, px((t - T0) // MIN)) for t in times]


def by_rows(times):
    return [by_row(t, px((t - T0) // MIN)) for t in times]


def write(path, rows, header):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path


def setup(tmp_path, bn=None, by=None, bn_header=BN_COLS, by_header=BY_COLS):
    times = [T0 + i * MIN for i in range(30)]
    b = write(tmp_path / "bn.csv", bn if bn is not None else bn_rows(times), bn_header)
    y = write(tmp_path / "by.csv", by if by is not None else by_rows(times), by_header)
    return b, y


def has(res, text):
    return any(text in m for m in res.hard_failures)


def test_clean_match_passes(tmp_path):
    b, y = setup(tmp_path)
    res = cc.run_checks(b, y)
    assert res.passed and not res.warnings
    assert res.overlap["rows"] == 30
    d = res.diff_stats
    assert d["max_abs"] == 0 and d["mean"] == 0 and d["over_flag"] == 0
    assert d["return_corr"] == pytest.approx(1.0)
    rep = tmp_path / "r.md"
    assert cc.main(["--binance", str(b), "--bybit", str(y), "--report", str(rep)]) == 0
    assert "PASS" in rep.read_text(encoding="utf-8")


def test_bybit_long_gap_is_hard_failure(tmp_path):
    times = [T0 + i * MIN for i in range(10)] + [T0 + i * MIN for i in range(30, 40)]  # 20 missing
    b, y = setup(tmp_path, by=by_rows(times))
    res = cc.run_checks(b, y)
    assert not res.passed and has(res, "longer than 15")
    assert res.gaps[0].minutes == 20 and res.gaps[0].start_ms == T0 + 10 * MIN


def test_bybit_short_gap_is_warning_and_listed(tmp_path):
    times = [T0 + i * MIN for i in range(10)] + [T0 + i * MIN for i in range(15, 30)]  # 5 missing
    b, y = setup(tmp_path, by=by_rows(times))
    res = cc.run_checks(b, y)
    assert res.passed and len(res.gaps) == 1 and res.gaps[0].minutes == 5
    assert res.bybit_summary["rows"] == 25 and res.bybit_summary["expected_rows"] == 30
    assert res.overlap["only_binance"]["inside_range"] == 5  # flagged as missing from Bybit
    assert any("only in Binance" in w for w in res.warnings)


def test_bybit_duplicate_fails(tmp_path):
    rows = by_rows([T0 + i * MIN for i in range(30)])
    rows.insert(5, list(rows[4]))
    b, y = setup(tmp_path, by=rows)
    res = cc.run_checks(b, y)
    assert not res.passed and has(res, "duplicate")


def test_bybit_unsorted_fails(tmp_path):
    rows = by_rows([T0 + i * MIN for i in range(30)])
    rows[3], rows[4] = rows[4], rows[3]
    b, y = setup(tmp_path, by=rows)
    assert has(cc.run_checks(b, y), "not monotonic")


def test_bybit_bad_ohlc_fails(tmp_path):
    rows = by_rows([T0 + i * MIN for i in range(30)])
    rows[7] = by_row(T0 + 7 * MIN, 1.07, o=1.07, h=1.0, l=0.9)  # high below close
    b, y = setup(tmp_path, by=rows)
    assert has(cc.run_checks(b, y), "OHLC")


def test_price_mismatch_above_1pct_is_flagged_not_failed(tmp_path):
    rows = by_rows([T0 + i * MIN for i in range(30)])
    rows[10] = by_row(T0 + 10 * MIN, px(10) * 1.05, v=0)  # +5%
    b, y = setup(tmp_path, by=rows)
    res = cc.run_checks(b, y)
    assert res.passed
    assert res.diff_stats["over_flag"] == 1
    assert res.flagged.iloc[0]["open_time"] == T0 + 10 * MIN
    assert res.flagged.iloc[0]["diff_pct"] == pytest.approx(5.0, abs=1e-6)
    assert res.top_diffs.iloc[0]["open_time"] == T0 + 10 * MIN
    assert any("more than 1.0%" in w for w in res.warnings)
    assert res.diff_stats["max_abs"] == pytest.approx(5.0, abs=1e-6)  # not clipped


def test_rows_only_in_one_file_outside_range_not_a_warning(tmp_path):
    bn_times = [T0 + i * MIN for i in range(30)]  # Binance starts earlier, ends later
    by_times = [T0 + i * MIN for i in range(5, 25)]
    b, y = setup(tmp_path, bn=bn_rows(bn_times), by=by_rows(by_times))
    res = cc.run_checks(b, y)
    o = res.overlap
    assert o["rows"] == 20
    assert o["only_binance"]["count"] == 10 and o["only_binance"]["outside_range"] == 10
    assert o["only_binance"]["inside_range"] == 0
    assert o["only_bybit"]["count"] == 0
    assert o["only_binance"]["first"][0] == T0 and o["only_binance"]["last"][-1] == T0 + 29 * MIN
    assert res.passed and not res.warnings


def test_rows_only_in_binance_inside_range_flagged(tmp_path):
    by_times = [T0 + i * MIN for i in range(30) if i != 12]
    b, y = setup(tmp_path, by=by_rows(by_times))
    res = cc.run_checks(b, y)
    assert res.overlap["only_binance"]["inside_examples"] == [T0 + 12 * MIN]
    assert res.passed  # a 1-minute gap is a Bybit warning, not a failure


def test_missing_column_fails(tmp_path):
    rows = [r[:6] for r in by_rows([T0 + i * MIN for i in range(30)])]
    b, y = setup(tmp_path, by=rows, by_header=BY_COLS[:6])
    res = cc.run_checks(b, y)
    assert not res.passed and has(res, "Bybit schema")
    assert cc.main(["--binance", str(b), "--bybit", str(y), "--report", str(tmp_path / "r.md")]) == 1


def test_binance_missing_column_fails(tmp_path):
    rows = [r[:6] for r in bn_rows([T0 + i * MIN for i in range(30)])]
    b, y = setup(tmp_path, bn=rows, bn_header=BN_COLS[:6])
    assert has(cc.run_checks(b, y), "Binance schema")


def test_no_overlap_is_hard_failure(tmp_path):
    b, y = setup(
        tmp_path,
        bn=bn_rows([T0 + i * MIN for i in range(5)]),
        by=by_rows([T0 + (i + 100) * MIN for i in range(5)]),
    )
    assert has(cc.run_checks(b, y), "no timestamps present in both")


def test_extremes_and_low_price_flags(tmp_path):
    times = [T0 + i * MIN for i in range(30)]
    bn = bn_rows(times)
    by = by_rows(times)
    bn[4] = bn_row(times[4], px(4), l=0.0003)  # Binance low 0.0003 (<= 0.00031)
    by[6] = by_row(times[6], px(6), l=0.0004)  # Bybit low 0.0004 (<0.0005 but > 0.00031)
    by[20] = by_row(times[20], px(20), h=9.0)  # Bybit high 9.0
    b, y = setup(tmp_path, bn=bn, by=by)
    res = cc.run_checks(b, y)
    assert res.extremes["Binance"]["low"] == 0.0003 and res.extremes["Binance"]["low_time"] == times[4]
    assert res.extremes["Bybit"]["low"] == 0.0004 and res.extremes["Bybit"]["low_time"] == times[6]
    assert res.extremes["Bybit"]["high"] == 9.0 and res.extremes["Bybit"]["high_time"] == times[20]
    lp = res.low_price
    assert lp["Binance"]["count_below_flag"] == 1 and lp["Binance"]["count_at_or_below_target"] == 1
    assert lp["Bybit"]["count_below_flag"] == 1 and lp["Bybit"]["count_at_or_below_target"] == 0
    assert lp["Binance"]["lowest"].iloc[0]["open_time"] == times[4]


def test_return_correlation_uses_only_consecutive_minutes(tmp_path):
    times = [T0 + i * MIN for i in range(30) if i != 10]  # a hole at minute 10 in BOTH files
    b, y = setup(tmp_path, bn=bn_rows(times), by=by_rows(times))
    res = cc.run_checks(b, y)
    assert res.diff_stats["return_pairs"] == 27  # 29 rows, 28 steps, minus the one across the hole
    assert res.diff_stats["return_corr"] == pytest.approx(1.0)


def test_inputs_never_modified_and_report_written(tmp_path):
    rows = by_rows([T0 + i * MIN for i in range(30)])
    rows.insert(5, list(rows[4]))  # dirty
    b, y = setup(tmp_path, by=rows)
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (b, y)]
    mtimes = [p.stat().st_mtime_ns for p in (b, y)]
    rep = tmp_path / "out" / "r.md"
    assert cc.main(["--binance", str(b), "--bybit", str(y), "--report", str(rep)]) == 1
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in (b, y)] == before
    assert [p.stat().st_mtime_ns for p in (b, y)] == mtimes
    assert "FAIL" in rep.read_text(encoding="utf-8")


@pytest.mark.parametrize("which", ["binance", "bybit"])
def test_report_path_equal_to_input_refused(tmp_path, which):
    b, y = setup(tmp_path)
    target = b if which == "binance" else y
    before = target.read_bytes()
    assert cc.main(["--binance", str(b), "--bybit", str(y), "--report", str(target)]) == 2
    assert target.read_bytes() == before


def test_missing_file_exit_2(tmp_path):
    b, y = setup(tmp_path)
    assert cc.main(["--binance", str(tmp_path / "nope.csv"), "--bybit", str(y), "--report", str(tmp_path / "r.md")]) == 2
    assert cc.main(["--binance", str(b), "--bybit", str(tmp_path / "nope.csv"), "--report", str(tmp_path / "r.md")]) == 2
