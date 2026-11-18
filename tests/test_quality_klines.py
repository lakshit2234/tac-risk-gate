import csv
import hashlib

import pytest

from tacgate.data import quality_klines as qk
from tacgate.data.binance_klines import COLUMNS

MIN = 60_000
T0 = 1_752_575_400_000


def row(t, o=1.0, h=1.2, l=0.9, c=1.1, v=100, trades=10, close_time=None):
    return [t, o, h, l, c, v, t + MIN - 1 if close_time is None else close_time, 150, trades, 50, 75, 0]


def good_rows(n=30):
    return [row(T0 + i * MIN) for i in range(n)]


def write_csv(path, rows, header=None):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header or COLUMNS)
        w.writerows(rows)
    return path


def run(tmp_path, rows, header=None):
    p = write_csv(tmp_path / "k.csv", rows, header)
    return qk.run_checks(p), p


def has(res, text):
    return any(text in m for m in res.hard_failures)


def test_clean_file_passes(tmp_path):
    res, p = run(tmp_path, good_rows())
    assert res.passed and not res.warnings and not res.gaps
    assert res.summary["rows"] == 30 and res.summary["expected_rows"] == 30
    rep = tmp_path / "r.md"
    assert qk.main(["--path", str(p), "--report", str(rep)]) == 0
    assert "PASS" in rep.read_text(encoding="utf-8")


def test_duplicate_fails(tmp_path):
    rows = good_rows()
    rows.insert(5, list(rows[4]))
    res, _ = run(tmp_path, rows)
    assert not res.passed and has(res, "duplicate")


def test_non_monotonic_fails(tmp_path):
    rows = good_rows()
    rows[10], rows[11] = rows[11], rows[10]
    res, _ = run(tmp_path, rows)
    assert has(res, "not monotonic")


def test_long_gap_is_hard_failure_and_listed(tmp_path):
    rows = good_rows(10) + [row(T0 + i * MIN) for i in range(30, 40)]  # 20 missing minutes
    res, _ = run(tmp_path, rows)
    assert not res.passed and has(res, "longer than 15")
    assert len(res.gaps) == 1
    g = res.gaps[0]
    assert g.minutes == 20 and g.start_ms == T0 + 10 * MIN and g.end_ms == T0 + 29 * MIN


def test_short_gap_is_warning_only(tmp_path):
    rows = good_rows(10) + [row(T0 + i * MIN) for i in range(15, 25)]  # 5 missing minutes
    res, _ = run(tmp_path, rows)
    assert res.passed
    assert len(res.gaps) == 1 and res.gaps[0].minutes == 5
    assert any("gap" in w for w in res.warnings)
    assert res.summary["missing_rows"] == 5


def test_gap_of_exactly_15_minutes_is_warning(tmp_path):
    rows = good_rows(5) + [row(T0 + i * MIN) for i in range(20, 25)]
    res, _ = run(tmp_path, rows)
    assert res.gaps[0].minutes == 15 and res.passed


@pytest.mark.parametrize(
    "bad",
    [
        row(T0 + 3 * MIN, o=1.0, h=0.95, l=0.9, c=1.1),  # high below close
        row(T0 + 3 * MIN, o=1.0, h=1.2, l=1.05, c=1.1),  # low above open
        row(T0 + 3 * MIN, o=0.0, h=1.2, l=0.0, c=1.1),  # zero price
        row(T0 + 3 * MIN, v=-1),  # negative volume
        row(T0 + 3 * MIN, trades=-5),  # negative trades
    ],
)
def test_bad_ohlc_fails(tmp_path, bad):
    rows = good_rows()
    rows[3] = bad
    res, _ = run(tmp_path, rows)
    assert not res.passed and has(res, "OHLC")


def test_bad_close_time_fails(tmp_path):
    rows = good_rows()
    rows[7] = row(T0 + 7 * MIN, close_time=T0 + 7 * MIN + 59_000)
    res, _ = run(tmp_path, rows)
    assert not res.passed and has(res, "close_time")


def test_bad_schema_wrong_columns_fails(tmp_path):
    res, _ = run(tmp_path, good_rows(), header=COLUMNS[:-1] + ["extra"])
    assert not res.passed and has(res, "Schema")


def test_bad_schema_non_numeric_fails(tmp_path):
    rows = good_rows()
    rows[2][1] = "abc"
    res, _ = run(tmp_path, rows)
    assert not res.passed and has(res, "non-numeric")


def test_zero_volume_counted_as_warning(tmp_path):
    rows = good_rows()
    rows[4] = row(T0 + 4 * MIN, v=0)
    res, _ = run(tmp_path, rows)
    assert res.passed and res.summary["zero_volume"] == 1


def test_outliers_flagged_not_removed_and_top_20(tmp_path):
    rows = [row(T0 + i * MIN, o=1, h=1.5, l=0.4, c=1.0 + 0.001 * i) for i in range(40)]
    rows[20] = row(T0 + 20 * MIN, o=1, h=1.5, l=0.2, c=0.3)  # crash
    res, _ = run(tmp_path, rows)
    assert len(res.outliers) == 20
    # the crash candle and the rebound right after it are the two biggest moves
    assert set(res.outliers["open_time"].head(2)) == {T0 + 20 * MIN, T0 + 21 * MIN}
    crash = res.outliers[res.outliers["open_time"] == T0 + 20 * MIN].iloc[0]
    assert crash["return_pct"] < -60
    assert res.outliers["return_pct"].abs().is_monotonic_decreasing
    assert res.summary["rows"] == 40  # nothing dropped


def test_summary_min_max_and_range(tmp_path):
    rows = good_rows()
    rows[6] = row(T0 + 6 * MIN, l=0.5, h=1.2)
    rows[9] = row(T0 + 9 * MIN, h=3.0, c=1.1)
    res, _ = run(tmp_path, rows)
    s = res.summary
    assert s["min_price"] == 0.5 and s["min_price_time"] == T0 + 6 * MIN
    assert s["max_price"] == 3.0 and s["max_price_time"] == T0 + 9 * MIN
    assert s["first"] == T0 and s["last"] == T0 + 29 * MIN


def test_failure_gives_nonzero_exit_and_report_written(tmp_path):
    rows = good_rows()
    rows.insert(5, list(rows[4]))
    p = write_csv(tmp_path / "k.csv", rows)
    rep = tmp_path / "out" / "r.md"
    assert qk.main(["--path", str(p), "--report", str(rep)]) == 1
    assert "FAIL" in rep.read_text(encoding="utf-8")


def test_raw_csv_is_never_modified(tmp_path):
    rows = good_rows()
    rows.insert(5, list(rows[4]))  # dirty file: checker must still not touch it
    p = write_csv(tmp_path / "k.csv", rows)
    before = hashlib.sha256(p.read_bytes()).hexdigest()
    mtime = p.stat().st_mtime_ns
    qk.main(["--path", str(p), "--report", str(tmp_path / "r.md")])
    assert hashlib.sha256(p.read_bytes()).hexdigest() == before
    assert p.stat().st_mtime_ns == mtime


def test_report_path_equal_to_csv_is_refused(tmp_path):
    p = write_csv(tmp_path / "k.csv", good_rows())
    before = p.read_bytes()
    assert qk.main(["--path", str(p), "--report", str(p)]) == 2
    assert p.read_bytes() == before


def test_missing_file_exit_2(tmp_path):
    assert qk.main(["--path", str(tmp_path / "nope.csv"), "--report", str(tmp_path / "r.md")]) == 2
