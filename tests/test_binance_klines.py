import csv
from unittest.mock import MagicMock

import pytest
import requests

from tacgate.data import binance_klines as bk

MIN = 60_000
T0 = 1_752_575_400_000
FAR_FUTURE = 10**15


def make_row(open_time):
    return [open_time, "1", "2", "0.5", "1.5", "100", open_time + MIN - 1, "150", 10, "50", "75", "0"]


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
    """Serves klines from an in-memory list, honouring startTime/endTime/limit."""

    def __init__(self, open_times):
        self.open_times = sorted(open_times)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(dict(params))
        rows = [
            make_row(t)
            for t in self.open_times
            if params["startTime"] <= t <= params["endTime"]
        ][: params["limit"]]
        return FakeResponse(200, rows)


def read_open_times(path):
    with open(path, newline="") as f:
        return [int(r["open_time"]) for r in csv.DictReader(f)]


def run(path, session, **kw):
    kw.setdefault("start_ms", T0)
    kw.setdefault("end_ms", T0 + 100 * MIN)
    kw.setdefault("clock", lambda: FAR_FUTURE)
    return bk.fetch_klines(path, session=session, sleep=lambda s: None, **kw)


def test_pagination_collects_all_pages_in_order(tmp_path):
    times = [T0 + i * MIN for i in range(25)]
    session = FakeSession(times)
    out = tmp_path / "k.csv"
    n = run(out, session, limit=10)
    assert n == 25
    assert read_open_times(out) == times
    # 3 data pages (10, 10, 5) + 1 empty terminating page
    assert [c["startTime"] for c in session.calls[:3]] == [T0, T0 + 10 * MIN, T0 + 20 * MIN]
    assert all(c["limit"] == 10 for c in session.calls)
    assert all(c["symbol"] == "TACUSDT" and c["interval"] == "1m" for c in session.calls)


def test_default_limit_is_binance_max():
    assert bk.MAX_LIMIT == 1500


def test_timestamps_kept_as_raw_ms_and_header_written(tmp_path):
    out = tmp_path / "k.csv"
    run(out, FakeSession([T0]))
    with open(out, newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == bk.COLUMNS
    assert rows[1][0] == str(T0)
    assert rows[1][6] == str(T0 + MIN - 1)


def test_resume_continues_from_last_saved_without_duplicates(tmp_path):
    times = [T0 + i * MIN for i in range(30)]
    out = tmp_path / "k.csv"
    # First run only gets the first 12 minutes
    run(out, FakeSession(times), end_ms=T0 + 11 * MIN, limit=5)
    assert read_open_times(out) == times[:12]
    # Second run resumes
    session2 = FakeSession(times)
    n = run(out, session2, end_ms=T0 + 29 * MIN, limit=5)
    assert session2.calls[0]["startTime"] == T0 + 12 * MIN
    assert n == 18
    assert read_open_times(out) == times


def test_no_duplicates_when_server_repeats_rows(tmp_path):
    times = [T0 + i * MIN for i in range(5)]
    out = tmp_path / "k.csv"
    run(out, FakeSession(times))
    # Server ignores startTime and returns everything again
    sess = MagicMock()
    sess.get.side_effect = [FakeResponse(200, [make_row(t) for t in times]), FakeResponse(200, [])]
    n = run(out, sess)
    assert n == 0
    assert read_open_times(out) == times


def test_rerun_with_nothing_new_is_noop(tmp_path):
    times = [T0 + i * MIN for i in range(5)]
    out = tmp_path / "k.csv"
    run(out, FakeSession(times))
    n = run(out, FakeSession(times))
    assert n == 0
    assert read_open_times(out) == times


def test_open_candle_is_not_saved(tmp_path):
    times = [T0 + i * MIN for i in range(3)]
    out = tmp_path / "k.csv"
    # "now" is in the middle of the third candle -> only 2 are closed
    run(out, FakeSession(times), clock=lambda: T0 + 2 * MIN + 10)
    assert read_open_times(out) == times[:2]


def test_retry_on_429_then_success():
    sleeps = []
    session = MagicMock()
    session.get.side_effect = [
        FakeResponse(429),
        FakeResponse(429, headers={"Retry-After": "7"}),
        FakeResponse(200, [make_row(T0)]),
    ]
    data = bk.get_with_retry(session, {"x": 1}, sleep=sleeps.append)
    assert data == [make_row(T0)]
    assert session.get.call_count == 3
    assert sleeps[0] == 1.0
    assert sleeps[1] == 7.0  # Retry-After wins over backoff (2.0)


def test_exponential_backoff_on_network_errors():
    sleeps = []
    session = MagicMock()
    session.get.side_effect = [
        requests.ConnectionError("boom"),
        requests.Timeout("slow"),
        FakeResponse(503),
        FakeResponse(200, []),
    ]
    assert bk.get_with_retry(session, {}, sleep=sleeps.append) == []
    assert sleeps == [1.0, 2.0, 4.0]


def test_gives_up_after_max_retries():
    session = MagicMock()
    session.get.return_value = FakeResponse(429)
    with pytest.raises(RuntimeError, match="Giving up"):
        bk.get_with_retry(session, {}, sleep=lambda s: None, max_retries=3)
    assert session.get.call_count == 4


def test_non_retryable_client_error_raises_immediately():
    session = MagicMock()
    session.get.return_value = FakeResponse(400)
    with pytest.raises(requests.HTTPError):
        bk.get_with_retry(session, {}, sleep=lambda s: None)
    assert session.get.call_count == 1


def test_progress_survives_failure_mid_download(tmp_path):
    times = [T0 + i * MIN for i in range(10)]
    out = tmp_path / "k.csv"
    good = FakeSession(times)
    calls = {"n": 0}

    class Flaky:
        def get(self, url, params=None, timeout=None):
            calls["n"] += 1
            if calls["n"] >= 3:
                return FakeResponse(429)
            return good.get(url, params, timeout)

    with pytest.raises(RuntimeError):
        bk.fetch_klines(
            out, start_ms=T0, end_ms=T0 + 9 * MIN, session=Flaky(),
            sleep=lambda s: None, clock=lambda: FAR_FUTURE, limit=4,
        )
    # rerun resumes cleanly after the partial save
    assert read_open_times(out) == times[:8]  # two full pages were saved before the failure
    run(out, good, start_ms=T0, end_ms=T0 + 9 * MIN, limit=4)
    assert read_open_times(out) == times


def test_parse_utc_ms():
    assert bk.parse_utc_ms("2025-07-15") == 1_752_537_600_000


def test_main_passes_args(tmp_path, monkeypatch):
    captured = {}

    def fake_fetch(path, start_ms=None, end_ms=None, **kw):
        captured.update(path=path, start_ms=start_ms, end_ms=end_ms)
        return 0

    monkeypatch.setattr(bk, "fetch_klines", fake_fetch)
    bk.main(["--start", "2025-08-01", "--end", "2025-08-02", "--out", str(tmp_path / "x.csv")])
    assert captured["start_ms"] == bk.parse_utc_ms("2025-08-01")
    assert captured["end_ms"] == bk.parse_utc_ms("2025-08-02")


# --- hardening: 418 ban and crash-safe resume --------------------------------

def test_418_raises_immediately_without_retry():
    sleeps = []
    session = MagicMock()
    session.get.return_value = FakeResponse(418, headers={"Retry-After": "120"})
    with pytest.raises(RuntimeError, match="banned") as exc:
        bk.get_with_retry(session, {}, sleep=sleeps.append)
    assert "Retry-After: 120" in str(exc.value)
    assert session.get.call_count == 1
    assert sleeps == []


def test_418_without_retry_after_header():
    session = MagicMock()
    session.get.return_value = FakeResponse(418)
    with pytest.raises(RuntimeError, match="banned"):
        bk.get_with_retry(session, {}, sleep=lambda s: None)
    assert session.get.call_count == 1


def test_418_not_in_retry_status():
    assert 418 not in bk.RETRY_STATUS
    assert {429, 500, 502, 503, 504} <= bk.RETRY_STATUS


def _write_good_rows(path, times):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(bk.COLUMNS)
        for t in times:
            w.writerow(make_row(t))


@pytest.mark.parametrize(
    "tail",
    [
        b"1752575700000,1,2,0.5",            # partial: no newline, too few columns
        b"1752575700000,1,2,0.5,1.5,100,175257576",  # cut mid-field
        b"1752575700000",                     # just the timestamp
        b"1752575700000,1,2,0.5\r\n",         # newline-terminated but too few columns
    ],
)
def test_partial_last_line_is_repaired_and_resume_is_exact(tmp_path, tail):
    times = [T0 + i * MIN for i in range(10)]
    out = tmp_path / "k.csv"
    _write_good_rows(out, times[:5])
    with open(out, "ab") as f:
        f.write(tail)

    # last_saved_open_time must ignore the partial row even before repair
    assert bk.last_saved_open_time(out) == times[4]

    session = FakeSession(times)
    n = run(out, session, end_ms=T0 + 9 * MIN, limit=4)
    assert session.calls[0]["startTime"] == times[5]
    assert n == 5
    assert read_open_times(out) == times  # no duplicates, nothing lost
    assert out.read_bytes().count(b"\n") == 11  # header + 10 rows, no stray fragments


def test_repair_truncates_to_end_of_last_complete_line(tmp_path):
    out = tmp_path / "k.csv"
    _write_good_rows(out, [T0, T0 + MIN])
    good = out.read_bytes()
    out.write_bytes(good + b"175257")
    assert bk.repair_csv(out) is True
    assert out.read_bytes() == good
    assert bk.repair_csv(out) is False  # already clean


def test_partial_header_only_file_is_reset(tmp_path):
    out = tmp_path / "k.csv"
    out.write_bytes(b"open_time,open,hi")
    session = FakeSession([T0, T0 + MIN])
    run(out, session)
    assert read_open_times(out) == [T0, T0 + MIN]


def test_unexpected_header_refuses_to_resume(tmp_path):
    out = tmp_path / "k.csv"
    out.write_bytes(b"a,b,c\n1,2,3\n")
    with pytest.raises(ValueError, match="header"):
        bk.repair_csv(out)


def test_last_saved_open_time_none_when_only_header(tmp_path):
    out = tmp_path / "k.csv"
    _write_good_rows(out, [])
    assert bk.last_saved_open_time(out) is None
