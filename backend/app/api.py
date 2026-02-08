import asyncio
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends
from typing import List, Dict, Set
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.scheduler_engine import SimEngine
from app.database import get_session
from app.models import Run

router = APIRouter()

# --- Connection Manager for WebSockets ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.active_connections.discard(connection)

manager = ConnectionManager()

# --- Simulation State ---
# Map run_id -> Engine Instance
active_engines: Dict[int, SimEngine] = {}
# Map run_id -> Asyncio Task
active_tasks: Dict[int, asyncio.Task] = {}

class StartRunRequest(BaseModel):
    strategy: str
    sim_steps: int = 2000
    arrival_prob: float = 0.4
    mean_service: float = 5.0
    seed: int = 42

class StopRunRequest(BaseModel):
    run_id: int

# --- Routes ---

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep alive / listen for client commands if needed
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@router.post("/runs/start")
async def start_run(req: StartRunRequest, db: AsyncSession = Depends(get_session)):
    # 1. Create Run entry in DB
    new_run = Run(strategy=req.strategy)
    db.add(new_run)
    await db.commit()
    await db.refresh(new_run)
    
    run_id = new_run.id
    
    # 2. Stop any existing runs (Single simulation mode for simplicity)
    for existing_id in list(active_tasks.keys()):
        await stop_simulation(existing_id, db)
        
    # 3. Initialize Engine
    engine = SimEngine(
        run_id=run_id, 
        strategy=req.strategy,
        arrival_prob=req.arrival_prob,
        mean_service=req.mean_service,
        seed=req.seed
    )
    
    # 4. Start background task
    task = asyncio.create_task(engine.run_loop(manager.broadcast))
    active_tasks[run_id] = task
    
    return {"status": "started", "run_id": run_id, "strategy": req.strategy}

@router.post("/runs/stop")
async def stop_run_endpoint(req: StopRunRequest, db: AsyncSession = Depends(get_session)):
    await stop_simulation(req.run_id, db)
    return {"status": "stopped", "run_id": req.run_id}

async def stop_simulation(run_id: int, db: AsyncSession):
    if run_id in active_engines:
        # Signal engine to stop
        engine = active_engines[run_id]
        engine.stop()
        
        # Cancel task
        if run_id in active_tasks:
            active_tasks[run_id].cancel()
            try:
                await active_tasks[run_id]
            except asyncio.CancelledError:
                pass
            del active_tasks[run_id]
        
        # Update DB with final stats
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
    # Simple fetch of run history
    from sqlmodel import select
    statement = select(Run).order_by(Run.id.desc()).offset(skip).limit(limit)
    result = await db.exec(statement)
    return result.all()

@router.delete("/runs/clear-all")
async def clear_all_runs(db: AsyncSession = Depends(get_session)):
    """Clear all simulation data from database"""
    from sqlmodel import select, delete
    from app.models import JobLog
    
    # Delete all job logs first (foreign key constraint)
    await db.exec(delete(JobLog))
    # Delete all runs
    await db.exec(delete(Run))
    await db.commit()
    
    return {"status": "success", "message": "All simulation data cleared"}


# --- Comparison Mode ---
class ComparisonRequest(BaseModel):
    base_strategy: str = "baseline"  # Fixed strategy for "without Gemini"
    steps: int = 100
    arrival_prob: float = 0.4
    mean_service: float = 5.0
    seed: int = 42

class ComparisonEngine:
    """Synchronous simulation for comparison (no WebSocket, just results)"""
    def __init__(self, strategy: str, arrival_prob: float, mean_service: float, seed: int, num_servers: int = 8):
        import random
        import numpy as np
        from collections import deque
        
        self.strategy = strategy
        self.num_servers = num_servers
        self.arrival_prob = arrival_prob
        self.mean_service = mean_service
        
        random.seed(seed)
        np.random.seed(seed)
        
        self.servers = [{"sid": i, "busy": False, "work_remaining": 0, "completed": 0, "current_job": None} for i in range(num_servers)]
        self.queue = deque()
        self.time_step = 0
        self.metrics_history = []
        
    def run_steps(self, num_steps: int, strategy_fn=None):
        """Run simulation for num_steps, optionally with dynamic strategy switching"""
        import random
        import numpy as np
        
        for _ in range(num_steps):
            self.time_step += 1
            
            # Job arrival
            if random.random() < self.arrival_prob:
                work = max(1, int(random.expovariate(1.0 / self.mean_service)))
                self.queue.append({"arrival": self.time_step, "work": work, "id": self.time_step})
            
            # Dynamic strategy switch (Gemini-like behavior)
            current_strategy = self.strategy
            if strategy_fn:
                current_strategy = strategy_fn(len(self.queue), self._fairness_std())
            
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
                "strategy": current_strategy
            })
    
    def _fairness_std(self):
        import numpy as np
        completed = [s["completed"] for s in self.servers]
        return float(np.std(completed)) if completed else 0.0
    
    def _execute_strategy(self, strategy: str):
        import random
        
        free_servers = [s for s in self.servers if not s["busy"]]
        
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
                random.shuffle(free_servers)
                for server in free_servers:
                    if self.queue:
                        job = self.queue.popleft()
                        server["busy"] = True
                        server["work_remaining"] = job["work"]
                        server["current_job"] = job
                        
        elif strategy == "consistent_hash":
            for job in list(self.queue):
                preferred = hash(job["id"]) % self.num_servers
                server = self.servers[preferred]
                if not server["busy"]:
                    self.queue.remove(job)
                    server["busy"] = True
                    server["work_remaining"] = job["work"]
                    server["current_job"] = job
                    
        elif strategy == "token_ring":
            token_pos = (self.time_step // 2) % self.num_servers
            server = self.servers[token_pos]
            if not server["busy"] and self.queue:
                job = self.queue.popleft()
                server["busy"] = True
                server["work_remaining"] = job["work"]
                server["current_job"] = job
                
        elif strategy == "leader_election":
            # Simple: first server is leader, distributes to others
            for server in free_servers:
                if self.queue:
                    job = self.queue.popleft()
                    server["busy"] = True
                    server["work_remaining"] = job["work"]
                    server["current_job"] = job

def gemini_strategy_selector(queue_len: int, fairness_std: float) -> str:
    """Simulates Gemini's decision rules from the system prompt"""
    if queue_len > 60:
        return "leader_election"
    elif fairness_std > 5:
        return "token_ring"
    elif queue_len > 40:
        return "random_backoff"
    elif queue_len >= 10:
        return "consistent_hash"
    else:
        return "baseline"

@router.post("/runs/compare")
async def run_comparison(req: ComparisonRequest):
    """Run two simulations: one with fixed strategy, one with AI-guided strategy switching"""
    import random
    import numpy as np
    
    # Run 1: Without Gemini (fixed strategy)
    random.seed(req.seed)
    np.random.seed(req.seed)
    engine_baseline = ComparisonEngine(
        strategy=req.base_strategy,
        arrival_prob=req.arrival_prob,
        mean_service=req.mean_service,
        seed=req.seed
    )
    engine_baseline.run_steps(req.steps)
    
    # Run 2: With Gemini (dynamic strategy based on rules)
    random.seed(req.seed)
    np.random.seed(req.seed)
    engine_gemini = ComparisonEngine(
        strategy=req.base_strategy,
        arrival_prob=req.arrival_prob,
        mean_service=req.mean_service,
        seed=req.seed
    )
    engine_gemini.run_steps(req.steps, strategy_fn=gemini_strategy_selector)
    
    # Build comparison data
    comparison_result = {
        "queueLength": [],
        "completedTotal": [],
        "fairnessStd": []
    }
    
    for i in range(len(engine_baseline.metrics_history)):
        baseline = engine_baseline.metrics_history[i]
        gemini = engine_gemini.metrics_history[i]
        
        comparison_result["queueLength"].append({
            "time": baseline["time"],
            "withGemini": gemini["queue_len"],
            "withoutGemini": baseline["queue_len"]
        })
        comparison_result["completedTotal"].append({
            "time": baseline["time"],
            "withGemini": gemini["completed_total"],
            "withoutGemini": baseline["completed_total"]
        })
        comparison_result["fairnessStd"].append({
            "time": baseline["time"],
            "withGemini": gemini["fairness_std"],
            "withoutGemini": baseline["fairness_std"]
        })
    
    return {
        "comparison": comparison_result,
        "summary": {
            "baseline_strategy": req.base_strategy,
            "steps": req.steps,
            "baseline_final_queue": engine_baseline.metrics_history[-1]["queue_len"] if engine_baseline.metrics_history else 0,
            "gemini_final_queue": engine_gemini.metrics_history[-1]["queue_len"] if engine_gemini.metrics_history else 0,
            "baseline_total_completed": engine_baseline.metrics_history[-1]["completed_total"] if engine_baseline.metrics_history else 0,
            "gemini_total_completed": engine_gemini.metrics_history[-1]["completed_total"] if engine_gemini.metrics_history else 0,
        }
    }