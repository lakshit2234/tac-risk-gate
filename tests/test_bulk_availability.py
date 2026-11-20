"""Tests for the data.binance.vision availability check (mocked HTTP, tiny synthetic data, no network)."""
import hashlib
import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from tacgate.data import bulk_availability as ba
from tacgate.data import binance_klines as bk

DAY = ba.DAY_MS
D0 = int(datetime(2026, 11, 10, tzinfo=timezone.utc).timestamp() * 1000)


def listing_xml(items, truncated=False, next_marker=""):
    body = "".join(
        f"<Contents><Key>{k}</Key><LastModified>{lm}</LastModified><ETag>x</ETag><Size>{sz}</Size></Contents>" for k, lm, sz in items
    )
    return (f'<?xml version="1.0" encoding="UTF-8"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>"
            + (f"<NextMarker>{next_marker}</NextMarker>" if next_marker else "") + body + "</ListBucketResult>").encode()


class Resp:
    def __init__(self, status=200, content=b"", headers=None):
        self.status_code, self.content, self.headers = status, content, headers or {}


class FakeSession:
    """Routes by URL; a list of responses is consumed in order (the last one repeats)."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        key = url if url != ba.LIST_URL else (url, (params or {}).get("prefix"), (params or {}).get("marker", ""))
        r = self.routes[key] if key in self.routes else self.routes.get(url, Resp(404))
        if isinstance(r, list):
            return r.pop(0) if len(r) > 1 else r[0]
        return r


def zip_bytes(name, text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, text)
    return buf.getvalue()


# ------------------------------------------------------------- listing ---

KEY = "data/futures/um/daily/metrics/TACUSDT/TACUSDT-metrics-2026-11-10.zip"


def test_parse_listing_reads_entries_and_flags():
    xml = listing_xml([(KEY, "2026-11-11T06:57:01.000Z", 11189), (KEY + ".CHECKSUM", "2026-11-11T06:57:01.000Z", 92)], True, KEY)
    entries, truncated, nxt = ba.parse_listing(xml)
    assert [e.key for e in entries] == [KEY, KEY + ".CHECKSUM"] and entries[0].size == 11189
    assert entries[0].last_modified == datetime(2026, 11, 11, 6, 57, 1, tzinfo=timezone.utc)
    assert truncated and nxt == KEY


def test_list_prefix_follows_pagination_and_pauses():
    p1 = listing_xml([(KEY, "2026-11-11T06:57:01.000Z", 1)], True, KEY)
    key2 = KEY.replace("11-10", "11-11")
    p2 = listing_xml([(key2, "2026-11-12T06:00:00.000Z", 2)])
    prefix = "data/futures/um/daily/metrics/TACUSDT/"
    s = FakeSession({(ba.LIST_URL, prefix, ""): Resp(200, p1), (ba.LIST_URL, prefix, KEY): Resp(200, p2)})
    sleeps = []
    out = ba.list_prefix(s, prefix, sleeps.append)
    assert [e.key for e in out] == [KEY, key2] and len(s.calls) == 2
    assert s.calls[0][1]["delimiter"] == "/" and s.calls[1][1]["marker"] == KEY
    assert sleeps == [ba.PAUSE_S]


def test_dataset_prefixes():
    assert ba.TYPES[0].prefix("daily") == "data/futures/um/daily/klines/TACUSDT/1m/"
    assert ba.DatasetType("metrics").prefix("monthly") == "data/futures/um/monthly/metrics/TACUSDT/"
    assert {t.name for t in ba.TYPES} == {"klines", "metrics", "bookDepth", "markPriceKlines", "indexPriceKlines", "premiumIndexKlines",
                                          "fundingRate", "aggTrades", "trades", "bookTicker", "liquidationSnapshot"}


def test_file_period_and_period_end():
    assert ba.file_period("x/TACUSDT-1m-2026-11-10.zip", "daily") == "2026-11-10"
    assert ba.file_period("x/TACUSDT-1m-2026-11-10.zip.CHECKSUM", "daily") is None
    assert ba.file_period("x/TACUSDT-fundingRate-2026-10.zip", "monthly") == "2026-10"
    assert ba.file_period("x/TACUSDT-1m-2026-11-10.zip", "monthly") is None  # a daily name is not a monthly file
    assert ba.period_end("2026-11-10") == datetime(2026, 11, 11, tzinfo=timezone.utc)
    assert ba.period_end("2026-12") == datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert ba.period_end("2026-02") == datetime(2026, 3, 1, tzinfo=timezone.utc)


def mk(period, lm, size=10, area="daily", suffix=""):
    return ba.Entry(f"data/x/TACUSDT-x-{period}.zip{suffix}", datetime.fromisoformat(lm).replace(tzinfo=timezone.utc), size)


def test_summarize_counts_and_ignores_checksum_files():
    ents = [mk("2026-11-10", "2026-11-11T08:00:00"), mk("2026-11-10", "2026-11-11T08:00:00", suffix=".CHECKSUM"), mk("2026-11-09", "2026-11-10T08:00:00")]
    s = ba.summarize(ents, "daily")
    assert (s.files, s.first, s.last, s.checksums, s.exists) == (2, "2026-11-09", "2026-11-10", 1, True)
    assert not ba.summarize([], "daily").exists


def test_lag_hours_and_stats():
    ents = [mk("2026-11-08", "2026-11-09T06:00:00"), mk("2026-11-09", "2026-11-10T08:00:00"), mk("2026-11-10", "2026-11-11T10:00:00")]
    lags = ba.lag_hours(ents, "daily")
    assert lags == {"2026-11-08": 6.0, "2026-11-09": 8.0, "2026-11-10": 10.0}
    st = ba.lag_stats(lags)
    assert st["latest_period"] == "2026-11-10" and st["latest"] == 10.0 and st["min"] == 6.0 and st["max"] == 10.0
    assert st["median"] == 8.0 and st["max_last90"] == 10.0 and st["n"] == 3
    assert ba.lag_stats({}) is None


def test_choose_sample():
    daily = [mk("2026-11-09", "2026-11-10T08:00:00"), mk("2026-11-10", "2026-11-11T08:00:00"), mk("2026-11-12", "2026-11-13T08:00:00")]
    assert ba.choose_sample(daily, [], "2026-11-10")[2] == "2026-11-10"  # preferred day when listed
    assert ba.choose_sample(daily, [], "2026-11-11")[2] == "2026-11-12"  # else the latest
    monthly = [mk("2026-09", "2026-10-10T00:00:00"), mk("2026-10", "2026-11-10T00:00:00")]
    area, entry, period = ba.choose_sample([], monthly, "2026-11-10")
    assert (area, period) == ("monthly", "2026-10")
    assert ba.choose_sample([], [], "2026-11-10") is None


# ----------------------------------------------------------------- HTTP ---

def test_http_get_ok_and_404():
    assert ba.http_get(FakeSession({"u": Resp(200, b"abc")}), "u") == b"abc"
    assert ba.http_get(FakeSession({"u": Resp(404)}), "u") is None


@pytest.mark.parametrize("code", [403, 418])
def test_refusal_stops_at_once_without_retry(code):
    s = FakeSession({"u": Resp(code)})
    with pytest.raises(ba.Refused, match=str(code)):
        ba.http_get(s, "u", sleep=lambda x: None)
    assert len(s.calls) == 1


def test_429_is_retried_honoring_retry_after_then_refused():
    s = FakeSession({"u": Resp(429, headers={"Retry-After": "30"})})
    sleeps = []
    with pytest.raises(ba.Refused, match="429"):
        ba.http_get(s, "u", sleep=sleeps.append)
    assert len(s.calls) == ba.MAX_RETRIES + 1 and sleeps[0] == 30


def test_5xx_retried_then_recovers_or_raises():
    s = FakeSession({"u": [Resp(503), Resp(200, b"ok")]})
    assert ba.http_get(s, "u", sleep=lambda x: None) == b"ok"
    with pytest.raises(RuntimeError, match="503"):
        ba.http_get(FakeSession({"u": Resp(503)}), "u", sleep=lambda x: None)


def test_survey_stops_at_the_first_refusal_and_run_reports_it(tmp_path):
    first = listing_xml([("data/futures/um/daily/klines/TACUSDT/1m/TACUSDT-1m-2026-11-10.zip", "2026-11-11T08:00:00.000Z", 5)])
    routes = {(ba.LIST_URL, ba.TYPES[0].prefix("daily"), ""): Resp(200, first),
              (ba.LIST_URL, ba.TYPES[0].prefix("monthly"), ""): Resp(403)}
    s = FakeSession(routes)
    res = ba.run(s, tmp_path / "out", tmp_path, "2026-11-10", sleep=lambda x: None)
    assert "403" in res.stopped and "stopping here" in res.stopped
    assert len(s.calls) == 2  # nothing was requested after the refusal
    assert res.samples == {}
    text = ba.render_report(res)
    assert "The run stopped early" in text and "not listed (run stopped)" in text


# --------------------------------------------------------------- samples ---

def sample_routes(csv_text, checksum_text, key=KEY, zname="TACUSDT-metrics-2026-11-10.csv"):
    z = zip_bytes(zname, csv_text)
    return z, {f"{ba.DOWNLOAD_URL}/{key}": Resp(200, z), f"{ba.DOWNLOAD_URL}/{key}.CHECKSUM": Resp(200, checksum_text.encode())}


def entry_for(z):
    return ba.Entry(KEY, datetime(2026, 11, 11, 7, tzinfo=timezone.utc), len(z))


def test_download_sample_verifies_checksum_and_extracts(tmp_path):
    z, routes = sample_routes("a,b\n1,2\n", "")
    routes[f"{ba.DOWNLOAD_URL}/{KEY}.CHECKSUM"] = Resp(200, f"{hashlib.sha256(z).hexdigest()}  TACUSDT-metrics-2026-11-10.zip\n".encode())
    sleeps = []
    smp = ba.download_sample(FakeSession(routes), "metrics", "daily", "2026-11-10", entry_for(z), True, tmp_path, sleeps.append)
    assert smp.checksum == "verified" and smp.csv_path.read_text() == "a,b\n1,2\n"
    assert smp.zip_path.parent.name == "metrics"  # one folder per type
    assert sleeps  # paused between requests


def test_download_sample_detects_a_checksum_mismatch_and_unreadable_and_unpublished(tmp_path):
    z, routes = sample_routes("a,b\n1,2\n", "0" * 64 + "  f.zip\n")
    assert ba.download_sample(FakeSession(routes), "metrics", "daily", "2026-11-10", entry_for(z), True, tmp_path / "1", lambda x: None).checksum == "MISMATCH"
    z, routes = sample_routes("a,b\n1,2\n", "garbage")
    assert ba.download_sample(FakeSession(routes), "metrics", "daily", "2026-11-10", entry_for(z), True, tmp_path / "2", lambda x: None).checksum == "unreadable"
    z, routes = sample_routes("a,b\n1,2\n", "")
    assert ba.download_sample(FakeSession(routes), "metrics", "daily", "2026-11-10", entry_for(z), False, tmp_path / "3", lambda x: None).checksum == "not published"


def test_download_sample_skips_huge_files_and_missing_ones(tmp_path):
    big = ba.Entry(KEY, datetime(2026, 11, 11, tzinfo=timezone.utc), ba.MAX_SAMPLE_BYTES + 1)
    s = FakeSession({})
    smp = ba.download_sample(s, "metrics", "daily", "2026-11-10", big, True, tmp_path, lambda x: None)
    assert "over the" in smp.skipped and s.calls == []
    small = ba.Entry(KEY, datetime(2026, 11, 11, tzinfo=timezone.utc), 10)
    smp = ba.download_sample(FakeSession({}), "metrics", "daily", "2026-11-10", small, True, tmp_path, lambda x: None)
    assert "404" in smp.skipped


def test_existing_sample_zip_is_reused_not_downloaded_again(tmp_path):
    z, routes = sample_routes("a,b\n1,2\n", "")
    routes[f"{ba.DOWNLOAD_URL}/{KEY}.CHECKSUM"] = Resp(200, f"{hashlib.sha256(z).hexdigest()}  f\n".encode())
    folder = tmp_path / "metrics"
    folder.mkdir()
    (folder / "TACUSDT-metrics-2026-11-10.zip").write_bytes(z)
    s = FakeSession(routes)
    smp = ba.download_sample(s, "metrics", "daily", "2026-11-10", entry_for(z), True, tmp_path, lambda x: None)
    assert smp.checksum == "verified"
    assert [c[0] for c in s.calls] == [f"{ba.DOWNLOAD_URL}/{KEY}.CHECKSUM"]  # only the tiny checksum file was requested


def test_parse_checksum():
    h = "ab" * 32
    assert ba.parse_checksum(f"{h}  file.zip\n") == h
    assert ba.parse_checksum("nonsense") == "" and ba.parse_checksum("") == ""


# -------------------------------------------------------------- formats ---

def test_classify_time():
    assert ba.classify_time("1794268800000").startswith("epoch milliseconds")
    assert ba.classify_time("1794268800000000").startswith("epoch microseconds")
    assert ba.classify_time("2026-11-10 02:40:00").startswith("datetime text")
    assert ba.classify_time("abc") == "other"


def test_describe_csv_header_time_column_and_order(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text("create_time,symbol,v\n2026-11-10 02:40:00,T,1\n2026-11-10 00:05:00,T,2\n2026-11-10 00:10:00,T,3\n2026-11-10 00:10:00,T,4\n")
    d = ba.describe_csv(p)
    assert d["header"] == ["create_time", "symbol", "v"] and d["rows"] == 4 and d["time_column"] == "create_time"
    assert d["time_format"].startswith("datetime text") and d["in_time_order"] is False and d["unique_times"] == 3
    assert len(d["first"]) == 3
    p2 = tmp_path / "k.csv"
    p2.write_text("1794268800000,0.1,0.2\n1794268860000,0.1,0.2\n")  # no header row
    d2 = ba.describe_csv(p2)
    assert d2["header"] is None and d2["rows"] == 2 and d2["in_time_order"] is True and d2["time_format"].startswith("epoch milliseconds")


def test_describe_csv_uses_the_time_column_by_name(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("id,price,time\n5,0.1,1794268800097\n6,0.1,1794268800099\n")
    d = ba.describe_csv(p)
    assert d["time_column"] == "time" and d["time_format"].startswith("epoch milliseconds")


def test_book_depth_facts(tmp_path):
    p = tmp_path / "b.csv"
    p.write_text("timestamp,percentage,depth,notional\n"
                 "2026-11-10 00:00:01,-1.00,5,1\n2026-11-10 00:00:01,1.00,6,2\n"
                 "2026-11-10 00:00:31,-1.00,5,1\n2026-11-10 00:00:31,1.00,6,2\n")
    f = ba.book_depth_facts(p)
    assert f["levels"] == [-1.0, 1.0] and f["snapshots"] == 2 and f["median_gap_s"] == 30.0


# ------------------------------------------------------------- overlaps ---

def kline_frame(rows):
    return pd.DataFrame([[str(x) for x in r] for r in rows], columns=bk.COLUMNS)


def kl(t, o=0.1, c=0.1, v=100):
    return [t, o, o, o, c, v, t + 59_999, 1, 5, 1, 1, 0]


def test_compare_klines_counts_differing_rows_and_columns():
    ours = kline_frame([kl(D0), kl(D0 + 60_000), kl(D0 + 120_000), kl(D0 + DAY)])  # the last row is another day
    bulk = kline_frame([kl(D0), kl(D0 + 60_000, c=0.2), kl(D0 + 180_000)])
    r = ba.compare_klines(bulk, ours, "2026-11-10")
    assert r["bulk_rows"] == 3 and r["our_rows"] == 3 and r["common"] == 2
    assert r["only_bulk"] == 1 and r["only_ours"] == 1 and r["differing_rows"] == 1
    assert r["differing_columns"] == {"close": 1} and r["examples"][0][0] == D0 + 60_000
    same = ba.compare_klines(kline_frame([kl(D0)]), kline_frame([kl(D0)]), "2026-11-10")
    assert same["differing_rows"] == 0 and same["differing_columns"] == {}


def test_to_ms_handles_text_and_numbers():
    assert list(ba.to_ms(pd.Series(["2026-11-10 00:05:00"]))) == [D0 + 300_000]
    assert list(ba.to_ms(pd.Series(["1794268800000"]))) == [1794268800000]


def metrics_frames(n=40, shift_ms=300_000):
    """Bulk rows at D0 + i*5min; our OI rows at the same instants + shift_ms with the same value; our ratio rounded."""
    times = [D0 + i * 300_000 for i in range(n)]
    bulk = pd.DataFrame({
        "create_time": [datetime.fromtimestamp(t / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") for t in times],
        "symbol": "TACUSDT",
        "sum_open_interest": [str(1000.0 + 7 * i) for i in range(n)],
        "mystery": [str(5.0 + (i % 3) * 0.37) for i in range(n)],
    })
    oi = pd.DataFrame({"symbol": "TACUSDT", "sumOpenInterest": [str(1000.0 + 7 * i) for i in range(n)],
                       "timestamp": [str(t + shift_ms) for t in times], "fetched_at_ms": "1"})
    other = pd.DataFrame({"longShortRatio": [str(100 + i * 11) for i in range(n)], "timestamp": [str(t + shift_ms) for t in times]})
    return bulk, {"open_interest": oi, "global_long_short": other}


def test_match_metrics_finds_the_column_and_the_time_shift():
    bulk, ours = metrics_frames()
    res = {r["bulk_column"]: r for r in ba.match_metrics(bulk, ours, "2026-11-10")}
    oi = res["sum_open_interest"]
    assert oi["ours"] == "open_interest.sumOpenInterest" and oi["shift_min"] == 5 and oi["close"] == 1.0 and oi["exact"] == 1.0
    assert oi["rows"] == 40 and oi["max_rel"] == 0.0
    assert "symbol" not in res  # text columns are skipped
    assert res["mystery"]["close"] < 0.5  # no counterpart: reported as a poor match, not forced


def test_match_metrics_zero_shift_and_rounding_is_close_not_exact():
    bulk, ours = metrics_frames(shift_ms=0)
    bulk["ratio"] = [str(1.23456789 + i) for i in range(len(bulk))]
    ours["global_long_short"]["longShortRatio"] = [f"{1.23456789 + i:.4f}" for i in range(len(bulk))]
    res = {r["bulk_column"]: r for r in ba.match_metrics(bulk, ours, "2026-11-10")}
    assert res["sum_open_interest"]["shift_min"] == 0
    r = res["ratio"]
    assert r["ours"] == "global_long_short.longShortRatio" and r["close"] == 1.0 and r["exact"] == 0.0 and 0 < r["max_rel"] < 1e-3


# --------------------------------------------------------------- report ---

def test_proposed_rules_daily_monthly_and_outliers():
    calm = ba.lag_stats({"2026-11-08": 6.0, "2026-11-09": 8.0, "2026-11-10": 10.0})
    assert "plus 24 h" in ba.proposed_rule("metrics", "daily", calm) and "2x margin" in ba.proposed_rule("metrics", "daily", calm)
    odd = ba.lag_stats({"2026-11-08": 6.0, "2026-11-09": 300.0, "2026-11-10": 8.0})
    assert "LastModified" in ba.proposed_rule("klines", "daily", odd)
    mon = ba.lag_stats({"2026-09": 100.0, "2026-10": 250.0}, )
    rule = ba.proposed_rule("trades", "monthly", mon)
    assert "plus 11 days" in rule  # 250 h rounded up to whole days
    assert ba.proposed_rule("x", "daily", None).startswith("no files")


def test_gate1_lines_say_what_the_listing_shows_and_nothing_more():
    res = ba.Result()
    res.listings = {(t.name, a): [] for t in ba.TYPES for a in ba.AREAS}
    res.listings[("metrics", "daily")] = [mk(f"2026-11-{d:02d}", f"2026-11-{d + 1:02d}T08:00:00") for d in range(1, 10)]
    lines = " ".join(ba.gate1_lines(res))
    assert "9 files" in lines and "instead of 32" in lines and "liquidationSnapshot" in lines and "does not exist in this archive" in lines
    res.listings[("metrics", "daily")] = []
    assert "gain no extra history" in " ".join(ba.gate1_lines(res))


# ------------------------------------------------------------------- CLI ---

def test_main_refuses_report_inside_data_dir(tmp_path, capsys):
    (tmp_path / bk.DEFAULT_OUT.name).write_text("x\n")
    assert ba.main(["--data-dir", str(tmp_path), "--report", str(tmp_path / "r.md"), "--out-dir", str(tmp_path / "o")]) == 2
    assert "Refusing" in capsys.readouterr().out
    assert not (tmp_path / "r.md").exists()


def test_main_needs_our_klines_file(tmp_path, capsys):
    assert ba.main(["--data-dir", str(tmp_path), "--report", str(tmp_path.parent / "r.md")]) == 2
    assert "not found" in capsys.readouterr().out


def test_default_sample_folder_is_under_data_raw():
    assert str(ba.DEFAULT_OUT_DIR).replace("\\", "/") == "data/raw/bulk_sample"


def test_report_ends_with_the_open_items_and_says_no_feature_was_built():
    text = ba.render_report(ba.Result())
    assert "## 7. Open items" in text and "one day only" in text and "provisional" in text
    assert "bookDepth bands differ from our snapshot bands" in text and "No feature was built" in text
    assert text.rstrip().endswith("No feature was built from any of this data.")
