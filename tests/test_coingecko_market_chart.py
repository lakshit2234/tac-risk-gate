"""Tests for the CoinGecko market_chart fetcher (mocked, no network)."""
import csv
import math

import pytest
import requests

from tacgate.data import coingecko_market_chart as cg

DAY = cg.DAY_MS
D0 = 1_794_960_000_000  # 2026-11-18 00:00:00 UTC (midnight aligned)
NOW = D0 + 2 * DAY + 16 * 3_600_000  # 2026-11-20 16:00 UTC: "today" is D0 + 2 days
TODAY_MIDNIGHT = D0 + 2 * DAY


def point_set(midnights, live_ts=None, scale=1.0):
    """Build a market_chart payload: one point per midnight, plus an optional live partial-day point."""
    stamps = list(midnights) + ([live_ts] if live_ts is not None else [])
    return {
        "prices": [[t, 0.001 * scale + i * 1e-5] for i, t in enumerate(stamps)],
        "market_caps": [[t, 8_000_000.0 * scale + i * 1000] for i, t in enumerate(stamps)],
        "total_volumes": [[t, 3_000_000.0 * scale + i * 100] for i, t in enumerate(stamps)],
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
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params)))
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        return r


def ok(payload):
    return FakeResponse(200, payload)


def run(tmp_path, session, now=NOW, days=365, name="cg.csv"):
    sleeps = []
    res = cg.fetch_market_chart(tmp_path / name, days=days, session=session, sleep=sleeps.append, clock=lambda: now)
    return res, sleeps


def rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- parse ---

def test_parse_valid_payload():
    out = cg.parse_market_chart(point_set([D0, D0 + DAY]))
    assert [r[0] for r in out] == [D0, D0 + DAY]
    assert out[0][1:] == (0.001, 8_000_000.0, 3_000_000.0)


def test_parse_accepts_whole_number_float_timestamps():
    p = point_set([D0])
    for k in cg.RESPONSE_KEYS:
        p[k][0][0] = float(D0)
    assert cg.parse_market_chart(p)[0][0] == D0


@pytest.mark.parametrize("mutate", [
    lambda p: p.pop("market_caps"),  # missing key
    lambda p: p.update(extra=[]),  # extra key
    lambda p: p.update(prices=[]),  # empty
    lambda p: p.update(prices="oops"),  # wrong type
    lambda p: p["prices"].__setitem__(0, [D0]),  # pair too short
    lambda p: p["prices"].__setitem__(0, [D0, None]),  # null value
    lambda p: p["prices"].__setitem__(0, [D0, "0.001"]),  # string value
    lambda p: p["prices"].__setitem__(0, [D0, float("nan")]),
    lambda p: p["prices"].__setitem__(0, [D0 + 0.5, 0.001]),  # fractional timestamp
    lambda p: p["market_caps"].__setitem__(0, [D0 + 1, 8e6]),  # timestamps differ between series
    lambda p: p["total_volumes"].pop(),  # different length
    lambda p: p["prices"].reverse(),  # not ascending
])
def test_parse_shape_change_fails_loudly(mutate):
    p = point_set([D0, D0 + DAY])
    mutate(p)
    with pytest.raises(cg.ShapeError):
        cg.parse_market_chart(p)


def test_parse_rejects_non_object():
    with pytest.raises(cg.ShapeError):
        cg.parse_market_chart([[1, 2]])


def test_parse_rejects_duplicate_timestamps():
    p = point_set([D0, D0])
    with pytest.raises(cg.ShapeError):
        cg.parse_market_chart(p)


def test_shape_change_in_a_fetch_writes_nothing(tmp_path):
    p = point_set([D0, D0 + DAY])
    p["extra"] = []
    with pytest.raises(cg.ShapeError):
        run(tmp_path, FakeSession(ok(p)))
    assert not (tmp_path / "cg.csv").exists() or (tmp_path / "cg.csv").read_text() == ""


# ---------------------------------------------------------------- fetch ---

def test_request_uses_verified_endpoint_and_params(tmp_path):
    s = FakeSession(ok(point_set([D0, D0 + DAY], live_ts=NOW - 600_000)))
    run(tmp_path, s)
    url, params = s.calls[0]
    assert url == "https://api.coingecko.com/api/v3/coins/tac/market_chart"
    assert params == {"vs_currency": "usd", "days": 365, "interval": "daily"}
    assert len(s.calls) == 1  # one request per run


def test_first_run_saves_raw_rows_with_fetched_at(tmp_path):
    s = FakeSession(ok(point_set([D0, D0 + DAY], live_ts=NOW - 600_000)))
    res, _ = run(tmp_path, s)
    got = rows(tmp_path / "cg.csv")
    assert list(got[0]) == cg.COLUMNS == ["timestamp_ms", "price", "market_cap", "total_volume", "fetched_at_ms"]
    assert [int(r["timestamp_ms"]) for r in got] == [D0, D0 + DAY]
    assert all(int(r["fetched_at_ms"]) == NOW for r in got)
    assert float(got[0]["price"]) == 0.001 and float(got[0]["market_cap"]) == 8_000_000.0
    assert res.added == 2 and res.total_rows == 2
    assert res.first_ts == D0 and res.last_ts == D0 + DAY and res.missing_days == []


def test_current_utc_day_row_is_skipped(tmp_path):
    live = TODAY_MIDNIGHT + 16 * 3_600_000 - 600_000  # the live partial point, on today
    s = FakeSession(ok(point_set([D0, D0 + DAY], live_ts=live)))
    res, _ = run(tmp_path, s)
    assert res.skipped_current_day == 1
    assert [int(r["timestamp_ms"]) for r in rows(tmp_path / "cg.csv")] == [D0, D0 + DAY]


def test_midnight_of_today_is_also_skipped(tmp_path):
    s = FakeSession(ok(point_set([D0, TODAY_MIDNIGHT])))
    res, _ = run(tmp_path, s)
    assert [int(r["timestamp_ms"]) for r in rows(tmp_path / "cg.csv")] == [D0]
    assert res.skipped_current_day == 1


def test_day_that_was_live_is_stored_complete_the_next_day(tmp_path):
    p1 = point_set([D0, D0 + DAY], live_ts=NOW)
    run(tmp_path, FakeSession(ok(p1)))
    nxt = NOW + DAY  # next day 16:00
    p2 = point_set([D0, D0 + DAY, D0 + 2 * DAY], live_ts=nxt - 600_000)
    res, _ = run(tmp_path, FakeSession(ok(p2)), now=nxt)
    assert res.added == 1
    assert [int(r["timestamp_ms"]) for r in rows(tmp_path / "cg.csv")] == [D0, D0 + DAY, D0 + 2 * DAY]


def test_dedupe_same_response_twice_adds_nothing(tmp_path):
    payload = point_set([D0, D0 + DAY])
    run(tmp_path, FakeSession(ok(payload)))
    before = (tmp_path / "cg.csv").read_bytes()
    res, _ = run(tmp_path, FakeSession(ok(payload)), now=NOW + 3600_000)
    assert res.added == 0 and res.compared == 2 and res.revisions == []
    assert (tmp_path / "cg.csv").read_bytes() == before  # not even touched


def test_resume_appends_only_new_days(tmp_path):
    run(tmp_path, FakeSession(ok(point_set([D0, D0 + DAY]))))
    first = (tmp_path / "cg.csv").read_bytes()
    nxt = NOW + DAY
    payload = point_set([D0, D0 + DAY, D0 + 2 * DAY])
    res, _ = run(tmp_path, FakeSession(ok(payload)), now=nxt)
    assert res.added == 1
    data = (tmp_path / "cg.csv").read_bytes()
    assert data.startswith(first)  # existing bytes untouched, new row appended after them
    got = rows(tmp_path / "cg.csv")
    assert int(got[-1]["fetched_at_ms"]) == nxt and int(got[0]["fetched_at_ms"]) == NOW  # honest fetch times


def test_existing_rows_never_rewritten_and_revision_not_applied(tmp_path):
    run(tmp_path, FakeSession(ok(point_set([D0, D0 + DAY]))))
    before = (tmp_path / "cg.csv").read_bytes()
    revised = point_set([D0, D0 + DAY])
    revised["prices"][0][1] = 0.002  # +100%
    revised["market_caps"][1][1] = 8_001_000.0 * 1.5  # a different change on the other day
    res, _ = run(tmp_path, FakeSession(ok(revised)), now=NOW + 3600_000)
    assert res.added == 0
    assert (tmp_path / "cg.csv").read_bytes() == before  # not applied
    assert len(res.revisions) == 2
    by_ts = {r.timestamp_ms: r for r in res.revisions}
    assert by_ts[D0].changes == {"price": pytest.approx(1.0)}
    assert set(by_ts[D0 + DAY].changes) == {"market_cap"}


def test_revision_report_and_log(tmp_path, caplog):
    run(tmp_path, FakeSession(ok(point_set([D0, D0 + DAY]))))
    revised = point_set([D0, D0 + DAY])
    revised["prices"][0][1] = 0.0015
    with caplog.at_level("WARNING"):
        res, _ = run(tmp_path, FakeSession(ok(revised)), now=NOW + 3600_000)
    text = "\n".join(cg.revision_lines(res))
    assert "1 of 2 already-stored days changed" in text
    assert "largest relative change in price: 0.5" in text
    assert "largest relative change in market_cap: 0" in text
    assert cg.utc_date(D0) in text
    assert "already-stored days changed" in caplog.text
    log_file = cg.revision_log_path(tmp_path / "cg.csv")
    assert log_file.exists() and "1 of 2" in log_file.read_text(encoding="utf-8")


def test_revision_list_capped_at_ten_largest_first(tmp_path):
    days = [D0 + i * DAY for i in range(15)]
    run(tmp_path, FakeSession(ok(point_set(days))), now=D0 + 20 * DAY)
    revised = point_set(days)
    for i in range(15):
        revised["prices"][i][1] = revised["prices"][i][1] * (1 + 0.01 * (i + 1))
    res, _ = run(tmp_path, FakeSession(ok(revised)), now=D0 + 21 * DAY)
    assert len(res.revisions) == 15
    listed = [ln for ln in cg.revision_lines(res) if ln.startswith("    20")]
    assert len(listed) == 10
    assert cg.utc_date(days[14]) in listed[0]  # largest change first


def test_no_revision_log_file_when_nothing_changed(tmp_path):
    run(tmp_path, FakeSession(ok(point_set([D0, D0 + DAY]))))
    run(tmp_path, FakeSession(ok(point_set([D0, D0 + DAY]))), now=NOW + 1000)
    assert not cg.revision_log_path(tmp_path / "cg.csv").exists()


def test_rel_change_edge_cases():
    assert cg.rel_change(2.0, 3.0) == 0.5
    assert cg.rel_change(0.0, 0.0) == 0.0
    assert math.isinf(cg.rel_change(0.0, 1.0))


def test_missing_days_inside_range_are_counted(tmp_path):
    s = FakeSession(ok(point_set([D0, D0 + 2 * DAY])))  # D0+1 day absent
    res, _ = run(tmp_path, s, now=D0 + 10 * DAY)
    assert res.missing_days == [D0 + DAY]
    assert "Days missing inside the range: 1 (" + cg.utc_date(D0 + DAY) in "\n".join(cg.summary_lines(res, tmp_path))


def test_late_filled_gap_is_appended_and_flagged(tmp_path):
    run(tmp_path, FakeSession(ok(point_set([D0, D0 + 2 * DAY]))), now=D0 + 10 * DAY)
    res, _ = run(tmp_path, FakeSession(ok(point_set([D0, D0 + DAY, D0 + 2 * DAY]))), now=D0 + 11 * DAY)
    assert res.added == 1 and res.out_of_order == 1 and res.missing_days == []


def test_summary_text(tmp_path):
    res, _ = run(tmp_path, FakeSession(ok(point_set([D0, D0 + DAY], live_ts=NOW - 1))))
    text = "\n".join(cg.summary_lines(res, tmp_path / "cg.csv"))
    assert "Rows added: 2" in text and "skipped 1" in text
    assert f"Stored dates: {cg.utc_date(D0)} to {cg.utc_date(D0 + DAY)}" in text
    assert "Total rows: 2" in text and "Days missing inside the range: 0" in text
    assert "revisions: 0 of 0" in text


# ---------------------------------------------------------- crash safety ---

def test_partial_last_line_is_repaired(tmp_path):
    run(tmp_path, FakeSession(ok(point_set([D0, D0 + DAY]))))
    path = tmp_path / "cg.csv"
    with path.open("a", newline="") as f:
        f.write(f"{D0 + 2 * DAY},0.00")  # crash mid-write: no newline, too few columns
    payload = point_set([D0, D0 + DAY, D0 + 2 * DAY])
    res, _ = run(tmp_path, FakeSession(ok(payload)), now=D0 + 10 * DAY)
    got = rows(path)
    assert [int(r["timestamp_ms"]) for r in got] == [D0, D0 + DAY, D0 + 2 * DAY]
    assert all(len(r) == 5 and None not in r.values() for r in got)  # no ragged rows
    assert res.added == 1


def test_wrong_header_is_refused_and_file_untouched(tmp_path):
    path = tmp_path / "cg.csv"
    path.write_text("a,b,c\n1,2,3\n")
    with pytest.raises(ValueError):
        run(tmp_path, FakeSession(ok(point_set([D0]))))
    assert path.read_text() == "a,b,c\n1,2,3\n"


# ----------------------------------------------------------------- HTTP ---

def test_429_is_retried_honoring_retry_after(tmp_path):
    s = FakeSession(
        FakeResponse(429, headers={"Retry-After": "90"}),
        FakeResponse(429),
        ok(point_set([D0, D0 + DAY])),
    )
    res, sleeps = run(tmp_path, s)
    assert res.added == 2 and len(s.calls) == 3
    assert sleeps[0] == 90  # Retry-After beats the 5 s backoff
    assert sleeps[1] == cg.BACKOFF_BASE * 2  # second wait: plain exponential backoff


def test_5xx_is_retried(tmp_path):
    s = FakeSession(FakeResponse(503), ok(point_set([D0])))
    res, sleeps = run(tmp_path, s)
    assert res.added == 1 and sleeps == [cg.BACKOFF_BASE]


@pytest.mark.parametrize("status", [401, 403])
def test_auth_or_plan_error_raises_immediately(tmp_path, status):
    s = FakeSession(FakeResponse(status, payload={"error": {"status": {"error_code": 10012}}}))
    with pytest.raises(RuntimeError, match=f"HTTP {status}"):
        run(tmp_path, s)
    assert len(s.calls) == 1  # never retried
    assert not (tmp_path / "cg.csv").exists() or (tmp_path / "cg.csv").read_text() == ""


def test_401_message_mentions_free_tier_limit(tmp_path):
    with pytest.raises(RuntimeError, match="10012"):
        run(tmp_path, FakeSession(FakeResponse(401)))


def test_gives_up_after_repeated_429(tmp_path):
    s = FakeSession(FakeResponse(429))
    with pytest.raises(RuntimeError, match="Giving up"):
        run(tmp_path, s)
    assert len(s.calls) == cg.MAX_RETRIES + 1


@pytest.mark.parametrize("days", [0, 366, -1])
def test_days_out_of_range_rejected_without_a_request(tmp_path, days):
    s = FakeSession(ok(point_set([D0])))
    with pytest.raises(ValueError, match="365"):
        run(tmp_path, s, days=days)
    assert s.calls == []


# ------------------------------------------------------------------ CLI ---

def test_main_reports_errors_cleanly(tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("HTTP 401 from CoinGecko")

    monkeypatch.setattr(cg, "fetch_market_chart", boom)
    assert cg.main(["--out", str(tmp_path / "x.csv")]) == 1
    assert "ERROR: HTTP 401" in capsys.readouterr().out


def test_main_prints_summary(tmp_path, monkeypatch, capsys):
    s = FakeSession(ok(point_set([D0, D0 + DAY])))
    real = cg.fetch_market_chart

    def patched(out_path, days):
        return real(out_path, days=days, session=s, sleep=lambda x: None, clock=lambda: NOW)

    monkeypatch.setattr(cg, "fetch_market_chart", patched)
    assert cg.main(["--days", "30", "--out", str(tmp_path / "x.csv")]) == 0
    out = capsys.readouterr().out
    assert "Rows added: 2" in out and s.calls[0][1]["days"] == 30
