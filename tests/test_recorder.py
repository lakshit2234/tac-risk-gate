import csv
from urllib.parse import urlparse

import pytest
import requests

from tacgate.data import recorder as rec
from tacgate.data.binance_klines import IPBannedError

P = rec.PERIOD_MS
NOW0 = 1_795_023_000_000  # a multiple of 5 minutes
HIST_PATHS = {ds.path: ds for ds in rec.DATASETS}


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


class Clock:
    def __init__(self, t=NOW0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, ms):
        self.t += int(ms)


def make_rec(ds, ts, extra=None):
    d = {f: "1.5" for f in ds.fields}
    if "symbol" in d:
        d["symbol"] = "TACUSDT"
    d["timestamp"] = ts
    d.update(extra or {})
    return d


DEEP_BOOK = {
    "lastUpdateId": 1, "E": 1, "T": 1,
    "bids": [["0.998", "100000"], ["0.99", "100000"]],
    "asks": [["1.002", "100000"], ["1.01", "100000"]],
}


class FakeApi:
    """Serves the recorder's endpoints like Binance does (history ascending within start..end, else latest rows)."""

    def __init__(self, clock, days=3, publish_delay_ms=0, taker_label_is_start=False):
        self.clock = clock
        self.publish_delay_ms = publish_delay_ms  # a row labelled t is only visible from t + delay
        self.taker_label_is_start = taker_label_is_start  # taker row labelled t is only visible from t + 5 min + delay
        start = clock.t - days * 86_400_000
        self.first = start - start % P
        self.calls = []
        self.fail_paths = set()
        self.fail_status = 503
        self.ban = False
        self.extra_field = False
        self.book = DEEP_BOOK
        self.premium = {
            "symbol": "TACUSDT", "markPrice": "1.0001", "indexPrice": "0.9999", "estimatedSettlePrice": "1.0",
            "lastFundingRate": "0.0001", "interestRate": "0.0001", "nextFundingTime": 1_795_036_800_000, "time": 777,
        }

    def available(self, ds=None):
        visible_until = self.clock.t - self.publish_delay_ms
        if self.taker_label_is_start and ds is not None and ds.name == "taker_buy_sell":
            visible_until -= P
        return list(range(self.first, visible_until - visible_until % P + 1, P))

    def get(self, url, params=None, timeout=None):
        path = urlparse(url).path
        self.calls.append((path, dict(params)))
        if self.ban:
            return FakeResponse(418, headers={"Retry-After": "120"})
        if path in self.fail_paths:
            return FakeResponse(self.fail_status)
        if path in HIST_PATHS:
            ds = HIST_PATHS[path]
            ts = self.available(ds)
            if "startTime" in params and "endTime" in params:
                ts = [t for t in ts if params["startTime"] <= t <= params["endTime"]][: params["limit"]]
            else:
                ts = ts[-params["limit"]:]
            recs = [make_rec(ds, t) for t in ts]
            if self.extra_field and recs:
                recs[0]["surprise"] = "x"
            return FakeResponse(200, recs)
        if path == "/fapi/v1/premiumIndex":
            return FakeResponse(200, self.premium)
        if path == "/fapi/v1/depth":
            return FakeResponse(200, self.book)
        return FakeResponse(404)

    def paths(self):
        return [p for p, _ in self.calls]


def read_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def ds_by_name(name):
    return next(d for d in rec.DATASETS if d.name == name)


OI = ds_by_name("open_interest")
TAKER = ds_by_name("taker_buy_sell")


def make_wait(clock, on_call=None):
    state = {"n": 0}

    def wait(seconds):
        state["n"] += 1
        if on_call:
            if on_call(state["n"]):
                return True
        clock.advance(seconds * 1000)
        return False

    return wait


# ----------------------------------------------------------------- backfill ---

def test_backfill_walks_windows_with_start_and_end_and_documented_limit(tmp_path):
    clock = Clock()
    api = FakeApi(clock)
    rec.backfill(tmp_path, api, sleep=lambda s: None, clock=clock)
    hist = [(p, q) for p, q in api.calls if p == OI.path]
    assert len(hist) > 10  # ~30 days / 500 periods per window
    assert all(q["limit"] == 500 and q["period"] == "5m" and q["symbol"] == "TACUSDT" for _, q in hist)
    assert all("startTime" in q and "endTime" in q for _, q in hist)  # start alone returns the LATEST rows
    starts = [q["startTime"] for _, q in hist]
    assert starts == sorted(starts) and starts[0] >= clock.t - 31 * 86_400_000
    assert all(q["endTime"] <= clock.t for _, q in hist)


def test_backfill_appends_dedupes_and_resumes_without_rewriting(tmp_path):
    clock = Clock()
    api = FakeApi(clock)
    counts = rec.backfill(tmp_path, api, sleep=lambda s: None, clock=clock)
    assert set(counts) == {d.name for d in rec.DATASETS}
    path = OI.csv_path(tmp_path)
    rows = read_rows(path)
    ts = [int(r["timestamp"]) for r in rows]
    assert counts["open_interest"] == len(rows) == len(api.available())
    assert ts == sorted(set(ts))
    assert list(rows[0]) == OI.columns
    before = path.read_bytes()

    # 2 hours later: only the new periods are appended, old bytes untouched, no duplicates
    clock.advance(2 * 3_600_000)
    counts2 = rec.backfill(tmp_path, api, sleep=lambda s: None, clock=clock)
    assert counts2["open_interest"] == 24
    after = path.read_bytes()
    assert after.startswith(before)
    ts2 = [int(r["timestamp"]) for r in read_rows(path)]
    assert ts2 == sorted(set(ts2)) and len(ts2) == len(ts) + 24

    # nothing new -> nothing written
    assert rec.backfill(tmp_path, api, sleep=lambda s: None, clock=clock)["open_interest"] == 0
    assert path.read_bytes() == after


def test_rows_carry_honest_fetched_at_not_the_period_time(tmp_path):
    clock = Clock()
    rec.backfill(tmp_path, FakeApi(clock), sleep=lambda s: None, clock=clock)
    for r in read_rows(OI.csv_path(tmp_path)):
        assert int(r["fetched_at_ms"]) == NOW0  # when we got it, even for a period from days ago
        assert int(r["timestamp"]) <= NOW0


def test_backfill_raw_fields_only_plus_fetched_at(tmp_path):
    clock = Clock()
    rec.backfill(tmp_path, FakeApi(clock), sleep=lambda s: None, clock=clock)
    assert list(read_rows(TAKER.csv_path(tmp_path))[0]) == ["buySellRatio", "buyVol", "sellVol", "timestamp", "fetched_at_ms"]
    assert list(read_rows(OI.csv_path(tmp_path))[0]) == [
        "symbol", "sumOpenInterest", "sumOpenInterestValue", "CMCCirculatingSupply", "timestamp", "fetched_at_ms"]


def test_schema_change_fails_loudly_and_saves_nothing(tmp_path):
    clock = Clock()
    api = FakeApi(clock)
    api.extra_field = True
    with pytest.raises(rec.SchemaError, match="fields changed"):
        rec.backfill_dataset(tmp_path, OI, api, sleep=lambda s: None, clock=clock)
    assert not OI.csv_path(tmp_path).exists() or len(read_rows(OI.csv_path(tmp_path))) == 0


def test_non_list_response_is_schema_error(tmp_path):
    clock = Clock()
    api = FakeApi(clock)
    api.get = lambda url, params=None, timeout=None: FakeResponse(200, {"code": -1, "msg": "nope"})
    with pytest.raises(rec.SchemaError, match="expected a list"):
        rec.fetch_dataset_page(api, OI, sleep=lambda s: None)


# ---------------------------------------------------------- depth / slippage ---

SIMPLE_ASKS = [(1.01, 500.0), (1.02, 1000.0)]
SIMPLE_BIDS = [(0.99, 500.0), (0.98, 1000.0)]


def test_slippage_buy_walks_the_asks():
    # $1000: level 1 gives 500 base for $505, remaining $495 buys 495/1.02 base
    base = 500 + 495 / 1.02
    expected = (1000 / base / 1.0 - 1) * 1e4  # about 149.25 bps vs mid 1.0
    assert rec.slippage_bps(SIMPLE_ASKS, 1000, 1.0, "buy") == pytest.approx(expected)
    assert rec.slippage_bps(SIMPLE_ASKS, 1000, 1.0, "buy") == pytest.approx(149.25, abs=0.01)


def test_slippage_sell_walks_the_bids():
    base = 500 + 505 / 0.98
    assert rec.slippage_bps(SIMPLE_BIDS, 1000, 1.0, "sell") == pytest.approx((1 - 1000 / base) * 1e4)
    assert rec.slippage_bps(SIMPLE_BIDS, 1000, 1.0, "sell") == pytest.approx(150.75, abs=0.01)


def test_slippage_inside_first_level_is_just_that_price():
    assert rec.slippage_bps([(1.01, 10_000.0)], 1000, 1.0, "buy") == pytest.approx(100.0)
    assert rec.slippage_bps([(0.99, 10_000.0)], 1000, 1.0, "sell") == pytest.approx(100.0)


def test_slippage_none_when_book_too_thin():
    assert rec.slippage_bps(SIMPLE_ASKS, 5000, 1.0, "buy") is None  # book holds only $1,525
    assert rec.slippage_bps([], 1000, 1.0, "buy") is None


def test_depth_within_bands_on_a_hand_made_book():
    bids = [(0.998, 100.0), (0.992, 200.0), (0.985, 300.0)]
    asks = [(1.002, 100.0), (1.008, 200.0), (1.015, 300.0)]
    mid = 1.0
    assert rec.depth_within(bids, mid * 0.995, "bid") == pytest.approx(99.8)
    assert rec.depth_within(bids, mid * 0.99, "bid") == pytest.approx(99.8 + 198.4)
    assert rec.depth_within(bids, mid * 0.98, "bid") == pytest.approx(99.8 + 198.4 + 295.5)
    assert rec.depth_within(asks, mid * 1.005, "ask") == pytest.approx(100.2)
    assert rec.depth_within(asks, mid * 1.01, "ask") == pytest.approx(100.2 + 201.6)
    assert rec.depth_within(asks, mid * 1.02, "ask") == pytest.approx(100.2 + 201.6 + 304.5)


def col(row, name):
    return row[rec.SNAPSHOT_COLUMNS.index(name)]


def test_snapshot_row_deep_book_is_filled_ok():
    row = rec.build_snapshot(FakeApi(Clock()).premium, DEEP_BOOK, 123456)
    assert len(row) == len(rec.SNAPSHOT_COLUMNS)
    assert col(row, "fetched_at_ms") == 123456 and col(row, "server_time_ms") == 777
    assert col(row, "mark") == "1.0001" and col(row, "index") == "0.9999"
    assert col(row, "lastFundingRate") == "0.0001" and col(row, "nextFundingTime") == 1_795_036_800_000
    assert col(row, "best_bid") == 0.998 and col(row, "best_ask") == 1.002
    assert float(col(row, "spread_bps")) == pytest.approx(40.0)  # (1.002-0.998)/1.0
    assert col(row, "filled_ok") == 1
    assert float(col(row, "slippage_bps_buy_1000")) == pytest.approx(20.0)  # fills at 1.002 vs mid 1.0
    assert float(col(row, "slippage_bps_sell_5000")) == pytest.approx(20.0)


def test_snapshot_thin_book_blank_slippage_and_filled_ok_zero():
    thin = {
        "lastUpdateId": 1, "E": 1, "T": 1,
        "bids": [["0.998", "100"], ["0.992", "200"], ["0.985", "300"]],  # $593.7 of bids
        "asks": [["1.002", "100"], ["1.008", "200"], ["1.015", "300"]],  # $606.3 of asks
    }
    row = rec.build_snapshot(FakeApi(Clock()).premium, thin, 1)
    for name in ("slippage_bps_buy_1000", "slippage_bps_buy_5000", "slippage_bps_sell_1000", "slippage_bps_sell_5000"):
        assert col(row, name) == ""
    assert col(row, "filled_ok") == 0
    assert float(col(row, "bid_depth_usd_2pct")) == pytest.approx(593.7)
    assert float(col(row, "ask_depth_usd_0p5pct")) == pytest.approx(100.2)
    assert float(col(row, "ask_depth_usd_1pct")) == pytest.approx(301.8)


def test_snapshot_partly_filled_book_blanks_only_what_cannot_fill():
    book = {"lastUpdateId": 1, "E": 1, "T": 1, "bids": [["0.99", "4000"]], "asks": [["1.01", "4000"]]}
    row = rec.build_snapshot(FakeApi(Clock()).premium, book, 1)  # ~$4,000 per side: $1000 fills, $5000 does not
    assert col(row, "slippage_bps_buy_1000") != "" and col(row, "slippage_bps_buy_5000") == ""
    assert col(row, "filled_ok") == 0


def test_snapshot_schema_changes_fail_loudly():
    api = FakeApi(Clock())
    bad_prem = {k: v for k, v in api.premium.items() if k != "markPrice"}
    with pytest.raises(rec.SchemaError, match="premiumIndex"):
        rec.build_snapshot(bad_prem, DEEP_BOOK, 1)
    with pytest.raises(rec.SchemaError, match="depth"):
        rec.build_snapshot(api.premium, {"bids": [], "asks": []}, 1)
    with pytest.raises(rec.SchemaError, match="empty"):
        rec.build_snapshot(api.premium, {**DEEP_BOOK, "asks": []}, 1)


# ----------------------------------------------------------------- run loop ---

def run(tmp_path, api, clock, max_cycles=2, on_wait=None, interval=300):
    out = []
    code = rec.run_loop(
        tmp_path, interval, session=api, sleep=lambda s: None, clock=clock,
        wait=make_wait(clock, on_wait), max_cycles=max_cycles, say=out.append,
    )
    return code, out


def test_cycle_offset_is_45_seconds():
    assert rec.CYCLE_OFFSET_MS == 45_000


def test_next_cycle_is_the_next_boundary_plus_45_s():
    b = 1_795_023_000_000
    assert rec.next_target_ms(b + 46_000, 300) == b + 300_000 + 45_000  # this boundary's slot has passed
    assert rec.next_target_ms(b + 45_000, 300) == b + 300_000 + 45_000  # exactly at the target: next one
    assert rec.next_target_ms(b + 10_000, 300) == b + 45_000  # before this boundary's slot
    assert rec.next_target_ms(b, 300) == b + 45_000
    assert rec.next_target_ms(b + 299_999, 300) == b + 300_000 + 45_000
    assert rec.next_target_ms(b + 61_000, 60) == b + 60_000 + 45_000  # 60 s interval keeps the same offset


def test_cycle_waits_at_44_s_and_runs_at_45_s(tmp_path):
    b = NOW0 + 3 * P  # a 5-minute boundary
    clock = Clock(b + 44_000)  # 44 s after the boundary: too early
    api = FakeApi(clock)
    waits, calls_before_first_cycle = [], []

    def wait(seconds):
        waits.append(seconds)
        if len(waits) == 1:
            calls_before_first_cycle.append(len(api.calls))
        clock.advance(seconds * 1000)
        return False

    code = rec.run_loop(tmp_path, 300, session=api, sleep=lambda s: None, clock=clock, wait=wait,
                        max_cycles=1, say=lambda m: None)
    assert code == 0
    assert waits[0] == pytest.approx(1.0)  # must wait the remaining 1 s, not run now
    assert calls_before_first_cycle == [0]  # nothing was requested before the wait
    assert clock.t >= b + 45_000  # the cycle ran at the 45 s mark


def test_cycle_after_45_s_waits_for_the_next_boundary(tmp_path):
    b = NOW0 + 3 * P
    clock = Clock(b + 46_000)  # this boundary's slot is already gone
    api = FakeApi(clock)
    waits = []

    def wait(seconds):
        waits.append(seconds)
        clock.advance(seconds * 1000)
        return False

    rec.run_loop(tmp_path, 300, session=api, sleep=lambda s: None, clock=clock, wait=wait, max_cycles=1, say=lambda m: None)
    assert waits[0] == pytest.approx((P + 45_000 - 46_000) / 1000)  # 299 s


def test_row_labelled_at_the_boundary_is_stored_in_that_cycle(tmp_path):
    b = NOW0 + 3 * P
    clock = Clock(b + 45_000)
    api = FakeApi(clock, publish_delay_ms=21_000)  # Binance publishes the boundary row about 21 s late
    rec.run_cycle(tmp_path, api, sleep=lambda s: None, clock=clock)
    for ds in (OI, ds_by_name("global_long_short"), ds_by_name("top_position_long_short")):
        rows = read_rows(ds.csv_path(tmp_path))
        assert int(rows[-1]["timestamp"]) == b  # the row labelled AT the boundary, not the previous one
        assert int(rows[-1]["fetched_at_ms"]) - b == 45_000
    snap = read_rows(rec.snapshot_path(tmp_path))
    assert int(snap[-1]["fetched_at_ms"]) == b + 45_000  # real fetch time, not the boundary


def test_old_5_s_offset_would_have_stored_the_previous_label(tmp_path):
    """Regression for the real-data finding: at +5 s the boundary row was not published yet."""
    b = NOW0 + 3 * P
    clock = Clock(b + 5_000)
    api = FakeApi(clock, publish_delay_ms=21_000)
    rec.run_cycle(tmp_path, api, sleep=lambda s: None, clock=clock)
    assert int(read_rows(OI.csv_path(tmp_path))[-1]["timestamp"]) == b - P  # previous label only


def test_late_row_is_caught_by_the_next_cycle_without_duplicates(tmp_path):
    b = NOW0 + 3 * P
    clock = Clock(b + 45_000)
    api = FakeApi(clock, publish_delay_ms=60_000)  # unusually slow publish: boundary row missing in this cycle
    rec.run_cycle(tmp_path, api, sleep=lambda s: None, clock=clock)
    assert int(read_rows(OI.csv_path(tmp_path))[-1]["timestamp"]) == b - P
    clock.advance(P)  # next cycle, five minutes later: latest 2 rows include the late boundary row
    rec.run_cycle(tmp_path, api, sleep=lambda s: None, clock=clock)
    ts = [int(r["timestamp"]) for r in read_rows(OI.csv_path(tmp_path))]
    assert ts == sorted(set(ts))  # no duplicates
    assert ts[-2:] == [b - P, b]  # the late row b arrived one cycle later; b + P is still hidden by the delay


def test_expected_live_lags_open_interest_45_s_taker_5_min_45_s(tmp_path):
    b = NOW0 + 3 * P
    clock = Clock(b + 45_000)
    api = FakeApi(clock, publish_delay_ms=21_000, taker_label_is_start=True)
    rec.run_cycle(tmp_path, api, sleep=lambda s: None, clock=clock)
    last_oi = read_rows(OI.csv_path(tmp_path))[-1]
    assert int(last_oi["fetched_at_ms"]) - int(last_oi["timestamp"]) == 45_000
    last_taker = read_rows(TAKER.csv_path(tmp_path))[-1]
    assert int(last_taker["timestamp"]) == b - P  # label is the period START: the period [b-5m, b) just closed
    assert int(last_taker["fetched_at_ms"]) - int(last_taker["timestamp"]) == P + 45_000  # 5 min 45 s


def test_run_records_all_datasets_and_snapshot_with_fetched_at(tmp_path):
    clock = Clock(NOW0 + 1_000)
    api = FakeApi(clock)
    code, _ = run(tmp_path, api, clock, max_cycles=2)
    assert code == 0
    for ds in rec.DATASETS:
        rows = read_rows(ds.csv_path(tmp_path))
        ts = [int(r["timestamp"]) for r in rows]
        assert ts == sorted(set(ts)) and len(ts) >= 2
        assert all(int(r["fetched_at_ms"]) >= int(r["timestamp"]) for r in rows)  # never known before it existed
    snap = read_rows(rec.snapshot_path(tmp_path))
    assert len(snap) == 2 and list(snap[0]) == rec.SNAPSHOT_COLUMNS
    assert [int(r["fetched_at_ms"]) for r in snap] == sorted(int(r["fetched_at_ms"]) for r in snap)
    assert all(r["fetched_at_ms"] for r in snap) and snap[0]["mark"] == "1.0001"
    assert "/fapi/v1/depth" in api.paths() and "/fapi/v1/premiumIndex" in api.paths()
    assert all(q["limit"] == 100 for p, q in api.calls if p == "/fapi/v1/depth")


def test_two_cycles_same_period_do_not_duplicate(tmp_path):
    clock = Clock(NOW0 + 1_000)
    api = FakeApi(clock)
    for _ in range(2):
        rec.run_cycle(tmp_path, api, sleep=lambda s: None, clock=clock)
    ts = [int(r["timestamp"]) for r in read_rows(OI.csv_path(tmp_path))]
    assert ts == sorted(set(ts)) and len(ts) == 2  # latest two periods, once each
    assert len(read_rows(rec.snapshot_path(tmp_path))) == 2  # snapshots are point-in-time, one per cycle


def test_one_failed_cycle_then_recovery(tmp_path):
    clock = Clock(NOW0 + 1_000)
    api = FakeApi(clock)
    api.fail_paths = {OI.path}

    def heal_after_first(n):
        if n == 2:
            api.fail_paths = set()
        return False

    code, out = run(tmp_path, api, clock, max_cycles=2, on_wait=heal_after_first)
    assert code == 0
    log = rec.errors_log_path(tmp_path).read_text(encoding="utf-8")
    assert "ERROR" in log and "open_interest" in log
    assert any("had 1 error" in line for line in out) and any("Cycle 2 ok" in line for line in out)
    # the other datasets were still recorded in the failed cycle; OI resumed afterwards
    assert len(read_rows(TAKER.csv_path(tmp_path))) >= 2
    assert len(read_rows(OI.csv_path(tmp_path))) >= 1
    assert len(read_rows(rec.snapshot_path(tmp_path))) == 2


def test_418_stops_immediately_with_clear_message(tmp_path):
    clock = Clock(NOW0 + 1_000)
    api = FakeApi(clock)
    api.ban = True
    code, out = run(tmp_path, api, clock, max_cycles=5)
    assert code == 1
    assert len(api.calls) == 1  # no retries, no further endpoints
    assert any("banned" in line and "STOPPED" in line for line in out)
    assert "FATAL" in rec.errors_log_path(tmp_path).read_text(encoding="utf-8")


def test_418_is_a_distinct_error_type():
    api = FakeApi(Clock())
    api.ban = True
    with pytest.raises(IPBannedError):
        rec.fetch_dataset_page(api, OI, sleep=lambda s: None)


def test_ten_consecutive_failed_cycles_stop_the_loop(tmp_path):
    clock = Clock(NOW0 + 1_000)
    api = FakeApi(clock)
    api.fail_paths = {"/fapi/v1/depth"}
    code, out = run(tmp_path, api, clock, max_cycles=50)
    assert code == 1
    assert any("10 consecutive failed cycles" in line for line in out)
    assert sum(p == "/fapi/v1/depth" for p in api.paths()) >= 10


def test_success_resets_the_consecutive_failure_counter(tmp_path):
    clock = Clock(NOW0 + 1_000)
    api = FakeApi(clock)
    api.fail_paths = {"/fapi/v1/depth"}

    def toggle(n):
        api.fail_paths = {"/fapi/v1/depth"} if n % 10 != 0 else set()  # a good cycle every 10th
        return False

    code, _ = run(tmp_path, api, clock, max_cycles=35, on_wait=toggle)
    assert code == 0  # never 10 failures in a row


def test_snapshot_schema_change_is_logged_not_fatal(tmp_path):
    clock = Clock(NOW0 + 1_000)
    api = FakeApi(clock)
    api.premium = {k: v for k, v in api.premium.items() if k != "markPrice"}
    code, _ = run(tmp_path, api, clock, max_cycles=1)
    assert code == 0
    assert "SchemaError" in rec.errors_log_path(tmp_path).read_text(encoding="utf-8")
    assert not rec.snapshot_path(tmp_path).exists()  # nothing partial written
    assert len(read_rows(OI.csv_path(tmp_path))) >= 1


def test_ctrl_c_exits_cleanly_with_no_partial_lines(tmp_path):
    clock = Clock(NOW0 + 1_000)
    api = FakeApi(clock)
    code, out = run(tmp_path, api, clock, max_cycles=None, on_wait=lambda n: n == 3)  # stop requested on 3rd wait
    assert code == 0 and "Stopped cleanly." in out
    for path in [rec.snapshot_path(tmp_path)] + [d.csv_path(tmp_path) for d in rec.DATASETS]:
        data = path.read_bytes()
        assert data.endswith(b"\n")
        assert all(len(r) == len(next(csv.reader([data.decode().splitlines()[0]]))) for r in csv.reader(data.decode().splitlines()))


# ---------------------------------------------------- crash safety and gaps ---

def write_oi_rows(path, stamps, fetched=1):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(OI.columns)
        for t in stamps:
            w.writerow(["TACUSDT", "1.5", "1.5", "1.5", t, fetched])


@pytest.mark.parametrize("tail", [b"TACUSDT,1.5,1.5,1.5,17950", b"TACUSDT", b"TACUSDT,1.5,1.5\r\n"])
def test_partial_last_line_repaired_then_no_duplicates_or_loss(tmp_path, tail):
    clock = Clock(NOW0 + 1_000)
    path = OI.csv_path(tmp_path)
    stamps = [NOW0 - 5 * P, NOW0 - 4 * P, NOW0 - 3 * P]
    write_oi_rows(path, stamps)
    with open(path, "ab") as f:
        f.write(tail)
    assert rec.last_saved_open_time(path, OI.columns, OI.ts_index) == stamps[-1]  # partial row ignored
    api = FakeApi(clock)
    rec.prepare_files(tmp_path, 300, clock, say=lambda m: None)
    rec.record_latest(tmp_path, OI, api, lambda s: None, clock)
    ts = [int(r["timestamp"]) for r in read_rows(path)]
    assert ts == sorted(set(ts))  # no duplicates
    assert ts[:3] == stamps  # nothing lost
    assert ts[-1] == NOW0
    assert path.read_bytes().count(b"\n") == len(ts) + 1  # header + rows, no fragments


def test_partial_snapshot_line_repaired(tmp_path):
    clock = Clock(NOW0 + 1_000)
    api = FakeApi(clock)
    rec.record_snapshot(tmp_path, api, lambda s: None, clock)
    path = rec.snapshot_path(tmp_path)
    with open(path, "ab") as f:
        f.write(b"123,456,1.0")  # crash mid-write
    clock.advance(60_000)
    rec.prepare_files(tmp_path, 60, clock, say=lambda m: None)
    rec.record_snapshot(tmp_path, api, lambda s: None, clock)
    rows = read_rows(path)
    assert len(rows) == 2 and all(len(r) == len(rec.SNAPSHOT_COLUMNS) for r in csv.reader(open(path, newline="")))


def test_gap_on_restart_is_logged_and_not_filled(tmp_path):
    clock = Clock(NOW0 + 1_000)
    path = OI.csv_path(tmp_path)
    old = [NOW0 - 12 * P, NOW0 - 11 * P]  # PC was off for about an hour
    write_oi_rows(path, old)
    said = []
    rec.prepare_files(tmp_path, 300, clock, say=said.append)
    assert any("GAP on restart" in m and "open_interest" in m for m in said)
    assert "GAP" in rec.errors_log_path(tmp_path).read_text(encoding="utf-8")
    assert [int(r["timestamp"]) for r in read_rows(path)] == old  # nothing fabricated


def test_gap_between_cycles_is_logged_not_filled(tmp_path):
    clock = Clock(NOW0 + 1_000)
    api = FakeApi(clock)
    rec.run_cycle(tmp_path, api, sleep=lambda s: None, clock=clock)
    clock.advance(10 * P)  # ten periods pass with no cycle
    rec.run_cycle(tmp_path, api, sleep=lambda s: None, clock=clock)
    assert "GAP" in rec.errors_log_path(tmp_path).read_text(encoding="utf-8")
    ts = [int(r["timestamp"]) for r in read_rows(OI.csv_path(tmp_path))]
    assert all(b - a != P for a, b in zip(ts, ts[1:])) is False  # contiguous pairs exist
    assert max(b - a for a, b in zip(ts, ts[1:])) > P  # and the hole is still a hole


def test_main_dispatch(tmp_path, monkeypatch):
    called = {}
    monkeypatch.setattr(rec, "backfill", lambda d: called.setdefault("bf", d) and {})
    assert rec.main(["backfill", "--data-dir", str(tmp_path)]) == 0
    assert called["bf"] == tmp_path
    monkeypatch.setattr(rec, "run_loop", lambda d, i, **kw: called.update(run=(d, i, kw["max_cycles"])) or 0)
    assert rec.main(["run", "--interval", "60", "--max-cycles", "2", "--data-dir", str(tmp_path)]) == 0
    assert called["run"] == (tmp_path, 60, 2)
