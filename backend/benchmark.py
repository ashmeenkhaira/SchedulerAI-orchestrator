"""Measure agent-guided scheduling against each static strategy.

Replaces calculate_metrics.py, which carried its own private copy of the
simulation with hand-added handicaps that existed in neither production path
(a dispatch cap on baseline, a +1 work penalty on random_backoff, an epoch
pause on leader_election) and a load curve that silently ignored arrival_prob.
Numbers produced by that script measured those handicaps, not the strategies.

This runs the same SimEngine the live backend runs, so a result here is a
statement about the actual system.

Two modes:

  replay  Pull a real logged Gemini decision sequence out of simulation.db and
          replay it against each static strategy. This is the only mode whose
          treatment arm reflects real agent behaviour. Single seed, because a
          decision log is tied to the run that produced it.

  sweep   Run the rule-based selector across many seeds. This is NOT Gemini and
          is labelled as such everywhere it appears. Use it to establish
          whether dynamic switching helps at all before attributing anything
          to the model.

Both arms of every comparison are built from the same seed, and the engine's
split RNG streams guarantee they see identical arrivals and failures. That is
asserted at runtime, not assumed - see `crn_verified` in the output.

Usage:
    python benchmark.py sweep  --seeds 30 --steps 500
    python benchmark.py replay --run-id 43
"""

import argparse
import json
import math
import os
import sqlite3
import statistics
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.api import build_heuristic_selector, build_replay_selector, summarise
from app.scheduler_engine import STRATEGIES, SimEngine

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "simulation.db")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")

# Two-sided 95% critical values, df 1..30; normal approximation beyond that.
T_CRITICAL_95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
    15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056,
    27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}

# Lower is better for these; higher is better for the rest.
LOWER_IS_BETTER = {"avg_queue_len", "max_queue_len", "avg_wait", "avg_turnaround",
                   "avg_fairness_std", "final_fairness_std", "starvation_steps"}

REPORTED = ["avg_queue_len", "avg_wait", "avg_turnaround", "throughput",
            "jobs_completed", "max_queue_len", "avg_fairness_std", "starvation_steps"]


def simulate(strategy, arrival_prob, mean_service, seed, steps, strategy_fn=None):
    engine = SimEngine(
        run_id=0, strategy=strategy, arrival_prob=arrival_prob,
        mean_service=mean_service, seed=seed, record_history=True,
    )
    engine.run_steps(steps, strategy_fn=strategy_fn)
    return engine


def crn_holds(control, treatment):
    """Both arms must have seen the same workload, or the comparison is noise."""
    return (
        control.jobs_arrived == treatment.jobs_arrived
        and [m["num_failed"] for m in control.metrics_history]
        == [m["num_failed"] for m in treatment.metrics_history]
    )


def paired_stats(deltas):
    """Deltas are paired by seed, which is what CRN buys us."""
    n = len(deltas)
    mean = statistics.fmean(deltas)
    if n < 2:
        return {"n": n, "mean": round(mean, 4), "std": None, "ci95": None,
                "seeds_improved": None}
    std = statistics.stdev(deltas)
    crit = T_CRITICAL_95.get(n - 1, 1.96)
    margin = crit * std / math.sqrt(n)
    return {
        "n": n,
        "mean": round(mean, 4),
        "std": round(std, 4),
        "ci95": [round(mean - margin, 4), round(mean + margin, 4)],
        "significant": (mean - margin) * (mean + margin) > 0,
    }


def compare(base_strategy, seeds, steps, arrival_prob, mean_service, selector_factory):
    per_seed, deltas = [], {m: [] for m in REPORTED}
    crn_failures = []

    for seed in seeds:
        control = simulate(base_strategy, arrival_prob, mean_service, seed, steps)
        treatment = simulate(base_strategy, arrival_prob, mean_service, seed, steps,
                             strategy_fn=selector_factory(base_strategy))

        if not crn_holds(control, treatment):
            crn_failures.append(seed)

        c, t = summarise(control), summarise(treatment)
        for metric in REPORTED:
            deltas[metric].append(t[metric] - c[metric])

        per_seed.append({
            "seed": seed,
            "control": c,
            "treatment": t,
            "strategies_used": sorted({m["strategy"] for m in treatment.metrics_history}),
            "steps_diverged": sum(1 for m in treatment.metrics_history
                                  if m["strategy"] != base_strategy),
        })

    summary = {}
    for metric in REPORTED:
        stats = paired_stats(deltas[metric])
        control_mean = statistics.fmean(s["control"][metric] for s in per_seed)
        treatment_mean = statistics.fmean(s["treatment"][metric] for s in per_seed)
        better = sum(
            1 for d in deltas[metric]
            if (d < 0 if metric in LOWER_IS_BETTER else d > 0)
        )
        summary[metric] = {
            "control_mean": round(control_mean, 4),
            "treatment_mean": round(treatment_mean, 4),
            "pct_change": round((treatment_mean - control_mean) / control_mean * 100, 1)
                          if control_mean else None,
            "paired_delta": stats,
            "seeds_treatment_better": better,
            "seeds_total": len(per_seed),
        }

    return {
        "base_strategy": base_strategy,
        "summary": summary,
        "per_seed": per_seed,
        "crn_verified": not crn_failures,
        "crn_failed_seeds": crn_failures,
    }


def load_decision_log(run_id):
    if not os.path.exists(DB_PATH):
        sys.exit(f"No database at {DB_PATH}")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    run = conn.execute("SELECT * FROM run WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        sys.exit(f"Run {run_id} not found in {DB_PATH}")
    rows = conn.execute(
        "SELECT step, strategy FROM geminidecision "
        "WHERE run_id = ? AND action = 'switch_strategy' ORDER BY step",
        (run_id,),
    ).fetchall()
    conn.close()
    log = [{"step": r["step"], "strategy": r["strategy"]}
           for r in rows if r["strategy"] in STRATEGIES]
    return dict(run), log


def run_replay(args):
    run, log = load_decision_log(args.run_id)
    if not log:
        sys.exit(f"Run {args.run_id} has no logged switch_strategy decisions to replay.")

    steps = run["total_steps"] or args.steps
    print(f"Replaying run #{args.run_id}: {len(log)} decisions, seed={run['seed']}, "
          f"arrival_prob={run['arrival_prob']}, mean_service={run['mean_service']}, "
          f"{steps} steps\n")

    results = {}
    for base in STRATEGIES:
        results[base] = compare(
            base, [run["seed"]], steps, run["arrival_prob"], run["mean_service"],
            selector_factory=lambda _b: build_replay_selector(log),
        )

    return {
        "mode": "replay",
        "treatment_source": "real logged Gemini decisions",
        "run_id": args.run_id,
        "config": {
            "seed": run["seed"], "steps": steps,
            "arrival_prob": run["arrival_prob"], "mean_service": run["mean_service"],
            "decisions_replayed": len(log),
        },
        "decision_log": log,
        "results": results,
    }


def run_sweep(args):
    seeds = list(range(1, args.seeds + 1))
    print(f"Sweeping {len(seeds)} seeds x {len(STRATEGIES)} strategies x {args.steps} steps")
    print("Treatment arm is the RULE-BASED selector, not Gemini.\n")

    results = {}
    for base in STRATEGIES:
        results[base] = compare(
            base, seeds, args.steps, args.arrival_prob, args.mean_service,
            selector_factory=lambda b: build_heuristic_selector(b),
        )

    return {
        "mode": "sweep",
        "treatment_source": "rule-based selector (NOT Gemini)",
        "config": {
            "seeds": seeds, "steps": args.steps,
            "arrival_prob": args.arrival_prob, "mean_service": args.mean_service,
        },
        "results": results,
    }


def render_markdown(report):
    is_replay = report["mode"] == "replay"
    cfg = report["config"]
    lines = [
        "# Benchmark Results",
        "",
        f"Generated {report['generated_at']} by `backend/benchmark.py`.",
        "",
        f"**Mode:** `{report['mode']}` — treatment arm is "
        f"**{report['treatment_source']}**.",
        "",
    ]

    if is_replay:
        lines += [
            f"Replaying the decision log of run #{report['run_id']} "
            f"({cfg['decisions_replayed']} decisions) against each static strategy.",
            "",
            "> Single seed. A decision log is tied to the run that produced it, so this "
            "cannot be replicated across seeds. It shows what the agent's *actual* choices "
            "did under CRN-controlled load — not a statistically powered result.",
            "",
            f"Config: seed `{cfg['seed']}`, {cfg['steps']} steps, "
            f"arrival_prob `{cfg['arrival_prob']}`, mean_service `{cfg['mean_service']}`.",
        ]
    else:
        lines += [
            f"{len(cfg['seeds'])} seeds, {cfg['steps']} steps, "
            f"arrival_prob `{cfg['arrival_prob']}`, mean_service `{cfg['mean_service']}`.",
            "",
            "> The treatment arm here is a deterministic rule table, **not** the LLM. "
            "It answers \"does dynamic switching help?\", not \"does Gemini help?\".",
        ]

    all_verified = all(r["crn_verified"] for r in report["results"].values())
    lines += [
        "",
        f"**CRN verified:** {'yes — both arms saw identical arrivals and failures in every pair' if all_verified else 'NO — results are not controlled'}.",
        "",
    ]

    for base, result in report["results"].items():
        s = result["summary"]
        lines += [
            f"## vs static `{base}`",
            "",
            "| Metric | Static | Agent-guided | Change | " +
            ("95% CI of paired delta |" if not is_replay else "Seeds better |"),
            "|---|---|---|---|---|",
        ]
        for metric in REPORTED:
            m = s[metric]
            arrow = "lower is better" if metric in LOWER_IS_BETTER else "higher is better"
            pct = f"{m['pct_change']:+.1f}%" if m["pct_change"] is not None else "—"
            if is_replay:
                last = f"{m['seeds_treatment_better']}/{m['seeds_total']}"
            else:
                ci = m["paired_delta"].get("ci95")
                last = f"[{ci[0]}, {ci[1]}]" if ci else "—"
            lines.append(
                f"| `{metric}` <sub>({arrow})</sub> | {m['control_mean']} | "
                f"{m['treatment_mean']} | {pct} | {last} |"
            )
        diverged = result["per_seed"][0]["steps_diverged"]
        used = result["per_seed"][0]["strategies_used"]
        lines += [
            "",
            f"Treatment arm ran a different strategy than `{base}` for "
            f"{diverged} steps; strategies used: {', '.join(f'`{u}`' for u in used)}.",
            "",
        ]

    if not is_replay:
        lines += [
            "## Reading the CI column",
            "",
            "Deltas are paired by seed, which is what CRN makes valid. A 95% interval "
            "that excludes 0 means the effect is consistent across seeds; one that "
            "spans 0 means it is not distinguishable from seed-to-seed variation, "
            "however large the percentage looks.",
            "",
        ]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)

    sweep = sub.add_parser("sweep", help="multi-seed rule-based selector vs static")
    sweep.add_argument("--seeds", type=int, default=30)
    sweep.add_argument("--steps", type=int, default=500)
    sweep.add_argument("--arrival-prob", type=float, default=0.6)
    sweep.add_argument("--mean-service", type=float, default=8.0)

    replay = sub.add_parser("replay", help="replay a real logged Gemini decision sequence")
    replay.add_argument("--run-id", type=int, required=True)
    replay.add_argument("--steps", type=int, default=200,
                        help="fallback if the run has no recorded total_steps")

    for p in (sweep, replay):
        p.add_argument("--out", default=RESULTS_DIR)

    args = parser.parse_args()
    report = run_sweep(args) if args.mode == "sweep" else run_replay(args)
    report["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    os.makedirs(args.out, exist_ok=True)
    json_path = os.path.join(args.out, f"benchmark_{args.mode}.json")
    md_path = os.path.join(args.out, f"BENCHMARK_{args.mode}.md")

    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(report))

    for base, result in report["results"].items():
        s = result["summary"]
        print(f"vs {base:17s} "
              f"queue {s['avg_queue_len']['pct_change']:+7.1f}%  "
              f"wait {s['avg_wait']['pct_change']:+7.1f}%  "
              f"throughput {s['throughput']['pct_change']:+7.1f}%  "
              f"fairness {s['avg_fairness_std']['pct_change']:+7.1f}%")

    print(f"\nWrote {json_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
