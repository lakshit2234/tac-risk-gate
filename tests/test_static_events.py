"""Tests for the static events/tokenomics loader and validator (tiny synthetic files, no network)."""
import csv
import socket
from pathlib import Path

import pytest

from tacgate.data import static_events as se

EV_COLS = se.EVENT_COLUMNS
TK_COLS = se.TOKENOMICS_COLUMNS
DAY = se.DAY_MS


def event(**kw):
    base = {"event_date_utc": "2026-01-10T00:00:00Z", "event_type": "other", "description": "something happened",
            "known_at_utc": "2026-01-10T12:00:00Z", "cause_status": "unverified", "source_url": "",
            "price_evidence": "", "notes": ""}
    base.update(kw)
    return base


def tok(**kw):
    base = {"category": "team", "percent_of_supply": "20", "vesting_terms": "locked 1 year from TGE",
            "source_url": "https://example.com/t", "retrieved_at_utc": "2026-11-20", "status": "sourced"}
    base.update(kw)
    return base


def write(path, columns, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def errs(rep, text):
    return any(text in m for m in rep.errors)


# ------------------------------------------------------------- parse_utc ---

def test_parse_utc_accepts_date_and_explicit_utc_datetimes():
    assert se.parse_utc("2026-01-10") == se.parse_utc("2026-01-10T00:00:00Z") == se.parse_utc("2026-01-10T00:00:00+00:00")
    assert se.parse_utc("2026-01-10T12:30:00Z") - se.parse_utc("2026-01-10") == 12.5 * 3_600_000
    assert se.iso_z(se.parse_utc("2026-01-10T12:30:00Z")) == "2026-01-10T12:30:00Z"


@pytest.mark.parametrize("bad", ["", "10/01/2026", "2026-01-10T12:00:00", "2026-01-10T12:00:00+02:00", "yesterday",
                                 "2026-13-40"])
def test_parse_utc_rejects(bad):
    with pytest.raises(ValueError):
        se.parse_utc(bad)


# --------------------------------------------------------------- loading ---

def test_missing_required_column_is_a_file_problem(tmp_path):
    p = tmp_path / "events.csv"
    write(p, EV_COLS[:-1], [])
    with pytest.raises(se.FileProblem, match="notes"):
        se.load_rows(p, EV_COLS)


def test_missing_file_is_a_file_problem(tmp_path):
    with pytest.raises(se.FileProblem):
        se.load_rows(tmp_path / "nope.csv", EV_COLS)


def test_load_rows_strips_and_never_writes(tmp_path):
    p = tmp_path / "events.csv"
    write(p, EV_COLS, [event(description="  padded  ")])
    before = p.read_bytes()
    assert se.load_rows(p, EV_COLS)[0]["description"] == "padded"
    assert p.read_bytes() == before


# ---------------------------------------------------------------- events ---

def test_valid_events_pass_and_count_sources():
    rep = se.validate_events([
        event(),
        event(event_date_utc="2026-02-01T00:00:00Z", known_at_utc="2026-02-01T01:00:00Z", description="b",
              cause_status="sourced", source_url="https://example.com/a"),
    ])
    assert rep.ok and rep.sourced == 1 and rep.unverified == 1 and rep.flagged == [] and rep.warnings == []


def test_bad_event_date_is_an_error():
    assert errs(se.validate_events([event(event_date_utc="2026-01-10T12:00:00")]), "event_date_utc does not parse as UTC")
    assert errs(se.validate_events([event(event_date_utc="soon")]), "event_date_utc does not parse as UTC")


def test_bad_known_at_is_an_error():
    assert errs(se.validate_events([event(known_at_utc="2026-01-10 12:00")]), "known_at_utc does not parse as UTC")


def test_event_type_must_be_allowed():
    assert errs(se.validate_events([event(event_type="hack")]), "event_type")
    for t in se.EVENT_TYPES:
        row = event(event_type=t, price_evidence="numbers 1.0" if t in se.DATA_DERIVED_TYPES else "")
        assert se.validate_events([row]).ok, t


def test_cause_status_must_be_sourced_or_unverified():
    assert errs(se.validate_events([event(cause_status="probably")]), "cause_status")


def test_sourced_row_needs_a_source_url():
    assert errs(se.validate_events([event(cause_status="sourced")]), "sourced row must have a source_url")
    assert se.validate_events([event(cause_status="sourced", source_url="https://a.example/x https://b.example/y")]).ok


def test_source_url_must_be_http():
    assert errs(se.validate_events([event(cause_status="sourced", source_url="see the blog")]), "http(s) URLs")


def test_empty_known_at_is_flagged_not_an_error_for_sourced_events():
    rep = se.validate_events([event(known_at_utc="", cause_status="sourced", source_url="https://example.com/a")])
    assert rep.ok and len(rep.flagged) == 1 and "2026-01-10" in rep.flagged[0]


def test_empty_known_at_on_a_data_derived_row_is_an_error():
    rep = se.validate_events([event(event_type="price_crash", known_at_utc="", price_evidence="open 1 low 0.5")])
    assert errs(rep, "must have known_at_utc") and len(rep.flagged) == 1


def test_data_derived_rows_need_price_evidence():
    for t in se.DATA_DERIVED_TYPES:
        assert errs(se.validate_events([event(event_type=t)]), "needs price_evidence"), t


def test_known_at_before_event_date_needs_an_explanation():
    early = event(known_at_utc="2026-01-09T00:00:00Z")
    assert errs(se.validate_events([early]), "before event_date_utc and notes do not explain it")
    rep = se.validate_events([event(known_at_utc="2026-01-09T00:00:00Z", notes="announced a day ahead by the source")])
    assert rep.ok and any("explained in notes" in w for w in rep.warnings)
    assert se.validate_events([event(known_at_utc="2026-01-10T00:00:00Z")]).ok  # equal is fine (minus 0)


def test_duplicate_rows_are_an_error():
    assert errs(se.validate_events([event(), event()]), "duplicate")


def test_empty_description_is_an_error():
    assert errs(se.validate_events([event(description="")]), "empty description")


# ------------------------------------------------------------ known_events ---

def test_known_events_never_returns_empty_or_future_known_at():
    rows = [event(description="a", known_at_utc="2026-01-10T12:00:00Z"),
            event(description="b", known_at_utc=""),
            event(description="c", known_at_utc="2026-03-01T00:00:00Z"),
            event(description="d", known_at_utc="2026-01-10T12:00:00Z", event_date_utc="2025-12-01T00:00:00Z")]
    got = se.known_events(rows, se.parse_utc("2026-02-01T00:00:00Z"))
    assert [r["description"] for r in got] == ["a", "d"]
    assert se.known_events(rows, se.parse_utc("2026-01-10T11:59:59Z")) == []  # before known_at, even though the event date passed
    assert [r["description"] for r in se.known_events(rows, se.parse_utc("2026-12-31"))] == ["a", "c", "d"]


# ------------------------------------------------------------ tokenomics ---

def test_percent_sum_is_reported_not_forced():
    rep = se.validate_tokenomics([tok(category="a", percent_of_supply="40"), tok(category="b", percent_of_supply="19.5"),
                                  tok(category="c", percent_of_supply="")])
    assert rep.ok and rep.percent_sum == 59.5 and rep.percent_rows == 2
    assert se.validate_tokenomics([tok(percent_of_supply="")]).percent_sum is None


def test_tokenomics_percent_checks():
    assert errs(se.validate_tokenomics([tok(percent_of_supply="a lot")]), "not a number")
    assert errs(se.validate_tokenomics([tok(percent_of_supply="120")]), "outside 0 to 100")
    assert errs(se.validate_tokenomics([tok(percent_of_supply="-1")]), "outside 0 to 100")


def test_tokenomics_status_source_and_terms_checks():
    assert errs(se.validate_tokenomics([tok(status="maybe")]), "status")
    assert errs(se.validate_tokenomics([tok(source_url="")]), "sourced row must have a source_url")
    assert se.validate_tokenomics([tok(source_url="", status="unverified")]).ok
    assert errs(se.validate_tokenomics([tok(vesting_terms="")]), "empty vesting_terms")
    assert errs(se.validate_tokenomics([tok(retrieved_at_utc="last week")]), "retrieved_at_utc")
    assert errs(se.validate_tokenomics([tok(category="")]), "empty category")


def test_tokenomics_counts_sourced_and_unverified():
    rep = se.validate_tokenomics([tok(), tok(category="x", status="unverified", source_url="")])
    assert (rep.sourced, rep.unverified) == (1, 1)


# --------------------------------------------------------- supply steps ---

def cg_file(tmp_path, supplies, price=0.001):
    p = tmp_path / "cg.csv"
    t0 = 1_790_000_000_000 // DAY * DAY
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(se.cgm.COLUMNS)
        for i, s in enumerate(supplies):
            w.writerow([t0 + i * DAY, price, price * s, 1.0, t0 + (i + 1) * DAY + 1000])
    return p, t0


def test_persistent_supply_step_is_found_with_known_at_plus_24h(tmp_path):
    p, t0 = cg_file(tmp_path, [1e9] * 6 + [1.05e9] * 6)
    steps = se.supply_steps(p)
    assert len(steps) == 1
    s = steps[0]
    assert s["timestamp_ms"] == t0 + 6 * DAY and s["known_at_ms"] == t0 + 7 * DAY
    assert s["change"] == pytest.approx(0.05) and s["tokens"] == pytest.approx(5e7) and s["baseline"] == pytest.approx(1e9)


def test_one_day_spike_and_reversal_is_not_a_step(tmp_path):
    p, _ = cg_file(tmp_path, [1e9] * 6 + [1.08e9] + [1e9] * 6)
    assert se.supply_steps(p) == []


def test_step_without_three_days_of_data_is_not_returned(tmp_path):
    p, _ = cg_file(tmp_path, [1e9] * 6 + [1.05e9] * 2)  # only 2 days at the new level so far
    assert se.supply_steps(p) == []
    p2, _ = cg_file(tmp_path, [1e9] * 6 + [1.05e9] * 3)
    assert len(se.supply_steps(p2)) == 1


def test_small_changes_and_drops(tmp_path):
    p, _ = cg_file(tmp_path, [1e9, 1.005e9, 1.01e9, 1.015e9, 1.02e9, 1.025e9, 1.03e9, 1.035e9])  # 0.5%/day: never > 1%
    assert se.supply_steps(p) == []
    p2, t0 = cg_file(tmp_path, [1e9] * 5 + [0.9e9] * 5)
    s = se.supply_steps(p2)
    assert len(s) == 1 and s[0]["change"] == pytest.approx(-0.1)


def test_supply_steps_never_modifies_the_file(tmp_path):
    p, _ = cg_file(tmp_path, [1e9] * 6 + [1.05e9] * 6)
    before = p.read_bytes()
    se.supply_steps(p)
    assert p.read_bytes() == before


# -------------------------------------------------------------- CLI / safety ---

def good_dir(tmp_path):
    d = tmp_path / "static"
    d.mkdir()
    write(d / se.EVENTS_NAME, EV_COLS, [event(known_at_utc="")])
    write(d / se.TOKENOMICS_NAME, TK_COLS, [tok(category="a", percent_of_supply="60")])
    return d


def test_validator_does_not_touch_the_network(tmp_path, monkeypatch):
    d = good_dir(tmp_path)

    def no_network(*a, **k):
        raise AssertionError("the validator tried to open a socket")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    ev, tk = se.check_dir(d)
    assert ev.ok and tk.ok


def test_main_exit_codes_and_output(tmp_path, capsys):
    d = good_dir(tmp_path)
    assert se.main(["--dir", str(d)]) == 0
    out = capsys.readouterr().out
    assert "sum to 60 (reported, not forced to 100)" in out and "EMPTY known_at_utc (1" in out
    write(d / se.EVENTS_NAME, EV_COLS, [event(event_type="hack")])
    assert se.main(["--dir", str(d)]) == 1
    (d / se.TOKENOMICS_NAME).unlink()
    assert se.main(["--dir", str(d)]) == 2
    assert se.main(["--dir", str(tmp_path / "nope")]) == 2


def test_committed_static_files_validate():
    repo = Path(__file__).resolve().parent.parent / "data" / "static"
    ev, tk = se.check_dir(repo)
    assert ev.ok and tk.ok, ev.errors + tk.errors
    assert ev.rows > 0 and tk.rows > 0
    # every sourced row has a URL, every flagged event is a sourced (non data-derived) row
    for line in ev.flagged:
        assert not any(t in line for t in se.DATA_DERIVED_TYPES)
