import asyncio
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger("uvicorn.error")

from google import genai
from google.genai import types

from app.config import settings

GEMINI_MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = """You are SchedulerAI, an intelligent orchestrator for a distributed job scheduler
running across 8 servers. Every ~15 seconds you receive a snapshot of current system metrics and must
decide whether to keep the current scheduling strategy or switch to a better one.

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
  Weaknesses: mathematically limited to ~0.5 jobs/step regardless of queue depth or free server count.
              At arrival_prob=0.6 the system receives ~0.6 jobs/step on average — meaning token_ring
              runs at a structural deficit of ~0.1 jobs/step under normal load, and up to ~0.45 jobs/step
              deficit during heavy arrival windows. This deficit compounds — every step token_ring runs
              under load, the queue grows by that deficit amount. The longer it runs under load, the
              deeper the backlog becomes, and the harder it is to recover even after switching away.
              Appropriate only when the queue is already actively draining AND fairness is the primary
              concern. When fairness matters but load is present, consistent_hash provides similar
              distribution benefits without the hard throughput ceiling.

leader_election
  How it works: the server with the most completed jobs becomes leader every 20 steps and actively
                distributes jobs to free workers
  Strengths: centralized coordination cuts queue fastest under rapid queue growth; good at draining backlogs
  Weaknesses: leader can become a bottleneck; re-election lag can cause brief coordination gaps

---

METRICS YOU RECEIVE:

- time: current simulation step
- queue_len: number of jobs waiting (not yet assigned to any server)
- queue_rate: smoothed rate of queue change per step — POSITIVE means queue is growing, NEGATIVE means draining
- num_failed: number of servers currently offline (failures are random, last 10–30 steps)
- fairness_std: standard deviation of completed-job counts across all 8 servers (0 = perfect fairness)
- completed_total: total jobs finished so far across all servers
- strategy: the strategy currently running
- servers[]: per-server detail — busy, completed count, failed status

---

HOW TO REASON (follow this process every cycle):

1. DIAGNOSE: What is the system's current condition?
   - Is the queue growing, stable, or draining? At what rate?
   - Are servers failing? How many, for how long?
   - Is load distribution fair across servers?
   - What is the trend over recent cycles — is this a transient spike or sustained pressure?

2. EVALUATE the current strategy: is it well-matched to the current condition, or is there evidence it
   is underperforming? Be specific — "queue_len is 45 and growing at +2/step despite 6 free servers"
   is evidence of underperformance; "queue_len is 12 and stable" is not.

3. CONSIDER alternatives: for each strategy you might switch to, state what specific benefit it would
   provide RIGHT NOW and what you would be trading away. Do not list all five — only the one or two
   most relevant to the current condition.

4. DECIDE: switch only if the expected benefit is clear and the current strategy is demonstrably
   struggling. If keeping the current strategy, say why it remains the right choice given current
   conditions — not just "no conditions met."

5. HYSTERESIS: Do not switch strategies unless you have held the current one for at least 20–30 steps,
   EXCEPT when num_failed >= 3 (server failure emergency — switch immediately to consistent_hash to
   protect jobs in-flight). Frequent switching has coordination overhead and disrupts in-progress work.
   A strategy that is "slightly suboptimal" is often better than a disruptive switch.

6. THROUGHPUT vs FAIRNESS TRADEOFF: these are competing objectives — reason about which one
   the system actually needs right now, not which one looks worse in the metrics.
   A growing queue (queue_rate > 0) means the system is falling behind on throughput — fairness
   optimizations are premature when jobs are accumulating faster than they are being processed,
   because a perfectly fair system that cannot drain its queue is worse than a slightly unfair
   one that can. Conversely, when the queue is stable or draining (queue_rate <= 0), fairness
   becomes the meaningful axis to optimize — sustained unfairness causes server starvation and
   tail latency even under light load. Always state explicitly in your message which objective
   you are prioritizing, why the current conditions justify that priority, and what you expect
   the chosen strategy to achieve over the next 15–30 steps.

---

RESPONSE FORMAT (strict JSON, no markdown):

{
  "action": "switch_strategy" | "explain",
  "strategy": "<strategy name if action is switch_strategy, else null>",
  "params": {},
  "message": "<Your reasoning. ALWAYS include: (1) what the current condition is, (2) what you
               considered switching to and why you rejected or accepted it, (3) what you expect
               to happen over the next 15-30 seconds under your chosen strategy. 2-4 sentences.>"
}

Use "switch_strategy" when you are changing to a different strategy.
Use "explain" when you are keeping the current strategy — but still provide full reasoning in message.

Do NOT use "start_run" or "stop_run" — those actions are not available to you.
Do NOT default to baseline just because nothing is obviously wrong — reason about whether the current
strategy is genuinely the best fit, not just whether an emergency threshold is crossed."""

_STRATEGY_ENUM = ["baseline", "random_backoff", "consistent_hash", "token_ring", "leader_election"]

_RESPONSE_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "action": types.Schema(type=types.Type.STRING, enum=["switch_strategy", "explain"]),
        "strategy": types.Schema(type=types.Type.STRING, nullable=True, enum=_STRATEGY_ENUM),
        "params": types.Schema(
            type=types.Type.OBJECT,
            nullable=True,
            properties={
                "priority": types.Schema(type=types.Type.STRING, nullable=True),
                "target_server": types.Schema(type=types.Type.INTEGER, nullable=True),
                "reason": types.Schema(type=types.Type.STRING, nullable=True),
            },
        ),
        "message": types.Schema(type=types.Type.STRING),
    },
    required=["action", "message"],
)

_client: Optional[genai.Client] = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not settings.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not configured on the server")
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def _parse_retry_delay(error: Exception) -> float:
    match = re.search(r'"retryDelay"\s*:\s*"(\d+)s"', str(error))
    return float(match.group(1)) if match else 0.0


async def _call_gemini_once(metrics: Dict[str, Any]) -> Dict[str, Any]:
    client = _get_client()
    response = await asyncio.to_thread(
        client.models.generate_content,
        model=GEMINI_MODEL,
        contents=str(metrics),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=_RESPONSE_SCHEMA,
        ),
    )
    if not response.text:
        raise RuntimeError("Empty response from Gemini")
    import json
    return json.loads(response.text)


async def get_agent_decision(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Mirrors the retry-once-then-degrade-gracefully behavior the frontend
    used to implement client-side, now running server-side so the API key
    never reaches the browser."""
    try:
        return await _call_gemini_once(metrics)
    except Exception as first_error:
        logger.exception("Gemini call failed (attempt 1)")
        delay = _parse_retry_delay(first_error)
        if delay > 0:
            await asyncio.sleep(delay)
            try:
                return await _call_gemini_once(metrics)
            except Exception:
                logger.exception("Gemini call failed (attempt 2, after retryDelay)")
                return {
                    "action": "explain",
                    "strategy": None,
                    "params": {},
                    "message": "Agent rate-limited. Decision making paused.",
                }
        return {
            "action": "explain",
            "strategy": None,
            "params": {},
            "message": "Agent connection interrupted. Decision making offline.",
        }
