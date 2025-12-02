import asyncio
import random
import uuid
import numpy as np
from collections import deque
from datetime import datetime
from typing import List, Dict, Optional, Callable
from app.models import Run, JobLog
from app.database import engine as db_engine
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

class Job:
    def __init__(self, arrival_time: int, work_required: int):
        self.id = str(uuid.uuid4())[:8]
        self.arrival_time = arrival_time
        self.work_required = work_required
        self.hash_id = int(self.id, 16)  # For consistent hashing

class Server:
    def __init__(self, sid: int):
        self.sid = sid
        self.busy = False
        self.current_job: Optional[Job] = None
        self.completed_count = 0
        self.work_remaining = 0
        self.backoff_until = 0  # Step number until which server is backed off

class SimEngine:
    def __init__(self, run_id: int, strategy: str, arrival_prob: float, mean_service: float, seed: int, num_servers: int = 8):
        self.run_id = run_id
        self.strategy = strategy
        self.num_servers = num_servers
        self.arrival_prob = arrival_prob    # <--- NEW
        self.mean_service = mean_service    # <--- NEW
        
        # Apply the seed for reproducible runs
        random.seed(seed)                   # <--- NEW
        np.random.seed(seed)                # <--- NEW

        self.servers = [Server(i) for i in range(num_servers)]
        self.queue: deque[Job] = deque()
        self.time_step = 0
        self.running = False
        self.deadlock_detected = False
        self.completed_jobs: List[JobLog] = []
        
        # Deadlock tracking
        self.last_completion_step = 0
        self.deadlock_threshold = 50
        
        # Strategy specific state
        self.token_position = 0
        self.leader_id = 0
        self.leader_epoch = 0
        self.LEADER_EPOCH_LEN = 20
        
        # Deadlock tracking
        self.last_completion_step = 0
        self.deadlock_threshold = 50
        
        # Strategy specific state
        self.token_position = 0
        self.leader_id = 0
        self.leader_epoch = 0
        self.LEADER_EPOCH_LEN = 20

    async def run_loop(self, broadcast_callback: Callable):
        self.running = True
        print(f"Run {self.run_id}: Started with strategy {self.strategy}")
        
        while self.running:
            self.step()
            
            # Broadcast metrics
            metrics = self.get_metrics()
            await broadcast_callback(metrics)
            
            # CHANGE THIS VALUE:
            await asyncio.sleep(0.5)  # 0.5 seconds = 2 steps per second (Readable speed)
            
    def stop(self):
        self.running = False

    def step(self):
        self.time_step += 1
        
        # 1. Job Arrival (Poisson-like)
        if random.random() < self.arrival_prob:
            # Use configured mean service time
            work = max(1, int(random.expovariate(1.0 / self.mean_service)))
            self.queue.append(Job(self.time_step, work))

        # 2. Strategy Execution
        if self.strategy == "baseline":
            self._strategy_baseline()
        elif self.strategy == "random_backoff":
            self._strategy_random_backoff()
        elif self.strategy == "consistent_hash":
            self._strategy_consistent_hash()
        elif self.strategy == "token_ring":
            self._strategy_token_ring()
        elif self.strategy == "leader_election":
            self._strategy_leader_election()

        # 3. Process Work
        for server in self.servers:
            if server.busy:
                server.work_remaining -= 1
                if server.work_remaining <= 0:
                    # Job Complete
                    self._complete_job(server)

        # 4. Deadlock Detection
        self._check_deadlock()

    def _complete_job(self, server: Server):
        job = server.current_job
        server.busy = False
        server.current_job = None
        server.completed_count += 1
        self.last_completion_step = self.time_step
        
        # Log for DB
        self.completed_jobs.append(JobLog(
            run_id=self.run_id,
            job_internal_id=job.id,
            arrival_step=job.arrival_time,
            completion_step=self.time_step,
            processed_by=server.sid
        ))

    def _check_deadlock(self):
        # Rule: No completions for X steps AND queue is growing
        time_since_last = self.time_step - self.last_completion_step
        if time_since_last > self.deadlock_threshold and len(self.queue) > 5:
            self.deadlock_detected = True

    # --- Strategies ---

    def _strategy_baseline(self):
        """Lowest Server ID claims first available job."""
        free_servers = [s for s in self.servers if not s.busy]
        free_servers.sort(key=lambda s: s.sid) # Deterministic
        
        for server in free_servers:
            if self.queue:
                job = self.queue.popleft()
                self._assign_job(server, job)

    def _strategy_random_backoff(self):
        """Servers pick random wait times on contention."""
        # 1. Check backoffs
        ready_servers = [
            s for s in self.servers 
            if not s.busy and self.time_step >= s.backoff_until
        ]
        
        if not ready_servers or not self.queue:
            return

        # 2. Emulate contention
        # If multiple servers want the same resource (front of queue)
        if len(ready_servers) > 1 and len(self.queue) < len(ready_servers):
            # Collision happens. Random winner, others backoff
            random.shuffle(ready_servers)
            winner = ready_servers[0]
            job = self.queue.popleft()
            self._assign_job(winner, job)
            
            # Losers backoff
            for loser in ready_servers[1:]:
                loser.backoff_until = self.time_step + random.randint(2, 6)
        else:
            # No contention
            for server in ready_servers:
                if self.queue:
                    job = self.queue.popleft()
                    self._assign_job(server, job)

    def _strategy_consistent_hash(self):
        """Jobs assigned to server based on Hash(Job) % N."""
        # Check all queued jobs to see if their preferred server is free
        # Limit checking depth to prevent O(N^2) in simulation
        snapshot_queue = list(self.queue)
        for job in snapshot_queue:
            preferred_sid = job.hash_id % self.num_servers
            server = self.servers[preferred_sid]
            
            if not server.busy:
                self.queue.remove(job)
                self._assign_job(server, job)

    def _strategy_token_ring(self):
        """Token rotates. Only holder can take job."""
        # Rotate token
        self.token_position = (self.time_step // 2) % self.num_servers
        token_holder = self.servers[self.token_position]
        
        if not token_holder.busy and self.queue:
            job = self.queue.popleft()
            self._assign_job(token_holder, job)

    def _strategy_leader_election(self):
        """Leader assigns jobs to others."""
        # 1. Elect leader periodically
        if self.time_step % self.LEADER_EPOCH_LEN == 0:
            # Simple election: server with most completions wins (meritocracy)
            # breaking ties randomly
            candidates = sorted(self.servers, key=lambda s: s.completed_count, reverse=True)
            self.leader_id = candidates[0].sid
            
        leader = self.servers[self.leader_id]
        
        # Leader logic: Distribute queued jobs to free workers
        free_workers = [s for s in self.servers if not s.busy and s.sid != leader.sid]
        
        while self.queue and free_workers:
            worker = free_workers.pop(0)
            job = self.queue.popleft()
            self._assign_job(worker, job)
            
        # Leader works too if needed
        if not leader.busy and self.queue and not free_workers:
             job = self.queue.popleft()
             self._assign_job(leader, job)

    def _assign_job(self, server: Server, job: Job):
        server.busy = True
        server.current_job = job
        server.work_remaining = job.work_required

    def get_metrics(self) -> dict:
        completed_counts = [s.completed_count for s in self.servers]
        return {
            "run_id": self.run_id,
            "payload": {
                "time": self.time_step,
                "queue_len": len(self.queue),
                "completed_total": sum(completed_counts),
                "deadlock_detected": self.deadlock_detected,
                "strategy": self.strategy,
                "fairness_std": float(np.std(completed_counts)) if completed_counts else 0.0,
                "servers": [
                    {
                        "sid": s.sid,
                        "busy": s.busy,
                        "completed": s.completed_count
                    } for s in self.servers
                ]
            }
        }