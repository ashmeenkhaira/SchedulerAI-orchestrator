# Target path in your project: app/scheduler_engine.py

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
        self.backoff_until = 0 # Step number until which server is backed off
        self.failed = False
        self.failure_duration = 0

class SimEngine:
    def __init__(self, run_id: int, strategy: str, arrival_prob: float, mean_service: float, seed: int, num_servers: int = 8):
        self.run_id = run_id
        self.strategy = strategy
        self.num_servers = num_servers
        self.arrival_prob = arrival_prob
        self.mean_service = mean_service

        # Apply the seed for reproducible runs
        random.seed(seed)
        np.random.seed(seed)

        self.servers = [Server(i) for i in range(num_servers)]
        self.queue: deque[Job] = deque()
        self.time_step = 0
        self.running = False
        self.deadlock_detected = False
        self.completed_jobs: List[JobLog] = []

        # New Metrics
        self.last_queue_len = 0
        self.queue_rate = 0.0

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

    def _get_dynamic_arrival_prob(self) -> float:
        # Phase 5: arrival_prob now actually does something. The original
        # hardcoded values (0.3 / 0.95 / 0.6 / 0.4 / 0.85) are kept as the
        # SHAPE of the load curve — light, heavy spike, taper, heavy again —
        # which is useful for testing varied conditions. arrival_prob scales
        # that shape relative to a baseline of 0.6 (≈ the schedule's
        # average), so arrival_prob=0.6 reproduces the original behavior
        # exactly, arrival_prob=0.3 halves intensity throughout, etc.
        # Clamped to [0, 1] since it's a probability.
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

    def step(self):
        self.time_step += 1
        self._process_failures()

        # Calculate queue rate (EMA)
        queue_diff = len(self.queue) - self.last_queue_len
        self.queue_rate = 0.8 * self.queue_rate + 0.2 * queue_diff
        self.last_queue_len = len(self.queue)

        # 1. Job Arrival (Poisson-like)
        current_arrival_prob = self._get_dynamic_arrival_prob()
        if random.random() < current_arrival_prob:
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

    def _process_failures(self):
        for server in self.servers:
            # Recover failed servers
            if server.failed:
                server.failure_duration -= 1
                if server.failure_duration <= 0:
                    server.failed = False
                    print(f"Server {server.sid} recovered at step {self.time_step}")

            # Random failure: 0.5% chance per server per step
            elif random.random() < 0.005:
                server.failed = True
                server.failure_duration = random.randint(10, 30)  # steps offline
                # Preempt in-progress job back to queue
                if server.busy:
                    self.queue.appendleft(server.current_job)  # priority re-queue
                    server.busy = False
                    server.current_job = None
                    server.work_remaining = 0

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
        free_servers = [s for s in self.servers if not s.busy and not s.failed]
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
        snapshot_queue = list(self.queue)
        for job in snapshot_queue:
            preferred_sid = job.hash_id % self.num_servers
            # Find the next free server in the ring
            for offset in range(self.num_servers):
                sid = (preferred_sid + offset) % self.num_servers
                server = self.servers[sid]
                if not server.busy and not server.failed:
                    self.queue.remove(job)
                    self._assign_job(server, job)
                    break

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
        num_failed = sum(1 for s in self.servers if s.failed)
        return {
            "run_id": self.run_id,
            "payload": {
                "time": self.time_step,
                "queue_len": len(self.queue),
                "queue_rate": round(self.queue_rate, 3),
                "num_failed": num_failed,
                "completed_total": sum(completed_counts),
                "deadlock_detected": self.deadlock_detected,
                "strategy": self.strategy,
                "fairness_std": float(np.std(completed_counts)) if completed_counts else 0.0,
                "servers": [
                    {
                        "sid": s.sid,
                        "busy": s.busy,
                        "completed": s.completed_count,
                        "failed": s.failed
                    } for s in self.servers
                ]
            }
        }