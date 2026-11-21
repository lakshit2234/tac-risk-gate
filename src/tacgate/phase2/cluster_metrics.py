"""Two reported-only metrics for the walk-forward harness: cluster-aware capture and the remaining adverse move after the first alarm.
Views, not selection criteria: nothing here picks, sorts or ranks a rule. Development period only; the holdout is never read.

FIXED in advance by the user on 2026-11-22 (proposed by Claude, approved by the user); each value is one named constant:
  1. Clusters, per side and per view: sort the episodes by start time; an episode joins the current cluster if its start is within CLUSTER_GAP of the previous
     episode's start (chained: "within" includes exactly 24 hours); otherwise it starts a new cluster.
  2. Cluster-aware capture: the FIRST episode of each cluster is the one tested, with the harness's own capture rule (stay out at some decision time in the
     primary lead window before its event time). Captured / clusters with the two-sided 95 percent exact interval; TOO FEW under MIN_CLUSTERS clusters.
  3. Remaining adverse move. Alarm time = first decision time of the continuous stay-out spell that contains the first stay-out decision time inside the
     lead window before the event time, but not earlier than ALARM_LOOKBACK before the event time. No such spell = not captured. For a captured episode the
     remaining move is the largest adverse move (1m low for long, 1m high for short) in the REMAINING_HORIZON after the alarm time, against the reference price at
     the alarm time (the close of the candle that ended then). The already-happened move is the adverse move from the reference price of the episode's first
     positive decision time to the reference price at the alarm time. For a not-captured episode the remaining move is the whole move: the largest adverse move in
     the REMAINING_HORIZON after the episode's first positive decision time, against its reference price. A move is a plain fraction (a fall for long, a rise for short).
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from tacgate.phase2 import loaders as ld
from tacgate.phase2 import rules_baseline as rb
from tacgate.phase2 import walkforward as wf

HOUR_MS = 3_600_000
MIN_MS = 60_000
CLUSTER_GAP_MS = 24 * HOUR_MS  # FIXED: chained start-to-start gap that keeps episodes in one cluster (inclusive)
ALARM_LOOKBACK_MS = 24 * HOUR_MS  # FIXED: the alarm spell is looked at no further back than this before the event time
REMAINING_HORIZON_MIN = 24 * 60  # FIXED: the remaining (and whole) move is measured over the next 24 hours
MIN_CLUSTERS = 4  # FIXED: fewer clusters than this prints TOO FEW
LEAD_MIN = wf.PRIMARY_LEAD_MIN  # FIXED earlier: the primary lead window, 1 h
FIXED_ON = "2026-11-22"
TRIAL_IDS = ("T0001", "T0002", "T0003", "T0004", "T0005", "T0006", "T0007")
LABELS = {**rb.LABELS}


# ---------------------------------------------------------------- clusters ---

def cluster_groups(eps: list[wf.Episode]) -> list[list[int]]:
    """Indexes into `eps` (sorted by start) grouped into clusters: chained, a gap of at most 24 hours between consecutive starts keeps the cluster."""
    order = sorted(range(len(eps)), key=lambda i: eps[i].start_ms)
    groups: list[list[int]] = []
    for i in order:
        if groups and eps[i].start_ms - eps[groups[-1][-1]].start_ms <= CLUSTER_GAP_MS:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


def episode_flags(T: np.ndarray, alarm: np.ndarray, eps: list[wf.Episode], lead_min: int = LEAD_MIN) -> np.ndarray:
    """The harness's capture rule: an alarm decision time in [event - lead, event - 5 min] among the decision times of the test period."""
    if not eps:
        return np.array([], bool)
    i0, i1 = wf._windows(T, eps, lead_min)
    cs = np.r_[0, np.cumsum(alarm)]
    return (cs[i1] - cs[i0]) > 0


# ----------------------------------------------------------- remaining move ---

@dataclass
class EpisodeMove:
    captured: bool
    alarm_ms: int | None
    remaining: float  # NaN if the 24 h window is not fully inside the data
    already: float  # NaN for a not-captured episode
    whole: float  # the whole move from the episode's own reference price (NaN if not measurable)


def _move(m, side: str, i0: int, ref: float) -> float:
    n = REMAINING_HORIZON_MIN
    if i0 < 1 or i0 + n > m.n or not np.isfinite(ref):
        return float("nan")
    if side == "long":
        return float(1.0 - np.min(m.low[i0:i0 + n]) / ref)
    return float(np.max(m.high[i0:i0 + n]) / ref - 1.0)


def episode_moves(T: np.ndarray, alarm: np.ndarray, eps: list[wf.Episode], m, side: str, lead_min: int = LEAD_MIN) -> list[EpisodeMove]:
    """Per episode: captured or not, the alarm time, the remaining move, the already-happened move and the whole move (see the module docstring)."""
    if side not in wf.SIDES:
        raise ValueError("side must be 'long' or 'short'")
    flags = episode_flags(T, alarm, eps, lead_min)
    run_start = wf._run_starts(alarm) if len(alarm) else alarm
    i0s, i1s = wf._windows(T, eps, lead_min) if eps else (np.array([], int), np.array([], int))
    out = []
    for k, e in enumerate(eps):
        j_s = int((e.start_ms - m.first_open) // MIN_MS)
        ref_s = float(m.close[j_s - 1]) if 1 <= j_s <= m.n else float("nan")
        whole = _move(m, side, j_s, ref_s)
        if not flags[k]:
            out.append(EpisodeMove(False, None, whole, float("nan"), whole))
            continue
        first = i0s[k] + int(np.flatnonzero(alarm[i0s[k]:i1s[k]])[0])  # the first stay-out decision time inside the lead window
        cap_idx = int(np.searchsorted(T, e.event_ms - ALARM_LOOKBACK_MS, "left"))
        ai = max(int(run_start[first]), cap_idx)  # first decision time of its continuous spell, looking back no further than 24 h
        alarm_ms = int(T[ai])
        j_a = int((alarm_ms - m.first_open) // MIN_MS)
        ref_a = float(m.close[j_a - 1]) if 1 <= j_a <= m.n else float("nan")
        rem = _move(m, side, j_a, ref_a)
        already = float(1.0 - ref_a / ref_s) if side == "long" else float(ref_a / ref_s - 1.0)
        out.append(EpisodeMove(True, alarm_ms, rem, already, whole))
    return out


def _stats(x) -> dict:
    v = np.array([a for a in x if np.isfinite(a)], dtype=float)
    return {"n": int(len(v)), "median": float(np.median(v)) if len(v) else None, "min": float(v.min()) if len(v) else None, "max": float(v.max()) if len(v) else None}


def summarize(T: np.ndarray, alarm: np.ndarray, eps: list[wf.Episode], m, side: str) -> dict:
    """Episodes, clusters, all-episode capture, cluster-aware capture and the move numbers, for one gate, one side and one view."""
    groups = cluster_groups(eps)
    flags = episode_flags(T, alarm, eps)
    first_flags = np.array([flags[g[0]] for g in groups], bool)
    n_c, k_c = len(groups), int(first_flags.sum())
    moves = episode_moves(T, alarm, eps, m, side)
    cap = [mv for mv in moves if mv.captured]
    miss = [mv for mv in moves if not mv.captured]
    ci = wf.clopper_pearson(k_c, n_c) if n_c else (None, None)
    return {"episodes": len(eps), "clusters": n_c, "captured_episodes": int(flags.sum()),
            "cluster_captured": k_c, "cluster_rate": k_c / n_c if n_c else None, "cluster_ci_low": ci[0], "cluster_ci_high": ci[1],
            "cluster_verdict": "TOO FEW" if n_c < MIN_CLUSTERS else "",
            "remaining_captured": _stats([mv.remaining for mv in cap]), "already_captured": _stats([mv.already for mv in cap]),
            "whole_not_captured": _stats([mv.whole for mv in miss]), "remaining_all_episodes": _stats([mv.remaining for mv in moves]),
            "not_measurable": int(sum(1 for mv in moves if not np.isfinite(mv.remaining)))}


# ------------------------------------------------------- the saved results ---

def diff(a, b, path: str = "") -> tuple[list[str], int]:
    """Exact comparison of two nested results: (list of differences, number of values compared)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out, n = [], 0
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}/{k}: only in one of them")
                continue
            d, c = diff(a[k], b[k], f"{path}/{k}")
            out += d
            n += c
        return out, n
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: length {len(a)} vs {len(b)}"], 1
        out, n = [], 0
        for i, (x, y) in enumerate(zip(a, b)):
            d, c = diff(x, y, f"{path}[{i}]")
            out += d
            n += c
        return out, n
    return ([] if a == b else [f"{path}: {a!r} vs {b!r}"]), 1


def rebuild(data_dir: Path) -> tuple[wf.Dataset, dict]:
    """Re-run the same rules and the same seeded anchors on the development period (no trial rows are written) and return the dataset and the gates."""
    data_dir = Path(data_dir)
    b = ld.load_klines(data_dir / "binance_TACUSDT_1m.csv", "binance")
    y = ld.load_klines(data_dir / "bybit_TACUSDT_1m.csv", "bybit")
    fu = ld.load_funding(data_dir / "binance_TACUSDT_funding.csv")
    ds = rb.add_funding(wf.build_dataset(b, y), fu)  # development dataset: the klines are cut before the holdout first
    rules = {"always_stay_out": wf.AlwaysStayOut(), "never": wf.NeverGate(), "random": wf.RandomGate(), **{r.name: r for r in rb.make_rules()}}
    blocks = wf.month_blocks(ds)
    gates = {name: wf.run_gate(rule, ds, blocks) for name, rule in rules.items()}
    return ds, {"blocks": blocks, "rules": rules, "gates": gates}


def run(data_dir: Path, report: Path, results_dir: Path = wf.RESULTS_DIR) -> int:
    saved = {t: json.loads((Path(results_dir) / f"{t}.json").read_text(encoding="utf-8")) for t in TRIAL_IDS}
    ds, rb_ = rebuild(data_dir)
    blocks, gates, rules = rb_["blocks"], rb_["gates"], rb_["rules"]
    eps = wf._episodes_all(ds, blocks[0][1], wf.lb.DEVELOPMENT_END_MS)
    total, problems = 0, []
    for tid, s in saved.items():
        g = gates[s["rule"]]
        got = {"metrics": wf._clean(wf.compute_metrics(g.times, g.states, eps)), "episodes": wf._clean({view_k + "_" + side: len(e) for (v, side), e in eps.items() for view_k in [wf.view_key(v)]})}
        want = {"metrics": s["metrics"], "episodes": s["episodes"]}
        if s["rule"] in rb.RULE_NAMES:
            got["rule_info"], want["rule_info"] = wf._clean(rules[s["rule"]].info()), s["rule_info"]
        d, n = diff(got, want, tid)
        total += n
        problems += d
    if problems:
        print(f"STOP: the re-run differs from the saved results in {len(problems)} value(s) (of {total:,} compared):")
        for p in problems[:30]:
            print("  ", p)
        return 1
    print(f"The re-run reproduces every saved number exactly: {total:,} values compared in {len(saved)} trials.")
    out = {}
    for tid, s in saved.items():
        g = gates[s["rule"]]
        alarm = {side: g.states[side] == wf.STAY_OUT for side in wf.SIDES}
        out[tid] = {"rule": s["rule"], "views": {wf.view_key(v): {side: summarize(g.times, alarm[side], eps[(v, side)], ds.minutes, side) for side in wf.SIDES} for v in wf.VIEWS}}
    Path(report).write_text(render_report(out, total), encoding="utf-8")
    print(f"report: {report}")
    return 0


# ------------------------------------------------------------------ report ---

def pct(x) -> str:
    return "-" if x is None else f"{100 * x:.1f}%"


def _rate(k: int, n: int, lo, hi) -> str:
    return "no episodes" if not n else f"{k}/{n} = {100 * k / n:.0f}% [{100 * lo:.0f}%, {100 * hi:.0f}%]"


def _range(st: dict) -> str:
    return "-" if not st["n"] else f"{pct(st['median'])} [{pct(st['min'])} to {pct(st['max'])}] (n={st['n']})"


def _med(st: dict) -> str:
    return "-" if not st["n"] else f"{pct(st['median'])} (n={st['n']})"


def vname(vk: str) -> str:
    return vk.replace("_", " / ").replace("pct", " percent").replace("h /", "h /")


def render_report(res: dict, n_compared: int) -> str:
    pk = wf.view_key(wf.PRIMARY_VIEW)
    first = next(iter(res.values()))
    names = {t: f"{t} {LABELS.get(r['rule'], r['rule'])}" for t, r in res.items()}
    L = ["# Phase 2 cluster-aware capture and remaining move (reported only)", "",
         f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d')} (UTC) by `python -m tacgate.phase2.cluster_metrics`. Development period only (test months 2025-09 to 2026-07, decision times up to 2026-07-31 00:00 UTC); "
         f"the holdout was not read or evaluated. The seven logged trials (T0001 to T0007) are re-reported; **no new trial was logged and no rule, threshold or window changed.** "
         "These are views, not selection criteria: the table order is the trial order, nothing is ranked, and no rule is picked.", "",
         "**Read this first.** With so few clusters no capture rate here supports a claim that a gate works, and none is made. A percentage always has its count next to it.", "",
         "## 1. Fixed definitions", "",
         f"Fixed in advance by the user on {FIXED_ON} (proposed by Claude, approved by the user); each value is a named constant in `src/tacgate/phase2/cluster_metrics.py`. Long and short are always separate.", "",
         "1. **Clusters** (per side and per view): sort the episodes by start time. An episode joins the current cluster if its start is within 24 hours of the previous episode's start in that cluster "
         "(chained; \"within\" includes exactly 24 hours). Otherwise it starts a new cluster.",
         f"2. **Cluster-aware capture:** the first episode of each cluster is the one tested, with the harness's own capture rule (stay out at some decision time in the 1 hour lead window before its event time). "
         f"Captured / clusters with the two-sided 95 percent exact Clopper-Pearson interval; TOO FEW under {MIN_CLUSTERS} clusters. The all-episode capture is printed next to it.",
         "3. **Remaining adverse move:** the alarm time is the first decision time of the continuous stay-out spell that contains the first stay-out decision time inside the lead window, looking back no further than "
         "24 hours before the event time; no such spell means not captured. For a captured episode the remaining move is the largest adverse move after the alarm time within the next 24 hours "
         "(1m low for long, 1m high for short), against the reference price at the alarm time. The already-happened move is the adverse move from the reference price of the episode's first positive decision time "
         "to the reference price at the alarm time. For a not-captured episode the remaining move is the whole move: the largest adverse move in the 24 hours after its first positive decision time, against its reference price. "
         "A move is a plain fraction (a fall for long, a rise for short); the already-happened move can be negative (the price went the other way before the alarm).", "",
         "Every number is on the Binance last-price klines (not mark price), as in the labels.", "",
         "## 2. The re-run is the same run", "",
         f"The saved results do not contain the per-decision gate series, so the same rules and the same seeded anchors were re-run on the development period without writing any trial row. "
         f"Before anything else every existing metric (episodes, capture, shares, intervals, random gate, lead times, cut-offs, NaN counts) of all seven trials was recomputed and compared with the saved number: "
         f"**{n_compared:,} values compared, 0 differences.** (Had one differed, the run would have stopped here.)", "",
         "## 3. Episodes and clusters", ""]
    L += ["| View | Side | Episodes | Clusters |", "|---|---|---|---|"]
    for vk in first["views"]:
        for side in wf.SIDES:
            c = first["views"][vk][side]
            L.append(f"| {vname(vk)} | {side} | {c['episodes']} | {c['clusters']} |")
    c24 = {s: first["views"][pk][s] for s in wf.SIDES}
    L += ["", f"Plainly: in the primary view ({vname(pk)}) there are {c24['long']['episodes']} long episodes in {c24['long']['clusters']} clusters and {c24['short']['episodes']} short episodes in "
          f"{c24['short']['clusters']} clusters. " +
          ("Here the cluster count equals the episode count, and that is structural: two 24 hour episodes are separated by at least 24 hours between the end of one and the start of the next, so their starts are always "
           "more than 24 hours apart (an exact tie is the only way they could be merged). **The 24 hour chaining gap therefore cannot merge any episode of the 24 h view;** the cluster view only changes the "
           "4 h and 1 h views, where episodes are shorter. This is raised as OPEN below." if all(c24[s]["episodes"] == c24[s]["clusters"] for s in wf.SIDES) else
           "Clusters merge some of the episodes."), ""]

    def cap_table(vk: str, side: str) -> list[str]:
        rows = ["| Trial | Episodes | Clusters | All-episode capture | Cluster-aware capture (first episode of each cluster) | Verdict |", "|---|---|---|---|---|---|"]
        for t, r in res.items():
            c = r["views"][vk][side]
            lo, hi = c["cluster_ci_low"], c["cluster_ci_high"]
            ep_lo, ep_hi = wf.clopper_pearson(c["captured_episodes"], c["episodes"]) if c["episodes"] else (0, 0)
            rows.append(f"| {names[t]} | {c['episodes']} | {c['clusters']} | {_rate(c['captured_episodes'], c['episodes'], ep_lo, ep_hi)} | "
                        f"{_rate(c['cluster_captured'], c['clusters'], lo, hi) if c['clusters'] else 'no clusters'} | {c['cluster_verdict'] or 'descriptive only'} |")
        return rows

    def move_table(vk: str, side: str) -> list[str]:
        rows = ["| Trial | Captured episodes | Remaining move, captured: median [range] | Already-happened move, captured: median | Not captured: whole move, median | Remaining move, all episodes: median |",
                "|---|---|---|---|---|---|"]
        for t, r in res.items():
            c = r["views"][vk][side]
            rows.append(f"| {names[t]} | {c['captured_episodes']} of {c['episodes']} | {_range(c['remaining_captured'])} | {_med(c['already_captured'])} | {_med(c['whole_not_captured'])} | {_med(c['remaining_all_episodes'])} |")
        return rows
    L += [f"## 4. Primary view {vname(pk)}: capture, all episodes and clusters", "", "Lead window 1 hour, alarm = stay out, whole test period. Trials in trial order.", ""]
    for side in wf.SIDES:
        L += [f"### {side.capitalize()} side", ""] + cap_table(pk, side) + [""]
    L += [f"## 5. Primary view {vname(pk)}: the move after the alarm", "",
          "Remaining move = what was still ahead after the first alarm (captured episodes), the already-happened move = what had already happened when the alarm came, "
          "and for a not-captured episode the whole move counts as unprotected. The last column mixes both as the definition says. "
          "An always-on gate has its alarm time pushed back to 24 hours before the event by the look-back cap, which is why its remaining move is the 24 hour move from there.", ""]
    for side in wf.SIDES:
        L += [f"### {side.capitalize()} side", ""] + move_table(pk, side) + [""]
    L += ["## 6. Reported-only views (never used to select)", ""]
    for vk in list(first["views"])[1:]:
        for side in wf.SIDES:
            L += [f"### {vname(vk)}, {side} side: capture", ""] + cap_table(vk, side) + ["", f"### {vname(vk)}, {side} side: the move after the alarm", ""] + move_table(vk, side) + [""]
    # the effect of the cluster view
    L += ["## 7. What the cluster view does to the baselines", ""]
    lines = []
    for vk in first["views"]:
        for side in wf.SIDES:
            c0 = first["views"][vk][side]
            if c0["clusters"] == c0["episodes"]:
                lines.append(f"- {vname(vk)}, {side}: {c0['episodes']} episodes in {c0['clusters']} clusters: nothing merges, so the cluster view equals the episode view.")
            else:
                diffs = []
                for t in ("T0004", "T0005", "T0006", "T0007"):
                    c = res[t]["views"][vk][side]
                    diffs.append(f"{LABELS[res[t]['rule']].split(' ')[0]} {c['captured_episodes']}/{c['episodes']} episodes vs {c['cluster_captured']}/{c['clusters']} clusters")
                lines.append(f"- {vname(vk)}, {side}: {c0['episodes']} episodes merge into {c0['clusters']} clusters. Episode view against cluster view: " + "; ".join(diffs) + ".")
    summ = []
    for vk in list(first["views"])[1:]:
        for side in wf.SIDES:
            for t in ("T0004", "T0007"):
                c = res[t]["views"][vk][side]
                if c["clusters"] < c["episodes"]:
                    summ.append(f"{LABELS[res[t]['rule']].split(' ')[0]} {vname(vk)} {side}: {100 * c['captured_episodes'] / c['episodes']:.0f}% of episodes "
                                f"({c['captured_episodes']}/{c['episodes']}) against {100 * c['cluster_captured'] / c['clusters']:.0f}% of clusters ({c['cluster_captured']}/{c['clusters']})")
    L += lines + ["", "In plain words: in the primary 24 h view the cluster view changes nothing, because nothing merges. In the 4 h and 1 h views the cluster view lowers the count of events, and the capture rate "
          "moves by a few points either way (R1 and R4, the bar named in the plan: " + "; ".join(summ) + "). The point is not the size of that move: each cluster-aware rate rests on 4 to 20 independent events, with intervals as wide as the tables show.",
          "",
          "Reading: where episodes merge, the number of independent events is the cluster count, not the episode count, and the cluster-aware rate rests on that smaller number. "
          "Where a rule's alarm stays on through a cluster, the all-episode rate counts the later episodes as captured too; the cluster-aware rate does not. "
          "No rate in any table supports a claim, and no rule is picked from this report.", "",
          "## Decisions", "",
          f"**Decided by the user ({FIXED_ON}, proposed by Claude, approved by the user):** the three definitions in section 1 (clusters chained within 24 hours; capture of the first episode of each cluster; "
          "remaining and already-happened move with the 24 hour look-back and the 24 hour horizon); that both are reported-only views, not selection criteria; that no new trial is logged, no rule, threshold or window changes, "
          "and the holdout is not read in this task.", "",
          "**OPEN (not decided):**", "",
          "- Whether the 24 hour chaining gap is right. By construction it cannot merge any episode of the 24 h view (section 3); a longer gap, or chaining on event times, would be a different definition and would have to be logged before it is used.",
          "- Whether the remaining move should later use the mark price instead of the last-price klines.",
          "- The 24 hour chaining gap cannot see multi-day clustering. In the primary 24 h view the episode definition already merges positives that overlap, so clusters equal episodes; but episodes recur every few days in 2026-07 and 2026-08, and a rule that stays on through a volatile period captures all of them. Before any real rule is evaluated, add a reported-only sensitivity view with a 7 day chaining gap (a sensitivity view, not a selection criterion, and not tuned), and report how many clusters it gives per side.", ""]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Cluster-aware capture and remaining move for the 7 logged trials (development period only; logs nothing).")
    ap.add_argument("--data-dir", default="data/raw")
    ap.add_argument("--report", default="docs/phase2_cluster_metrics.md")
    args = ap.parse_args(argv)
    d_res, r_res = Path(args.data_dir).resolve(), Path(args.report).resolve()
    if r_res == d_res or d_res in r_res.parents:
        print(f"Refusing: --report must not be inside the data directory {args.data_dir}.")
        return 2
    return run(Path(args.data_dir), Path(args.report))


if __name__ == "__main__":
    raise SystemExit(main())
