"""Tests for the Aug 2026 divergence check (tiny synthetic data, mocked HTTP, no network, no real data)."""
import csv
from pathlib import Path

import pytest
import requests

from tacgate.data import binance_klines as bk
from tacgate.data import bybit_klines as by
from tacgate.data import divergence_check as dv

DAY = dv.DAY_MS
HOUR = dv.HOUR_MS
START = dv.to_ms(dv.WINDOW_START)  # 2026-08-20 00:00 UTC
END = dv.to_ms(dv.WINDOW_END)  # 2026-08-27 00:00 UTC (exclusive)
D = lambda n: START + n * DAY  # day n of the window: 0 = 08-20, 3 = 08-23


def write_csv(path, columns, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(columns)
        w.writerows(rows)


def perp_rows(price_at, ncols=6, dip=None):
    """1m rows for the whole window. price_at(minute_ms) -> price. dip = (minute_ms, price) sets one low."""
    rows = []
    for t in range(START, END, 60_000):
        p = price_at(t)
        low = dip[1] if dip and t == dip[0] else p
        rows.append([t, p, p, low, p, 100] + ([p] if ncols == 7 else []))
    return rows


def spot_rows(price_at, open_at=None):
    rows = []
    for t in range(START, END, HOUR):
        c = price_at(t)
        o = open_at(t) if open_at else c
        rows.append([t, o, max(o, c), min(o, c), c, 10, t + HOUR - 1, 1, 1, 1, 1, 0])
    return rows


def make_dir(tmp_path, price=lambda t: 0.002, agg=None, spot=None, dip=None, funding=None):
    """agg: {day index: price} applied to both DeFiLlama and CoinGecko at that day's midnight."""
    d = tmp_path / "raw"
    d.mkdir()
    write_csv(d / bk.DEFAULT_OUT.name, bk.COLUMNS,
              [[t, o, h, lo, c, v, t + 59_999, 1, 1, 1, 1, 0] for t, o, h, lo, c, v in perp_rows(price, dip=dip)])
    write_csv(d / by.DEFAULT_OUT.name, by.COLUMNS, [r + [1.0] for r in perp_rows(price, dip=dip)])
    agg = agg or {}
    days = list(range(7))
    cg_rows = [[D(i), agg.get(i, price(D(i))), 8e6, 3e6, D(i) + DAY + 1000] for i in days]
    dl_rows = [[D(i) + (-17_000 if i % 2 else 1_000), agg.get(i, price(D(i))), 0.99, D(i) + DAY + 1000] for i in days]
    write_csv(d / dv.cgm.DEFAULT_OUT.name, dv.cgm.COLUMNS, cg_rows)
    write_csv(d / dv.dl.PRICE.default_out.name, dv.dl.PRICE.columns, dl_rows)
    write_csv(d / dv.bf.DEFAULT_OUT.name, dv.bf.FUNDING_COLUMNS,
              funding or [["TACUSDT", D(1) + 8 * HOUR, "0.00005", "0.002", "Regular"],
                          ["TACUSDT", D(3), "-0.001", "0.0016", "Regular"]])
    if spot is not None:
        write_csv(d / dv.SPOT_OUT_NAME, bk.COLUMNS, spot)
    return d


# ------------------------------------------------------------ analysis ---

def test_perp_day_table_ohlc_volume_and_bps(tmp_path):
    d = make_dir(tmp_path, price=lambda t: 0.002 if t < D(1) else 0.003)
    a = dv.analyse(d)
    row0 = a.days[a.days.day == D(0)].iloc[0]
    assert row0.bn_open == 0.002 and row0.bn_close == 0.002 and row0.bn_minutes == 1440
    assert row0.bn_volume == 1440 * 100
    row1 = a.days[a.days.day == D(1)].iloc[0]
    assert row1.bn_open == 0.003
    assert len(a.days) == 7
    assert row0.bps_min == 0 and row0.bps_max == 0  # identical prices on both exchanges


def test_bps_difference_min_and_max_per_day(tmp_path):
    d = make_dir(tmp_path)
    # make Bybit 10 bps above Binance for one minute and 20 bps below for another on day 2
    rows = []
    with open(d / by.DEFAULT_OUT.name, newline="") as f:
        rows = list(csv.reader(f))
    hdr, body = rows[0], rows[1:]
    for r in body:
        t = int(r[0])
        if t == D(2) + 60_000:
            r[4] = str(0.002 / 1.001)  # Binance 0.002 is +10 bps vs Bybit
        if t == D(2) + 120_000:
            r[4] = str(0.002 / 0.998)  # Binance is -20 bps vs Bybit
    write_csv(d / by.DEFAULT_OUT.name, hdr, body)
    a = dv.analyse(d)
    r2 = a.days[a.days.day == D(2)].iloc[0]
    assert r2.bps_max == pytest.approx(10, abs=0.1) and r2.bps_min == pytest.approx(-20, abs=0.1)


def test_daily_external_uses_nearest_midnight():
    import pandas as pd
    df = pd.DataFrame({"timestamp_ms": [D(1) - 18_000, D(2) + 1_000, D(30)], "price": [1.0, 2.0, 3.0]})
    assert dv.daily_external(df, "price", START, END) == {D(1): 1.0, D(2): 2.0}


def test_funding_rows_in_window(tmp_path):
    a = dv.analyse(make_dir(tmp_path))
    assert list(a.funding.fundingRate) == [0.00005, -0.001] and list(a.funding.markPrice) == [0.002, 0.0016]


def test_missing_file_is_a_file_problem(tmp_path):
    d = make_dir(tmp_path)
    (d / by.DEFAULT_OUT.name).unlink()
    with pytest.raises(dv.FileProblem):
        dv.analyse(d)


def test_partial_last_line_ignored(tmp_path):
    d = make_dir(tmp_path)
    with open(d / dv.bf.DEFAULT_OUT.name, "a") as f:
        f.write(f"TACUSDT,{D(4)},0.0")  # no newline
    assert len(dv.analyse(d).funding) == 2


def test_spot_vs_perp_percent_and_largest_gap(tmp_path):
    bad_hour = D(2) + 5 * HOUR
    spot = spot_rows(lambda t: 0.0016 if t == bad_hour else 0.002)
    a = dv.analyse(make_dir(tmp_path, spot=spot))
    h = a.hourly
    assert len(h) == 168
    worst = h.loc[h.pct.abs().idxmax()]
    assert worst.open_time == bad_hour and worst.pct == pytest.approx(-20.0)
    assert (h.pct.drop(h.pct.abs().idxmax()).abs() < 1e-9).all()


# -------------------------------------------------------------- verdicts ---

def test_verdict_spot_crashed_perp_held(tmp_path):
    crash_hour = D(2) + 20 * HOUR

    def spot_close(t):
        return 0.001 if t == crash_hour else 0.002

    spot = spot_rows(spot_close, open_at=lambda t: 0.00105 if t == D(3) else spot_close(t))
    a = dv.analyse(make_dir(tmp_path, agg={3: 0.00102}, spot=spot))
    assert a.verdict == dv.VERDICT_SPOT
    assert "closer to spot" in a.verdict_reason


def test_verdict_aggregators_wrong_spot_and_perp_agree(tmp_path):
    spot = spot_rows(lambda t: 0.002 * 1.005)  # +0.5% vs perp everywhere
    a = dv.analyse(make_dir(tmp_path, agg={3: 0.0012}, spot=spot))
    assert a.verdict == dv.VERDICT_AGG


def test_verdict_cannot_tell_without_spot_and_mentions_perp_low(tmp_path):
    dip = (D(2) + 20 * HOUR + 20 * 60_000, 0.00104)
    a = dv.analyse(make_dir(tmp_path, agg={3: 0.00102}, dip=dip))
    assert a.verdict.startswith(dv.VERDICT_UNKNOWN_PREFIX) and "no spot data" in a.verdict
    assert a.lows["Binance perp"] == (0.00104, dip[0])
    assert "did not hold" in a.verdict_reason and "within 2% of that perp low" in a.verdict_reason
    assert "unverified" in a.verdict_reason


def test_verdict_cannot_tell_when_spot_is_between_thresholds(tmp_path):
    spot = spot_rows(lambda t: 0.002 * 0.97)  # 3% below perp: not "agree", not "far"
    a = dv.analyse(make_dir(tmp_path, agg={3: 0.0012}, spot=spot))
    assert a.verdict.startswith(dv.VERDICT_UNKNOWN_PREFIX)


def test_verdict_cannot_tell_when_no_aggregator_disagrees(tmp_path):
    spot = spot_rows(lambda t: 0.001 if t == D(2) + HOUR else 0.002)
    a = dv.analyse(make_dir(tmp_path, spot=spot))
    assert a.verdict.startswith(dv.VERDICT_UNKNOWN_PREFIX) and "no aggregator price" in a.verdict


def test_verdict_is_always_one_of_the_three_forms(tmp_path):
    a = dv.analyse(make_dir(tmp_path))
    assert a.verdict in (dv.VERDICT_SPOT, dv.VERDICT_AGG) or a.verdict.startswith(dv.VERDICT_UNKNOWN_PREFIX + ",")


# ------------------------------------------------------------ spot fetch ---

class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code, self._payload, self.headers = status, payload, {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error")


class FakeSession:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params)))
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def spot_page(n=168):
    return [[START + i * HOUR, "0.002", "0.002", "0.002", "0.002", "10", START + i * HOUR + HOUR - 1, "1", 1, "1", "1", "0"]
            for i in range(n)]


def test_fetch_spot_saves_a_new_file_with_one_request(tmp_path):
    s = FakeSession(FakeResponse(200, spot_page()))
    out = tmp_path / "spot.csv"
    res = dv.fetch_spot(out, START, END, session=s, sleep=lambda x: None)
    assert res.ok and res.rows == 168 and len(s.calls) == 1
    url, params = s.calls[0]
    assert params["symbol"] == "TACUSDT" and params["interval"] == "1h" and params["limit"] == 168
    assert params["startTime"] == START and params["endTime"] == END - 1
    with open(out, newline="") as f:
        got = list(csv.reader(f))
    assert got[0] == bk.COLUMNS and len(got) == 169


def test_fetch_spot_uses_spot_endpoint_not_futures(tmp_path):
    seen = []

    class S(FakeSession):
        def get(self, url, params=None, timeout=None):
            seen.append(url)
            return FakeResponse(200, spot_page())

    dv.fetch_spot(tmp_path / "s.csv", START, END, session=S(), sleep=lambda x: None)
    assert seen == ["https://api.binance.com/api/v3/klines"]


def test_fetch_spot_refused_says_so_writes_no_csv_and_does_not_retry(tmp_path):
    s = FakeSession(FakeResponse(400))
    out = tmp_path / "spot.csv"
    res = dv.fetch_spot(out, START, END, session=s, sleep=lambda x: None)
    assert not res.ok and "refused" in res.message and "400" in res.message
    assert len(s.calls) == 1  # a 400 is never retried
    assert not out.exists()
    assert "400" in dv.spot_error_path(out).read_text(encoding="utf-8")


def test_fetch_spot_server_errors_stop_after_the_bounded_retries(tmp_path):
    s = FakeSession(FakeResponse(503))
    res = dv.fetch_spot(tmp_path / "s.csv", START, END, session=s, sleep=lambda x: None)
    assert not res.ok and len(s.calls) == dv.SPOT_MAX_RETRIES + 1


def test_fetch_spot_never_overwrites_an_existing_file(tmp_path):
    out = tmp_path / "spot.csv"
    out.write_text("keep me\n")
    s = FakeSession(FakeResponse(200, spot_page()))
    res = dv.fetch_spot(out, START, END, session=s, sleep=lambda x: None)
    assert not res.ok and s.calls == [] and out.read_text() == "keep me\n"


def test_fetch_spot_rejects_unexpected_layout(tmp_path):
    res = dv.fetch_spot(tmp_path / "s.csv", START, END, session=FakeSession(FakeResponse(200, [[1, 2, 3]])), sleep=lambda x: None)
    assert not res.ok and "layout" in res.message and not (tmp_path / "s.csv").exists()


def test_refusal_is_reported_in_the_report_on_rerun(tmp_path):
    d = make_dir(tmp_path)
    dv.fetch_spot(d / dv.SPOT_OUT_NAME, START, END, session=FakeSession(FakeResponse(400)), sleep=lambda x: None)
    a = dv.analyse(d)
    text = dv.render_report(a)
    assert "Spot request failed or was refused" in text and "unknown symbol" in text and "unverified" in text


# ----------------------------------------------------------------- CLI ---

def test_main_writes_report_and_never_modifies_inputs(tmp_path, capsys):
    d = make_dir(tmp_path, agg={3: 0.00102})
    before = {p.name: p.read_bytes() for p in d.iterdir()}
    report = tmp_path / "docs" / "r.md"
    assert dv.main(["--dir", str(d), "--report", str(report)]) == 0
    assert {p.name: p.read_bytes() for p in d.iterdir()} == before
    text = report.read_text(encoding="utf-8")
    assert "## Verdict" in text and "unverified" in text and "Binance minus Bybit" in text and "Funding" in text
    assert "verdict: cannot tell" in capsys.readouterr().out


def test_main_refuses_report_inside_data_dir(tmp_path, capsys):
    d = make_dir(tmp_path)
    for bad in (d / "r.md", d / "sub" / "r.md"):
        assert dv.main(["--dir", str(d), "--report", str(bad)]) == 2
        assert not bad.exists()
    assert "Refusing" in capsys.readouterr().out


def test_main_missing_dir_or_file(tmp_path):
    assert dv.main(["--dir", str(tmp_path / "nope"), "--report", str(tmp_path / "r.md")]) == 2
    d = make_dir(tmp_path)
    (d / dv.cgm.DEFAULT_OUT.name).unlink()
    assert dv.main(["--dir", str(d), "--report", str(tmp_path / "r.md")]) == 2


def test_report_contains_tables_and_largest_gap_when_spot_exists(tmp_path):
    spot = spot_rows(lambda t: 0.001 if t == D(2) + 20 * HOUR else 0.002)
    a = dv.analyse(make_dir(tmp_path, agg={3: 0.00102}, spot=spot))
    text = dv.render_report(a)
    assert "Spot vs perp, per hour" in text and "Largest absolute gap: 50.00%" in text
    assert "2026-08-22 20:00" in text
