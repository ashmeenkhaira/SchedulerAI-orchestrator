# Target path in your project: app/api.py

import asyncio
import random
from collections import deque
from datetime import datetime
from typing import List, Dict, Set, Optional

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, delete

from app.scheduler_engine import SimEngine
from app.database import get_session
from app.models import Run, JobLog, GeminiDecision
from app.gemini_service import get_agent_decision

router = APIRouter()


# --- Connection Manager for WebSockets ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        # One shared delay per broadcast call, not per-connection — with the
        # old per-connection sleep, a second open tab made updates lag an
        # extra full second behind the first, compounding with more tabs.
        await asyncio.sleep(1.0)
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.active_connections.discard(connection)


manager = ConnectionManager()

# --- Simulation State ---
active_engines: Dict[int, SimEngine] = {}
active_tasks: Dict[int, asyncio.Task] = {}


class StartRunRequest(BaseModel):
    strategy: str
    sim_steps: int = 2000
    arrival_prob: float = 0.4
    mean_service: float = 5.0
    seed: int = 42


class StopRunRequest(BaseModel):
    run_id: int


class LogDecisionRequest(BaseModel):
    run_id: int
    step: int
    strategy: str
    action: str = "switch_strategy"
    raw_message: str = ""


# --- Phase 2: decision log now lives in the DB, not a process-local dict ---

@router.post("/runs/log-decision")
async def log_decision(req: LogDecisionRequest, db: AsyncSession = Depends(get_session)):
    decision = GeminiDecision(
        run_id=req.run_id,
        step=req.step,
        strategy=req.strategy,
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


class SwitchStrategyRequest(BaseModel):
    run_id: int
    strategy: str


@router.post("/runs/switch-strategy")
async def switch_strategy(req: SwitchStrategyRequest):
    if req.run_id not in active_engines:
        raise HTTPException(status_code=404, detail="No active run found")

    valid = ["baseline", "random_backoff", "consistent_hash", "token_ring", "leader_election"]
    if req.strategy not in valid:
        raise HTTPException(status_code=400, detail="Invalid strategy")

    active_engines[req.run_id].strategy = req.strategy
    return {"status": "switched", "strategy": req.strategy}


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


@router.post("/agent/decide")
async def agent_decide(req: AgentDecideRequest):
    """Server-side Gemini proxy — keeps GEMINI_API_KEY out of the browser
    bundle. Accepts the same metrics snapshot the frontend used to send
    directly to Gemini and returns the same AgentDecision shape."""
    metrics = req.model_dump(exclude_none=True)
    decision = await get_agent_decision(metrics)
    return decision


# --- Routes ---

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
    # Phase 1: persist the actual config used for this run. This is what
    # lets /runs/compare later look up ground-truth seed/load/steps instead
    # of trusting whatever the frontend happens to send at comparison time.
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

    # Stop any existing runs (single simulation mode for simplicity)
    for existing_id in list(active_tasks.keys()):
        await stop_simulation(existing_id, db)

    engine = SimEngine(
        run_id=run_id,
        strategy=req.strategy,
        arrival_prob=req.arrival_prob,
        mean_service=req.mean_service,
        seed=req.seed,
    )

    active_engines[run_id] = engine
    task = asyncio.create_task(engine.run_loop(manager.broadcast))
    active_tasks[run_id] = task

    return {"status": "started", "run_id": run_id, "strategy": req.strategy}


@router.post("/runs/stop")
async def stop_run_endpoint(req: StopRunRequest, db: AsyncSession = Depends(get_session)):
    await stop_simulation(req.run_id, db)
    return {"status": "stopped", "run_id": req.run_id}


async def stop_simulation(run_id: int, db: AsyncSession):
    if run_id in active_engines:
        engine = active_engines[run_id]
        engine.stop()

        if run_id in active_tasks:
            active_tasks[run_id].cancel()
            try:
                await active_tasks[run_id]
            except asyncio.CancelledError:
                pass
            del active_tasks[run_id]

        run_record = await db.get(Run, run_id)
        if run_record:
            run_record.end_time = datetime.utcnow()
            run_record.total_completed = sum(s.completed_count for s in engine.servers)
            run_record.total_steps = engine.time_step
            run_record.deadlock_occurred = engine.deadlock_detected
            db.add(run_record)
            await db.commit()

        del active_engines[run_id]


@router.get("/runs")
async def list_runs(skip: int = 0, limit: int = 10, db: AsyncSession = Depends(get_session)):
    statement = select(Run).order_by(Run.id.desc()).offset(skip).limit(limit)
    result = await db.exec(statement)
    return result.all()


@router.delete("/runs/clear-all")
async def clear_all_runs(db: AsyncSession = Depends(get_session)):
    """Clear all simulation data from database"""
    await db.exec(delete(JobLog))
    await db.exec(delete(GeminiDecision))
    await db.exec(delete(Run))
    await db.commit()

    return {"status": "success", "message": "All simulation data cleared"}


# --- Comparison Mode ---

class ComparisonRequest(BaseModel):
    base_strategy: str = "baseline"
    replay_run_id: Optional[int] = None
    # Only used when replay_run_id is NOT provided (an ad-hoc comparison
    # with no original live run to anchor against). When replay_run_id IS
    # provided, these four are ignored in favor of the original run's
    # actual stored config — see run_comparison() below.
    steps: int = 200
    arrival_prob: float = 0.4
    mean_service: float = 5.0
    seed: int = 42


class ComparisonEngine:
    """Synchronous simulation for comparison (no WebSocket, just results).

    Phase 4: each instance owns its own isolated RNG streams (self.rng /
    self.np_rng) instead of reseeding the global random/numpy modules. This
    guarantees that one engine's strategy-driven RNG consumption (e.g.
    random_backoff's shuffle calls, which the other strategies never make)
    can't desync the other engine's arrival/failure draw sequence. Both
    engines see identical load for as long as they're constructed with the
    same seed, regardless of which strategy either one is running.
    """

    def __init__(self, strategy: str, arrival_prob: float, mean_service: float, seed: int, num_servers: int = 8):
        self.rng = random.Random(seed)
        self.np_rng = np.random.RandomState(seed)

        self.strategy = strategy
        self.num_servers = num_servers
        self.arrival_prob = arrival_prob
        self.mean_service = mean_service

        self.servers = [
            {"sid": i, "busy": False, "work_remaining": 0, "completed": 0,
             "current_job": None, "failed": False, "failure_duration": 0}
            for i in range(num_servers)
        ]
        self.queue = deque()
        self.time_step = 0
        self.metrics_history = []
        self.last_queue_len = 0
        self.queue_rate = 0.0
        self.last_strategy = strategy
        self.steps_since_switch = 0

    def _get_dynamic_arrival_prob(self) -> float:
        # Phase 5: arrival_prob now actually does something — kept IDENTICAL
        # to SimEngine's version. These two must stay in lockstep: if they
        # used different load curves, a comparison replaying a live run's
        # decisions onto this engine's trace would no longer reflect the
        # conditions Gemini actually responded to, undermining the whole
        # point of Phase 3's seed/config lookup.
        if self.time_step <= 80:
            base = 0.3
        elif self.time_step <= 180:
            base = 0.95
        elif self.time_step <= 300:
            base = 0.6
        elif self.time_step <= 400:
            base = 0.4
        else:
            base = 0.85

        scale = self.arrival_prob / 0.6
        return max(0.0, min(1.0, base * scale))

    def run_steps(self, num_steps: int, strategy_fn=None):
        """Run simulation for num_steps, optionally with dynamic strategy switching."""
        for _ in range(num_steps):
            self.time_step += 1
            self.steps_since_switch += 1

            # Process failures
            num_failed = 0
            for server in self.servers:
                if server["failed"]:
                    server["failure_duration"] -= 1
                    if server["failure_duration"] <= 0:
                        server["failed"] = False
                elif self.rng.random() < 0.005:
                    server["failed"] = True
                    server["failure_duration"] = self.rng.randint(10, 30)
                    if server["busy"]:
                        self.queue.appendleft(server["current_job"])
                        server["busy"] = False
                        server["current_job"] = None
                        server["work_remaining"] = 0

                if server["failed"]:
                    num_failed += 1

            # Queue rate (EMA)
            queue_diff = len(self.queue) - self.last_queue_len
            self.queue_rate = 0.8 * self.queue_rate + 0.2 * queue_diff
            self.last_queue_len = len(self.queue)

            # Job arrival
            current_arrival_prob = self._get_dynamic_arrival_prob()
            if self.rng.random() < current_arrival_prob:
                work = max(1, int(self.rng.expovariate(1.0 / self.mean_service)))
                self.queue.append({"arrival": self.time_step, "work": work, "id": self.time_step})

            # Dynamic strategy switch (Gemini-like behavior, or real replay)
            current_strategy = self.strategy
            if strategy_fn:
                suggested_strategy = strategy_fn(len(self.queue), self._fairness_std(), num_failed, self.queue_rate)
                if suggested_strategy != self.last_strategy and self.steps_since_switch >= 15:
                    self.last_strategy = suggested_strategy
                    self.steps_since_switch = 0
                current_strategy = self.last_strategy
                self.strategy = current_strategy

            # Execute strategy
            self._execute_strategy(current_strategy)

            # Process work
            for server in self.servers:
                if server["busy"]:
                    server["work_remaining"] -= 1
                    if server["work_remaining"] <= 0:
                        server["busy"] = False
                        server["current_job"] = None
                        server["completed"] += 1

            # Record metrics
            self.metrics_history.append({
                "time": self.time_step,
                "queue_len": len(self.queue),
                "completed_total": sum(s["completed"] for s in self.servers),
                "fairness_std": self._fairness_std(),
                "strategy": current_strategy,
            })

    def _fairness_std(self):
        completed = [s["completed"] for s in self.servers]
        return float(np.std(completed)) if completed else 0.0

    def _execute_strategy(self, strategy: str):
        free_servers = [s for s in self.servers if not s["busy"] and not s["failed"]]

        if strategy == "baseline":
            free_servers.sort(key=lambda s: s["sid"])
            for server in free_servers:
                if self.queue:
                    job = self.queue.popleft()
                    server["busy"] = True
                    server["work_remaining"] = job["work"]
                    server["current_job"] = job

        elif strategy == "random_backoff":
            if free_servers and self.queue:
                self.rng.shuffle(free_servers)
                for server in free_servers:
                    if self.queue:
                        job = self.queue.popleft()
                        server["busy"] = True
                        server["work_remaining"] = job["work"]
                        server["current_job"] = job

        elif strategy == "consistent_hash":
            for job in list(self.queue):
                preferred = hash(job["id"]) % self.num_servers
                for offset in range(self.num_servers):
                    sid = (preferred + offset) % self.num_servers
                    server = self.servers[sid]
                    if not server["busy"] and not server["failed"]:
                        self.queue.remove(job)
                        server["busy"] = True
                        server["work_remaining"] = job["work"]
                        server["current_job"] = job
                        break

        elif strategy == "token_ring":
            token_pos = (self.time_step // 2) % self.num_servers
            server = self.servers[token_pos]
            if not server["busy"] and not server["failed"] and self.queue:
                job = self.queue.popleft()
                server["busy"] = True
                server["work_remaining"] = job["work"]
                server["current_job"] = job

        elif strategy == "leader_election":
            for server in free_servers:
                if self.queue:
                    job = self.queue.popleft()
                    server["busy"] = True
                    server["work_remaining"] = job["work"]
                    server["current_job"] = job


def gemini_strategy_selector(queue_len: int, fairness_std: float, num_failed: int, queue_rate: float) -> str:
    """Heuristic fallback ONLY — used when no real logged Gemini decisions
    exist for the run being compared against. This is NOT Gemini. Its
    output must never be presented to a viewer as real AI reasoning; see
    meta.used_replay in the response below, which the frontend should
    surface so this distinction is never silently lost.
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


@router.post("/runs/compare")
async def run_comparison(req: ComparisonRequest, db: AsyncSession = Depends(get_session)):
    """Run two simulations: one with a fixed strategy, one with AI-guided
    strategy switching.

    Phase 3: if replay_run_id is provided and that run has a logged
    decision history, the AI arm replays those REAL Gemini decisions and
    uses the ORIGINAL run's seed/load/step-count pulled from the DB — not
    whatever the frontend happened to send — so the comparison reflects the
    exact conditions Gemini actually responded to. If no real decision log
    is found, this falls back to a heuristic stand-in and reports that
    honestly via meta.used_replay so it's never silently mistaken for a
    real-AI result.
    """
    used_replay = False
    decision_log: List[dict] = []
    source_run_id: Optional[int] = None

    if req.replay_run_id is not None:
        run_record = await db.get(Run, req.replay_run_id)
        if run_record is None:
            raise HTTPException(status_code=404, detail="Original run not found")

        # Ground truth comes from the DB record, not the request body.
        seed = run_record.seed
        arrival_prob = run_record.arrival_prob
        mean_service = run_record.mean_service
        steps = run_record.total_steps if run_record.total_steps > 0 else req.steps
        source_run_id = run_record.id

        statement = (
            select(GeminiDecision)
            .where(GeminiDecision.run_id == req.replay_run_id)
            .order_by(GeminiDecision.step)
        )
        result = await db.exec(statement)
        decision_log = [{"step": d.step, "strategy": d.strategy} for d in result.all()]
        used_replay = len(decision_log) > 0
    else:
        # No original run to anchor against — explicit ad-hoc comparison
        # using whatever the caller sent.
        seed = req.seed
        arrival_prob = req.arrival_prob
        mean_service = req.mean_service
        steps = req.steps

    # Run 1: Without Gemini (fixed strategy) — isolated RNG, seeded once.
    engine_baseline = ComparisonEngine(
        strategy=req.base_strategy,
        arrival_prob=arrival_prob,
        mean_service=mean_service,
        seed=seed,
    )
    engine_baseline.run_steps(steps)

    # Run 2: With Gemini (real replay or heuristic fallback) — a SEPARATE
    # isolated RNG instance constructed with the same seed, so both arms
    # see identical arrival/failure draws regardless of which strategy
    # either one ends up running.
    engine_gemini = ComparisonEngine(
        strategy=req.base_strategy,
        arrival_prob=arrival_prob,
        mean_service=mean_service,
        seed=seed,
    )

    strategy_fn = gemini_strategy_selector
    if used_replay:
        decision_map = {d["step"]: d["strategy"] for d in decision_log}
        current_step = [0]

        def replay_selector(queue_len, fairness_std, num_failed, queue_rate):
            current_step[0] += 1
            step = current_step[0]
            if step in decision_map:
                return decision_map[step]
            past = [d for d in decision_log if d["step"] <= step]
            return past[-1]["strategy"] if past else req.base_strategy

        strategy_fn = replay_selector

    engine_gemini.run_steps(steps, strategy_fn=strategy_fn)

    # Build comparison data
    comparison_result = {
        "queueLength": [],
        "completedTotal": [],
        "fairnessStd": [],
    }

    for i in range(len(engine_baseline.metrics_history)):
        baseline = engine_baseline.metrics_history[i]
        gemini = engine_gemini.metrics_history[i]

        comparison_result["queueLength"].append({
            "time": baseline["time"],
            "withGemini": gemini["queue_len"],
            "withoutGemini": baseline["queue_len"],
        })
        comparison_result["completedTotal"].append({
            "time": baseline["time"],
            "withGemini": gemini["completed_total"],
            "withoutGemini": baseline["completed_total"],
        })
        comparison_result["fairnessStd"].append({
            "time": baseline["time"],
            "withGemini": gemini["fairness_std"],
            "withoutGemini": baseline["fairness_std"],
        })

    # Phase 7: diagnostic so a "no difference" result can be told apart from
    # a broken comparison — if steps_gemini_used_other_strategy stays near
    # zero, the AI arm genuinely agreed with the static choice; that's a
    # real (if less dramatic) finding, not a bug.
    steps_matched_base = sum(
        1 for m in engine_gemini.metrics_history if m["strategy"] == req.base_strategy
    )

    return {
        "comparison": comparison_result,
        "summary": {
            "baseline_strategy": req.base_strategy,
            "steps": steps,
            "baseline_final_queue": engine_baseline.metrics_history[-1]["queue_len"] if engine_baseline.metrics_history else 0,
            "gemini_final_queue": engine_gemini.metrics_history[-1]["queue_len"] if engine_gemini.metrics_history else 0,
            "baseline_total_completed": engine_baseline.metrics_history[-1]["completed_total"] if engine_baseline.metrics_history else 0,
            "gemini_total_completed": engine_gemini.metrics_history[-1]["completed_total"] if engine_gemini.metrics_history else 0,
        },
        "meta": {
            "used_replay": used_replay,
            "source_run_id": source_run_id,
            "seed": seed,
            "steps": steps,
            "decisions_replayed": len(decision_log),
        },
        "diagnostics": {
            "steps_gemini_matched_base_strategy": steps_matched_base,
            "steps_gemini_used_other_strategy": steps - steps_matched_base,
        },
    }