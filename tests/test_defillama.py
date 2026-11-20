"""Tests for the DeFiLlama TVL and price fetchers (mocked, no network)."""
import csv

import pytest
import requests

from tacgate.data import defillama as dl

DAY = dl.DAY_MS
D0 = 1_794_960_000_000  # a UTC midnight (ms)
NOW = D0 + 5 * DAY + 16 * 3_600_000  # "today" is D0 + 5 days, 16:00 UTC
TODAY = D0 + 5 * DAY


def tvl_payload(days, base=1000.0):
    return [{"date": (D0 + d * DAY) // 1000, "tvl": base + d} for d in days]


def price_payload(stamps_s, confidence=0.99, base=0.001):
    coin = {"symbol": "TAC", "prices": [{"timestamp": s, "price": base + i * 1e-5} for i, s in enumerate(stamps_s)]}
    if confidence is not None:
        coin["confidence"] = confidence
    return {"coins": {"coingecko:tac": coin}}


def day_stamp(d, jitter=0):
    """Unix SECONDS of day D0+d midnight plus a jitter in seconds (price points are not exactly midnight)."""
    return (D0 + d * DAY) // 1000 + jitter


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
        self.calls.append((url, dict(params or {})))
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def ok(p):
    return FakeResponse(200, p)


def run(tmp_path, spec, session, now=NOW, name="x.csv"):
    sleeps = []
    res = dl.fetch(spec, tmp_path / name, session=session, sleep=sleeps.append, clock=lambda: now)
    return res, sleeps


def rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


# ------------------------------------------------------------ parse: tvl ---

def test_parse_tvl_converts_seconds_to_milliseconds():
    out = dl.parse_tvl([{"date": 1752796800, "tvl": 9095944}, {"date": 1752883200, "tvl": 43839344.5}])
    assert out == [(1752796800000, {"tvl": 9095944.0}), (1752883200000, {"tvl": 43839344.5})]


@pytest.mark.parametrize("payload", [
    {"date": 1, "tvl": 2},  # not a list
    [],  # empty
    [{"date": 1752796800}],  # missing key
    [{"date": 1752796800, "tvl": 1, "extra": 2}],  # extra key
    [{"date": 1752796800, "tvl": None}],  # null value
    [{"date": 1752796800, "tvl": "5"}],  # string value
    [{"date": 1752796800000, "tvl": 5}],  # milliseconds instead of seconds
    [{"date": 1752796800.5, "tvl": 5}],  # fractional seconds
    [{"date": 0, "tvl": 5}],
    [{"date": 1752883200, "tvl": 1}, {"date": 1752796800, "tvl": 1}],  # not ascending
    [{"date": 1752796800, "tvl": 1}, {"date": 1752796800, "tvl": 2}],  # duplicate
    ["x"],
])
def test_parse_tvl_shape_change_fails_loudly(payload):
    with pytest.raises(dl.ShapeError):
        dl.parse_tvl(payload)


# ---------------------------------------------------------- parse: price ---

def test_parse_price_converts_seconds_and_keeps_confidence():
    out = dl.parse_price(price_payload([1752624001, 1752710399], confidence=0.99))
    assert [p[0] for p in out] == [1752624001000, 1752710399000]
    assert out[0][1] == {"price": 0.001, "confidence": 0.99}


def test_parse_price_confidence_is_optional():
    out = dl.parse_price(price_payload([1752624001], confidence=None))
    assert out[0][1]["confidence"] == ""


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(extra=1),
    lambda p: p.__setitem__("coins", {}),
    lambda p: p.__setitem__("coins", {"coingecko:other": {}}),
    lambda p: p["coins"]["coingecko:tac"].update(decimals=8),  # unknown coin key
    lambda p: p["coins"]["coingecko:tac"].pop("prices"),
    lambda p: p["coins"]["coingecko:tac"].update(symbol="XXX"),
    lambda p: p["coins"]["coingecko:tac"].update(prices=[]),
    lambda p: p["coins"]["coingecko:tac"].update(confidence="high"),
    lambda p: p["coins"]["coingecko:tac"]["prices"][0].update(extra=1),
    lambda p: p["coins"]["coingecko:tac"]["prices"][0].update(price=None),
    lambda p: p["coins"]["coingecko:tac"]["prices"][0].update(timestamp=1752624001000),  # ms, not seconds
    lambda p: p["coins"]["coingecko:tac"]["prices"].reverse(),
])
def test_parse_price_shape_change_fails_loudly(mutate):
    p = price_payload([1752624001, 1752710399, 1752796801])
    mutate(p)
    with pytest.raises(dl.ShapeError):
        dl.parse_price(p)


def test_parse_price_rejects_non_object():
    with pytest.raises(dl.ShapeError):
        dl.parse_price([1, 2])


# ----------------------------------------------------------- fetch: tvl ---

def test_tvl_request_and_first_run(tmp_path):
    s = FakeSession(ok(tvl_payload([0, 1, 2])))
    res, _ = run(tmp_path, dl.TVL, s)
    url, params = s.calls[0]
    assert url == "https://api.llama.fi/v2/historicalChainTvl/TAC" and params == {}
    assert len(s.calls) == 1
    got = rows(tmp_path / "x.csv")
    assert list(got[0]) == ["timestamp_ms", "tvl", "fetched_at_ms"]
    assert [int(r["timestamp_ms"]) for r in got] == [D0, D0 + DAY, D0 + 2 * DAY]
    assert all(int(r["fetched_at_ms"]) == NOW for r in got)
    assert float(got[1]["tvl"]) == 1001.0
    assert res.added == 3 and res.total_rows == 3 and res.missing_days == []


def test_stored_timestamp_is_milliseconds_not_seconds(tmp_path):
    run(tmp_path, dl.TVL, FakeSession(ok(tvl_payload([0]))))
    assert int(rows(tmp_path / "x.csv")[0]["timestamp_ms"]) == D0 // 1000 * 1000
    assert int(rows(tmp_path / "x.csv")[0]["timestamp_ms"]) > 10**12


def test_tvl_current_day_is_skipped(tmp_path):
    # days 0..4 are past; day 5 (today's midnight point, a live value) must be skipped
    res, _ = run(tmp_path, dl.TVL, FakeSession(ok(tvl_payload([3, 4, 5]))))
    assert res.skipped_current_day == 1
    assert [int(r["timestamp_ms"]) for r in rows(tmp_path / "x.csv")] == [D0 + 3 * DAY, D0 + 4 * DAY]


def test_tvl_dedupe_and_untouched_file(tmp_path):
    run(tmp_path, dl.TVL, FakeSession(ok(tvl_payload([0, 1]))))
    before = (tmp_path / "x.csv").read_bytes()
    res, _ = run(tmp_path, dl.TVL, FakeSession(ok(tvl_payload([0, 1]))), now=NOW + 1000)
    assert res.added == 0 and res.compared == 2 and res.revisions == []
    assert (tmp_path / "x.csv").read_bytes() == before


def test_tvl_resume_appends_only_new(tmp_path):
    run(tmp_path, dl.TVL, FakeSession(ok(tvl_payload([0, 1]))))
    first = (tmp_path / "x.csv").read_bytes()
    nxt = NOW + DAY
    res, _ = run(tmp_path, dl.TVL, FakeSession(ok(tvl_payload([0, 1, 2, 5]))), now=nxt)
    assert res.added == 2  # day 2 and day 5 (day 5 is now yesterday-or-earlier)
    assert (tmp_path / "x.csv").read_bytes().startswith(first)
    got = rows(tmp_path / "x.csv")
    assert int(got[0]["fetched_at_ms"]) == NOW and int(got[-1]["fetched_at_ms"]) == nxt


def test_tvl_revision_logged_but_not_applied(tmp_path, caplog):
    run(tmp_path, dl.TVL, FakeSession(ok(tvl_payload([0, 1, 2]))))
    before = (tmp_path / "x.csv").read_bytes()
    revised = tvl_payload([0, 1, 2])
    revised[1]["tvl"] = 2000.0  # stored 1001.0 -> +99.8%
    with caplog.at_level("WARNING"):
        res, _ = run(tmp_path, dl.TVL, FakeSession(ok(revised)), now=NOW + 1000)
    assert (tmp_path / "x.csv").read_bytes() == before  # never rewritten
    assert res.added == 0 and len(res.revisions) == 1
    text = "\n".join(dl.revision_lines(dl.TVL, res))
    assert "1 of 3 already-stored days changed" in text
    assert "largest relative change in tvl: 0.998" in text
    assert dl.utc_date(D0 + DAY) in text
    assert "already-stored days changed" in caplog.text
    assert "1 of 3" in dl.revision_log_path(tmp_path / "x.csv").read_text(encoding="utf-8")


def test_no_revision_log_when_nothing_changed(tmp_path):
    run(tmp_path, dl.TVL, FakeSession(ok(tvl_payload([0, 1]))))
    run(tmp_path, dl.TVL, FakeSession(ok(tvl_payload([0, 1]))), now=NOW + 1)
    assert not dl.revision_log_path(tmp_path / "x.csv").exists()


def test_revision_list_capped_at_ten(tmp_path):
    run(tmp_path, dl.TVL, FakeSession(ok(tvl_payload(range(15)))), now=D0 + 20 * DAY)
    revised = tvl_payload(range(15))
    for i, p in enumerate(revised):
        p["tvl"] *= 1 + 0.01 * (i + 1)
    res, _ = run(tmp_path, dl.TVL, FakeSession(ok(revised)), now=D0 + 21 * DAY)
    listed = [ln for ln in dl.revision_lines(dl.TVL, res) if ln.startswith("    20")]
    assert len(res.revisions) == 15 and len(listed) == 10
    assert dl.utc_date(D0 + 14 * DAY) in listed[0]  # largest first


def test_tvl_missing_days_reported_not_filled(tmp_path):
    res, _ = run(tmp_path, dl.TVL, FakeSession(ok(tvl_payload([0, 1, 4]))))
    assert res.missing_days == [D0 + 2 * DAY, D0 + 3 * DAY]
    assert [int(r["timestamp_ms"]) for r in rows(tmp_path / "x.csv")] == [D0, D0 + DAY, D0 + 4 * DAY]
    text = "\n".join(dl.summary_lines(dl.TVL, res, tmp_path / "x.csv"))
    assert "Days missing inside the range: 2" in text
    assert f"{dl.utc_date(D0 + 2 * DAY)}..{dl.utc_date(D0 + 3 * DAY)}" in text  # listed as one gap


# --------------------------------------------------------- fetch: price ---

def test_price_request_params_and_row_layout(tmp_path):
    s = FakeSession(ok(price_payload([day_stamp(0, 1), day_stamp(1, -17)])))
    res, _ = run(tmp_path, dl.PRICE, s)
    url, params = s.calls[0]
    assert url == "https://coins.llama.fi/chart/coingecko:tac"
    assert params["period"] == "1d" and params["start"] == dl.PRICE_START_S
    assert params["span"] >= (NOW // 1000 - dl.PRICE_START_S) // 86400  # reaches through today
    got = rows(tmp_path / "x.csv")
    assert list(got[0]) == ["timestamp_ms", "price", "confidence", "fetched_at_ms"]
    # timestamps are stored exactly as returned (jitter kept), converted to ms
    assert [int(r["timestamp_ms"]) for r in got] == [D0 + 1000, D0 + DAY - 17_000]
    assert all(float(r["confidence"]) == 0.99 for r in got)
    assert all(int(r["fetched_at_ms"]) == NOW for r in got)


def test_price_current_day_skipped(tmp_path):
    # 23:59:42 on day 4 is a complete past point; 00:00:23 on day 5 and 15:00 on day 5 are on today
    stamps = [day_stamp(3), day_stamp(5, 23), day_stamp(5, 15 * 3600)]
    res, _ = run(tmp_path, dl.PRICE, FakeSession(ok(price_payload([day_stamp(4, -18)] + stamps[1:]))))
    assert res.skipped_current_day == 2 and res.added == 1
    assert int(rows(tmp_path / "x.csv")[0]["timestamp_ms"]) == D0 + 4 * DAY - 18_000


def test_price_jitter_does_not_invent_gaps(tmp_path):
    # points at 23:59:42 of day 0, 00:00:23 of day 2, 23:59:50 of day 2 (-> nominal day 3), 00:00:05 of day 4
    stamps = [day_stamp(1, -18), day_stamp(2, 23), day_stamp(3, -10), day_stamp(4, 5)]
    res, _ = run(tmp_path, dl.PRICE, FakeSession(ok(price_payload(stamps))))
    # nominal days (nearest midnight): 1, 2, 3, 4 -> no missing days
    assert res.missing_days == []


def test_price_missing_days_listed_not_filled(tmp_path):
    stamps = [day_stamp(0, 1), day_stamp(1, -5), day_stamp(4, 2)]  # nominal days 0, 1, 4 -> 2,3 missing
    res, _ = run(tmp_path, dl.PRICE, FakeSession(ok(price_payload(stamps))))
    assert res.missing_days == [D0 + 2 * DAY, D0 + 3 * DAY]
    assert len(rows(tmp_path / "x.csv")) == 3
    assert "Gaps (not filled): " in "\n".join(dl.summary_lines(dl.PRICE, res, tmp_path / "x.csv"))


def test_price_blank_confidence_when_absent(tmp_path):
    run(tmp_path, dl.PRICE, FakeSession(ok(price_payload([day_stamp(0, 1)], confidence=None))))
    assert rows(tmp_path / "x.csv")[0]["confidence"] == ""
    # and a second run can still read the file back
    res, _ = run(tmp_path, dl.PRICE, FakeSession(ok(price_payload([day_stamp(0, 1)], confidence=None))), now=NOW + 1)
    assert res.compared == 1 and res.revisions == []


def test_price_revision_logged_not_applied_and_confidence_ignored(tmp_path):
    run(tmp_path, dl.PRICE, FakeSession(ok(price_payload([day_stamp(0, 1), day_stamp(1, -5)]))))
    before = (tmp_path / "x.csv").read_bytes()
    revised = price_payload([day_stamp(0, 1), day_stamp(1, -5)], confidence=0.5, base=0.002)
    res, _ = run(tmp_path, dl.PRICE, FakeSession(ok(revised)), now=NOW + 1)
    assert (tmp_path / "x.csv").read_bytes() == before
    assert len(res.revisions) == 2 and set(res.revisions[0].changes) == {"price"}


def test_price_dedupe_and_append_only(tmp_path):
    run(tmp_path, dl.PRICE, FakeSession(ok(price_payload([day_stamp(0, 1), day_stamp(1, -5)]))))
    first = (tmp_path / "x.csv").read_bytes()
    res, _ = run(tmp_path, dl.PRICE, FakeSession(ok(price_payload([day_stamp(0, 1), day_stamp(1, -5), day_stamp(2, 3)]))),
                 now=NOW + 1)
    assert res.added == 1
    assert (tmp_path / "x.csv").read_bytes().startswith(first)


# ------------------------------------------------------- crash safety / HTTP ---

@pytest.mark.parametrize("spec,payload", [
    (dl.TVL, tvl_payload([0, 1])),
    (dl.PRICE, price_payload([day_stamp(0, 1), day_stamp(1, -5)])),
])
def test_partial_last_line_repaired(tmp_path, spec, payload):
    run(tmp_path, spec, FakeSession(ok(payload)))
    path = tmp_path / "x.csv"
    with path.open("a", newline="") as f:
        f.write(f"{D0 + 9 * DAY},0.0")  # crash mid-write: no newline, too few columns
    res, _ = run(tmp_path, spec, FakeSession(ok(payload)), now=NOW + 1)
    got = rows(path)
    assert len(got) == 2 and all(None not in r.values() for r in got)
    assert res.added == 0 and res.total_rows == 2


def test_wrong_header_refused_file_untouched(tmp_path):
    (tmp_path / "x.csv").write_text("a,b,c\n1,2,3\n")
    with pytest.raises(ValueError):
        run(tmp_path, dl.TVL, FakeSession(ok(tvl_payload([0]))))
    assert (tmp_path / "x.csv").read_text() == "a,b,c\n1,2,3\n"


def test_429_retried_honoring_retry_after(tmp_path):
    s = FakeSession(FakeResponse(429, headers={"Retry-After": "45"}), FakeResponse(429), ok(tvl_payload([0, 1])))
    res, sleeps = run(tmp_path, dl.TVL, s)
    assert res.added == 2 and len(s.calls) == 3
    assert sleeps[0] == 45 and sleeps[1] == dl.BACKOFF_BASE * 2


def test_5xx_retried(tmp_path):
    res, sleeps = run(tmp_path, dl.TVL, FakeSession(FakeResponse(502), ok(tvl_payload([0]))))
    assert res.added == 1 and sleeps == [dl.BACKOFF_BASE]


@pytest.mark.parametrize("status", [401, 402, 403])
@pytest.mark.parametrize("spec", [dl.TVL, dl.PRICE])
def test_auth_or_plan_error_raises_immediately(tmp_path, spec, status):
    s = FakeSession(FakeResponse(status, payload="Upgrade to the paid API plan"))
    with pytest.raises(RuntimeError, match=f"HTTP {status}"):
        run(tmp_path, spec, s)
    assert len(s.calls) == 1
    assert not (tmp_path / "x.csv").exists() or (tmp_path / "x.csv").read_text() == ""


def test_402_message_says_paid_plan(tmp_path):
    with pytest.raises(RuntimeError, match="paid plan"):
        run(tmp_path, dl.TVL, FakeSession(FakeResponse(402)))


def test_shape_change_in_fetch_writes_nothing(tmp_path):
    with pytest.raises(dl.ShapeError):
        run(tmp_path, dl.TVL, FakeSession(ok({"error": "moved"})))
    assert not (tmp_path / "x.csv").exists() or (tmp_path / "x.csv").read_text() == ""


# ------------------------------------------------------------------ misc ---

def test_gaps_grouping():
    d = [D0, D0 + DAY, D0 + 3 * DAY]
    assert dl.gaps(d) == [(D0, D0 + DAY), (D0 + 3 * DAY, D0 + 3 * DAY)]
    assert dl.gaps([]) == []


def test_late_filled_gap_flagged(tmp_path):
    run(tmp_path, dl.TVL, FakeSession(ok(tvl_payload([0, 2]))))
    res, _ = run(tmp_path, dl.TVL, FakeSession(ok(tvl_payload([0, 1, 2]))), now=NOW + 1)
    assert res.added == 1 and res.out_of_order == 1 and res.missing_days == []


def test_cli_dispatch_and_error_exit(tmp_path, monkeypatch, capsys):
    s = FakeSession(ok(tvl_payload([0, 1])))
    real = dl.fetch
    monkeypatch.setattr(dl, "fetch", lambda spec, out: real(spec, out, session=s, sleep=lambda x: None, clock=lambda: NOW))
    assert dl.main(["tvl", "--out", str(tmp_path / "t.csv")]) == 0
    out = capsys.readouterr().out
    assert "[tvl] Rows added: 2" in out and "Total rows: 2" in out

    def boom(spec, out):
        raise RuntimeError("HTTP 402 from DeFiLlama: paid")

    monkeypatch.setattr(dl, "fetch", boom)
    assert dl.main(["price", "--out", str(tmp_path / "p.csv")]) == 1
    assert "ERROR: HTTP 402" in capsys.readouterr().out


def test_cli_requires_a_subcommand():
    with pytest.raises(SystemExit):
        dl.main([])


def test_default_output_paths():
    assert str(dl.TVL.default_out).replace("\\", "/") == "data/raw/defillama_TAC_chain_tvl_daily.csv"
    assert str(dl.PRICE.default_out).replace("\\", "/") == "data/raw/defillama_TAC_price_daily.csv"
