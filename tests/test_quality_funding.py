import csv
import hashlib

import pytest

from tacgate.data import quality_funding as qf

H = 3_600_000
T0 = 1_752_580_800_000
COLS = qf.FUNDING_COLUMNS


def rec(t, rate="0.00005000", mark="0.021"):
    return ["TACUSDT", t, rate, mark, "Regular"]


def good(n=12):
    return [rec(T0 + i * 4 * H) for i in range(n)]


def write_csv(path, rows, header=None):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header or COLS)
        w.writerows(rows)
    return path


def run(tmp_path, rows, header=None):
    p = write_csv(tmp_path / "f.csv", rows, header)
    return qf.run_checks(p), p


def has(res, text):
    return any(text in m for m in res.hard_failures)


def test_clean_file_passes(tmp_path):
    res, p = run(tmp_path, good())
    assert res.passed and not res.odd_gaps
    assert res.summary["rows"] == 12 and res.summary["expected_if_4h"] == 12 and res.summary["difference"] == 0
    rep = tmp_path / "r.md"
    assert qf.main(["--path", str(p), "--report", str(rep)]) == 0
    assert "PASS" in rep.read_text(encoding="utf-8")


def test_duplicate_fails(tmp_path):
    rows = good()
    rows.insert(4, list(rows[3]))
    res, _ = run(tmp_path, rows)
    assert not res.passed and has(res, "duplicate")


def test_unsorted_fails(tmp_path):
    rows = good()
    rows[5], rows[6] = rows[6], rows[5]
    res, _ = run(tmp_path, rows)
    assert not res.passed and has(res, "not monotonic")


@pytest.mark.parametrize("bad", ["", "nan", "abc"])
def test_nan_rate_fails(tmp_path, bad):
    rows = good()
    rows[3][2] = bad
    res, _ = run(tmp_path, rows)
    assert not res.passed and has(res, "NaN")


def test_missing_column_fails(tmp_path):
    rows = [r[:4] for r in good()]
    res, _ = run(tmp_path, rows, header=COLS[:4])
    assert not res.passed and has(res, "Schema")


def test_non_numeric_funding_time_fails(tmp_path):
    rows = good()
    rows[2][1] = "soon"
    res, _ = run(tmp_path, rows)
    assert not res.passed and has(res, "fundingTime")


def test_odd_gap_listed_but_not_failed(tmp_path):
    # 4h steps, then one 8h step (a missing slot), then a 1h step
    times = [T0, T0 + 4 * H, T0 + 12 * H, T0 + 16 * H, T0 + 17 * H]
    res, _ = run(tmp_path, [rec(t) for t in times])
    assert res.passed
    assert sorted(round(o.hours) for o in res.odd_gaps) == [1, 8]
    eight = next(o for o in res.odd_gaps if round(o.hours) == 8)
    assert eight.prev_ms == T0 + 4 * H and eight.next_ms == T0 + 12 * H
    assert any("not 4h" in w for w in res.warnings)
    assert res.gap_distribution.to_dict() == {1.0: 1, 4.0: 2, 8.0: 1}
    assert res.summary["rows"] == 5
    assert res.summary["expected_if_4h"] == 5  # 17h span rounds to 4 slots +1: shows grid is not assumed


def test_row_count_difference_explained_by_actual_gap(tmp_path):
    times = [T0 + i * 4 * H for i in range(5)] + [T0 + i * 4 * H for i in range(6, 9)]  # one slot missing
    res, _ = run(tmp_path, [rec(t) for t in times])
    assert res.summary["expected_if_4h"] - res.summary["rows"] == 1
    text = "\n".join(qf.explain_difference(res))
    assert "8.00h" in text and "+1.00 slot" in text


def test_millisecond_jitter_is_not_an_odd_gap(tmp_path):
    times = [T0, T0 + 4 * H + 5, T0 + 8 * H + 2, T0 + 12 * H - 3]
    res, _ = run(tmp_path, [rec(t) for t in times])
    assert res.passed and not res.odd_gaps and not res.warnings
    assert res.jitter["exact_4h"] == 0 and res.jitter["jitter_only"] == 3
    assert (res.jitter["dev_min_ms"], res.jitter["dev_max_ms"]) == (-5, 5)  # gaps are 4h+5, 4h-3, 4h-5 ms
    assert res.gap_distribution.to_dict() == {4.0: 3}


def test_gap_over_24h_fails(tmp_path):
    times = [T0, T0 + 4 * H, T0 + 4 * H + 25 * H, T0 + 4 * H + 29 * H]
    res, _ = run(tmp_path, [rec(t) for t in times])
    assert not res.passed and has(res, "above 24h")


def test_gap_of_exactly_24h_is_warning_only(tmp_path):
    times = [T0, T0 + 24 * H, T0 + 28 * H]
    res, _ = run(tmp_path, [rec(t) for t in times])
    assert res.passed and len(res.odd_gaps) == 1


def test_rate_extremes_flagged_not_failed_and_not_removed(tmp_path):
    rows = good()
    rows[2][2] = "0.0052"
    rows[7][2] = "-0.0021"
    res, _ = run(tmp_path, rows)
    assert res.passed
    r = res.rate_stats
    assert r["max"] == 0.0052 and r["min"] == -0.0021 and r["above"] == 1 and r["below"] == 1
    assert res.summary["rows"] == 12
    assert res.extreme_rates.iloc[0]["fundingRate"] == 0.0052
    assert len(res.extreme_rates) <= qf.TOP_RATES


def test_blank_or_zero_markprice_reported_not_failed(tmp_path):
    rows = good()
    rows[1][3] = ""
    rows[2][3] = "0"
    res, _ = run(tmp_path, rows)
    assert res.passed
    assert res.summary["markprice_blank"] == 1 and res.summary["markprice_nonpositive"] == 1
    assert any("markPrice" in w for w in res.warnings)


def test_failure_gives_exit_1_and_report_written(tmp_path):
    rows = good()
    rows.insert(4, list(rows[3]))
    p = write_csv(tmp_path / "f.csv", rows)
    rep = tmp_path / "out" / "r.md"
    assert qf.main(["--path", str(p), "--report", str(rep)]) == 1
    assert "FAIL" in rep.read_text(encoding="utf-8")


def test_raw_csv_never_modified(tmp_path):
    rows = good()
    rows.insert(4, list(rows[3]))
    p = write_csv(tmp_path / "f.csv", rows)
    before, mtime = hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns
    qf.main(["--path", str(p), "--report", str(tmp_path / "r.md")])
    assert hashlib.sha256(p.read_bytes()).hexdigest() == before
    assert p.stat().st_mtime_ns == mtime


def test_report_path_equal_to_csv_refused(tmp_path):
    p = write_csv(tmp_path / "f.csv", good())
    before = p.read_bytes()
    assert qf.main(["--path", str(p), "--report", str(p)]) == 2
    assert p.read_bytes() == before


def test_missing_file_exit_2(tmp_path):
    assert qf.main(["--path", str(tmp_path / "nope.csv"), "--report", str(tmp_path / "r.md")]) == 2
