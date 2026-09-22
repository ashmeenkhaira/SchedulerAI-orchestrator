# Target path in your project: app/api.py

import asyncio
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.config import settings
from app.database import get_session
from app.gemini_service import get_agent_decision
from app.models import GeminiDecision, Run
from app.scheduler_engine import STRATEGIES, SimEngine

router = APIRouter()


# --- WebSocket fan-out ---

class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        # Send concurrently rather than awaiting each client in turn, so one
        # slow consumer no longer delays everyone behind it. The previous
        # version also slept 1.0s here, which silently tripled the simulation
        # tick: the engine's own 0.5s sleep plus this one meant a "2 steps per
        # second" loop actually advanced one step every 1.5s. Pacing belongs
        # to the engine (settings.SIM_DELAY), not to the broadcaster.
        if not self.active_connections:
            return
        targets = list(self.active_connections)
        results = await asyncio.gather(
            *(ws.send_json(message) for ws in targets),
            return_exceptions=True,
        )
        for ws, result in zip(targets, results):
            if isinstance(result, Exception):
                self.active_connections.discard(ws)


manager = ConnectionManager()

active_engines: Dict[int, SimEngine] = {}
active_tasks: Dict[int, asyncio.Task] = {}


# --- Request models ---

class StartRunRequest(BaseModel):
    strategy: str
    sim_steps: int = 2000
    arrival_prob: float = 0.6
    mean_service: float = 8.0
    seed: int = 1


class StopRunRequest(BaseModel):
    run_id: int


class LogDecisionRequest(BaseModel):
    run_id: int
    step: int
    strategy: Optional[str] = None
    action: str = "switch_strategy"
    raw_message: str = ""


class SwitchStrategyRequest(BaseModel):
    run_id: int
    strategy: str


class AgentDecideRequest(BaseModel):
    time: int
    queue_len: int
    completed_total: int
    fairness_std: float
    queue_rate: float
    num_failed: int
    servers: List[dict]
    run_id: Optional[int] = None
    strategy: Optional[str] = None


class ComparisonRequest(BaseModel):
    base_strategy: str = "baseline"
    replay_run_id: Optional[int] = None
    # "replay"    - treatment arm replays the run's real logged agent decisions
    # "heuristic" - treatment arm runs gemini_strategy_selector, a rule table
    #
    # The heuristic must be asked for explicitly. It used to be a silent
    # fallback whenever a run had no replayable decisions, which meant a run
    # where the model was never reached still produced a full result table
    # with an "Agent" column that no agent had any part in.
    treatment: str = "replay"
    # Used only when replay_run_id is absent. With it, the original run's
    # stored config wins — see run_comparison().
    steps: int = 200
    arrival_prob: float = 0.6
    mean_service: float = 8.0
    seed: int = 1


def _validate_strategy(name: str):
    if name not in STRATEGIES:
        raise HTTPException(status_code=400, detail=f"Invalid strategy. Expected one of {STRATEGIES}")


# --- Decision log ---

@router.post("/runs/log-decision")
async def log_decision(req: LogDecisionRequest, db: AsyncSession = Depends(get_session)):
    decision = GeminiDecision(
        run_id=req.run_id,
        step=req.step,
        strategy=req.strategy or "",
        action=req.action,
        raw_message=req.raw_message,
    )
    db.add(decision)
    await db.commit()
    return {"status": "logged"}


@router.get("/runs/{run_id}/decisions")
async def get_decisions(run_id: int, db: AsyncSession = Depends(get_session)):
    statement = (
        select(GeminiDecision)
        .where(GeminiDecision.run_id == run_id)
        .order_by(GeminiDecision.step)
    )
    result = await db.exec(statement)
    return result.all()


@router.delete("/runs/{run_id}/decisions")
async def clear_decisions(run_id: int, db: AsyncSession = Depends(get_session)):
    statement = select(GeminiDecision).where(GeminiDecision.run_id == run_id)
    result = await db.exec(statement)
    for decision in result.all():
        await db.delete(decision)
    await db.commit()
    return {"status": "cleared"}


# --- Live run control ---

@router.post("/runs/switch-strategy")
async def switch_strategy(req: SwitchStrategyRequest):
    if req.run_id not in active_engines:
        raise HTTPException(status_code=404, detail="No active run found")
    _validate_strategy(req.strategy)
    active_engines[req.run_id].strategy = req.strategy
    return {"status": "switched", "strategy": req.strategy}


@router.post("/agent/decide")
async def agent_decide(req: AgentDecideRequest):
    """Server-side Gemini proxy — keeps GEMINI_API_KEY out of the browser bundle."""
    return await get_agent_decision(req.model_dump(exclude_none=True))


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@router.post("/runs/start")
async def start_run(req: StartRunRequest, db: AsyncSession = Depends(get_session)):
    _validate_strategy(req.strategy)

    new_run = Run(
        strategy=req.strategy,
        seed=req.seed,
        arrival_prob=req.arrival_prob,
        mean_service=req.mean_service,
        sim_steps=req.sim_steps,
    )
    db.add(new_run)
    await db.commit()
    await db.refresh(new_run)
    run_id = new_run.id

    # Single-simulation mode: stop anything already running.
    for existing_id in list(active_tasks.keys()):
        await stop_simulation(existing_id, db)

    engine = SimEngine(
        run_id=run_id,
        strategy=req.strategy,
        arrival_prob=req.arrival_prob,
        mean_service=req.mean_service,
        seed=req.seed,
        num_servers=settings.NUM_SERVERS,
        sim_steps=req.sim_steps,
    )

    active_engines[run_id] = engine
    active_tasks[run_id] = asyncio.create_task(
        engine.run_loop(manager.broadcast, settings.SIM_DELAY)
    )

    return {"status": "started", "run_id": run_id, "strategy": req.strategy}


@router.post("/runs/stop")
async def stop_run_endpoint(req: StopRunRequest, db: AsyncSession = Depends(get_session)):
    await stop_simulation(req.run_id, db)
    return {"status": "stopped", "run_id": req.run_id}


async def stop_simulation(run_id: int, db: AsyncSession):
    if run_id not in active_engines:
        return

    engine = active_engines.pop(run_id)
    engine.stop()

    task = active_tasks.pop(run_id, None)
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    run_record = await db.get(Run, run_id)
    if run_record:
        run_record.end_time = datetime.utcnow()
        run_record.total_completed = engine.jobs_completed
        run_record.total_steps = engine.time_step
        run_record.deadlock_occurred = engine.starvation_steps > 0
        # avg_wait_time was declared on the model but never written, so the
        # one metric a scheduler is most expected to report was always 0.0.
        run_record.avg_wait_time = engine.avg_wait()
        db.add(run_record)

        # Per-job records were accumulated in memory and discarded on stop.
        # Persist them so wait-time distributions can be analysed after the
        # fact rather than only as a single mean.
        for job_log in engine.completed_jobs:
            db.add(job_log)

        await db.commit()


@router.get("/runs")
async def list_runs(skip: int = 0, limit: int = 10, db: AsyncSession = Depends(get_session)):
    statement = select(Run).order_by(Run.id.desc()).offset(skip).limit(limit)
    result = await db.exec(statement)
    return result.all()


# --- Comparison pipeline ---

def gemini_strategy_selector(queue_len: int, fairness_std: float, num_failed: int, queue_rate: float) -> str:
    """Rule-based stand-in used ONLY when a run has no logged Gemini decisions.

    This is NOT Gemini. Responses built from it are flagged via
    meta.used_replay = false so a viewer can never mistake it for real agent
    output.
    """
    if num_failed >= 2:
        return "consistent_hash"
    if queue_rate > 3:
        return "leader_election"
    if fairness_std > 5 and queue_len < 20:
        return "token_ring"
    if queue_len > 30:
        return "random_backoff"
    return "baseline"


def build_replay_selector(decision_log: List[dict]) -> Callable:
    """Apply each logged decision at exactly the step it was recorded.

    The previous implementation routed replayed decisions through the same
    15-step hysteresis gate as the heuristic. Because run 43's decisions were
    logged 10-20 steps apart, that gate delayed every switch and dropped some
    outright — so the "AI arm" was never actually running the sequence the
    agent produced. Hysteresis is a property of the live agent's prompt, not
    of replaying a recorded history.
    """
    by_step = {d["step"]: d["strategy"] for d in decision_log if d.get("strategy")}

    def selector(step, queue_len, fairness_std, num_failed, queue_rate):
        # None means "hold the current strategy", which reproduces the
        # hold-until-next-switch semantics without rescanning the log.
        return by_step.get(step)

    return selector


def build_heuristic_selector(base_strategy: str, min_hold: int = 15) -> Callable:
    """Heuristic selector with its own hysteresis, applied only to itself."""
    state = {"current": base_strategy, "last_switch": 0}

    def selector(step, queue_len, fairness_std, num_failed, queue_rate):
        suggested = gemini_strategy_selector(queue_len, fairness_std, num_failed, queue_rate)
        if suggested != state["current"] and step - state["last_switch"] >= min_hold:
            state["current"] = suggested
            state["last_switch"] = step
        return state["current"]

    return selector


def _simulate(strategy: str, arrival_prob: float, mean_service: float, seed: int,
              steps: int, strategy_fn: Optional[Callable] = None) -> SimEngine:
    engine = SimEngine(
        run_id=0,
        strategy=strategy,
        arrival_prob=arrival_prob,
        mean_service=mean_service,
        seed=seed,
        num_servers=settings.NUM_SERVERS,
        record_history=True,
    )
    engine.run_steps(steps, strategy_fn=strategy_fn)
    return engine


def summarise(engine: SimEngine) -> dict:
    history = engine.metrics_history
    return {
        "avg_queue_len": round(engine.avg_queue_len(), 3),
        "max_queue_len": engine.max_queue_len,
        "avg_wait": round(engine.avg_wait(), 3),
        "avg_turnaround": round(engine.avg_turnaround(), 3),
        "throughput": round(engine.throughput(), 4),
        "jobs_arrived": engine.jobs_arrived,
        "jobs_completed": engine.jobs_completed,
        "final_queue_len": history[-1]["queue_len"] if history else 0,
        "final_fairness_std": round(history[-1]["fairness_std"], 3) if history else 0.0,
        "avg_fairness_std": round(
            sum(m["fairness_std"] for m in history) / len(history), 3
        ) if history else 0.0,
        "starvation_steps": engine.starvation_steps,
    }


def _run_both_arms(base_strategy: str, arrival_prob: float, mean_service: float,
                   seed: int, steps: int, strategy_fn: Optional[Callable]) -> dict:
    """Blocking. Called via asyncio.to_thread so the event loop keeps serving
    the live run's WebSocket broadcasts while a comparison is in flight.

    `strategy_fn` of None means the treatment arm holds base_strategy, which
    is the faithful replay of a run whose agent never switched: both arms are
    then identical and every delta is zero. That is a real result, and it is
    the honest thing to show rather than substituting a different selector.
    """
    control = _simulate(base_strategy, arrival_prob, mean_service, seed, steps)
    treatment = _simulate(base_strategy, arrival_prob, mean_service, seed, steps, strategy_fn)

    series = {"queueLength": [], "completedTotal": [], "fairnessStd": []}
    for c, t in zip(control.metrics_history, treatment.metrics_history):
        series["queueLength"].append(
            {"time": c["time"], "withGemini": t["queue_len"], "withoutGemini": c["queue_len"]}
        )
        series["completedTotal"].append(
            {"time": c["time"], "withGemini": t["completed_total"], "withoutGemini": c["completed_total"]}
        )
        series["fairnessStd"].append(
            {"time": c["time"], "withGemini": round(t["fairness_std"], 3),
             "withoutGemini": round(c["fairness_std"], 3)}
        )

    steps_diverged = sum(
        1 for m in treatment.metrics_history if m["strategy"] != base_strategy
    )
    strategies_used = sorted({m["strategy"] for m in treatment.metrics_history})

    # CRN self-check. Both arms must have seen the same workload; if this is
    # ever false the comparison is not controlled and the numbers are noise.
    crn_ok = (
        control.jobs_arrived == treatment.jobs_arrived
        and [m["num_failed"] for m in control.metrics_history]
        == [m["num_failed"] for m in treatment.metrics_history]
    )

    return {
        "series": series,
        "control": summarise(control),
        "treatment": summarise(treatment),
        "steps_diverged": steps_diverged,
        "strategies_used": strategies_used,
        "crn_ok": crn_ok,
    }


@router.post("/runs/compare")
async def run_comparison(req: ComparisonRequest, db: AsyncSession = Depends(get_session)):
    """Control arm (fixed strategy) vs treatment arm (agent-guided), under
    Common Random Numbers.

    When replay_run_id names a run with logged decisions, the treatment arm
    replays those real decisions and both arms inherit that run's stored
    seed/load/step-count. Otherwise a rule-based stand-in is used and
    meta.used_replay reports that honestly.
    """
    _validate_strategy(req.base_strategy)
    if req.treatment not in ("replay", "heuristic"):
        raise HTTPException(status_code=400, detail="treatment must be 'replay' or 'heuristic'")

    decision_log: List[dict] = []
    decisions_logged = 0
    source_run_id: Optional[int] = None

    if req.replay_run_id is not None:
        run_record = await db.get(Run, req.replay_run_id)
        if run_record is None:
            raise HTTPException(status_code=404, detail="Original run not found")

        seed = run_record.seed
        arrival_prob = run_record.arrival_prob
        mean_service = run_record.mean_service
        steps = run_record.total_steps if run_record.total_steps > 0 else req.steps
        source_run_id = run_record.id

        # Load EVERY decision, not just switches. The count is what separates
        # "the agent held its strategy" from "the agent was never consulted",
        # and the old query could not tell those apart.
        statement = (
            select(GeminiDecision)
            .where(GeminiDecision.run_id == req.replay_run_id)
            .order_by(GeminiDecision.step)
        )
        rows = (await db.exec(statement)).all()
        decisions_logged = len(rows)
        decision_log = [
            {"step": d.step, "strategy": d.strategy}
            for d in rows
            if d.action == "switch_strategy" and d.strategy in STRATEGIES
        ]
    else:
        seed = req.seed
        arrival_prob = req.arrival_prob
        mean_service = req.mean_service
        steps = req.steps

    if steps <= 0:
        raise HTTPException(status_code=400, detail="steps must be positive")

    # Four distinct situations, reported distinctly.
    if req.treatment == "heuristic":
        treatment_mode = "heuristic"
        strategy_fn = build_heuristic_selector(req.base_strategy)
    elif decision_log:
        treatment_mode = "replay"
        strategy_fn = build_replay_selector(decision_log)
    elif decisions_logged:
        treatment_mode = "agent_held"
        strategy_fn = None
    else:
        treatment_mode = "no_agent_data"
        strategy_fn = None

    outcome = await asyncio.to_thread(
        _run_both_arms,
        req.base_strategy, arrival_prob, mean_service, seed, steps, strategy_fn,
    )

    control, treatment = outcome["control"], outcome["treatment"]

    def delta_pct(before: float, after: float) -> Optional[float]:
        if before == 0:
            return None
        return round(((after - before) / before) * 100, 1)

    return {
        "comparison": outcome["series"],
        "summary": {
            "baseline_strategy": req.base_strategy,
            "steps": steps,
            "control": control,
            "treatment": treatment,
            "delta_pct": {
                "avg_queue_len": delta_pct(control["avg_queue_len"], treatment["avg_queue_len"]),
                "avg_wait": delta_pct(control["avg_wait"], treatment["avg_wait"]),
                "throughput": delta_pct(control["throughput"], treatment["throughput"]),
                "avg_fairness_std": delta_pct(control["avg_fairness_std"], treatment["avg_fairness_std"]),
            },
        },
        "meta": {
            # "replay"        - replaying real logged agent switches
            # "agent_held"    - agent ran but never switched; arms are identical
            # "no_agent_data" - no agent decisions exist for this run
            # "heuristic"     - rule table, explicitly requested, NOT the model
            "treatment_mode": treatment_mode,
            "used_replay": treatment_mode == "replay",
            "source_run_id": source_run_id,
            "seed": seed,
            "steps": steps,
            "arrival_prob": arrival_prob,
            "mean_service": mean_service,
            "decisions_logged": decisions_logged,
            "decisions_replayed": len(decision_log),
            "crn_verified": outcome["crn_ok"],
        },
        "diagnostics": {
            "steps_gemini_matched_base_strategy": steps - outcome["steps_diverged"],
            "steps_gemini_used_other_strategy": outcome["steps_diverged"],
            "strategies_used_by_treatment": outcome["strategies_used"],
        },
    }
