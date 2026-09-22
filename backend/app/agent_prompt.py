"""The decision contract, shared by every provider.

Prompt, response schema and validation live here rather than inside one
provider module, so that swapping Ollama for Gemini changes *how* a decision
is obtained and nothing about *what* a decision is. The evaluation harness
depends on that: a score is only comparable across providers if both were
asked the same question and held to the same output shape.
"""

from typing import Any, Dict, Optional, Tuple

from app.scheduler_engine import STRATEGIES

SYSTEM_PROMPT = """You are SchedulerAI, an orchestrator for a distributed job scheduler running across
8 servers. You receive a snapshot of current system metrics and must decide whether to keep the
current scheduling strategy or switch to a different one.

---

STRATEGIES AND THEIR TRADEOFFS:

baseline
  How it works: servers claim jobs in fixed ID order (server 0 first, then 1, etc.)
  Strengths: simple, predictable, low overhead, works well under light/stable load
  Weaknesses: overloads low-ID servers under sustained load; unfair distribution over time

random_backoff
  How it works: servers compete for jobs with randomized retry delays on contention
  Strengths: avoids thundering-herd contention; distributes load well under sustained high load
  Weaknesses: adds latency under low load; random delays can briefly leave free servers idle

consistent_hash
  How it works: each job is hashed to a preferred server, with ring-based fallback if that server is busy/failed
  Strengths: resilient to server failures and churn — jobs reroute automatically; good locality
  Weaknesses: can starve some servers if job IDs hash unevenly; less adaptive to dynamic load

token_ring
  How it works: a token rotates across servers (one rotation every 2 steps); only the token holder picks up a job
  Strengths: perfectly fair; no starvation; ordered access
  Weaknesses: structurally limited to about 0.5 assignments per step regardless of queue depth or how
              many servers are free, because the holder can only claim one job and is then busy when
              the token returns. If jobs arrive faster than that, the queue grows by the difference
              every step, and the backlog persists long after switching away.
              Appropriate only when the queue is already draining AND fairness is the priority.

leader_election
  How it works: the server with the most completed jobs becomes leader every 20 steps and actively
                distributes jobs to free workers
  Strengths: centralized coordination drains a backlog quickly under rapid queue growth
  Weaknesses: leader can become a bottleneck; re-election lag can cause brief coordination gaps

---

METRICS YOU RECEIVE:

- time: current simulation step
- queue_len: number of jobs waiting (not yet assigned to any server)
- queue_rate: smoothed rate of queue change per step — POSITIVE means growing, NEGATIVE means draining
- num_failed: number of servers currently offline (failures are random, last 10-30 steps).
              A failed server cannot accept work and makes no progress on the job it held;
              that job returns to the front of the queue.
- fairness_std: standard deviation of completed-job counts across all 8 servers (0 = perfect fairness)
- completed_total: total jobs finished so far across all servers
- avg_wait: mean steps a job spent queued before a server picked it up
- strategy: the strategy currently running
- servers[]: per-server detail — busy, completed count, failed status

---

HOW TO REASON (follow this process every cycle):

1. DIAGNOSE: is the queue growing, stable, or draining, and at what rate? Are servers failing?
   Is load distribution fair? Is this a transient spike or sustained pressure?

2. EVALUATE the current strategy: is it well matched to this condition, or is there specific evidence
   it is underperforming? "queue_len is 45 and growing at +2/step despite 6 free servers" is evidence.
   "queue_len is 12 and stable" is not.

3. CONSIDER alternatives: for the one or two most relevant strategies, state what they would buy you
   right now and what you would trade away. Do not enumerate all five.

4. DECIDE: switch only if the expected benefit is clear and the current strategy is demonstrably
   struggling. If holding, say why it remains right for these conditions.

5. HYSTERESIS: do not switch unless the current strategy has been held for at least 20-30 steps,
   EXCEPT when num_failed >= 3 (switch to consistent_hash immediately to protect in-flight jobs).
   Switching has coordination overhead; a slightly suboptimal strategy usually beats a disruptive switch.

6. THROUGHPUT vs FAIRNESS: these compete. A growing queue (queue_rate > 0) means the system is falling
   behind on throughput, and fairness optimisation is premature while jobs accumulate faster than they
   are processed. When the queue is stable or draining (queue_rate <= 0), fairness becomes the
   meaningful axis. State which objective you are prioritising and what you expect over the next
   15-30 steps.

---

RESPONSE FORMAT (strict JSON, no markdown):

{
  "action": "switch_strategy" | "explain",
  "strategy": "<strategy name if action is switch_strategy, else null>",
  "message": "<Your reasoning: (1) the current condition, (2) what you considered switching to and
               why you accepted or rejected it, (3) what you expect over the next 15-30 steps.
               2-4 sentences.>"
}

Use "switch_strategy" when changing strategy. Use "explain" when holding, with full reasoning anyway.
Do NOT default to baseline just because nothing is obviously wrong."""


# --- Prompt variants, for ablation -------------------------------------------
#
# The full prompt does a lot of work: it states each strategy's tradeoffs, and
# for token_ring it hands over the throughput ceiling outright. A model
# following that faithfully looks like it is reasoning about scheduling when it
# may only be reciting the brief. These variants separate the two.
#
#   full          what the live system ships
#   no_ceiling    token_ring described without its throughput ceiling. If the
#                 fairness_std -> token_ring boundary survives, the model is
#                 weighing fairness; if it collapses, the boundary was the hint.
#   minimal       strategy names and the output contract, nothing else. If this
#                 performs like `full`, the prompt engineering is not the thing
#                 producing the decisions.

_TOKEN_RING_NEUTRAL = """token_ring
  How it works: a token rotates across servers (one rotation every 2 steps); only the token holder picks up a job
  Strengths: perfectly fair; no starvation; ordered access
  Weaknesses: only the token holder may claim a job, so dispatch is serialised through one server at a time."""

_TOKEN_RING_FULL_START = "token_ring\n  How it works:"
_TOKEN_RING_FULL_END = "\n\nleader_election"


def _prompt_without_ceiling_hint() -> str:
    start = SYSTEM_PROMPT.index(_TOKEN_RING_FULL_START)
    end = SYSTEM_PROMPT.index(_TOKEN_RING_FULL_END, start)
    return SYSTEM_PROMPT[:start] + _TOKEN_RING_NEUTRAL + SYSTEM_PROMPT[end:]


MINIMAL_PROMPT = """You are a scheduling orchestrator for a distributed job scheduler across 8 servers.
You receive a snapshot of system metrics and choose which scheduling strategy should run.

The available strategies are: baseline, random_backoff, consistent_hash, token_ring, leader_election.

Respond in strict JSON:

{
  "action": "switch_strategy" | "explain",
  "strategy": "<strategy name if switching, else null>",
  "message": "<brief reasoning>"
}

Use "switch_strategy" to change strategy, "explain" to keep the current one."""


PROMPT_VARIANTS = {
    "full": SYSTEM_PROMPT,
    "no_ceiling": _prompt_without_ceiling_hint(),
    "minimal": MINIMAL_PROMPT,
}


# One schema, expressed in plain JSON Schema. Ollama takes this verbatim in its
# `format` field; the Gemini provider translates it into google-genai's Schema
# objects. Keeping the plain form canonical means the two providers cannot
# drift into accepting different response shapes.
DECISION_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["switch_strategy", "explain"]},
        "strategy": {"type": "string", "enum": STRATEGIES},
        "message": {"type": "string"},
    },
    "required": ["action", "message"],
}

# Metrics keys the agent is allowed to see. The harness builds synthetic states
# from exactly this set, so a probe state and a live state are indistinguishable
# to the model.
METRIC_KEYS = (
    "time", "queue_len", "queue_rate", "num_failed", "fairness_std",
    "completed_total", "avg_wait", "strategy",
)


def validate_decision(raw: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Return (decision, None) or (None, reason).

    Returning the reason rather than raising is deliberate: schema-violation
    rate is itself one of the things being measured, so the caller needs to
    record *why* a response was rejected, not just that it was.
    """
    if not isinstance(raw, dict):
        return None, f"not_an_object:{type(raw).__name__}"

    action = raw.get("action")
    if action not in ("switch_strategy", "explain"):
        return None, f"bad_action:{action!r}"

    strategy = raw.get("strategy")
    if action == "switch_strategy":
        if strategy not in STRATEGIES:
            return None, f"unknown_strategy:{strategy!r}"
    else:
        # A model that says "explain" while naming a strategy is ambiguous, but
        # the naming is harmless as long as we ignore it — normalise to None so
        # downstream code has exactly one representation of "hold".
        strategy = None

    message = raw.get("message")
    if not isinstance(message, str) or not message.strip():
        return None, "missing_message"

    return {"action": action, "strategy": strategy, "message": message.strip()}, None
