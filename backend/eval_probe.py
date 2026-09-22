"""What decision function is the model actually implementing?

eval_oracle.py scores outcomes. This asks a different and more awkward
question: hold every input fixed but one, sweep that one across its range, and
watch where the model's answer changes. What comes back is the decision
boundary it implements — the if/else it is, whether or not it was written as
one.

Four things get measured, and only the first is about being right:

  boundary      which strategy it picks as each metric varies. If the answer
                never moves, the model is not reading the state at all.
  consistency   the same state asked REPEATS times. Identical input, identical
                question. Anything below 100% is variance a scheduler would
                have to absorb, and it bounds how much of an outcome
                difference can be attributed to judgement rather than noise.
  rule agreement how often it lands on the same strategy as the 12-line rule
                table. This is the "expensive if/else" question, answered with
                a number instead of an opinion.
  cost          schema-validity rate, latency percentiles, tokens per call.

The states here are synthetic, assembled from exactly the keys the prompt
promises (agent_prompt.METRIC_KEYS), so the model cannot distinguish a probe
from a live snapshot.

A note on what this cannot show: a synthetic state has no history, so the
prompt's hysteresis instruction ("hold 20-30 steps before switching") has
nothing to bind to. The `strategy` sweep is the closest available proxy — it
varies only which strategy is currently running and measures how often the
model stays put.

Usage:
    AGENT_PROVIDER=mock python eval_probe.py --repeats 3   # verifies the harness
    python eval_probe.py --repeats 5 --concurrency 4
"""

import argparse
import asyncio
import json
import math
import os
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Model prose routinely contains non-ASCII punctuation, and a Windows console
# defaults to cp1252, which raises on it mid-run. Report files are already
# written as UTF-8; this stops the console from being the weak link.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from app.agent_prompt import METRIC_KEYS
from app.agent_service import request_decision
from app.api import gemini_strategy_selector
from app.config import settings
from app.scheduler_engine import STRATEGIES

RESULTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results"
)

# Everything not being swept is pinned here: a mid-run, unremarkable system.
# Deliberately unremarkable, so that a change in the model's answer is
# attributable to the swept variable and nothing else.
BASE_STATE = {
    "time": 150,
    "queue_len": 10,
    "queue_rate": 0.0,
    "num_failed": 0,
    "fairness_std": 2.0,
    "completed_total": 80,
    "avg_wait": 4.0,
    "strategy": "baseline",
}

SWEEPS = {
    "queue_len": [0, 5, 10, 20, 30, 45, 60, 80],
    "queue_rate": [-3.0, -1.0, 0.0, 1.0, 2.0, 4.0, 6.0],
    "num_failed": [0, 1, 2, 3, 5],
    "fairness_std": [0.0, 1.0, 3.0, 6.0, 9.0, 14.0],
    "strategy": list(STRATEGIES),
}


def state_for(variable: str, value) -> dict:
    state = dict(BASE_STATE)
    state[variable] = value
    assert set(state) == set(METRIC_KEYS), "probe state drifted from the prompt contract"
    return state


def effective_choice(decision: dict, state: dict) -> str:
    """"explain" means hold, which is a choice of the current strategy."""
    if decision["action"] == "explain":
        return state["strategy"]
    return decision["strategy"]


async def probe_point(variable, value, repeats, temperature, semaphore) -> dict:
    state = state_for(variable, value)

    async def once():
        async with semaphore:
            return await request_decision(state, temperature=temperature)

    results = await asyncio.gather(*(once() for _ in range(repeats)))

    valid = [r for r in results if r.ok]
    choices = [effective_choice(r.decision, state) for r in valid]
    held = sum(1 for r in valid if r.decision["action"] == "explain")
    distribution = Counter(choices)
    modal, modal_count = (distribution.most_common(1)[0] if distribution else (None, 0))

    latencies = sorted(r.latency_s for r in results)
    prompt_tok = [r.prompt_tokens for r in valid if r.prompt_tokens is not None]
    out_tok = [r.completion_tokens for r in valid if r.completion_tokens is not None]

    return {
        "variable": variable,
        "value": value,
        "repeats": repeats,
        "valid": len(valid),
        "errors": [r.error for r in results if not r.ok],
        "distribution": dict(distribution),
        "modal_choice": modal,
        # Share of valid answers matching the modal one. 1.0 = deterministic.
        "consistency": round(modal_count / len(valid), 4) if valid else None,
        "held_current": held,
        "rule_choice": gemini_strategy_selector(
            state["queue_len"], state["fairness_std"],
            state["num_failed"], state["queue_rate"],
        ),
        "latency_p50": _percentile(latencies, 50),
        "latency_p95": _percentile(latencies, 95),
        "mean_prompt_tokens": round(statistics.fmean(prompt_tok), 1) if prompt_tok else None,
        "mean_completion_tokens": round(statistics.fmean(out_tok), 1) if out_tok else None,
        "sample_message": valid[0].decision["message"] if valid else None,
    }


def _percentile(sorted_values: List[float], pct: float):
    if not sorted_values:
        return None
    k = (len(sorted_values) - 1) * pct / 100
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return round(sorted_values[int(k)], 3)
    return round(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo), 3)


async def run(args) -> dict:
    semaphore = asyncio.Semaphore(args.concurrency)
    sweeps: Dict[str, List[dict]] = {}

    variables = args.variables or list(SWEEPS)
    for variable in variables:
        if variable not in SWEEPS:
            sys.exit(f"Unknown variable {variable!r}. Expected any of {list(SWEEPS)}")
        print(f"sweeping {variable} ({len(SWEEPS[variable])} points "
              f"x {args.repeats} repeats)", flush=True)
        points = []
        for value in SWEEPS[variable]:
            point = await probe_point(variable, value, args.repeats,
                                      args.temperature, semaphore)
            points.append(point)
            print(f"  {variable}={str(value):<8} -> {point['modal_choice']:<16} "
                  f"consistency {point['consistency']}  "
                  f"(rule: {point['rule_choice']})", flush=True)
        sweeps[variable] = points

    all_points = [p for points in sweeps.values() for p in points]
    valid_points = [p for p in all_points if p["valid"]]

    total_calls = sum(p["repeats"] for p in all_points)
    total_valid = sum(p["valid"] for p in all_points)
    consistencies = [p["consistency"] for p in valid_points if p["consistency"] is not None]
    rule_matches = [p for p in valid_points if p["modal_choice"] == p["rule_choice"]]

    # A sweep whose modal answer never changes means the model ignored that
    # variable. Reported per variable, because ignoring `fairness_std` and
    # ignoring `queue_len` are very different failures.
    responsiveness = {
        variable: {
            "distinct_modal_choices": len({p["modal_choice"] for p in points if p["valid"]}),
            "modal_sequence": [p["modal_choice"] for p in points],
            "responsive": len({p["modal_choice"] for p in points if p["valid"]}) > 1,
        }
        for variable, points in sweeps.items()
    }

    latencies = sorted(p["latency_p50"] for p in all_points if p["latency_p50"] is not None)
    errors = Counter(e for p in all_points for e in p["errors"])

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "config": {
            "provider": settings.AGENT_PROVIDER,
            "model": (settings.OLLAMA_MODEL if settings.AGENT_PROVIDER == "ollama"
                      else settings.GEMINI_MODEL if settings.AGENT_PROVIDER == "gemini"
                      else "rule-table"),
            "temperature": args.temperature,
            "repeats": args.repeats,
            "base_state": BASE_STATE,
            "variables": variables,
        },
        "summary": {
            "total_calls": total_calls,
            "schema_valid": total_valid,
            "schema_valid_rate": round(total_valid / total_calls, 4) if total_calls else None,
            "mean_consistency": round(statistics.fmean(consistencies), 4) if consistencies else None,
            "fully_consistent_points": sum(1 for c in consistencies if c == 1.0),
            "total_points": len(all_points),
            "rule_agreement": round(len(rule_matches) / len(valid_points), 4) if valid_points else None,
            "median_latency_s": _percentile(latencies, 50),
            "p95_latency_s": _percentile(latencies, 95),
            "errors": dict(errors),
        },
        "responsiveness": responsiveness,
        "sweeps": sweeps,
    }


def render_markdown(report: dict) -> str:
    cfg, summary = report["config"], report["summary"]
    lines = [
        "# The decision boundary the model implements",
        "",
        f"Generated {report['generated_at']} by `backend/eval_probe.py`.",
        "",
        f"Model `{cfg['model']}` via `{cfg['provider']}`, temperature {cfg['temperature']}, "
        f"{cfg['repeats']} repeats per point.",
        "",
        "Every input is held fixed but one. Where the answer changes as that one varies is "
        "the boundary the model is implementing. Asking the identical state several times "
        "measures how much of that answer is judgement and how much is sampling noise.",
        "",
        "Base state (the pinned values):",
        "",
        "```json",
        json.dumps(cfg["base_state"], indent=2),
        "```",
        "",
        "## Headline",
        "",
        f"- **Schema-valid responses:** {summary['schema_valid']}/{summary['total_calls']} "
        f"({(summary['schema_valid_rate'] or 0) * 100:.1f}%)",
        f"- **Self-consistency on identical input:** "
        f"{(summary['mean_consistency'] or 0) * 100:.1f}% mean; "
        f"{summary['fully_consistent_points']}/{summary['total_points']} states answered "
        f"the same way every time",
        f"- **Agreement with the 12-line rule table:** "
        f"{(summary['rule_agreement'] or 0) * 100:.1f}%",
        f"- **Latency:** {summary['median_latency_s']}s median, "
        f"{summary['p95_latency_s']}s p95 per decision",
        "",
    ]
    if summary["errors"]:
        lines += ["- **Failures:** " + ", ".join(
            f"`{k}` x{v}" for k, v in summary["errors"].items()), ""]

    lines += ["## Does the model read each input?", "",
              "| Input | distinct answers across its range | reads it? |", "|---|---|---|"]
    for variable, info in report["responsiveness"].items():
        lines.append(
            f"| `{variable}` | {info['distinct_modal_choices']} | "
            f"{'yes' if info['responsive'] else '**no — answer never moved**'} |"
        )
    lines += ["", "An input the answer never responds to is one the model is not using, "
              "whatever its stated reasoning says.", ""]

    for variable, points in report["sweeps"].items():
        lines += [
            f"## Sweeping `{variable}`",
            "",
            "| value | model picks | consistency | held current | rule table picks | agree |",
            "|---|---|---|---|---|---|",
        ]
        for p in points:
            consistency = f"{p['consistency'] * 100:.0f}%" if p["consistency"] is not None else "—"
            spread = "" if len(p["distribution"]) <= 1 else (
                " <sub>" + ", ".join(f"{k}x{v}" for k, v in sorted(p["distribution"].items())) + "</sub>"
            )
            agree = "yes" if p["modal_choice"] == p["rule_choice"] else "no"
            lines.append(
                f"| {p['value']} | `{p['modal_choice']}`{spread} | {consistency} | "
                f"{p['held_current']}/{p['valid']} | `{p['rule_choice']}` | {agree} |"
            )
        lines.append("")

    lines += [
        "## How to read this",
        "",
        "- **Consistency below 100%** is the cost of putting a sampled model in a control "
        "loop: the same system state can produce different actions. Any outcome difference "
        "smaller than this variance cannot be attributed to the model's judgement.",
        "- **High rule agreement** means the model is reproducing a rule table that runs in "
        "microseconds for free. **Low agreement** is only interesting if the outcome "
        "numbers in `EVAL_oracle.md` show the disagreement paid off.",
        "- **An input the answer never moves with** is an input the model is ignoring, "
        "regardless of what its `message` field claims to have considered.",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repeats", type=int, default=5,
                        help="calls per state; >1 is what measures self-consistency")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--variables", nargs="*", default=None,
                        help=f"subset of {list(SWEEPS)}")
    parser.add_argument("--out", default=RESULTS_DIR)
    parser.add_argument("--tag", default="probe")
    args = parser.parse_args()

    report = asyncio.run(run(args))

    os.makedirs(args.out, exist_ok=True)
    json_path = os.path.join(args.out, f"eval_{args.tag}.json")
    md_path = os.path.join(args.out, f"EVAL_{args.tag}.md")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(report))

    s = report["summary"]
    print(f"\n  schema valid    {s['schema_valid']}/{s['total_calls']}")
    print(f"  consistency     {(s['mean_consistency'] or 0) * 100:.1f}%")
    print(f"  rule agreement  {(s['rule_agreement'] or 0) * 100:.1f}%")
    print(f"  latency p50/p95 {s['median_latency_s']}s / {s['p95_latency_s']}s")
    print(f"\nWrote {json_path}\nWrote {md_path}")


if __name__ == "__main__":
    main()
