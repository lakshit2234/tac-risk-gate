"""Tests for the read-only recorder lag analysis (synthetic CSVs, no network, no real data)."""
import csv
from pathlib import Path

import pytest

from tacgate.data import lag_analysis as la
from tacgate.data.recorder import DATASETS, PERIOD_MS

BASE = 1_795_104_000_000  # 2026-11-19 16:00:00 UTC, aligned to 5 minutes
SINCE = BASE
DS = {d.name: d for d in DATASETS}
NON_TAKER = ["open_interest", "global_long_short", "top_position_long_short"]


def make_row(ds, ts, fetched):
    row = []
    for f in ds.fields:
        row.append("TACUSDT" if f == "symbol" else ts if f == "timestamp" else "1.5")
    return row + [fetched]


def write_csv(directory: Path, name: str, entries, partial: str = ""):
    """entries: list of (timestamp, fetched_at_ms)."""
    ds = DS[name]
    path = ds.csv_path(directory)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(ds.columns)
        for ts, fe in entries:
            w.writerow(make_row(ds, ts, fe))
    if partial:
        with path.open("a", newline="") as f:
            f.write(partial)  # no trailing newline = partial last line


def write_all(directory, per_file):
    """per_file: dict name -> entries; unlisted datasets get one on-time row."""
    for ds in DATASETS:
        off = PERIOD_MS if ds.name == la.TAKER else 0
        default = [(BASE, BASE + off + 45_000)]
        write_csv(directory, ds.name, per_file.get(ds.name, default))


def on_time(n, name="open_interest"):
    off = PERIOD_MS if name == la.TAKER else 0
    return [(BASE + i * PERIOD_MS, BASE + i * PERIOD_MS + off + 45_000) for i in range(n)]


def analyse(tmp_path, name, since=SINCE):
    return la.analyse_dataset(DS[name], tmp_path, since)


def test_all_on_time(tmp_path):
    write_all(tmp_path, {"open_interest": on_time(10)})
    r = analyse(tmp_path, "open_interest")
    assert len(r.live) == 10
    assert r.counts() == {"first": 10, "second": 0, "later": 0}
    assert r.first_pct() == 100.0
    assert r.percentiles()["p50"] == 45_000 and r.percentiles()["max"] == 45_000
    assert la.verdict_line(r) == "open_interest: offset 45 s sufficient: 100.0% first-cycle"


def test_some_late_are_bucketed_and_listed(tmp_path):
    entries = [
        (BASE, BASE + 45_000),  # first
        (BASE + PERIOD_MS, BASE + PERIOD_MS + 119_999),  # first (just under 120 s)
        (BASE + 2 * PERIOD_MS, BASE + 2 * PERIOD_MS + 120_000),  # second (boundary)
        (BASE + 3 * PERIOD_MS, BASE + 3 * PERIOD_MS + 420_000),  # second (upper boundary)
        (BASE + 4 * PERIOD_MS, BASE + 4 * PERIOD_MS + 420_001),  # later
    ]
    write_all(tmp_path, {"open_interest": entries})
    r = analyse(tmp_path, "open_interest")
    assert r.counts() == {"first": 2, "second": 2, "later": 1}
    assert r.first_pct() == 40.0
    late = [x for x in r.live if x.bucket != "first"]
    assert [x.ts for x in late] == [BASE + 2 * PERIOD_MS, BASE + 3 * PERIOD_MS, BASE + 4 * PERIOD_MS]
    assert r.percentiles()["max"] == 420_001
    text = la.render_report([r], la.agreement([r]), tmp_path, SINCE)
    assert "Rows not captured in the first cycle (3 in total)" in text
    assert utc_of(BASE + 4 * PERIOD_MS) in text


def utc_of(ms):
    return la.utc(ms)


def test_backfilled_rows_skipped_and_counted(tmp_path):
    entries = [
        (BASE, BASE + 45_000),
        (BASE + PERIOD_MS, BASE + PERIOD_MS + la.BACKFILL_LAG_MS),  # exactly 15 min: still live
        (BASE + 2 * PERIOD_MS, BASE + 2 * PERIOD_MS + la.BACKFILL_LAG_MS + 1),  # backfilled
        (BASE + 3 * PERIOD_MS, BASE + 3 * PERIOD_MS + 3_600_000),  # backfilled
    ]
    write_all(tmp_path, {"open_interest": entries})
    r = analyse(tmp_path, "open_interest")
    assert r.backfilled == 2
    assert len(r.live) == 2
    assert r.counts()["later"] == 1  # the exactly-15-min row is live and "later"


def test_taker_label_offset(tmp_path):
    # label = period start: closes 300 s later. fetched 345 s after the label = 45 s after close = first cycle.
    entries = [
        (BASE, BASE + PERIOD_MS + 45_000),  # first
        (BASE + PERIOD_MS, BASE + 2 * PERIOD_MS + 45_000 + 120_000),  # 165 s after close: second
    ]
    write_all(tmp_path, {"taker_buy_sell": entries})
    r = analyse(tmp_path, "taker_buy_sell")
    assert [x.lag for x in r.live] == [345_000, 465_000]
    assert [x.after_close for x in r.live] == [45_000, 165_000]
    assert [x.bucket for x in r.live] == ["first", "second"]
    # a lag of 345 s is NOT mistaken for a backfill or a late row
    assert r.backfilled == 0
    # hour breakdown uses the period close, not the label: label 15:57 closes in hour 16
    r2 = la.DatasetResult("taker_buy_sell", True)
    r2.live.append(la.Live(BASE - 3 * 60_000, BASE + 100_000, 0, 0, "first"))
    assert list(r2.by_hour()) == [16]


def test_non_taker_label_is_not_offset(tmp_path):
    write_all(tmp_path, {"open_interest": [(BASE, BASE + 200_000)]})
    r = analyse(tmp_path, "open_interest")
    assert r.live[0].after_close == 200_000 and r.live[0].bucket == "second"


def test_partial_last_line_ignored(tmp_path):
    write_all(tmp_path, {"open_interest": on_time(3)})
    write_csv(tmp_path, "open_interest", on_time(3), partial=f"TACUSDT,1.5,1.5,1.5,{BASE + 9 * PERIOD_MS},17951")
    r = analyse(tmp_path, "open_interest")
    assert len(r.live) == 3
    assert r.ignored_partial_bytes > 0
    assert r.malformed == 0  # the partial line is ignored, not counted as a bad row


def test_malformed_row_counted_not_fatal(tmp_path):
    write_all(tmp_path, {"open_interest": on_time(2)})
    path = DS["open_interest"].csv_path(tmp_path)
    with path.open("a", newline="") as f:
        f.write("TACUSDT,1,2\n")  # wrong column count
    r = analyse(tmp_path, "open_interest")
    assert len(r.live) == 2 and r.malformed == 1


def test_since_ms_filter(tmp_path):
    entries = [(BASE - 10 * PERIOD_MS + i * PERIOD_MS, BASE - 10 * PERIOD_MS + i * PERIOD_MS + 45_000) for i in range(15)]
    write_all(tmp_path, {"open_interest": entries})
    r = analyse(tmp_path, "open_interest", since=BASE)
    # fetched_at_ms >= BASE: rows i=10..14 only (row 9 fetched at BASE - 5 min + 45 s)
    assert len(r.live) == 5
    assert r.before_since == 10
    assert min(x.fetched for x in r.live) >= BASE
    r_all = analyse(tmp_path, "open_interest", since=0)
    assert len(r_all.live) == 15 and r_all.before_since == 0


def test_hour_breakdown(tmp_path):
    h16 = BASE  # 16:00
    h17 = BASE + 3_600_000
    entries = [(h16, h16 + 45_000), (h16 + PERIOD_MS, h16 + PERIOD_MS + 200_000),
               (h17, h17 + 45_000)]
    write_all(tmp_path, {"open_interest": entries})
    r = analyse(tmp_path, "open_interest")
    assert r.by_hour() == {16: (1, 2), 17: (1, 1)}


def test_agreement_mixed_and_aligned(tmp_path):
    t = [BASE + i * PERIOD_MS for i in range(4)]
    oi = [(t[0], t[0] + 45_000), (t[1], t[1] + 45_000), (t[2], t[2] + 300_000), (t[3], t[3] + 45_000)]
    gl = [(t[0], t[0] + 45_000), (t[1], t[1] + 200_000), (t[2], t[2] + 300_000), (t[3], t[3] + 45_000)]
    tp = [(t[0], t[0] + 45_000), (t[1], t[1] + 45_000), (t[2], t[2] + 300_000), (t[3], t[3] + 45_000)]
    write_all(tmp_path, {"open_interest": oi, "global_long_short": gl, "top_position_long_short": tp})
    results, ag = la.run(tmp_path, SINCE)
    assert ag.common == 4
    assert ag.all_first == 2 and ag.all_not_first == 1 and ag.mixed == 1
    assert ag.late_by_file["global_long_short"] == 1 and ag.late_by_file["open_interest"] == 0
    assert ag.examples[0][0] == t[1]
    assert "taker_buy_sell" not in ag.names


def test_agreement_only_counts_timestamps_in_all_files(tmp_path):
    write_all(tmp_path, {
        "open_interest": on_time(3),
        "global_long_short": on_time(3),
        "top_position_long_short": on_time(2),  # missing the third timestamp
    })
    _, ag = la.run(tmp_path, SINCE)
    assert ag.common == 2 and ag.mixed == 0 and ag.all_first == 2


def test_no_live_rows_gives_no_verdict(tmp_path):
    write_all(tmp_path, {"open_interest": [(BASE, BASE + 7_200_000)]})
    r = analyse(tmp_path, "open_interest")
    assert r.live == [] and r.backfilled == 1
    assert "no verdict" in la.verdict_line(r)


def test_verdict_line_for_every_file(tmp_path):
    write_all(tmp_path, {n: on_time(4, n) for n in DS})
    results, ag = la.run(tmp_path, SINCE)
    lines = [la.verdict_line(r) for r in results]
    assert len(lines) == 4
    assert all("offset 45 s sufficient: 100.0% first-cycle" in ln for ln in lines)


def test_wrong_header_is_file_problem(tmp_path):
    write_all(tmp_path, {})
    DS["open_interest"].csv_path(tmp_path).write_text("a,b,c\n1,2,3\n")
    with pytest.raises(la.FileProblem):
        analyse(tmp_path, "open_interest")


def test_missing_file_is_file_problem(tmp_path):
    with pytest.raises(la.FileProblem):
        analyse(tmp_path, "open_interest")


def test_main_refuses_report_inside_data_dir(tmp_path, capsys):
    write_all(tmp_path, {})
    for bad in (tmp_path / "report.md", tmp_path / "sub" / "report.md"):
        assert la.main(["--dir", str(tmp_path), "--report", str(bad)]) == 2
        assert not bad.exists()
    assert "Refusing" in capsys.readouterr().out


def test_main_writes_report_and_never_modifies_csvs(tmp_path, capsys):
    data = tmp_path / "raw"
    data.mkdir()
    write_all(data, {n: on_time(5, n) for n in DS})
    before = {p.name: p.read_bytes() for p in data.iterdir()}
    report = tmp_path / "docs" / "lag.md"
    assert la.main(["--dir", str(data), "--since-ms", str(SINCE), "--report", str(report)]) == 0
    assert {p.name: p.read_bytes() for p in data.iterdir()} == before
    text = report.read_text(encoding="utf-8")
    assert "## Verdicts" in text and "Do the files agree?" in text
    out = capsys.readouterr().out
    assert "offset 45 s sufficient: 100.0% first-cycle" in out


def test_main_missing_dir(tmp_path, capsys):
    assert la.main(["--dir", str(tmp_path / "nope"), "--report", str(tmp_path / "r.md")]) == 2


def test_default_since_is_the_restart():
    from datetime import datetime, timezone

    assert la.DEFAULT_SINCE_MS == int(datetime(2026, 11, 19, 16, 0, tzinfo=timezone.utc).timestamp() * 1000)


def test_report_lists_only_the_most_recent_late_rows_but_shows_total(tmp_path):
    n = la.MAX_LATE_LISTED + 7
    entries = [(BASE + i * PERIOD_MS, BASE + i * PERIOD_MS + 300_000) for i in range(n)]  # all second-cycle
    write_all(tmp_path, {"open_interest": entries})
    r = analyse(tmp_path, "open_interest")
    text = la.render_report([r], la.agreement([r]), tmp_path, SINCE)
    assert f"({n} in total)" in text
    assert f"Showing the {la.MAX_LATE_LISTED} most recent of {n}" in text
    assert la.utc(BASE + (n - 1) * PERIOD_MS) in text  # newest listed
    assert la.utc(BASE + 6 * PERIOD_MS) not in text  # 7 oldest dropped
    assert la.utc(BASE + 7 * PERIOD_MS) in text  # oldest still listed
