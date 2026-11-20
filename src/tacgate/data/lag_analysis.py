"""Read-only lag analysis for the forward recorder files.

Question: does the recorder's cycle offset (CYCLE_OFFSET_MS, 45 s) capture each 5-minute period's row in
its FIRST cycle, or does the row show up in a later cycle? Reports what the data shows, no recommendation.

Read-only: each file is read once into memory, a partial last line is ignored, nothing is locked or
rewritten, no network. File names and columns come from recorder.py (never guessed).

Definitions:
  lag_ms             = fetched_at_ms - timestamp
  lag after close    = lag_ms for open interest / long-short (label = sample time);
                       lag_ms - 300000 for taker (label = period START, so the period closes 5 min later)
  backfilled row     = lag_ms above 15 minutes: skipped
  first-cycle        = lag after close < 120 s
  second-cycle       = 120 s to 420 s
  later              = above 420 s

Run: python -m tacgate.data.lag_analysis [--dir data/raw] [--since-ms 1795104000000] [--report docs/lag_analysis_report.md]
Exit codes: 0 ok, 2 bad arguments or file problem.
"""
from __future__ import annotations

import argparse
import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from tacgate.data.quality_recorder import FileProblem, read_once
from tacgate.data.recorder import CYCLE_OFFSET_MS, DATASETS, PERIOD_MS, Dataset

# 2026-11-19 16:00:00 UTC: the restart that put the 45 s offset in force.
DEFAULT_SINCE_MS = 1_795_104_000_000
DEFAULT_DIR = Path("data/raw")
DEFAULT_REPORT = Path("docs/lag_analysis_report.md")

BACKFILL_LAG_MS = 15 * 60_000  # lag above this = backfilled, skipped
FIRST_CYCLE_MAX_MS = 120_000  # lag after close below this = first-cycle capture
SECOND_CYCLE_MAX_MS = 420_000  # up to and including this = second-cycle capture
TAKER = "taker_buy_sell"
BUCKETS = ("first", "second", "later")
PCTS = (50, 90, 95, 99)
MAX_LATE_LISTED = 20  # report lists only the most recent late rows per file; the total count is always shown


def utc(ms: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def bucket_of(after_close_ms: int) -> str:
    if after_close_ms < FIRST_CYCLE_MAX_MS:
        return "first"
    if after_close_ms <= SECOND_CYCLE_MAX_MS:
        return "second"
    return "later"


@dataclass
class Live:
    ts: int
    fetched: int
    lag: int
    after_close: int
    bucket: str


@dataclass
class DatasetResult:
    name: str
    label_is_period_start: bool
    total_rows: int = 0  # complete data rows in the file
    malformed: int = 0
    before_since: int = 0  # fetched_at_ms < since-ms
    backfilled: int = 0  # lag above 15 minutes
    negative: int = 0  # fetched before its own label (clock problem), excluded
    ignored_partial_bytes: int = 0
    live: list[Live] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        c = {b: 0 for b in BUCKETS}
        for r in self.live:
            c[r.bucket] += 1
        return c

    def first_pct(self) -> float | None:
        return 100.0 * self.counts()["first"] / len(self.live) if self.live else None

    def percentiles(self) -> dict[str, float] | None:
        if not self.live:
            return None
        a = np.array([r.after_close for r in self.live], dtype=float)
        out = {f"p{p}": float(np.percentile(a, p)) for p in PCTS}
        out["max"] = float(a.max())
        return out

    def by_hour(self) -> dict[int, tuple[int, int]]:
        """UTC hour of the period CLOSE -> (first-cycle count, total live rows)."""
        out: dict[int, list[int]] = {}
        for r in self.live:
            close = r.ts + (PERIOD_MS if self.label_is_period_start else 0)
            h = (close // 3_600_000) % 24
            cell = out.setdefault(int(h), [0, 0])
            cell[1] += 1
            if r.bucket == "first":
                cell[0] += 1
        return {h: (v[0], v[1]) for h, v in sorted(out.items())}


def analyse_dataset(ds: Dataset, directory: Path, since_ms: int) -> DatasetResult:
    path = ds.csv_path(directory)
    res = DatasetResult(ds.name, label_is_period_start=ds.name == TAKER)
    data, ignored = read_once(path)  # one read, complete lines only
    res.ignored_partial_bytes = ignored
    if not data:
        raise FileProblem(f"{path}: file is empty (no complete header line)")
    reader = csv.reader(io.StringIO(data.decode("utf-8", errors="replace"), newline=""))
    header = next(reader, [])
    if header != ds.columns:
        raise FileProblem(f"{path}: expected columns {ds.columns}, got {header}")
    ts_i, f_i = ds.ts_index, ds.columns.index("fetched_at_ms")
    offset = PERIOD_MS if res.label_is_period_start else 0
    for row in reader:
        if not row:
            continue
        res.total_rows += 1
        if len(row) != len(ds.columns):
            res.malformed += 1
            continue
        try:
            ts, fetched = int(row[ts_i]), int(row[f_i])
        except ValueError:
            res.malformed += 1
            continue
        if fetched < since_ms:
            res.before_since += 1
            continue
        lag = fetched - ts
        if lag > BACKFILL_LAG_MS:
            res.backfilled += 1
            continue
        after_close = lag - offset
        if after_close < 0:
            res.negative += 1
            continue
        res.live.append(Live(ts, fetched, lag, after_close, bucket_of(after_close)))
    return res


@dataclass
class Agreement:
    names: list[str]
    common: int = 0  # timestamps live in all three files
    all_first: int = 0
    all_not_first: int = 0
    mixed: int = 0  # one file first-cycle while another was not, same timestamp
    late_by_file: dict[str, int] = field(default_factory=dict)  # in mixed cases, which file was the late one
    examples: list[tuple[int, dict[str, str]]] = field(default_factory=list)


def agreement(results: list[DatasetResult]) -> Agreement:
    non_taker = [r for r in results if not r.label_is_period_start]
    ag = Agreement([r.name for r in non_taker], late_by_file={r.name: 0 for r in non_taker})
    maps = [{x.ts: x for x in r.live} for r in non_taker]
    if not maps:
        return ag
    common = set(maps[0])
    for m in maps[1:]:
        common &= set(m)
    ag.common = len(common)
    for ts in sorted(common):
        buckets = {r.name: m[ts].bucket for r, m in zip(non_taker, maps)}
        firsts = [b == "first" for b in buckets.values()]
        if all(firsts):
            ag.all_first += 1
        elif not any(firsts):
            ag.all_not_first += 1
        else:
            ag.mixed += 1
            for n, b in buckets.items():
                if b != "first":
                    ag.late_by_file[n] += 1
            ag.examples.append((ts, buckets))
    return ag


def verdict_line(r: DatasetResult) -> str:
    p = r.first_pct()
    if p is None:
        return f"{r.name}: no live rows since the cutoff, no verdict"
    return f"{r.name}: offset {CYCLE_OFFSET_MS // 1000} s sufficient: {p:.1f}% first-cycle"


def run(directory: Path, since_ms: int) -> tuple[list[DatasetResult], Agreement]:
    results = [analyse_dataset(ds, directory, since_ms) for ds in DATASETS]
    return results, agreement(results)


# ---------------------------------------------------------------- output ---

def _s(ms: float) -> str:
    return f"{ms / 1000:.1f} s"


def _pct(n: int, d: int) -> str:
    return f"{100.0 * n / d:.1f}%" if d else "n/a"


def render_report(results: list[DatasetResult], ag: Agreement, directory: Path, since_ms: int) -> str:
    L: list[str] = [
        "# Recorder lag analysis",
        "",
        f"Data directory: `{directory}`. Rows with fetched_at_ms >= {since_ms} ({utc(since_ms)} UTC). "
        f"Cycle offset in force: {CYCLE_OFFSET_MS // 1000} s after each 5-minute boundary.",
        "",
        "Read-only: each file read once, partial last line ignored, no network.",
        "",
        "Lag after close = fetched_at_ms - timestamp; for the taker file (label = period start) minus a further 300 s. "
        "Rows with lag above 15 minutes are backfilled and skipped. "
        f"Buckets: first-cycle < {FIRST_CYCLE_MAX_MS // 1000} s, second-cycle {FIRST_CYCLE_MAX_MS // 1000}-"
        f"{SECOND_CYCLE_MAX_MS // 1000} s, later > {SECOND_CYCLE_MAX_MS // 1000} s.",
        "",
        "## Verdicts",
        "",
    ]
    L += [f"- {verdict_line(r)}" for r in results]
    for r in results:
        L += ["", f"## {r.name}", ""]
        L.append(
            f"Rows in file: {r.total_rows}. Before cutoff (fetched_at_ms < since-ms): {r.before_since}. "
            f"Skipped as backfilled (lag > 15 min): {r.backfilled}. Malformed: {r.malformed}. "
            f"Negative lag (excluded): {r.negative}. **Live rows analysed: {len(r.live)}.**"
        )
        if r.ignored_partial_bytes:
            L.append(f"Ignored a partial last line ({r.ignored_partial_bytes} bytes).")
        if not r.live:
            L += ["", "No live rows to analyse."]
            continue
        c = r.counts()
        n = len(r.live)
        L += ["", "| Capture | Rows | Share |", "|---|---|---|"]
        for b, name in zip(BUCKETS, ("first-cycle", "second-cycle", "later")):
            L.append(f"| {name} | {c[b]} | {_pct(c[b], n)} |")
        pc = r.percentiles() or {}
        L += ["", "Lag after close: " + ", ".join(f"{k} {_s(v)}" for k, v in pc.items()) + "."]
        if r.label_is_period_start:
            L.append("(Raw lag is this plus 300 s.)")
        late = [x for x in r.live if x.bucket != "first"]
        shown = sorted(late, key=lambda x: x.ts)[-MAX_LATE_LISTED:]
        L += ["", f"### Rows not captured in the first cycle ({len(late)} in total)", ""]
        if late:
            if len(shown) < len(late):
                L += [f"Showing the {len(shown)} most recent of {len(late)}.", ""]
            L += ["| Timestamp (UTC) | Lag | Lag after close | Bucket |", "|---|---|---|---|"]
            L += [f"| {utc(x.ts)} | {_s(x.lag)} | {_s(x.after_close)} | {x.bucket} |" for x in shown]
        else:
            L.append("None.")
        L += ["", "### First-cycle share by UTC hour (hour of the period close)", "",
              "| Hour | First-cycle | Live rows | Share |", "|---|---|---|---|"]
        for h, (f, t) in r.by_hour().items():
            L.append(f"| {h:02d} | {f} | {t} | {_pct(f, t)} |")
    L += ["", "## Do the files agree?", "",
          f"Timestamps live in all of {', '.join(ag.names)}: {ag.common}."]
    if ag.common:
        L += [
            "",
            f"- all three first-cycle: {ag.all_first} ({_pct(ag.all_first, ag.common)})",
            f"- all three NOT first-cycle: {ag.all_not_first} ({_pct(ag.all_not_first, ag.common)})",
            f"- mixed (one file late while another was on time, same timestamp): {ag.mixed} "
            f"({_pct(ag.mixed, ag.common)})",
        ]
        if ag.mixed:
            L += ["", "In mixed cases, the late file was: "
                  + ", ".join(f"{n} {k}x" for n, k in ag.late_by_file.items()) + ".", "",
                  "| Timestamp (UTC) | " + " | ".join(ag.names) + " |", "|---|" + "---|" * len(ag.names)]
            L += [f"| {utc(ts)} | " + " | ".join(b[n] for n in ag.names) + " |" for ts, b in ag.examples]
    L.append("")
    return "\n".join(L)


def console_summary(results: list[DatasetResult], ag: Agreement, report: Path, since_ms: int) -> str:
    out = [f"Recorder lag analysis (rows fetched since {utc(since_ms)} UTC, offset {CYCLE_OFFSET_MS // 1000} s)"]
    for r in results:
        c = r.counts()
        out.append(
            f"  {r.name}: live {len(r.live)}, skipped backfilled {r.backfilled}, before cutoff {r.before_since}"
            f" | first {c['first']} second {c['second']} later {c['later']}"
        )
        pc = r.percentiles()
        if pc:
            out.append("    lag after close: " + ", ".join(f"{k} {_s(v)}" for k, v in pc.items()))
    out.append(f"  agreement: {ag.common} common timestamps, mixed {ag.mixed}")
    out += [""] + [verdict_line(r) for r in results]
    out.append(f"  report: {report}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only lag analysis of the forward recorder files.")
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    ap.add_argument("--since-ms", type=int, default=DEFAULT_SINCE_MS,
                    help="only rows with fetched_at_ms >= this (default %(default)s = 2026-11-19 16:00 UTC)")
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    args = ap.parse_args(argv)
    directory, report = Path(args.dir), Path(args.report)

    d_res, r_res = directory.resolve(), report.resolve()
    if r_res == d_res or d_res in r_res.parents:
        print(f"Refusing: --report must not be inside the data directory {directory}.")
        return 2
    if not directory.is_dir():
        print(f"Directory not found: {directory}")
        return 2
    try:
        results, ag = run(directory, args.since_ms)
    except FileProblem as exc:
        print(str(exc))
        return 2
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(results, ag, directory, args.since_ms), encoding="utf-8")
    print(console_summary(results, ag, report, args.since_ms))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
