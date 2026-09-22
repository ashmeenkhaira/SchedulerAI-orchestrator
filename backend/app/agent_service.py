"""Provider-agnostic access to the scheduling agent.

Three backends answer the same question with the same contract:

  ollama  hosted or local; the default, because the evaluation harness issues
          hundreds of calls per sweep and no per-day quota survives that
  gemini  original backend, kept working
  mock    deterministic rule table, no network

`mock` is not a stub for convenience. The harness is measuring things like
self-consistency and schema-violation rate, and a measurement that reports
disagreement where none exists is worse than no measurement. Running the
harness against `mock` must yield 100% consistency and 0% violations; if it
does not, the harness is wrong, not the model.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx

from app.agent_prompt import (
    DECISION_JSON_SCHEMA,
    SYSTEM_PROMPT,
    validate_decision,
)
from app.config import settings

logger = logging.getLogger("uvicorn.error")

REQUEST_TIMEOUT_SECONDS = float(120)


@dataclass
class AgentResponse:
    """One call's outcome, including everything the harness needs to score it.

    `decision` is None exactly when `error` is set. Both the latency and the
    token counts are recorded even on failure, because a provider that fails
    slowly costs more than one that fails fast.
    """

    provider: str
    model: str
    latency_s: float
    decision: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    raw_text: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.decision is not None


# --- Ollama -----------------------------------------------------------------

async def _call_ollama(metrics: Dict[str, Any], temperature: float,
                       system_prompt: str = SYSTEM_PROMPT) -> AgentResponse:
    url = f"{settings.OLLAMA_BASE_URL}/api/chat"
    headers = {"Content-Type": "application/json"}
    if settings.OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {settings.OLLAMA_API_KEY}"

    body = {
        "model": settings.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(metrics)},
        ],
        "stream": False,
        # Ollama enforces this server-side, so a malformed response means the
        # model failed the task rather than that we failed to parse it.
        "format": DECISION_JSON_SCHEMA,
        "options": {"temperature": temperature},
    }

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return AgentResponse(
            provider="ollama", model=settings.OLLAMA_MODEL,
            latency_s=time.perf_counter() - started,
            error=f"transport:{type(exc).__name__}:{exc}",
        )

    latency = time.perf_counter() - started
    text = (payload.get("message") or {}).get("content", "")
    result = AgentResponse(
        provider="ollama",
        model=payload.get("model", settings.OLLAMA_MODEL),
        latency_s=latency,
        prompt_tokens=payload.get("prompt_eval_count"),
        completion_tokens=payload.get("eval_count"),
        raw_text=text,
    )

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        result.error = "invalid_json"
        return result

    decision, reason = validate_decision(parsed)
    result.decision, result.error = decision, reason
    return result


# --- Gemini -----------------------------------------------------------------

_gemini_client = None
# Keyed by (temperature, system_prompt): the ablation harness varies both.
_gemini_config_cache: Dict[Any, Any] = {}


def _gemini_schema(types):
    """Translate DECISION_JSON_SCHEMA into google-genai's Schema objects.

    Derived from the canonical schema rather than restated, so the two
    providers cannot end up enforcing different contracts.
    """
    props = DECISION_JSON_SCHEMA["properties"]
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "action": types.Schema(type=types.Type.STRING, enum=props["action"]["enum"]),
            "strategy": types.Schema(
                type=types.Type.STRING, nullable=True, enum=props["strategy"]["enum"]
            ),
            "message": types.Schema(type=types.Type.STRING),
        },
        required=list(DECISION_JSON_SCHEMA["required"]),
    )


def _get_gemini(temperature: float, system_prompt: str):
    global _gemini_client
    from google import genai
    from google.genai import types

    if _gemini_client is None:
        if not settings.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not configured on the server")
        _gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)

    key = (temperature, system_prompt)
    if key not in _gemini_config_cache:
        _gemini_config_cache[key] = types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=_gemini_schema(types),
            temperature=temperature,
        )
    return _gemini_client, _gemini_config_cache[key]


async def _call_gemini(metrics: Dict[str, Any], temperature: float,
                       system_prompt: str = SYSTEM_PROMPT) -> AgentResponse:
    started = time.perf_counter()
    try:
        client, config = _get_gemini(temperature, system_prompt)
        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=settings.GEMINI_MODEL,
                contents=json.dumps(metrics),
                config=config,
            ),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        return AgentResponse(
            provider="gemini", model=settings.GEMINI_MODEL,
            latency_s=time.perf_counter() - started,
            error=f"transport:{type(exc).__name__}:{exc}",
        )

    latency = time.perf_counter() - started
    usage = getattr(response, "usage_metadata", None)
    result = AgentResponse(
        provider="gemini",
        model=settings.GEMINI_MODEL,
        latency_s=latency,
        prompt_tokens=getattr(usage, "prompt_token_count", None),
        completion_tokens=getattr(usage, "candidates_token_count", None),
        raw_text=response.text,
    )

    if not response.text:
        result.error = "empty_response"
        return result

    try:
        parsed = json.loads(response.text)
    except json.JSONDecodeError:
        result.error = "invalid_json"
        return result

    decision, reason = validate_decision(parsed)
    result.decision, result.error = decision, reason
    return result


# --- Mock -------------------------------------------------------------------

def _mock_choice(metrics: Dict[str, Any]) -> str:
    if metrics.get("num_failed", 0) >= 2:
        return "consistent_hash"
    if metrics.get("queue_rate", 0.0) > 3:
        return "leader_election"
    if metrics.get("fairness_std", 0.0) > 5 and metrics.get("queue_len", 0) < 20:
        return "token_ring"
    if metrics.get("queue_len", 0) > 30:
        return "random_backoff"
    return "baseline"


async def _call_mock(metrics: Dict[str, Any], temperature: float,
                     system_prompt: str = SYSTEM_PROMPT) -> AgentResponse:
    """Deterministic: identical metrics always produce an identical decision.

    Ignores both temperature and prompt by design — it is the fixed point the
    harness is validated against, so it must not vary with anything.
    """
    started = time.perf_counter()
    choice = _mock_choice(metrics)
    holding = choice == metrics.get("strategy")
    decision = {
        "action": "explain" if holding else "switch_strategy",
        "strategy": None if holding else choice,
        "message": f"mock provider: rule table selects {choice}",
    }
    return AgentResponse(
        provider="mock", model="rule-table",
        latency_s=time.perf_counter() - started,
        decision=decision, prompt_tokens=0, completion_tokens=0,
        raw_text=json.dumps(decision),
    )


# --- Dispatch ---------------------------------------------------------------

_PROVIDERS = {"ollama": _call_ollama, "gemini": _call_gemini, "mock": _call_mock}

DEFAULT_TEMPERATURE = 0.7


async def request_decision(
    metrics: Dict[str, Any],
    temperature: float = DEFAULT_TEMPERATURE,
    system_prompt: str = SYSTEM_PROMPT,
) -> AgentResponse:
    """One call, no retry. The harness wants raw per-call outcomes — retrying
    inside here would hide exactly the failure rate it is trying to measure.

    `system_prompt` is overridable so the ablation harness can ask whether the
    prompt or the model is producing the decisions.
    """
    provider = settings.AGENT_PROVIDER
    call = _PROVIDERS.get(provider)
    if call is None:
        return AgentResponse(
            provider=provider, model="?", latency_s=0.0,
            error=f"unknown_provider:{provider!r} (expected one of {sorted(_PROVIDERS)})",
        )
    return await call(metrics, temperature, system_prompt)


async def get_agent_decision(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Live-UI entry point: one retry, then a degraded response the dashboard
    can display.

    `degraded` distinguishes "the agent looked and chose to hold" from "the
    agent was never reached". Both surface as action="explain", and without the
    flag the second kind gets written into the decision log as though it were
    real model output.
    """
    result = await request_decision(metrics)
    if result.ok:
        return {**result.decision, "params": {}, "degraded": False}

    logger.warning("Agent call failed (attempt 1): %s", result.error)
    retry = await request_decision(metrics)
    if retry.ok:
        return {**retry.decision, "params": {}, "degraded": False}

    logger.warning("Agent call failed (attempt 2): %s", retry.error)
    return {
        "action": "explain",
        "strategy": None,
        "params": {},
        "message": f"Agent unavailable ({retry.error}). Decision making paused.",
        "degraded": True,
    }
