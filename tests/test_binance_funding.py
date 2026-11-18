import csv
from unittest.mock import MagicMock

import pytest
import requests

from tacgate.data import binance_funding as bf
from tacgate.data import binance_klines as bk

H4 = 4 * 3_600_000
T0 = 1_752_580_800_000
FAR_FUTURE = 10**15


def make_rec(t, rate="0.00005000"):
    return {
        "symbol": "TACUSDT",
        "fundingTime": t,
        "fundingRate": rate,
        "markPrice": "0.02100000",
        "rateType": "Regular",
    }


class FakeResponse:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self._payload = payload if payload is not None else []
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """Serves funding records ascending from startTime (inclusive), like the API."""

    def __init__(self, times):
        self.times = sorted(times)
        self.calls = []
        self.urls = []

    def get(self, url, params=None, timeout=None):
        self.urls.append(url)
        self.calls.append(dict(params))
        recs = [
            make_rec(t)
            for t in self.times
            if params["startTime"] <= t <= params["endTime"]
        ][: params["limit"]]
        return FakeResponse(200, recs)


def read_times(path):
    with open(path, newline="") as f:
        return [int(r["fundingTime"]) for r in csv.DictReader(f)]


def run(path, session, **kw):
    kw.setdefault("start_ms", T0)
    kw.setdefault("end_ms", T0 + 10_000 * H4)
    kw.setdefault("clock", lambda: FAR_FUTURE)
    return bf.fetch_funding(path, session=session, sleep=lambda s: None, **kw)


def test_pagination_in_order_and_uses_funding_endpoint(tmp_path):
    times = [T0 + i * H4 for i in range(25)]
    session = FakeSession(times)
    out = tmp_path / "f.csv"
    n = run(out, session, limit=10)
    assert n == 25
    assert read_times(out) == times
    # cursor advances from the last fundingTime (+1 ms): 10, 20 rows, then the rest
    assert [c["startTime"] for c in session.calls[:3]] == [T0, times[9] + 1, times[19] + 1]
    assert all(c["symbol"] == "TACUSDT" and c["limit"] == 10 for c in session.calls)
    assert all("interval" not in c for c in session.calls)
    assert all(u.endswith("/fapi/v1/fundingRate") for u in session.urls)


def test_default_limit_is_documented_max():
    assert bf.MAX_LIMIT == 1000


def test_exact_api_fields_and_raw_ms_saved(tmp_path):
    out = tmp_path / "f.csv"
    run(out, FakeSession([T0 + 5]))  # ms jitter, like the real 1752609600005
    with open(out, newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["symbol", "fundingTime", "fundingRate", "markPrice", "rateType"]
    assert rows[1] == ["TACUSDT", str(T0 + 5), "0.00005000", "0.02100000", "Regular"]


def test_resume_continues_without_duplicates(tmp_path):
    times = [T0 + i * H4 for i in range(20)]
    out = tmp_path / "f.csv"
    run(out, FakeSession(times), end_ms=times[7], limit=3)
    assert read_times(out) == times[:8]
    s2 = FakeSession(times)
    n = run(out, s2, end_ms=times[-1], limit=3)
    assert s2.calls[0]["startTime"] == times[7] + 1
    assert n == 12
    assert read_times(out) == times


def test_no_duplicates_when_server_repeats_rows(tmp_path):
    times = [T0 + i * H4 for i in range(5)]
    out = tmp_path / "f.csv"
    run(out, FakeSession(times))
    sess = MagicMock()
    sess.get.side_effect = [FakeResponse(200, [make_rec(t) for t in times]), FakeResponse(200, [])]
    assert run(out, sess) == 0
    assert read_times(out) == times


def test_rerun_with_nothing_new_is_noop(tmp_path):
    times = [T0 + i * H4 for i in range(5)]
    out = tmp_path / "f.csv"
    run(out, FakeSession(times))
    assert run(out, FakeSession(times)) == 0
    assert read_times(out) == times


def test_retry_on_429_then_success():
    sleeps = []
    session = MagicMock()
    session.get.side_effect = [
        FakeResponse(429),
        FakeResponse(429, headers={"Retry-After": "9"}),
        FakeResponse(200, [make_rec(T0)]),
    ]
    data = bk.get_with_retry(session, {"x": 1}, sleep=sleeps.append, path=bf.FUNDING_PATH)
    assert data == [make_rec(T0)]
    assert sleeps == [1.0, 9.0]
    assert session.get.call_args[0][0].endswith("/fapi/v1/fundingRate")


def test_429_retry_inside_fetch(tmp_path):
    out = tmp_path / "f.csv"
    good = FakeSession([T0, T0 + H4])
    calls = {"n": 0}

    class Flaky:
        def get(self, url, params=None, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return FakeResponse(429)
            return good.get(url, params, timeout)

    bf.fetch_funding(out, start_ms=T0, end_ms=T0 + 5 * H4, session=Flaky(),
                     sleep=lambda s: None, clock=lambda: FAR_FUTURE)
    assert read_times(out) == [T0, T0 + H4]


def test_418_raises_immediately_without_retry(tmp_path):
    sleeps = []
    session = MagicMock()
    session.get.return_value = FakeResponse(418, headers={"Retry-After": "300"})
    with pytest.raises(RuntimeError, match="banned") as exc:
        bf.fetch_funding(tmp_path / "f.csv", start_ms=T0, end_ms=T0 + H4, session=session,
                         sleep=sleeps.append, clock=lambda: FAR_FUTURE)
    assert "Retry-After: 300" in str(exc.value)
    assert session.get.call_count == 1
    assert sleeps == []


def _write_rows(path, times):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(bf.FUNDING_COLUMNS)
        for t in times:
            w.writerow([r for r in make_rec(t).values()])


@pytest.mark.parametrize(
    "tail",
    [
        b"TACUSDT,1752700000000,0.0000",             # cut mid-field, no newline
        b"TACUSDT",                                   # just the symbol
        b"TACUSDT,1752700000000,0.00005000\r\n",      # newline-terminated, too few columns
    ],
)
def test_partial_tail_repaired_then_resume_exact(tmp_path, tail):
    times = [T0 + i * H4 for i in range(10)]
    out = tmp_path / "f.csv"
    _write_rows(out, times[:4])
    with open(out, "ab") as f:
        f.write(tail)
    assert bk.last_saved_open_time(out, bf.FUNDING_COLUMNS, bf.TIME_INDEX) == times[3]
    s = FakeSession(times)
    n = run(out, s, end_ms=times[-1], limit=4)
    assert s.calls[0]["startTime"] == times[3] + 1
    assert n == 6
    assert read_times(out) == times
    assert out.read_bytes().count(b"\n") == 11  # header + 10 rows, no fragments


def test_klines_header_in_funding_file_refused(tmp_path):
    out = tmp_path / "f.csv"
    out.write_bytes((",".join(bk.COLUMNS) + "\n1,2,3,4,5,6,7,8,9,10,11,12\n").encode())
    with pytest.raises(ValueError, match="header"):
        bf.fetch_funding(out, start_ms=T0, end_ms=T0 + H4, session=FakeSession([]),
                         sleep=lambda s: None, clock=lambda: FAR_FUTURE)


def test_uneven_funding_interval_handled_without_error(tmp_path):
    # 8h, then switches to 4h, then 1h, with ms jitter and a short page mid-way
    times = [T0, T0 + 8 * 3_600_000 + 5, T0 + 16 * 3_600_000 + 5]
    t = times[-1]
    for step_h in (4, 4, 4, 1, 1, 1, 1):
        t += step_h * 3_600_000 + 11
        times.append(t)
    out = tmp_path / "f.csv"
    n = run(out, FakeSession(times), limit=4)  # pages of 4,4,2: short last page, no assumptions
    assert n == len(times)
    assert read_times(out) == times


def test_short_page_does_not_stop_pagination(tmp_path):
    times = [T0 + i * H4 for i in range(6)]
    out = tmp_path / "f.csv"
    sess = MagicMock()
    sess.get.side_effect = [
        FakeResponse(200, [make_rec(t) for t in times[:2]]),  # short page, more data exists
        FakeResponse(200, [make_rec(t) for t in times[2:]]),
        FakeResponse(200, []),
    ]
    assert run(out, sess, limit=1000) == 6
    assert read_times(out) == times


def test_unexpected_fields_refused(tmp_path):
    sess = MagicMock()
    sess.get.return_value = FakeResponse(200, [{**make_rec(T0), "newField": "x"}])
    with pytest.raises(ValueError, match="Unexpected funding fields"):
        run(tmp_path / "f.csv", sess)


def test_main_passes_args(tmp_path, monkeypatch):
    captured = {}

    def fake_fetch(path, start_ms=None, end_ms=None, **kw):
        captured.update(path=path, start_ms=start_ms, end_ms=end_ms)
        return 0

    monkeypatch.setattr(bf, "fetch_funding", fake_fetch)
    bf.main(["--start", "2025-08-01", "--end", "2025-08-02", "--out", str(tmp_path / "x.csv")])
    assert captured["start_ms"] == bk.parse_utc_ms("2025-08-01")
    assert captured["end_ms"] == bk.parse_utc_ms("2025-08-02")
