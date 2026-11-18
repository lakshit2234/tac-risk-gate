import csv
from unittest.mock import MagicMock

import pytest
import requests

from tacgate.data import binance_klines as bk
from tacgate.data import bybit_klines as bb

MIN = 60_000
T0 = 1_752_577_200_000
FAR_FUTURE = 10**15


def kl(t):
    """One Bybit kline entry: all strings, [start, o, h, l, c, volume, turnover]."""
    return [str(t), "1.0", "1.2", "0.9", "1.1", "100", "110.5"]


def envelope(rows, code=0, msg="OK", symbol="TACUSDT"):
    return {
        "retCode": code,
        "retMsg": msg,
        "result": {"symbol": symbol, "category": "linear", "list": rows},
        "retExtInfo": {},
        "time": 0,
    }


class FakeResponse:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """Serves klines like Bybit: window [start, end], NEWEST FIRST, capped at limit."""

    def __init__(self, open_times, launch=None):
        self.times = sorted(open_times)
        self.launch = launch
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params)))
        if url.endswith("/v5/market/instruments-info"):
            return FakeResponse(200, envelope([{"symbol": "TACUSDT", "launchTime": str(self.launch)}]))
        sel = [t for t in self.times if params["start"] <= t <= params["end"]]
        sel = sorted(sel, reverse=True)[: params["limit"]]
        return FakeResponse(200, envelope([kl(t) for t in sel]))

    def kline_calls(self):
        return [p for u, p in self.calls if u.endswith("/v5/market/kline")]


def read_times(path):
    with open(path, newline="") as f:
        return [int(r["open_time"]) for r in csv.DictReader(f)]


def run(path, session, **kw):
    kw.setdefault("start_ms", T0)
    kw.setdefault("end_ms", T0 + 5_000 * MIN)
    kw.setdefault("clock", lambda: FAR_FUTURE)
    return bb.fetch_klines(path, session=session, sleep=lambda s: None, **kw)


def test_newest_first_is_sorted_ascending_in_file(tmp_path):
    times = [T0 + i * MIN for i in range(8)]
    out = tmp_path / "b.csv"
    assert run(out, FakeSession(times)) == 8
    assert read_times(out) == times  # ascending although the API returns newest first


def test_parse_sorts_and_dedupes():
    rows = bb.parse_kline_response(envelope([kl(T0 + 2 * MIN), kl(T0), kl(T0 + MIN), kl(T0 + MIN)]))
    assert [int(r[0]) for r in rows] == [T0, T0 + MIN, T0 + 2 * MIN]


def test_dedupe_across_overlapping_pages(tmp_path):
    times = [T0 + i * MIN for i in range(6)]
    out = tmp_path / "b.csv"
    sess = MagicMock()
    sess.get.side_effect = [
        FakeResponse(200, envelope([kl(t) for t in reversed(times)])),
        FakeResponse(200, envelope([kl(t) for t in reversed(times[3:])])),  # repeats old rows
    ]
    run(out, sess, end_ms=T0 + 8 * MIN, limit=5)
    assert read_times(out) == times


def test_raw_fields_and_header(tmp_path):
    out = tmp_path / "b.csv"
    run(out, FakeSession([T0]))
    with open(out, newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["open_time", "open", "high", "low", "close", "volume", "turnover"]
    assert rows[1] == [str(T0), "1.0", "1.2", "0.9", "1.1", "100", "110.5"]


def test_windows_walk_forward_and_empty_window_does_not_stop(tmp_path):
    # data in window 1 and window 3; window 2 (a hole) is empty
    times = [T0, T0 + MIN] + [T0 + 10 * MIN, T0 + 11 * MIN]
    sess = FakeSession(times)
    out = tmp_path / "b.csv"
    run(out, sess, limit=5, end_ms=T0 + 14 * MIN)
    assert [c["start"] for c in sess.kline_calls()] == [T0, T0 + 5 * MIN, T0 + 10 * MIN]
    assert all(c["limit"] == 5 and c["category"] == "linear" and c["interval"] == "1" for c in sess.kline_calls())
    assert read_times(out) == times


def test_default_limit_is_1000():
    assert bb.MAX_LIMIT == 1000


def test_open_candle_is_not_saved(tmp_path):
    times = [T0 + i * MIN for i in range(3)]
    out = tmp_path / "b.csv"
    run(out, FakeSession(times), clock=lambda: T0 + 2 * MIN + 10)  # 3rd candle still open
    assert read_times(out) == times[:2]


def test_candle_closing_exactly_now_is_saved(tmp_path):
    out = tmp_path / "b.csv"
    run(out, FakeSession([T0]), clock=lambda: T0 + MIN)
    assert read_times(out) == [T0]


def test_retcode_error_fails_loudly_with_retmsg(tmp_path):
    sess = MagicMock()
    sess.get.return_value = FakeResponse(200, envelope([], code=10001, msg="Illegal category"))
    with pytest.raises(RuntimeError, match="10001.*Illegal category"):
        run(tmp_path / "b.csv", sess)


@pytest.mark.parametrize(
    "payload",
    [
        {"foo": 1},
        {"retCode": 0, "result": {}},
        {"retCode": 0, "result": {"symbol": "TACUSDT", "category": "linear", "list": [["1", "2"]]}},
        {"retCode": 0, "result": {"symbol": "TACUSDT", "category": "linear", "list": [[1, 2, 3, 4, 5, 6, 7]]}},
        envelope([], symbol="BTCUSDT"),
    ],
)
def test_changed_response_shape_fails_loudly(tmp_path, payload):
    sess = MagicMock()
    sess.get.return_value = FakeResponse(200, payload)
    with pytest.raises(ValueError, match="shape changed"):
        run(tmp_path / "b.csv", sess)


def test_403_raises_immediately_without_retry(tmp_path):
    sleeps = []
    sess = MagicMock()
    sess.get.return_value = FakeResponse(403)
    with pytest.raises(RuntimeError, match="403") as exc:
        bb.fetch_klines(tmp_path / "b.csv", start_ms=T0, end_ms=T0 + MIN, session=sess,
                        sleep=sleeps.append, clock=lambda: FAR_FUTURE)
    assert "Do not retry" in str(exc.value) and "10 minutes" in str(exc.value)
    assert sess.get.call_count == 1 and sleeps == []


def test_429_retries_then_succeeds_honoring_retry_after():
    sleeps = []
    sess = MagicMock()
    sess.get.side_effect = [
        FakeResponse(429),
        FakeResponse(429, headers={"Retry-After": "6"}),
        FakeResponse(200, envelope([kl(T0)])),
    ]
    rows = bb.fetch_window(sess, T0, T0 + MIN, sleep=sleeps.append)
    assert [int(r[0]) for r in rows] == [T0]
    assert sleeps == [1.0, 6.0]
    assert sess.get.call_args[0][0] == "https://api.bybit.com/v5/market/kline"


def test_5xx_retries():
    sess = MagicMock()
    sess.get.side_effect = [FakeResponse(503), FakeResponse(200, envelope([kl(T0)]))]
    assert len(bb.fetch_window(sess, T0, T0 + MIN, sleep=lambda s: None)) == 1


def test_binance_default_behavior_unchanged_for_403():
    sess = MagicMock()
    sess.get.return_value = FakeResponse(403)
    with pytest.raises(requests.HTTPError):  # old behavior: plain raise_for_status, no custom message
        bk.get_with_retry(sess, {}, sleep=lambda s: None)
    assert sess.get.call_args[0][0].startswith("https://fapi.binance.com")


def _write_rows(path, times):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(bb.COLUMNS)
        for t in times:
            w.writerow(kl(t))


@pytest.mark.parametrize(
    "tail",
    [
        b"1752577620000,1.0,1.2,0.9",  # cut mid-row, no newline
        b"1752577620000",  # only the timestamp
        b"1752577620000,1.0,1.2\r\n",  # newline-terminated but too few columns
    ],
)
def test_resume_after_partial_last_line(tmp_path, tail):
    times = [T0 + i * MIN for i in range(12)]
    out = tmp_path / "b.csv"
    _write_rows(out, times[:5])
    with open(out, "ab") as f:
        f.write(tail)
    sess = FakeSession(times)
    n = bb.fetch_klines(out, end_ms=times[-1], session=sess, sleep=lambda s: None,
                        clock=lambda: FAR_FUTURE, limit=4)  # start_ms=None -> resume point
    assert sess.kline_calls()[0]["start"] == times[4] + MIN  # no detection request needed
    assert not any(u.endswith("instruments-info") for u, _ in sess.calls)
    assert n == 7
    assert read_times(out) == times  # no duplicates, nothing lost
    assert out.read_bytes().count(b"\n") == 13


def test_rerun_with_nothing_new_is_noop(tmp_path):
    times = [T0 + i * MIN for i in range(5)]
    out = tmp_path / "b.csv"
    run(out, FakeSession(times))
    assert run(out, FakeSession(times)) == 0
    assert read_times(out) == times


def test_existing_rows_never_rewritten(tmp_path):
    times = [T0 + i * MIN for i in range(5)]
    out = tmp_path / "b.csv"
    run(out, FakeSession(times[:3]), end_ms=times[2])
    before = out.read_bytes()
    run(out, FakeSession(times), end_ms=times[-1])
    assert out.read_bytes().startswith(before)


def test_detects_first_kline_from_launch_time(tmp_path):
    first = T0 + 7 * MIN
    times = [first + i * MIN for i in range(4)]
    sess = FakeSession(times, launch=first - 90_000)  # launch is mid-minute, before first candle
    out = tmp_path / "b.csv"
    n = bb.fetch_klines(out, end_ms=first + 10 * MIN, session=sess, sleep=lambda s: None,
                        clock=lambda: FAR_FUTURE)
    assert n == 4 and read_times(out) == times
    assert sess.calls[0][0].endswith("/v5/market/instruments-info")


def test_detection_failure_is_loud():
    sess = FakeSession([], launch=T0)
    with pytest.raises(RuntimeError, match="--start"):
        bb.detect_first_kline(sess, sleep=lambda s: None)


def test_main_passes_args(tmp_path, monkeypatch):
    got = {}

    def fake_fetch(path, start_ms=None, end_ms=None, **kw):
        got.update(path=path, start_ms=start_ms, end_ms=end_ms)
        return 0

    monkeypatch.setattr(bb, "fetch_klines", fake_fetch)
    bb.main(["--start", "2025-08-01", "--end", "2025-08-02", "--out", str(tmp_path / "x.csv")])
    assert got["start_ms"] == bk.parse_utc_ms("2025-08-01")
    assert got["end_ms"] == bk.parse_utc_ms("2025-08-02")
    bb.main(["--out", str(tmp_path / "x.csv")])
    assert got["start_ms"] is None  # detection happens inside fetch_klines
