"""Loader and validator for the hand-written Phase 0 static files in data/static/.

  data/static/tokenomics.csv  category, percent_of_supply, vesting_terms, source_url, retrieved_at_utc, status
  data/static/events.csv      event_date_utc, event_type, description, known_at_utc, cause_status, source_url,
                              price_evidence, notes

Rules these files follow (see docs/phase0_sources.md): only what a fetched page or our own data shows; a fact
with no source is left empty and marked "unverified"; unlock timing that cannot be sourced is "unknown".

The validator reads local files only (no network). It does NOT change any file.

known_at_utc is when an event became public. Features must only use an event from known_at_utc on. A row with an
EMPTY known_at_utc is flagged and `known_events()` never returns it, so features cannot use it by accident.

Run: python -m tacgate.data.static_events [--dir data/static]
Exit code: 0 = valid (flags and warnings allowed), 1 = validation errors, 2 = file problem.
"""
from __future__ import annotations

import argparse
import csv
import io
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tacgate.data import coingecko_market_chart as cgm

DEFAULT_DIR = Path("data/static")
EVENTS_NAME = "events.csv"
TOKENOMICS_NAME = "tokenomics.csv"

EVENT_COLUMNS = ["event_date_utc", "event_type", "description", "known_at_utc", "cause_status", "source_url",
                 "price_evidence", "notes"]
TOKENOMICS_COLUMNS = ["category", "percent_of_supply", "vesting_terms", "source_url", "retrieved_at_utc", "status"]
EVENT_TYPES = ("price_crash", "price_spike", "exploit", "unlock", "listing", "market_wide", "supply_step", "other")
STATUSES = ("sourced", "unverified")
# Derived from our own price/supply data: they must carry numeric evidence and a known_at (end of the data window).
DATA_DERIVED_TYPES = ("price_crash", "price_spike", "supply_step")

DAY_MS = 86_400_000


class FileProblem(Exception):
    """A file is missing, unreadable or has the wrong header (exit code 2)."""


def parse_utc(text: str) -> int:
    """Parse 'YYYY-MM-DD' or an ISO datetime that is explicitly UTC ('Z' or '+00:00') to epoch ms.

    A datetime without an explicit UTC marker is rejected: the files must never depend on a local time zone."""
    t = text.strip()
    if not t:
        raise ValueError("empty date")
    if len(t) == 10:
        dt = datetime.strptime(t, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        if not (t.endswith("Z") or t.endswith("+00:00")):
            raise ValueError(f"{text!r} is not explicitly UTC (needs a trailing Z or +00:00)")
        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)


def iso_z(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------- loading ---

def load_rows(path: Path, columns: list[str]) -> list[dict]:
    """Read a static CSV once (read-only). The header must contain every required column."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FileProblem(f"Cannot read {path}: {exc}") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = reader.fieldnames or []
    missing = [c for c in columns if c not in header]
    if missing:
        raise FileProblem(f"{path}: missing required column(s) {missing}; found {header}")
    rows = []
    for r in reader:
        if None in r:  # more cells than header columns
            raise FileProblem(f"{path}: a row has more cells than the header")
        rows.append({k: (v or "").strip() for k, v in r.items()})
    return rows


@dataclass
class Report:
    name: str
    rows: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    flagged: list[str] = field(default_factory=list)  # events with an empty known_at_utc: not usable by features
    sourced: int = 0
    unverified: int = 0
    percent_sum: float | None = None
    percent_rows: int = 0
    extra_columns: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _urls_ok(value: str) -> bool:
    parts = value.split()
    return bool(parts) and all(p.startswith(("http://", "https://")) for p in parts)


# -------------------------------------------------------------- validation ---

def validate_events(rows: list[dict]) -> Report:
    rep = Report("events", rows=len(rows))
    seen = set()
    for i, r in enumerate(rows, start=2):  # line number in the file (header is line 1)
        where = f"events.csv line {i}"
        desc = r.get("description", "")
        if not desc:
            rep.errors.append(f"{where}: empty description")
        key = (r.get("event_date_utc"), r.get("event_type"), desc)
        if key in seen:
            rep.errors.append(f"{where}: duplicate of an earlier row")
        seen.add(key)

        try:
            ev = parse_utc(r["event_date_utc"])
        except (ValueError, KeyError) as exc:
            ev = None
            rep.errors.append(f"{where}: event_date_utc does not parse as UTC ({exc})")
        if r["event_type"] not in EVENT_TYPES:
            rep.errors.append(f"{where}: event_type {r['event_type']!r} is not one of {list(EVENT_TYPES)}")
        status = r["cause_status"]
        if status not in STATUSES:
            rep.errors.append(f"{where}: cause_status {status!r} must be 'sourced' or 'unverified'")
        elif status == "sourced":
            rep.sourced += 1
        else:
            rep.unverified += 1
        if status == "sourced" and not r["source_url"]:
            rep.errors.append(f"{where}: a sourced row must have a source_url")
        if r["source_url"] and not _urls_ok(r["source_url"]):
            rep.errors.append(f"{where}: source_url must be one or more http(s) URLs separated by spaces")

        known = r["known_at_utc"]
        if not known:
            rep.flagged.append(f"line {i}: {r['event_date_utc']} {r['event_type']}: {desc[:70]}")
            if r["event_type"] in DATA_DERIVED_TYPES:
                rep.errors.append(f"{where}: a {r['event_type']} row is derived from our data and must have known_at_utc "
                                  "(the end of the price window)")
        else:
            try:
                kn = parse_utc(known)
            except ValueError as exc:
                kn = None
                rep.errors.append(f"{where}: known_at_utc does not parse as UTC ({exc})")
            if kn is not None and ev is not None and kn < ev:
                # Never before the event itself, except when a source published earlier; that must be explained.
                if r["notes"]:
                    rep.warnings.append(f"{where}: known_at_utc is before event_date_utc (explained in notes)")
                else:
                    rep.errors.append(f"{where}: known_at_utc is before event_date_utc and notes do not explain it")
        if r["event_type"] in DATA_DERIVED_TYPES and not r["price_evidence"]:
            rep.errors.append(f"{where}: a {r['event_type']} row needs price_evidence (numbers from our files)")
    return rep


def validate_tokenomics(rows: list[dict]) -> Report:
    rep = Report("tokenomics", rows=len(rows))
    total, n = 0.0, 0
    for i, r in enumerate(rows, start=2):
        where = f"tokenomics.csv line {i}"
        if not r["category"]:
            rep.errors.append(f"{where}: empty category")
        if not r["vesting_terms"]:
            rep.errors.append(f"{where}: empty vesting_terms (write 'unknown' if it cannot be sourced)")
        status = r["status"]
        if status not in STATUSES:
            rep.errors.append(f"{where}: status {status!r} must be 'sourced' or 'unverified'")
        elif status == "sourced":
            rep.sourced += 1
        else:
            rep.unverified += 1
        if status == "sourced" and not r["source_url"]:
            rep.errors.append(f"{where}: a sourced row must have a source_url")
        if r["source_url"] and not _urls_ok(r["source_url"]):
            rep.errors.append(f"{where}: source_url must be one or more http(s) URLs separated by spaces")
        try:
            parse_utc(r["retrieved_at_utc"])
        except ValueError as exc:
            rep.errors.append(f"{where}: retrieved_at_utc does not parse as UTC ({exc})")
        if r["percent_of_supply"]:
            try:
                p = float(r["percent_of_supply"])
            except ValueError:
                rep.errors.append(f"{where}: percent_of_supply {r['percent_of_supply']!r} is not a number")
                continue
            if not 0 <= p <= 100:
                rep.errors.append(f"{where}: percent_of_supply {p} is outside 0 to 100")
            total += p
            n += 1
    rep.percent_rows = n
    rep.percent_sum = round(total, 6) if n else None  # reported, never forced to 100
    return rep


def check_dir(directory: Path) -> tuple[Report, Report]:
    directory = Path(directory)
    ev = validate_events(load_rows(directory / EVENTS_NAME, EVENT_COLUMNS))
    tk = validate_tokenomics(load_rows(directory / TOKENOMICS_NAME, TOKENOMICS_COLUMNS))
    return ev, tk


# ------------------------------------------------------------ use by features ---

def known_events(rows: list[dict], as_of_ms: int) -> list[dict]:
    """Events a feature may use at time as_of_ms: known_at_utc present and not after as_of_ms.

    Rows with an empty known_at_utc are NEVER returned. Nothing is looked up by event_date_utc: an event is
    invisible until it was public."""
    out = []
    for r in rows:
        if not r["known_at_utc"]:
            continue
        if parse_utc(r["known_at_utc"]) <= as_of_ms:
            out.append(r)
    return out


# ------------------------------------------------------------ supply steps ---

def supply_steps(cg_csv: Path, threshold: float = 0.01, min_days: int = 3, baseline_days: int = 3) -> list[dict]:
    """Derived circulating supply (CoinGecko market_cap / price) steps that persist. Read-only.

    A step on day t needs |supply[t] / supply[t-1] - 1| > threshold, and supply on days t .. t+min_days-1 must all sit
    more than `threshold` from the baseline in the same direction. The baseline is the median of the previous
    `baseline_days` days, so a one-day spike and its reversal the next day is NOT a step (it looks like sampling
    noise). Steps without min_days of later data (the newest days) are not returned: persistence cannot be
    confirmed yet. known_at is timestamp + 24 h, like every daily external row."""
    path = Path(cg_csv)
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    if rows and not {"timestamp_ms", "price", "market_cap"} <= set(rows[0]):
        raise FileProblem(f"{path}: expected CoinGecko columns {cgm.COLUMNS}")
    rows = sorted(rows, key=lambda r: int(r["timestamp_ms"]))
    ts = [int(r["timestamp_ms"]) for r in rows]
    s = [float(r["market_cap"]) / float(r["price"]) for r in rows]
    out = []
    for i in range(max(baseline_days, 1), len(s) - min_days + 1):
        change = s[i] / s[i - 1] - 1
        if abs(change) <= threshold:
            continue
        window = sorted(s[i - baseline_days:i])
        base = window[len(window) // 2] if len(window) % 2 else (window[len(window) // 2 - 1] + window[len(window) // 2]) / 2
        moves = [s[i + j] / base - 1 for j in range(min_days)]
        if all(abs(m) > threshold and (m > 0) == (change > 0) for m in moves):
            out.append({"timestamp_ms": ts[i], "baseline": base, "before": s[i - 1], "after": s[i],
                        "change": change, "tokens": s[i] - s[i - 1], "moves": moves,
                        "known_at_ms": ts[i] + DAY_MS})
    return out


# -------------------------------------------------------------------- CLI ---

def render(ev: Report, tk: Report) -> str:
    out = []
    for rep in (ev, tk):
        out.append(f"{rep.name}: {rep.rows} rows, sourced {rep.sourced}, unverified {rep.unverified}, "
                   f"errors {len(rep.errors)}, warnings {len(rep.warnings)}")
    if tk.percent_sum is not None:
        out.append(f"tokenomics percent_of_supply: {tk.percent_rows} rows sum to {tk.percent_sum:g} (reported, not forced to 100)")
    if ev.flagged:
        out.append(f"events with EMPTY known_at_utc ({len(ev.flagged)}; features never use these):")
        out += [f"  - {m}" for m in ev.flagged]
    for rep in (ev, tk):
        out += [f"  ERROR ({rep.name}): {m}" for m in rep.errors]
        out += [f"  warning ({rep.name}): {m}" for m in rep.warnings]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate data/static/tokenomics.csv and events.csv (local files only).")
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    args = ap.parse_args(argv)
    try:
        ev, tk = check_dir(Path(args.dir))
    except FileProblem as exc:
        print(str(exc))
        return 2
    print(render(ev, tk))
    return 0 if ev.ok and tk.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
