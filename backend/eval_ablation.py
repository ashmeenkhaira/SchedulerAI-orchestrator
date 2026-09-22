"""Ablations: which part of the system is actually producing the decisions?

`eval_oracle.py` says the agent underperforms. `eval_probe.py` says it reads
queue_rate and ignores queue_len. Neither says *why*, and "the model is bad at
this" is not a finding, it is a shrug. These ablations remove one component at
a time and measure what changes.

  prompt       full vs. the same prompt with token_ring's throughput ceiling
               removed vs. strategy names only. The full prompt hands over a
               lot of the answer; a model following it faithfully looks like it
               is reasoning about scheduling when it may be reciting a brief.
               If `minimal` behaves like `full`, the prompt engineering is not
               what is producing the decisions. If the fairness -> token_ring
               boundary disappears under `no_ceiling`, that boundary was the
               hint rather than a judgement about fairness.

  inputs       drop one metric from the state at a time. The probe found the
               model acting on queue_rate and not queue_len; this tests that
               directly. If removing queue_rate makes it start reacting to
               queue_len, the ordering was deliberate. If nothing changes, it
               was not reading either.

  temperature  0.0 / 0.7 / 1.0 over identical states. The probe measured 85.2%
               self-consistency at 0.7. This asks what that costs and whether
               sampling is where the variance comes from — a control loop that
               takes different actions in identical states has a problem that
               is fixable at the call site rather than in the model.

States are fixed across every condition so that a difference is attributable to
the ablated component and nothing else. Two of them are deliberate conflicts,
where fairness and throughput point opposite ways — those are where a judgement
call is actually being made.

Usage:
    AGENT_PROVIDER=mock python eval_ablation.py --mode prompt --repeats 2
    python eval_ablation.py --mode prompt --repeats 3
    python eval_ablation.py --mode inputs --repeats 3
    python eval_ablation.py --mode temperature --repeats 5
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from app.agent_prompt import METRIC_KEYS, PROMPT_VARIANTS, SYSTEM_PROMPT
from app.agent_service import request_decision
from app.api import gemini_strategy_selector
from app.config import settings

RESULTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results"
)

# Fixed across every condition. The last two are the ones worth watching: they
# pit fairness against throughput, which is the only place a real judgement
# call exists.
STATES = {
    "idle": dict(queue_len=0, queue_rate=0.0, num_failed=0, fairness_std=0.5),
    "light_stable": dict(queue_len=8, queue_rate=0.0, num_failed=0, fairness_std=2.0),
    "deep_stable": dict(queue_len=60, queue_rate=0.0, num_failed=0, fairness_std=2.0),
    "growing": dict(queue_len=15, queue_rate=3.0, num_failed=0, fairness_std=2.0),
    "draining": dict(queue_len=25, queue_rate=-2.0, num_failed=0, fairness_std=2.0),
    "failures": dict(queue_len=15, queue_rate=0.5, num_failed=3, fairness_std=2.0),
    # Conflict 1: fairness is bad, but the queue is calm, so acting is safe.
    "unfair_calm": dict(queue_len=10, queue_rate=0.0, num_failed=0, fairness_std=10.0),
    # Conflict 2: fairness is bad AND the queue is growing. The prompt says
    # throughput wins here. token_ring would be the wrong answer.
    "unfair_growing": dict(queue_len=30, queue_rate=3.0, num_failed=0, fairness_std=10.0),
}

DROPPABLE = ["queue_len", "queue_rate", "num_failed", "fairness_std", "avg_wait"]

TEMPERATURES = [0.0, 0.7, 1.0]


def build_state(name: str, drop: str = None) -> dict:
    state = {
        "time": 150,
        "completed_total": 80,
        "avg_wait": 4.0,
        "strategy": "baseline",
        **STATES[name],
    }
    assert set(state) == set(METRIC_KEYS), "ablation state drifted from the prompt contract"
    if drop:
        state.pop(drop)
    return state


def choice_of(decision: dict, state: dict) -> str:
    if decision["action"] == "explain":
        return state.get("strategy", "baseline")
    return decision["strategy"]


async def ask(state, repeats, temperature, prompt, semaphore) -> dict:
    async def once():
        async with semaphore:
            return await request_decision(state, temperature=temperature,
                                          system_prompt=prompt)

    results = await asyncio.gather(*(once() for _ in range(repeats)))
    valid = [r for r in results if r.ok]
    choices = [choice_of(r.decision, state) for r in valid]
    distribution = Counter(choices)
    modal, count = (distribution.most_common(1)[0] if distribution else (None, 0))
    return {
        "modal_choice": modal,
        "distribution": dict(distribution),
        "consistency": round(count / len(valid), 4) if valid else None,
        "valid": len(valid),
        "repeats": repeats,
        "errors": [r.error for r in results if not r.ok],
        "mean_latency_s": round(statistics.fmean(r.latency_s for r in results), 3),
        "held": sum(1 for r in valid if r.decision["action"] == "explain"),
        "sample_message": valid[0].decision["message"] if valid else None,
    }


async def run_conditions(conditions: List[tuple], args) -> dict:
    """`conditions` is a list of (label, prompt, temperature, drop)."""
    semaphore = asyncio.Semaphore(args.concurrency)
    results: Dict[str, Dict[str, dict]] = {}

    for label, prompt, temperature, drop in conditions:
        print(f"\ncondition: {label}", flush=True)
        per_state = {}
        for state_name in STATES:
            state = build_state(state_name, drop)
            outcome = await ask(state, args.repeats, temperature, prompt, semaphore)
            per_state[state_name] = outcome
            print(f"  {state_name:<16} -> {str(outcome['modal_choice']):<16} "
                  f"consistency {outcome['consistency']}", flush=True)
        results[label] = per_state
    return results


def compare_to_reference(results: dict, reference_label: str) -> dict:
    """How far each condition moved from the reference condition."""
    reference = results[reference_label]
    comparison = {}
    for label, per_state in results.items():
        if label == reference_label:
            continue
        changed = [
            name for name, outcome in per_state.items()
            if outcome["modal_choice"] != reference[name]["modal_choice"]
        ]
        comparison[label] = {
            "states_changed": sorted(changed),
            "agreement_with_reference": round(
                1 - len(changed) / len(per_state), 4) if per_state else None,
        }
    return comparison


def render_markdown(report: dict) -> str:
    cfg = report["config"]
    mode = cfg["mode"]
    lines = [
        f"# Ablation: `{mode}`",
        "",
        f"Generated {report['generated_at']} by `backend/eval_ablation.py`.",
        "",
        f"Model `{cfg['model']}` via `{cfg['provider']}`, {cfg['repeats']} repeats "
        f"per state, {len(STATES)} fixed states.",
        "",
        cfg["blurb"],
        "",
        "## Modal choice per state",
        "",
        "| State | " + " | ".join(f"`{c}`" for c in report["conditions"]) + " |",
        "|---" * (len(report["conditions"]) + 1) + "|",
    ]
    for state_name in STATES:
        cells = []
        for label in report["conditions"]:
            outcome = report["results"][label][state_name]
            cell = f"`{outcome['modal_choice']}`"
            if outcome["consistency"] is not None and outcome["consistency"] < 1.0:
                cell += f" <sub>{outcome['consistency'] * 100:.0f}%</sub>"
            cells.append(cell)
        lines.append(f"| `{state_name}` | " + " | ".join(cells) + " |")

    lines += ["", "Superscript is self-consistency where it was below 100%.", ""]

    if report.get("comparison"):
        reference = report["reference"]
        lines += [
            f"## Divergence from `{reference}`",
            "",
            "| Condition | agreement | states whose answer changed |",
            "|---|---|---|",
        ]
        for label, info in report["comparison"].items():
            changed = ", ".join(f"`{s}`" for s in info["states_changed"]) or "none"
            lines.append(
                f"| `{label}` | {info['agreement_with_reference'] * 100:.0f}% | {changed} |"
            )
        lines.append("")

    lines += ["## Mean self-consistency per condition", "",
              "| Condition | mean consistency | fully consistent states |", "|---|---|---|"]
    for label in report["conditions"]:
        values = [o["consistency"] for o in report["results"][label].values()
                  if o["consistency"] is not None]
        full = sum(1 for v in values if v == 1.0)
        lines.append(
            f"| `{label}` | {statistics.fmean(values) * 100:.1f}% | {full}/{len(values)} |"
            if values else f"| `{label}` | — | — |"
        )
    lines.append("")

    lines += [
        "## Rule table, for reference",
        "",
        "| State | rule table picks |",
        "|---|---|",
    ]
    for state_name in STATES:
        state = build_state(state_name)
        lines.append(
            f"| `{state_name}` | `{gemini_strategy_selector(state['queue_len'], state['fairness_std'], state['num_failed'], state['queue_rate'])}` |"
        )
    lines.append("")
    return "\n".join(lines)


BLURBS = {
    "prompt": (
        "Each column is the same model on the same states with a different system "
        "prompt. `full` is what the live system ships. `no_ceiling` describes "
        "`token_ring` without handing over its throughput ceiling. `minimal` gives "
        "strategy names and the output contract only. If `minimal` matches `full`, "
        "the prompt engineering is not what is producing the decisions."
    ),
    "inputs": (
        "Each column removes one metric from the state entirely. `full` keeps all of "
        "them. The probe found the model acting on `queue_rate` while ignoring "
        "`queue_len`; if dropping `queue_rate` makes it start reacting to "
        "`queue_len`, that ordering was deliberate rather than inattention."
    ),
    "temperature": (
        "Each column is a different sampling temperature over identical states. "
        "A control loop that takes different actions in identical states has a "
        "problem; this asks whether it is fixable at the call site."
    ),
}


async def main_async(args) -> dict:
    if args.mode == "prompt":
        conditions = [(name, prompt, args.temperature, None)
                      for name, prompt in PROMPT_VARIANTS.items()]
        reference = "full"
    elif args.mode == "inputs":
        conditions = [("full", SYSTEM_PROMPT, args.temperature, None)]
        conditions += [(f"drop_{d}", SYSTEM_PROMPT, args.temperature, d)
                       for d in DROPPABLE]
        reference = "full"
    else:
        conditions = [(f"temp_{t}", SYSTEM_PROMPT, t, None) for t in TEMPERATURES]
        reference = f"temp_{args.temperature}"
        if reference not in [c[0] for c in conditions]:
            reference = conditions[0][0]

    results = await run_conditions(conditions, args)
    labels = [c[0] for c in conditions]

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "config": {
            "mode": args.mode,
            "provider": settings.AGENT_PROVIDER,
            "model": (settings.OLLAMA_MODEL if settings.AGENT_PROVIDER == "ollama"
                      else settings.GEMINI_MODEL if settings.AGENT_PROVIDER == "gemini"
                      else "rule-table"),
            "repeats": args.repeats,
            "temperature": args.temperature,
            "blurb": BLURBS[args.mode],
        },
        "conditions": labels,
        "reference": reference,
        "results": results,
        "comparison": compare_to_reference(results, reference),
        "states": {name: build_state(name) for name in STATES},
    }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", required=True, choices=["prompt", "inputs", "temperature"])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--out", default=RESULTS_DIR)
    args = parser.parse_args()

    report = asyncio.run(main_async(args))

    os.makedirs(args.out, exist_ok=True)
    json_path = os.path.join(args.out, f"eval_ablation_{args.mode}.json")
    md_path = os.path.join(args.out, f"EVAL_ablation_{args.mode}.md")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(report))

    print(f"\nDivergence from `{report['reference']}`:")
    for label, info in report["comparison"].items():
        print(f"  {label:<20} agreement {info['agreement_with_reference'] * 100:5.1f}%  "
              f"changed: {', '.join(info['states_changed']) or 'none'}")
    print(f"\nWrote {json_path}\nWrote {md_path}")


if __name__ == "__main__":
    main()
