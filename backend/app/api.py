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