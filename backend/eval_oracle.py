"""How much is the switching decision actually worth, and who captures it?

The question this project used to ask was "does the LLM beat a static
strategy?", which is unanswerable as posed: the answer depends entirely on
which static strategy you pick as the opponent, and picking the worst one
flatters the agent. This asks a better-posed question instead.

Every policy below faces the same decision at the same cadence from the same
CRN-controlled workload, and differs only in how it chooses:

  static:<s>  never switches. Five of these; the best is the bar to clear.
  random      uniform over the five strategies. The "is this better than
              noise?" control. A policy that cannot beat this has learned
              nothing, whatever its percentage improvements look like.
  rule        a 12-line rule table. The "is the LLM an expensive if/else?"
              control, and the one that matters most in an interview.
  oracle      greedy lookahead: at each decision point it forks the live state
              once per candidate strategy, runs each fork forward `horizon`
              steps under the identical arrival and failure sequence, and
              takes the argmax. It sees the future; no deployable policy can.
  agent       the LLM, via whichever provider AGENT_PROVIDER names.

The oracle is the point of the exercise. It converts "the agent improved
queue length by N%" — a number that means nothing without knowing what was
available — into "the agent captured N% of the improvement that was there to
capture". If the oracle itself barely beats the best static strategy, then
there was no headroom, and *no* switching policy could have helped. That is a
real finding about the problem, and it is invisible to a two-arm comparison.

IMPORTANT, and stated plainly because an interviewer will ask:
  - The oracle is greedy over one horizon, not globally optimal. A cleverer
    policy could in principle beat it. It is a strong reference, not a proven
    ceiling.
  - It has perfect foresight of arrivals and failures. It is deliberately
    unfair. Its job is to bound the prize, not to be a fair opponent.
  - Its ranking depends on the objective it maximises, which is a judgement
    call, so two objectives are reported (see OBJECTIVES). Where they disagree,
    the disagreement is the result.

Usage:
    python eval_oracle.py --policies static,random,rule --seeds 10
    python eval_oracle.py --policies all --seeds 5        # includes the model
"""

import argparse
import asyncio
import json
import math
import os
import random
import statistics
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# See eval_probe.py: a cp1252 console raises on the punctuation these models
# emit, which would kill a sweep partway through.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from app.agent_prompt import METRIC_KEYS
from app.agent_service import request_decision
from app.api import gemini_strategy_selector, summarise
from app.config import settings
from app.scheduler_engine import STRATEGIES, SimEngine

RESULTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results"
)

# Lower is better for these; higher for the rest.
LOWER_IS_BETTER = {"avg_queue_len", "max_queue_len", "avg_wait", "avg_turnaround",
                   "avg_fairness_std", "final_fairness_std", "starvation_steps"}

REPORTED = ["avg_queue_len", "avg_wait", "throughput", "avg_fairness_std"]

# Two-sided 95% critical values, df 1..30; normal approximation beyond.
T_CRITICAL_95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
    15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056,
    27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}


def paired_ci(deltas: List[float]) -> dict:
    """95% interval on a per-seed paired difference.

    Pairing is what CRN buys: both policies met the identical workload on each
    seed, so the seed-to-seed variation cancels. An interval spanning 0 means
    the difference is not distinguishable from seed noise — however large the
    percentage in the outcome table looks.
    """
    n = len(deltas)
    mean = statistics.fmean(deltas) if deltas else 0.0
    if n < 2:
        return {"n": n, "mean": round(mean, 4), "ci95": None, "significant": None}
    spread = statistics.stdev(deltas)
    margin = T_CRITICAL_95.get(n - 1, 1.96) * spread / math.sqrt(n)
    low, high = mean - margin, mean + margin
    return {
        "n": n,
        "mean": round(mean, 4),
        "ci95": [round(low, 4), round(high, 4)],
        "significant": low * high > 0,
    }

# The oracle's edge over the best static strategy must be at least this
# fraction of the best static value before it is worth normalising against.
# Relative rather than absolute: a headroom of 0.07 jobs is negligible when the
# best static sits at 2.5 and substantial when it sits at 0.5. Dividing by a
# negligible headroom turns rounding noise into four-digit percentages, so
# below the threshold the result is reported as "no headroom" instead — which
# is the finding, not a failure to compute one.
HEADROOM_MIN_RELATIVE = 0.05


# --- Objectives -------------------------------------------------------------
#
# What the oracle maximises over a lookahead window. Higher is better in both.
# FAIRNESS_WEIGHT is a judgement call, not a derived constant, which is exactly
# why both objectives are reported rather than one being declared correct.

FAIRNESS_WEIGHT = 1.0


def objective_queue(parent: SimEngine, fork: SimEngine) -> float:
    """Backlog only. Ignores fairness entirely, so it will never choose
    token_ring — which is correct under this objective and is the reason the
    second objective exists."""
    return -fork.avg_queue_len()


def objective_balanced(parent: SimEngine, fork: SimEngine) -> float:
    """Backlog plus imbalance, in the same units the prompt asks the agent to
    trade off. Scoring the agent only on queue length while the prompt tells it
    to weigh fairness would measure the gap between the prompt and the metric,
    not the agent."""
    return -(fork.avg_queue_len() + FAIRNESS_WEIGHT * fork.fairness_std())


def objective_fairness(parent: SimEngine, fork: SimEngine) -> float:
    """Imbalance only.

    This is the objective with something to optimise. Backlog is governed by
    capacity and work conservation, not by dispatch policy — see
    eval_mechanism.py — so the strategies that differ on queue length are
    exactly the ones that decline to dispatch. Which server receives a job is
    the part the strategy genuinely controls, and it varies severalfold.
    """
    return -fork.fairness_std()


OBJECTIVES = {
    "queue": objective_queue,
    "balanced": objective_balanced,
    "fairness": objective_fairness,
}


def lookahead_choice(engine: SimEngine, horizon: int, objective) -> str:
    """Fork once per strategy, run each forward, return the best.

    test_engine.py::test_forks_see_identical_workload_whatever_strategy_they_run
    pins the property this depends on: the forks differ by strategy alone.
    """
    best, best_score = engine.strategy, -math.inf
    for candidate in STRATEGIES:
        fork = engine.fork(candidate)
        fork.run_steps(horizon)
        score = objective(engine, fork)
        if score > best_score:
            best, best_score = candidate, score
    return best


# --- Policies ---------------------------------------------------------------

class Policy:
    """Asked for a strategy at each decision point. Async because one of the
    implementations is a network call and the rest must share its interface."""

    requires_model = False

    def __init__(self, name: str):
        self.name = name

    async def choose(self, engine: SimEngine, state: dict) -> Optional[str]:
        raise NotImplementedError

    def telemetry(self) -> dict:
        return {}


class StaticPolicy(Policy):
    def __init__(self, strategy: str):
        super().__init__(f"static:{strategy}")
        self.strategy = strategy

    async def choose(self, engine, state):
        return self.strategy


class RandomPolicy(Policy):
    """Its own RNG, deliberately not one of the engine's streams — drawing from
    those would perturb the arrival or failure sequence and break CRN."""

    def __init__(self, seed: int):
        super().__init__("random")
        self.rng = random.Random(seed * 7919 + 13)

    async def choose(self, engine, state):
        return self.rng.choice(STRATEGIES)


class RulePolicy(Policy):
    def __init__(self):
        super().__init__("rule")

    async def choose(self, engine, state):
        return gemini_strategy_selector(
            state["queue_len"], state["fairness_std"],
            state["num_failed"], state["queue_rate"],
        )


class OraclePolicy(Policy):
    def __init__(self, horizon: int, objective_name: str):
        super().__init__(f"oracle:{objective_name}")
        self.horizon = horizon
        self.objective = OBJECTIVES[objective_name]

    async def choose(self, engine, state):
        return lookahead_choice(engine, self.horizon, self.objective)


class AgentPolicy(Policy):
    """The LLM. Records every call's outcome, including the failures: a policy
    that silently falls back to holding on error would otherwise be scored as
    if it had decided to hold."""

    requires_model = True

    def __init__(self, temperature: float):
        super().__init__("agent")
        self.temperature = temperature
        self.calls: List[dict] = []

    async def choose(self, engine, state):
        result = await request_decision(state, temperature=self.temperature)
        self.calls.append({
            "step": state["time"],
            "ok": result.ok,
            "error": result.error,
            "latency_s": round(result.latency_s, 3),
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "action": (result.decision or {}).get("action"),
            "strategy": (result.decision or {}).get("strategy"),
        })
        if not result.ok:
            return None  # hold; counted separately as a failed call
        if result.decision["action"] == "explain":
            return None  # the agent chose to hold
        return result.decision["strategy"]

    def telemetry(self) -> dict:
        latencies = sorted(c["latency_s"] for c in self.calls)
        ok = [c for c in self.calls if c["ok"]]
        prompt_tok = [c["prompt_tokens"] for c in ok if c["prompt_tokens"] is not None]
        out_tok = [c["completion_tokens"] for c in ok if c["completion_tokens"] is not None]
        return {
            "calls": len(self.calls),
            "ok": len(ok),
            "failed": len(self.calls) - len(ok),
            "schema_ok_rate": round(len(ok) / len(self.calls), 4) if self.calls else None,
            "errors": sorted({c["error"] for c in self.calls if c["error"]}),
            "latency_s": {
                "p50": _percentile(latencies, 50),
                "p95": _percentile(latencies, 95),
                "total": round(sum(latencies), 2),
            },
            "mean_prompt_tokens": round(statistics.fmean(prompt_tok), 1) if prompt_tok else None,
            "mean_completion_tokens": round(statistics.fmean(out_tok), 1) if out_tok else None,
            "holds": sum(1 for c in ok if c["action"] == "explain"),
            "switches": sum(1 for c in ok if c["action"] == "switch_strategy"),
        }


def _percentile(sorted_values: List[float], pct: float) -> Optional[float]:
    if not sorted_values:
        return None
    k = (len(sorted_values) - 1) * pct / 100
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return round(sorted_values[int(k)], 3)
    return round(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo), 3)


# --- Driver -----------------------------------------------------------------

def snapshot(engine: SimEngine) -> dict:
    """Exactly the keys the agent is promised in the prompt, so a probe state
    and a live state are indistinguishable to the model."""
    state = {
        "time": engine.time_step,
        "queue_len": len(engine.queue),
        "queue_rate": round(engine.queue_rate, 3),
        "num_failed": sum(1 for s in engine.servers if s.failed),
        "fairness_std": round(engine.fairness_std(), 3),
        "completed_total": engine.jobs_completed,
        "avg_wait": round(engine.avg_wait(), 2),
        "strategy": engine.strategy,
    }
    assert set(state) == set(METRIC_KEYS), "snapshot drifted from the documented contract"
    return state


async def run_policy(policy: Policy, base_strategy: str, seed: int, steps: int,
                     interval: int, arrival_prob: float, mean_service: float,
                     horizon: int, reference_objective: str) -> dict:
    """One policy, one seed. Also records what a lookahead would have chosen at
    each decision point along *this* policy's own trajectory, which is what
    makes the agreement figure meaningful: it asks "given where you actually
    were, did you choose what foresight would have chosen?"."""
    engine = SimEngine(
        run_id=0, strategy=base_strategy, arrival_prob=arrival_prob,
        mean_service=mean_service, seed=seed,
        num_servers=settings.NUM_SERVERS, record_history=True,
    )
    objective = OBJECTIVES[reference_objective]
    decisions = []

    for step in range(steps):
        if step % interval == 0:
            state = snapshot(engine)
            reference = lookahead_choice(engine, horizon, objective)
            chosen = await policy.choose(engine, state)
            effective = chosen if chosen is not None else engine.strategy
            decisions.append({
                "step": engine.time_step,
                "held": chosen is None,
                "chosen": effective,
                "reference": reference,
                "agreed": effective == reference,
                "queue_len": state["queue_len"],
                "queue_rate": state["queue_rate"],
                "num_failed": state["num_failed"],
            })
            engine.strategy = effective
        engine.step()

    agreements = [d["agreed"] for d in decisions]
    return {
        "policy": policy.name,
        "seed": seed,
        "metrics": summarise(engine),
        "decisions": decisions,
        "agreement_rate": round(sum(agreements) / len(agreements), 4) if agreements else None,
        "switches": sum(
            1 for a, b in zip(decisions, decisions[1:]) if a["chosen"] != b["chosen"]
        ),
        "strategies_used": sorted({m["strategy"] for m in engine.metrics_history}),
        "telemetry": policy.telemetry(),
    }


def build_policies(names: List[str], seed: int, horizon: int) -> List[Policy]:
    policies: List[Policy] = []
    for name in names:
        if name == "static":
            policies += [StaticPolicy(s) for s in STRATEGIES]
        elif name == "random":
            policies.append(RandomPolicy(seed))
        elif name == "rule":
            policies.append(RulePolicy())
        elif name == "oracle":
            policies += [OraclePolicy(horizon, obj) for obj in OBJECTIVES]
        elif name == "agent":
            policies.append(AgentPolicy(temperature=0.7))
        else:
            sys.exit(f"Unknown policy {name!r}. Expected any of: "
                     "static, random, rule, oracle, agent, all")
    return policies


def headroom_analysis(by_policy: Dict[str, dict], metric: str) -> dict:
    """Convert raw percentages into "share of the available prize".

    A raw "-88% queue length" says nothing until you know whether 88% was easy
    or was most of what existed. This divides by what the oracle found.
    """
    lower_better = metric in LOWER_IS_BETTER
    statics = {n: v for n, v in by_policy.items() if n.startswith("static:")}
    oracles = {n: v for n, v in by_policy.items() if n.startswith("oracle:")}
    if not statics or not oracles:
        return {}

    pick = min if lower_better else max
    best_static_name = pick(statics, key=lambda n: statics[n][metric])
    best_static = statics[best_static_name][metric]
    best_oracle_name = pick(oracles, key=lambda n: oracles[n][metric])
    best_oracle = oracles[best_oracle_name][metric]

    headroom = (best_static - best_oracle) if lower_better else (best_oracle - best_static)
    scale = abs(best_static) or 1.0
    negligible = headroom <= HEADROOM_MIN_RELATIVE * scale

    shares = {}
    for name, values in by_policy.items():
        gain = (best_static - values[metric]) if lower_better else (values[metric] - best_static)
        shares[name] = None if negligible else round(gain / headroom, 4)

    return {
        "metric": metric,
        "lower_is_better": lower_better,
        "best_static": {"policy": best_static_name, "value": round(best_static, 4)},
        "best_oracle": {"policy": best_oracle_name, "value": round(best_oracle, 4)},
        "headroom": round(headroom, 4),
        "headroom_relative": round(headroom / scale, 4),
        "headroom_is_negligible": negligible,
        "share_of_headroom_captured": shares,
    }


# Axes a policy is judged on jointly. Both are lower-is-better, and they pull
# against each other: the strategies that spread work evenly are the ones that
# decline to dispatch.
PARETO_AXES = ("avg_queue_len", "avg_fairness_std")


def dominates(a: dict, b: dict, axes=PARETO_AXES) -> bool:
    """`a` is at least as good as `b` everywhere and strictly better somewhere."""
    return (all(a[axis] <= b[axis] for axis in axes)
            and any(a[axis] < b[axis] for axis in axes))


def pareto_analysis(by_policy: Dict[str, dict]) -> dict:
    """Which policies beat every fixed strategy on both axes at once?

    This is the framing the per-metric headroom table cannot express. Judged on
    one metric at a time, the best fixed strategy for fairness is `token_ring`
    — which is also the worst for backlog by a wide margin, so "14% better
    fairness than token_ring" flatters a policy that simply refuses to use
    token_ring. Judged on both axes together, the question becomes the one that
    matters: is there a switching policy that no single fixed strategy can
    match? That is the entire case for switching at all, and it is what the
    agent should be measured against.
    """
    statics = {n: v for n, v in by_policy.items() if n.startswith("static:")}
    if not statics:
        return {}

    frontier = [
        name for name, values in statics.items()
        if not any(dominates(other, values) for other in statics.values())
    ]

    verdicts = {}
    for name, values in by_policy.items():
        if name in statics:
            continue
        beaten = [s for s, sv in statics.items() if dominates(values, sv)]
        beaten_by = [s for s, sv in statics.items() if dominates(sv, values)]
        verdicts[name] = {
            "dominates_statics": sorted(beaten),
            "dominated_by_statics": sorted(beaten_by),
            # The claim worth making: no fixed strategy matches this policy.
            "beats_every_static_on_both_axes": not beaten_by and bool(beaten),
            "axes": {axis: round(values[axis], 4) for axis in PARETO_AXES},
        }

    return {
        "axes": list(PARETO_AXES),
        "static_frontier": sorted(frontier),
        "static_values": {
            n: {axis: round(v[axis], 4) for axis in PARETO_AXES}
            for n, v in statics.items()
        },
        "policies": verdicts,
    }


async def main_async(args) -> dict:
    names = (["static", "random", "rule", "oracle", "agent"]
             if "all" in args.policies else args.policies)
    seeds = list(range(1, args.seeds + 1))

    if any(build_policies([n], 1, args.horizon)[0].requires_model for n in names
           if n in ("agent",)):
        print(f"Agent policy enabled: provider={settings.AGENT_PROVIDER} "
              f"model={settings.OLLAMA_MODEL if settings.AGENT_PROVIDER == 'ollama' else settings.GEMINI_MODEL}")

    runs: List[dict] = []
    for seed in seeds:
        for policy in build_policies(names, seed, args.horizon):
            print(f"  seed {seed:>3}  {policy.name}", flush=True)
            runs.append(await run_policy(
                policy, args.base_strategy, seed, args.steps, args.interval,
                args.arrival_prob, args.mean_service, args.horizon, args.reference,
            ))

    # Mean of each metric per policy, across seeds.
    by_policy: Dict[str, dict] = {}
    for name in sorted({r["policy"] for r in runs}):
        matching = [r for r in runs if r["policy"] == name]
        entry = {m: statistics.fmean(r["metrics"][m] for r in matching) for m in REPORTED}
        agreements = [r["agreement_rate"] for r in matching if r["agreement_rate"] is not None]
        entry["agreement_rate"] = round(statistics.fmean(agreements), 4) if agreements else None
        entry["switches"] = round(statistics.fmean(r["switches"] for r in matching), 2)
        entry["seeds"] = len(matching)
        telemetry = [r["telemetry"] for r in matching if r["telemetry"]]
        if telemetry:
            entry["telemetry"] = telemetry
        by_policy[name] = entry

    # Paired deltas against the best static policy, seed by seed. Pairing is
    # only valid because both policies met the identical workload on each seed.
    per_seed: Dict[str, Dict[int, dict]] = {}
    for r in runs:
        per_seed.setdefault(r["policy"], {})[r["seed"]] = r["metrics"]

    paired: Dict[str, dict] = {}
    for metric in REPORTED:
        statics = {n: v for n, v in by_policy.items() if n.startswith("static:")}
        if not statics:
            continue
        pick = min if metric in LOWER_IS_BETTER else max
        reference_name = pick(statics, key=lambda n: statics[n][metric])
        reference = per_seed[reference_name]
        paired[metric] = {
            "reference": reference_name,
            "deltas": {
                name: paired_ci([
                    values[s][metric] - reference[s][metric]
                    for s in sorted(values) if s in reference
                ])
                for name, values in per_seed.items() if name != reference_name
            },
        }

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "config": {
            "seeds": seeds, "steps": args.steps, "decision_interval": args.interval,
            "lookahead_horizon": args.horizon, "reference_objective": args.reference,
            "fairness_weight": FAIRNESS_WEIGHT,
            "base_strategy": args.base_strategy,
            "arrival_prob": args.arrival_prob, "mean_service": args.mean_service,
            "provider": settings.AGENT_PROVIDER if "agent" in names else None,
            "model": (settings.OLLAMA_MODEL if settings.AGENT_PROVIDER == "ollama"
                      else settings.GEMINI_MODEL) if "agent" in names else None,
        },
        "by_policy": by_policy,
        "headroom": {m: headroom_analysis(by_policy, m) for m in REPORTED},
        "pareto": pareto_analysis(by_policy),
        "paired_vs_best_static": paired,
        "runs": runs,
    }


def render_markdown(report: dict) -> str:
    cfg = report["config"]
    lines = [
        "# Who captures the value of switching?",
        "",
        f"Generated {report['generated_at']} by `backend/eval_oracle.py`.",
        "",
        f"{len(cfg['seeds'])} seeds x {cfg['steps']} steps, one decision every "
        f"{cfg['decision_interval']} steps, starting from `{cfg['base_strategy']}`. "
        f"Lookahead horizon {cfg['lookahead_horizon']} steps. "
        f"Agreement is scored against the `{cfg['reference_objective']}` objective.",
        "",
    ]
    if cfg.get("model"):
        lines += [f"Agent: `{cfg['model']}` via `{cfg['provider']}`.", ""]

    lines += [
        "Every policy faces the same decisions at the same cadence under Common "
        "Random Numbers. `oracle:*` forks the live state once per candidate strategy "
        "and looks ahead with perfect foresight of arrivals and failures — it is not "
        "deployable and is not meant to be. It exists to size the prize.",
        "",
        "## Outcome per policy",
        "",
        "| Policy | avg queue | avg wait | throughput | fairness std | switches | agrees with lookahead |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, v in report["by_policy"].items():
        agree = f"{v['agreement_rate'] * 100:.0f}%" if v["agreement_rate"] is not None else "—"
        lines.append(
            f"| `{name}` | {v['avg_queue_len']:.2f} | {v['avg_wait']:.2f} | "
            f"{v['throughput']:.4f} | {v['avg_fairness_std']:.2f} | {v['switches']:.1f} | {agree} |"
        )

    pareto = report.get("pareto") or {}
    if pareto:
        lines += [
            "## Does any switching policy beat every fixed strategy at once?",
            "",
            "Judged one metric at a time, the best fixed strategy for fairness is "
            "`static:token_ring` — which is also the worst for backlog by a wide margin. "
            "\"Better fairness than token_ring\" therefore flatters any policy that merely "
            "declines to use it. Judged on backlog **and** fairness together, the question "
            "becomes the one that actually matters: is there a switching policy that no "
            "single fixed strategy can match?",
            "",
            f"Axes (both lower is better): {', '.join(f'`{a}`' for a in pareto['axes'])}. "
            f"Fixed strategies on the frontier: "
            f"{', '.join(f'`{s}`' for s in pareto['static_frontier'])}.",
            "",
            "| Policy | avg queue | fairness std | fixed strategies it beats on both | beaten by |",
            "|---|---|---|---|---|",
        ]
        for name, v in pareto["policies"].items():
            beats = ", ".join(f"`{s}`" for s in v["dominates_statics"]) or "—"
            beaten = ", ".join(f"`{s}`" for s in v["dominated_by_statics"]) or "—"
            flag = " **✓**" if v["beats_every_static_on_both_axes"] else ""
            lines.append(
                f"| `{name}`{flag} | {v['axes']['avg_queue_len']:.2f} | "
                f"{v['axes']['avg_fairness_std']:.2f} | {beats} | {beaten} |"
            )
        winners = [n for n, v in pareto["policies"].items()
                   if v["beats_every_static_on_both_axes"]]
        lines += [
            "",
            (f"**✓ = beats at least one fixed strategy on both axes while being beaten by "
             f"none.** {', '.join(f'`{w}`' for w in winners)} "
             f"{'qualifies' if len(winners) == 1 else 'qualify'}."
             if winners else
             "**No switching policy here beats a fixed strategy on both axes at once.**"),
            "",
        ]

    lines += ["", "## Share of available headroom captured", ""]
    for metric, analysis in report["headroom"].items():
        if not analysis:
            continue
        lines += [f"### `{metric}`", ""]
        if analysis["headroom_is_negligible"]:
            lines += [
                f"**No meaningful headroom** ({analysis['headroom_relative'] * 100:.1f}%). "
                f"The best static policy (`{analysis['best_static']['policy']}`, "
                f"{analysis['best_static']['value']}) is within {analysis['headroom']} of the "
                f"lookahead oracle (`{analysis['best_oracle']['policy']}`, "
                f"{analysis['best_oracle']['value']}), which sees every future arrival and "
                "failure. With foresight itself worth this little, no switching policy — LLM "
                "or otherwise — had much to win here. A large percentage against a *badly "
                "chosen* static opponent is still available; it just would not mean anything.",
                "",
            ]
            continue
        lines += [
            f"Best static: `{analysis['best_static']['policy']}` at "
            f"{analysis['best_static']['value']}. Lookahead oracle: "
            f"`{analysis['best_oracle']['policy']}` at {analysis['best_oracle']['value']}. "
            f"Headroom = {analysis['headroom']}.",
            "",
            "| Policy | share of headroom captured |",
            "|---|---|",
        ]
        ranked = sorted(
            analysis["share_of_headroom_captured"].items(),
            key=lambda kv: (kv[1] is None, -(kv[1] or 0)),
        )
        for name, share in ranked:
            lines.append(f"| `{name}` | {'—' if share is None else f'{share * 100:.0f}%'} |")
        lines.append("")

    paired = report.get("paired_vs_best_static") or {}
    if paired:
        lines += [
            "## Is the difference real, or seed noise?",
            "",
            "Per-seed paired differences against the best static policy. CRN makes the "
            "pairing valid: on each seed both policies met the identical arrival and "
            "failure sequence, so seed-to-seed variation cancels. An interval spanning 0 "
            "means the difference cannot be told apart from noise.",
            "",
        ]
        for metric, block in paired.items():
            lines += [
                f"### `{metric}` vs `{block['reference']}`",
                "",
                "| Policy | mean paired delta | 95% CI | distinguishable from noise |",
                "|---|---|---|---|",
            ]
            for name, stats in sorted(block["deltas"].items()):
                ci = (f"[{stats['ci95'][0]}, {stats['ci95'][1]}]"
                      if stats["ci95"] else "— (need 2+ seeds)")
                verdict = ("—" if stats["significant"] is None
                           else "yes" if stats["significant"] else "**no**")
                lines.append(f"| `{name}` | {stats['mean']} | {ci} | {verdict} |")
            lines.append("")

    agent = report["by_policy"].get("agent")
    if agent and agent.get("telemetry"):
        calls = sum(t["calls"] for t in agent["telemetry"])
        ok = sum(t["ok"] for t in agent["telemetry"])
        p95 = [t["latency_s"]["p95"] for t in agent["telemetry"] if t["latency_s"]["p95"]]
        total_s = sum(t["latency_s"]["total"] for t in agent["telemetry"])
        errors = sorted({e for t in agent["telemetry"] for e in t["errors"]})
        lines += [
            "## Cost of the agent",
            "",
            f"- {calls} calls, {ok} returning a schema-valid decision "
            f"({ok / calls * 100:.1f}%)" if calls else "- no calls",
            f"- p95 latency {max(p95):.2f}s; {total_s:.0f}s of wall clock spent waiting on the model",
            f"- the `rule` policy reaches its decision in microseconds, with no network and no key",
            "",
        ]
        if errors:
            lines += [f"- failure modes observed: {', '.join(f'`{e}`' for e in errors)}", ""]

    lines += [
        "## How to read this",
        "",
        "- A policy that cannot beat `random` has not demonstrated judgement, "
        "no matter how large its improvement over a badly chosen static opponent.",
        "- A policy that cannot beat `rule` has not justified an API call.",
        "- The two `oracle:*` rows maximise different objectives (`queue` ignores "
        "fairness; `balanced` weighs it at "
        f"{cfg['fairness_weight']}). Where they disagree, the choice of objective is "
        "doing the work, not the policy.",
        "- The oracle is greedy over one horizon, not globally optimal, so it is a "
        "strong reference rather than a proven ceiling.",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--policies", default="static,random,rule,oracle",
                        help="comma-separated: static,random,rule,oracle,agent or 'all'")
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--interval", type=int, default=20,
                        help="steps between decision points")
    parser.add_argument("--horizon", type=int, default=40,
                        help="lookahead window per candidate strategy")
    parser.add_argument("--reference", default="queue", choices=sorted(OBJECTIVES),
                        help="objective the agreement column is scored against")
    parser.add_argument("--base-strategy", default="baseline")
    parser.add_argument("--arrival-prob", type=float, default=0.6)
    parser.add_argument("--mean-service", type=float, default=8.0)
    parser.add_argument("--out", default=RESULTS_DIR)
    parser.add_argument("--tag", default="oracle",
                        help="output filename suffix, for keeping runs side by side")
    args = parser.parse_args()
    args.policies = [p.strip() for p in args.policies.split(",") if p.strip()]

    report = asyncio.run(main_async(args))

    os.makedirs(args.out, exist_ok=True)
    json_path = os.path.join(args.out, f"eval_{args.tag}.json")
    md_path = os.path.join(args.out, f"EVAL_{args.tag}.md")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(report))

    print()
    for name, v in report["by_policy"].items():
        agree = f"{v['agreement_rate'] * 100:5.1f}%" if v["agreement_rate"] is not None else "    —"
        print(f"  {name:22s} queue {v['avg_queue_len']:7.2f}  "
              f"throughput {v['throughput']:.4f}  agree {agree}")
    print(f"\nWrote {json_path}\nWrote {md_path}")


if __name__ == "__main__":
    main()
