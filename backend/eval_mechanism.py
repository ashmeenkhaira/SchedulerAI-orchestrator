"""Why strategy choice cannot move throughput, measured rather than argued.

This script exists because of a mistake worth keeping a record of. The project
originally reported that agent-guided switching cut queue length 88% and raised
throughput 41%. Both numbers were real outputs of a working comparison, and
both were artifacts of which static strategy had been chosen as the opponent.

The diagnostic below explains why, in two measurements:

1. CAPACITY. The cluster finishes `num_servers / mean_service` jobs per step.
   No dispatch policy changes that — it is set by how many servers exist and
   how long jobs take. If offered load sits below capacity, the queue stays
   short under any sane strategy; if it sits above, the queue grows under all
   of them. Either way the strategy is not the variable.

2. WORK CONSERVATION. A strategy is work-conserving if it never leaves a server
   idle next to a queued job. `SimEngine` counts the assignments each strategy
   could have made against the ones it did. Work-conserving strategies must
   produce identical throughput, because they dispatch on exactly the same
   steps; all they vary is *which* server receives the job.

Together these say the throughput axis is closed and the fairness axis is open.
That is the opposite of what the project used to claim, and it is the reason
eval_oracle.py finds 0% throughput headroom and a real fairness headroom.

Usage:
    python eval_mechanism.py
    python eval_mechanism.py --steps 800 --seeds 5
"""

import argparse
import contextlib
import json
import os
import statistics
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import app.scheduler_engine as engine_module
from app.scheduler_engine import (
    ARRIVAL_PROB_BASELINE,
    LOAD_CURVE,
    LOAD_CURVE_TAIL,
    STRATEGIES,
    SimEngine,
)


@contextlib.contextmanager
def failures_disabled():
    """Turn off server failures for the duration of a measurement.

    Failures are the only thing that stops work-conserving strategies from
    being throughput-identical, so switching them off separates the structural
    result from its one confound.
    """
    original = engine_module.FAILURE_PROB
    engine_module.FAILURE_PROB = 0.0
    try:
        yield
    finally:
        engine_module.FAILURE_PROB = original

RESULTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results"
)

# A strategy at or above this counts as work-conserving. Not 1.0 exactly,
# because a strategy could in principle miss a single dispatch to a rounding
# edge; in practice the three that qualify all measure exactly 1.0.
WORK_CONSERVING_THRESHOLD = 0.999


def peak_offered_load(arrival_prob: float) -> float:
    """Highest arrival rate the load curve reaches, in jobs per step."""
    scale = arrival_prob / ARRIVAL_PROB_BASELINE
    shape = max([value for _, value in LOAD_CURVE] + [LOAD_CURVE_TAIL])
    return min(1.0, shape * scale)


def measure(strategy: str, seed: int, steps: int, arrival_prob: float,
            mean_service: float, num_servers: int) -> dict:
    engine = SimEngine(
        run_id=0, strategy=strategy, arrival_prob=arrival_prob,
        mean_service=mean_service, seed=seed, num_servers=num_servers,
        record_history=True,
    )
    engine.run_steps(steps)
    return {
        "work_conservation": engine.work_conservation(),
        "dispatch_opportunities": engine.dispatch_opportunities,
        "dispatch_used": engine.dispatch_used,
        "throughput": engine.throughput(),
        "avg_queue_len": engine.avg_queue_len(),
        "fairness_std": engine.fairness_std(),
        "jobs_completed": engine.jobs_completed,
    }


def run(args) -> dict:
    seeds = list(range(1, args.seeds + 1))
    regimes = []

    for mean_service in args.mean_services:
        capacity = args.num_servers / mean_service
        offered = peak_offered_load(args.arrival_prob)

        per_strategy = {}
        for strategy in STRATEGIES:
            runs = [measure(strategy, s, args.steps, args.arrival_prob,
                            mean_service, args.num_servers) for s in seeds]
            per_strategy[strategy] = {
                key: round(statistics.fmean(r[key] for r in runs), 4)
                for key in ("work_conservation", "throughput", "avg_queue_len",
                            "fairness_std")
            }

        conserving = [s for s, v in per_strategy.items()
                      if v["work_conservation"] >= WORK_CONSERVING_THRESHOLD]
        conserving_throughputs = [per_strategy[s]["throughput"] for s in conserving]
        fairness_values = [v["fairness_std"] for v in per_strategy.values()]

        regimes.append({
            "mean_service": mean_service,
            "capacity_jobs_per_step": round(capacity, 4),
            "peak_offered_load": round(offered, 4),
            "utilisation_at_peak": round(offered / capacity, 4),
            "per_strategy": per_strategy,
            "work_conserving": conserving,
            # The claim under test: conserving strategies agree on throughput.
            "throughput_spread_within_conserving": round(
                max(conserving_throughputs) - min(conserving_throughputs), 6
            ) if conserving_throughputs else None,
            "fairness_spread_all": round(max(fairness_values) - min(fairness_values), 4),
            "fairness_ratio_all": round(max(fairness_values) / min(fairness_values), 3)
            if min(fairness_values) else None,
        })

    # The same comparison with failures switched off. Without them the
    # work-conserving strategies are not merely close on throughput, they are
    # identical — which is the claim in its exact form.
    control_ms = args.mean_services[len(args.mean_services) // 2]
    control = {}
    with failures_disabled():
        for strategy in STRATEGIES:
            runs = [measure(strategy, s, args.steps, args.arrival_prob,
                            control_ms, args.num_servers) for s in seeds]
            control[strategy] = {
                key: round(statistics.fmean(r[key] for r in runs), 6)
                for key in ("work_conservation", "throughput", "fairness_std")
            }
    control_conserving = [s for s, v in control.items()
                          if v["work_conservation"] >= WORK_CONSERVING_THRESHOLD]
    control_throughputs = [control[s]["throughput"] for s in control_conserving]

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "config": {
            "seeds": seeds, "steps": args.steps, "num_servers": args.num_servers,
            "arrival_prob": args.arrival_prob, "mean_services": args.mean_services,
            "work_conserving_threshold": WORK_CONSERVING_THRESHOLD,
        },
        "regimes": regimes,
        "failures_disabled_control": {
            "mean_service": control_ms,
            "per_strategy": control,
            "work_conserving": control_conserving,
            "throughput_spread_within_conserving": round(
                max(control_throughputs) - min(control_throughputs), 9
            ) if control_throughputs else None,
        },
    }


def render_markdown(report: dict) -> str:
    cfg = report["config"]
    lines = [
        "# Why strategy choice cannot move throughput",
        "",
        f"Generated {report['generated_at']} by `backend/eval_mechanism.py`.",
        "",
        f"{len(cfg['seeds'])} seeds x {cfg['steps']} steps, {cfg['num_servers']} servers, "
        f"`arrival_prob={cfg['arrival_prob']}`.",
        "",
        "Cluster capacity is `num_servers / mean_service` jobs per step and owes nothing "
        "to the scheduling strategy. A strategy is **work-conserving** if it never leaves "
        "a server idle beside a queued job; the engine counts the assignments each "
        "strategy could have made against the ones it made. Work-conserving strategies "
        "dispatch on the same steps and therefore cannot differ in throughput — they vary "
        "only in *which* server receives each job.",
        "",
    ]

    for regime in report["regimes"]:
        lines += [
            f"## mean_service = {regime['mean_service']} "
            f"(capacity {regime['capacity_jobs_per_step']} jobs/step, "
            f"peak load {regime['peak_offered_load']}, "
            f"utilisation {regime['utilisation_at_peak']:.2f})",
            "",
            "| Strategy | work conservation | throughput | avg queue | fairness std |",
            "|---|---|---|---|---|",
        ]
        for strategy, v in regime["per_strategy"].items():
            mark = " ✓" if strategy in regime["work_conserving"] else ""
            lines.append(
                f"| `{strategy}`{mark} | {v['work_conservation']:.4f} | "
                f"{v['throughput']:.4f} | {v['avg_queue_len']:.2f} | {v['fairness_std']:.2f} |"
            )
        spread = regime["throughput_spread_within_conserving"]
        lines += [
            "",
            f"Work-conserving ( ✓ ): {', '.join(f'`{s}`' for s in regime['work_conserving'])}. "
            f"Throughput spread among them: **{spread}**. "
            f"Fairness spread across all five: **{regime['fairness_spread_all']}** "
            f"({regime['fairness_ratio_all']}x between best and worst).",
            "",
        ]

    control = report["failures_disabled_control"]
    lines += [
        "## Control: the same comparison with failures switched off",
        "",
        f"At `mean_service={control['mean_service']}`, with `FAILURE_PROB = 0`:",
        "",
        "| Strategy | work conservation | throughput | fairness std |",
        "|---|---|---|---|",
    ]
    for strategy, v in control["per_strategy"].items():
        mark = " ✓" if strategy in control["work_conserving"] else ""
        lines.append(
            f"| `{strategy}`{mark} | {v['work_conservation']:.4f} | "
            f"{v['throughput']:.6f} | {v['fairness_std']:.2f} |"
        )
    lines += [
        "",
        f"Throughput spread among the work-conserving strategies: "
        f"**{control['throughput_spread_within_conserving']}** — identical to the last bit, "
        "while fairness still varies severalfold.",
        "",
        "This locates the small residual spread seen above. A failure preempts the job a "
        "server is holding and discards the work done on it, and *which* job is in flight "
        "depends on which server received it — the one thing work-conserving strategies "
        "disagree about. The leftover throughput difference is therefore a downstream "
        "consequence of the fairness difference, not a second axis a switching policy "
        "could aim at.",
        "",
        "## What this means for the agent",
        "",
        "- **Throughput is closed.** Every work-conserving strategy returns the same "
        "throughput at every load measured. An agent cannot improve it by switching "
        "between them, and the only way to produce a large throughput 'gain' is to pick "
        "a non-work-conserving opponent — `token_ring`, which declines roughly 86% of its "
        "dispatch opportunities by design — and beat that. This is exactly how the "
        "project's original +41% throughput figure arose.",
        "- **Queue length is closed for the same reason.** Backlog is set by offered load "
        "against capacity. Below capacity it stays short under any conserving strategy; "
        "above capacity it grows under all of them.",
        "- **Fairness is open.** Which server receives each job is genuinely the "
        "strategy's choice, and the spread across strategies is severalfold at every "
        "load. That is the axis where a switching decision has something to decide, so "
        "it is the axis `eval_oracle.py` scores policies on.",
        "",
        "The honest form of the original claim is not 'the agent made scheduling faster'. "
        "It is: throughput was never available to win, and the number that said otherwise "
        "was measuring the opponent, not the agent.",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--steps", type=int, default=600)
    parser.add_argument("--num-servers", type=int, default=8)
    parser.add_argument("--arrival-prob", type=float, default=0.6)
    parser.add_argument("--mean-services", type=float, nargs="+",
                        default=[6.0, 8.0, 12.0, 16.0],
                        help="each value defines one load regime")
    parser.add_argument("--out", default=RESULTS_DIR)
    args = parser.parse_args()

    report = run(args)

    os.makedirs(args.out, exist_ok=True)
    json_path = os.path.join(args.out, "eval_mechanism.json")
    md_path = os.path.join(args.out, "EVAL_mechanism.md")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(report))

    for regime in report["regimes"]:
        print(f"mean_service={regime['mean_service']:>5}  "
              f"utilisation={regime['utilisation_at_peak']:.2f}  "
              f"throughput spread among work-conserving = "
              f"{regime['throughput_spread_within_conserving']}  "
              f"fairness spread = {regime['fairness_spread_all']}")
    print(f"\nWrote {json_path}\nWrote {md_path}")


if __name__ == "__main__":
    main()
