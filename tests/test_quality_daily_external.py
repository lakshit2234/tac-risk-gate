"""Tests for the daily external data quality checker (synthetic CSVs, no network, no real data)."""
import csv
from pathlib import Path

import pytest

from tacgate.data import binance_klines as bk
from tacgate.data import quality_daily_external as q
from tacgate.data.recorder import DATASETS

DAY = q.DAY_MS
D0 = 1_790_000_000_000 // DAY * DAY  # a UTC midnight
NOW = D0 + 30 * DAY + 5 * 3_600_000  # "today" is D0 + 30 days
N = 10
OI = next(d for d in DATASETS if d.name == "open_interest")


class Data:
    """Synthetic file contents. Tests mutate the row lists, then write() them into a directory."""

    def __init__(self, n=N):
        self.price = [0.001 + i * 1e-5 for i in range(n)]
        self.supply = [1_000_000_000.0] * n
        self.ts = [D0 + i * DAY for i in range(n)]
        self.cg = [[t, p, p * s, 3_000_000.0 + i, t + DAY + 60_000]
                   for i, (t, p, s) in enumerate(zip(self.ts, self.price, self.supply))]
        self.tvl = [[t, 5_000_000.0 + i * 1000, t + DAY + 60_000] for i, t in enumerate(self.ts)]
        # DeFiLlama price timestamps jitter by seconds around midnight
        self.dl = [[t - 18_000 if i % 2 else t + 1_000, p, 0.99, t + DAY + 60_000]
                   for i, (t, p) in enumerate(zip(self.ts, self.price))]
        self.klines = None  # built in write() from the price list unless set
        self.oi = [["TACUSDT", "1", "2", s, t, t + 300_000] for t, s in zip(self.ts, self.supply)]
        self.bn_scale = {}  # day index -> multiplier on the Binance open (to create a mismatch)

    def write(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)

        def put(name, cols, rows):
            with open(directory / name, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(cols)
                w.writerows(rows)

        put(q.CG_NAME, q.cgm.COLUMNS, self.cg)
        put(q.TVL_NAME, q.dl.TVL.columns, self.tvl)
        put(q.PRICE_NAME, q.dl.PRICE.columns, self.dl)
        put(OI.csv_path(directory).name, OI.columns, self.oi)
        kl = self.klines
        if kl is None:
            kl = []
            for i, t in enumerate(self.ts):
                o = self.price[i] * self.bn_scale.get(i, 1.0)
                kl.append([t, o, o, o, o, 1, t + 59_999, 1, 1, 1, 1, 0])
        put(q.KLINES_NAME, bk.COLUMNS, kl)


def run(tmp_path, data=None, now=NOW):
    data = data or Data()
    data.write(tmp_path)
    return q.run_checks(tmp_path, now=now)


def fails(res, text):
    return any(text in m for m in res.hard_failures)


def warns(res, text):
    return any(text in m for m in res.warnings)


# ------------------------------------------------------------ part A ---

def test_clean_pass(tmp_path):
    res = run(tmp_path)
    assert res.passed, res.hard_failures
    assert set(res.files) == {"coingecko", "defillama_tvl", "defillama_price"}
    for d in res.files.values():
        assert d["rows"] == N and d["gaps"] == [] and d["current_day_rows"] == 0 and d["lookahead_violations"] == 0
    assert res.cross["coingecko_vs_binance"]["above"][0.01] == 0
    assert res.cross["supply_vs_recorder"]["match"] == N
    assert not any("differ" in w for w in res.warnings)


def test_jitter_within_tolerance_is_not_a_gap(tmp_path):
    res = run(tmp_path)
    d = res.files["defillama_price"]
    assert d["gaps"] == [] and d["short_steps"] == [] and 0 < d["max_jitter_s"] < 60


def test_duplicate_timestamp_fails(tmp_path):
    data = Data()
    data.cg.insert(3, list(data.cg[2]))
    res = run(tmp_path, data)
    assert not res.passed and fails(res, "duplicate timestamp")


def test_unsorted_fails(tmp_path):
    data = Data()
    data.tvl[4], data.tvl[5] = data.tvl[5], data.tvl[4]
    res = run(tmp_path, data)
    assert fails(res, "not strictly increasing")


def test_nan_fails(tmp_path):
    data = Data()
    data.cg[2][2] = ""  # blank market_cap
    data.dl[1][1] = "nan"
    res = run(tmp_path, data)
    assert fails(res, "coingecko: 1 NaN/blank")
    assert fails(res, "defillama_price: 1 NaN/blank")


def test_blank_confidence_is_only_a_warning(tmp_path):
    data = Data()
    data.dl[0][2] = ""
    res = run(tmp_path, data)
    assert res.passed and warns(res, "blank value(s) in confidence")


def test_missing_column_fails_cleanly(tmp_path):
    data = Data()
    data.write(tmp_path)
    (tmp_path / q.TVL_NAME).write_text("timestamp_ms,fetched_at_ms\n1,2\n")
    res = q.run_checks(tmp_path, now=NOW)
    assert fails(res, "defillama_tvl schema")
    assert "defillama_tvl" not in res.files  # the rest still ran
    assert "coingecko" in res.files


def test_missing_file_is_a_file_problem(tmp_path):
    data = Data()
    data.write(tmp_path)
    (tmp_path / q.CG_NAME).unlink()
    with pytest.raises(q.FileProblem):
        q.run_checks(tmp_path, now=NOW)


def test_gap_is_listed_not_failed(tmp_path):
    data = Data()
    del data.cg[4:6]  # two days missing
    res = run(tmp_path, data)
    d = res.files["coingecko"]
    assert res.passed
    assert d["missing_days"] == 2 and len(d["gaps"]) == 1
    assert d["gaps"][0] == (D0 + 3 * DAY, D0 + 6 * DAY, 2)
    assert warns(res, "coingecko: 1 gap(s)")
    assert q._ts(D0 + 6 * DAY) in q.render_report(res)


def test_current_day_row_fails(tmp_path):
    data = Data()
    today_mid = (NOW // DAY) * DAY
    data.tvl.append([today_mid, 5_100_000.0, NOW])
    res = run(tmp_path, data)
    assert not res.passed and fails(res, "defillama_tvl: 1 row(s) dated on the current UTC day")


def test_lookahead_violation_fails(tmp_path):
    data = Data()
    data.dl[3][3] = data.dl[3][0] - 1  # fetched before its own timestamp
    res = run(tmp_path, data)
    assert fails(res, "defillama_price: 1 look-ahead violation")
    assert res.files["defillama_price"]["lookahead_violations"] == 1


def test_fetched_before_known_at_is_info_not_failure(tmp_path):
    data = Data()
    data.cg[-1][4] = data.cg[-1][0] + 3_600_000  # fetched 1 h after the timestamp, before timestamp + 24 h
    res = run(tmp_path, data)
    assert res.passed and res.files["coingecko"]["fetched_before_known_at"] == 1
    assert "known at timestamp + 24 h" in q.render_report(res)


def test_non_positive_values_fail_and_zero_tvl_is_allowed(tmp_path):
    data = Data()
    data.cg[1][1] = 0.0
    data.tvl[0][1] = 0.0  # allowed: tvl >= 0
    data.tvl[1][1] = -5.0  # not allowed
    res = run(tmp_path, data)
    assert fails(res, "coingecko: 1 value(s) in price that are not positive")
    assert fails(res, "defillama_tvl: 1 negative value(s) in tvl")


def test_tvl_jump_listed(tmp_path):
    data = Data()
    data.tvl[5][1] = data.tvl[4][1] * 0.3  # -70%
    res = run(tmp_path, data)
    jumps = res.files["defillama_tvl"]["tvl_jumps"]
    assert res.passed and len(jumps) >= 1 and jumps[0][0] == D0 + 5 * DAY
    assert jumps[0][3] == pytest.approx(-0.7, abs=0.01)
    assert warns(res, "TVL change above 50%")


def test_partial_last_line_ignored(tmp_path):
    data = Data()
    data.write(tmp_path)
    with open(tmp_path / q.CG_NAME, "a", newline="") as f:
        f.write(f"{D0 + 20 * DAY},0.00")  # no newline: a fetcher mid-write
    res = q.run_checks(tmp_path, now=NOW)
    assert res.passed and res.files["coingecko"]["rows"] == N
    assert warns(res, "ignored a partial last line")


# ------------------------------------------------------------ part B ---

def test_price_mismatch_above_2_percent_flagged_with_month_breakdown(tmp_path):
    data = Data()
    data.bn_scale = {2: 1 / 1.5, 3: 1 / 1.03}  # external prices are 50% and 3% above Binance on days 2 and 3
    res = run(tmp_path, data)
    assert res.passed  # mismatches are warnings only
    c = res.cross["coingecko_vs_binance"]
    assert c["n"] == N and c["above"] == {0.01: 2, 0.02: 2, 0.05: 1}
    assert c["top"][0][0] == D0 + 2 * DAY and c["top"][0][3] == pytest.approx(0.5)
    assert sum(n2 for n2, _ in c["by_month_over2"].values()) == 2
    assert warns(res, "coingecko price differs from the Binance 1m open by more than 2% on 2 of 10")
    assert warns(res, "defillama_price price differs")
    # the two external series agree with each other
    assert res.cross["coingecko_vs_defillama"]["above"][0.01] == 0


def test_defillama_jitter_uses_nearest_minute_and_midnight(tmp_path):
    res = run(tmp_path)
    assert res.cross["defillama_price_vs_binance"]["above"][0.01] == 0
    assert res.cross["defillama_price_vs_binance"]["unmatched"] == 0
    assert res.cross["coingecko_vs_defillama"]["n"] == N


def test_unmatched_binance_days_are_counted(tmp_path):
    data = Data()
    data.klines = [[t, 0.001, 0.001, 0.001, 0.001, 1, t + 59_999, 1, 1, 1, 1, 0] for t in data.ts[:5]]
    res = run(tmp_path, data)
    assert res.cross["coingecko_vs_binance"]["n"] == 5 and res.cross["coingecko_vs_binance"]["unmatched"] == 5


def test_supply_step_listed_with_cause_unverified(tmp_path):
    data = Data()
    for i in range(6, N):
        data.supply[i] = 1_050_000_000.0  # +5% from day 6
    data.cg = [[t, p, p * s, 3_000_000.0, t + DAY + 60_000] for t, p, s in zip(data.ts, data.price, data.supply)]
    data.oi = [["TACUSDT", "1", "2", s, t, t + 300_000] for t, s in zip(data.ts, data.supply)]
    res = run(tmp_path, data)
    s = res.cross["supply"]
    assert s["first"][1] == pytest.approx(1e9) and s["last"][1] == pytest.approx(1.05e9)
    assert len(s["steps"]) == 1
    t, tokens, pct = s["steps"][0]
    assert t == D0 + 6 * DAY and tokens == pytest.approx(5e7) and pct == pytest.approx(0.05)
    assert "cause unverified" in q.render_report(res)
    assert "cause unverified" in q.console_summary(res, Path("r.md"))


def test_supply_vs_recorder_mismatch_listed(tmp_path):
    data = Data()
    data.oi[4][3] = 1_100_000_000.0  # recorder says +10% on day 4
    data.oi[5][3] = 1_000_500_000.0  # +0.05%: within 0.1%
    res = run(tmp_path, data)
    r = res.cross["supply_vs_recorder"]
    assert r["overlap"] == N and r["match"] == N - 1
    assert len(r["mismatches"]) == 1 and r["mismatches"][0][0] == D0 + 4 * DAY
    assert r["mismatches"][0][3] == pytest.approx(0.10)
    assert res.passed and warns(res, "1 of 10 overlapping day(s) differ by more than 0.1%")


def test_supply_uses_only_midnight_recorder_rows(tmp_path):
    data = Data()
    data.oi += [["TACUSDT", "1", "2", 9_999_999_999.0, D0 + 3 * DAY + 300_000, 0]]  # a 00:05 row: ignored
    res = run(tmp_path, data)
    assert res.cross["supply_vs_recorder"]["match"] == N


# ----------------------------------------------------------- CLI / safety ---

def test_report_written_and_csvs_never_modified(tmp_path, capsys):
    raw = tmp_path / "raw"
    Data().write(raw)
    before = {p.name: p.read_bytes() for p in raw.iterdir()}
    report = tmp_path / "docs" / "r.md"
    code = q.main(["--dir", str(raw), "--report", str(report)])  # real clock: well after D0 + 10 days
    assert code == 0
    assert {p.name: p.read_bytes() for p in raw.iterdir()} == before
    text = report.read_text(encoding="utf-8")
    assert "Part A" in text and "Part B" in text and "timestamp + 24 h" in text
    assert "Gate 1 daily external quality: PASS" in capsys.readouterr().out


def test_main_exit_1_on_hard_failure(tmp_path):
    raw = tmp_path / "raw"
    data = Data()
    data.cg.insert(3, list(data.cg[2]))
    data.write(raw)
    assert q.main(["--dir", str(raw), "--report", str(tmp_path / "r.md")]) == 1


def test_main_exit_2_on_missing_file_or_dir(tmp_path):
    raw = tmp_path / "raw"
    Data().write(raw)
    (raw / q.PRICE_NAME).unlink()
    assert q.main(["--dir", str(raw), "--report", str(tmp_path / "r.md")]) == 2
    assert q.main(["--dir", str(tmp_path / "nope"), "--report", str(tmp_path / "r.md")]) == 2


def test_refuses_report_path_inside_data_dir(tmp_path, capsys):
    raw = tmp_path / "raw"
    Data().write(raw)
    for bad in (raw / "report.md", raw / "sub" / "report.md"):
        assert q.main(["--dir", str(raw), "--report", str(bad)]) == 2
        assert not bad.exists()
    assert "Refusing" in capsys.readouterr().out


def test_file_names_come_from_the_fetchers():
    assert q.CG_NAME == "coingecko_TAC_market_chart_daily.csv"
    assert q.TVL_NAME == "defillama_TAC_chain_tvl_daily.csv"
    assert q.PRICE_NAME == "defillama_TAC_price_daily.csv"
    assert q.KLINES_NAME == "binance_TACUSDT_1m.csv"
