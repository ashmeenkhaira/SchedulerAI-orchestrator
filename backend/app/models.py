from datetime import datetime
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship

class Run(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy: str
    seed: int
    arrival_prob: float
    mean_service: float
    sim_steps: int
    start_time: datetime = Field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    total_completed: int = 0
    total_steps: int = 0
    deadlock_occurred: bool = False
    avg_wait_time: float = 0.0

class JobLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id")
    job_internal_id: str
    arrival_step: int
    completion_step: int
    processed_by: int

class GeminiDecision(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id")
    step: int
    strategy: str
    action: str
    raw_message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)