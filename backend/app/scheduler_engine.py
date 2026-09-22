# Target path in your project: app/scheduler_engine.py

import asyncio
import random
from collections import deque
from typing import Callable, List, Optional

import numpy as np

from app.models import JobLog

# Single source of truth for strategy names. api.py imports this rather than
# keeping its own literal copy.
STRATEGIES = [
    "baseline",
    "random_backoff",
    "consistent_hash",
    "token_ring",
    "leader_election",
]

# Load-curve shape, scaled by arrival_prob / ARRIVAL_PROB_BASELINE. Defined
# once here so the live path and the comparison path cannot drift apart.
LOAD_CURVE = [(80, 0.3), (180, 0.95), (300, 0.6), (400, 0.4)]
LOAD_CURVE_TAIL = 0.85
ARRIVAL_PROB_BASELINE = 0.6

FAILURE_PROB = 0.005
FAILURE_DURATION = (10, 30)
BACKOFF_DURATION = (2, 6)
LEADER_EPOCH_LEN = 20
STARVATION_THRESHOLD = 50
STARVATION_MIN_QUEUE = 5
EMA_ALPHA = 0.2


class Job:
    __slots__ = ("id", "arrival_time", "work_required", "hash_id", "start_step")

    def __init__(self, job_id: str, arrival_time: int, work_required: int):
        self.id = job_id
        self.arrival_time = arrival_time
        self.work_required = work_required
        # Derived from the engine's seeded RNG (see SimEngine._new_job), so a
        # given seed always produces the same hash ring placement. Previously
        # this came from uuid.uuid4(), which draws from os.urandom and is NOT
        # seeded — consistent_hash was therefore non-reproducible across runs
        # with identical seeds, silently breaking the CRN guarantee.
        self.hash_id = int(job_id, 16)
        self.start_step: Optional[int] = None


class Server:
    __slots__ = (
        "sid", "busy", "current_job", "completed_count",
        "work_remaining", "backoff_until", "failed", "failure_duration",
    )

    def __init__(self, sid: int):
        self.sid = sid
        self.busy = False
        self.current_job: Optional[Job] = None
        self.completed_count = 0
        self.work_remaining = 0
        self.backoff_until = 0
        self.failed = False
        self.failure_duration = 0

    @property
    def available(self) -> bool:
        """Can this server accept a new job right now?

        Every strategy must gate on this. Previously random_backoff,
        token_ring and leader_election checked only `busy`, so failed servers
        kept accepting and completing work — which made failure injection
        largely inert and the num_failed signal meaningless to the agent.
        """
        return not self.busy and not self.failed


class SimEngine:
    """Discrete-step scheduler simulation.

    The same instance type backs both the live WebSocket run and the offline
    comparison arms. There is exactly one implementation of each strategy;
    the comparison path drives `step()` synchronously instead of going
    through `run_loop()`.
    """

    def __init__(
        self,
        run_id: int,
        strategy: str,
        arrival_prob: float,
        mean_service: float,
        seed: int,
        num_servers: int = 8,
        sim_steps: int = 0,
        record_history: bool = False,
    ):
        if strategy not in STRATEGIES:
            raise ValueError(f"Unknown strategy: {strategy!r}. Expected one of {STRATEGIES}")

        self.run_id = run_id
        self.strategy = strategy
        self.num_servers = num_servers
        self.arrival_prob = arrival_prob
        self.mean_service = mean_service
        self.seed = seed
        # sim_steps <= 0 means "run until stopped".
        self.sim_steps = sim_steps

        # Three independent streams, all derived from `seed`. This is what
        # makes Common Random Numbers actually hold.
        #
        # SimEngine used to call random.seed()/np.random.seed(), mutating
        # global module state. The comparison path then used one isolated
        # stream per engine, which stops two arms interfering with each other
        # but does NOT stop a strategy from perturbing its own arm: only
        # random_backoff draws (shuffle + backoff), so every draw it made
        # shifted that arm's subsequent arrival and failure values. The two
        # arms therefore saw different workloads, which is precisely the
        # confound CRN exists to remove.
        #
        # With the streams split by concern, arrival and failure sequences are
        # identical across any two engines built from the same seed, whatever
        # strategies they run.
        self.rng_arrival = random.Random(seed * 1_000_003 + 1)
        self.rng_failure = random.Random(seed * 1_000_003 + 2)
        self.rng_strategy = random.Random(seed * 1_000_003 + 3)

        self.servers = [Server(i) for i in range(num_servers)]
        self.queue: deque = deque()
        self.time_step = 0
        self.running = False

        self.completed_jobs: List[JobLog] = []
        self.total_wait = 0          # arrival -> assignment
        self.total_turnaround = 0    # arrival -> completion
        self.jobs_arrived = 0
        self.jobs_assigned = 0
        self.jobs_completed = 0
        self.max_queue_len = 0

        self.last_queue_len = 0
        self.queue_rate = 0.0

        self.last_completion_step = 0
        self.starving = False        # current state, not a latch
        self.starvation_steps = 0    # cumulative evidence

        self.token_position = 0
        self.leader_id = 0

        self.record_history = record_history
        self.metrics_history: List[dict] = []

    # --- Lifecycle ---

    async def run_loop(self, broadcast_callback: Callable, tick_seconds: float):
        self.running = True
        print(f"Run {self.run_id}: started strategy={self.strategy} seed={self.seed}")

        while self.running:
            self.step()
            await broadcast_callback(self.get_metrics())

            # sim_steps is now actually enforced. It used to be persisted to
            # the DB and never read, so a run only ever ended by manual stop.
            if self.sim_steps > 0 and self.time_step >= self.sim_steps:
                print(f"Run {self.run_id}: reached sim_steps={self.sim_steps}, stopping")
                self.running = False
                break

            await asyncio.sleep(tick_seconds)

    def stop(self):
        self.running = False

    def run_steps(self, num_steps: int, strategy_fn: Optional[Callable] = None):
        """Synchronous driver used by the comparison pipeline.

        `strategy_fn(step, queue_len, fairness_std, num_failed, queue_rate)`
        returns the strategy to run for this step. It is applied verbatim —
        any hysteresis belongs inside the callable, not here.
        """
        for _ in range(num_steps):
            if strategy_fn is not None:
                chosen = strategy_fn(
                    self.time_step + 1,
                    len(self.queue),
                    self.fairness_std(),
                    sum(1 for s in self.servers if s.failed),
                    self.queue_rate,
                )
                if chosen is not None:
                    if chosen not in STRATEGIES:
                        raise ValueError(f"strategy_fn returned unknown strategy: {chosen!r}")
                    self.strategy = chosen
            self.step()

    # --- Core step ---

    def _current_arrival_prob(self) -> float:
        base = LOAD_CURVE_TAIL
        for boundary, value in LOAD_CURVE:
            if self.time_step <= boundary:
                base = value
                break
        scale = self.arrival_prob / ARRIVAL_PROB_BASELINE
        return max(0.0, min(1.0, base * scale))

    def _new_job(self) -> Job:
        job_id = f"{self.rng_arrival.getrandbits(32):08x}"
        work = max(1, int(self.rng_arrival.expovariate(1.0 / self.mean_service)))
        return Job(job_id, self.time_step, work)

    def step(self):
        self.time_step += 1
        self._process_failures()

        queue_diff = len(self.queue) - self.last_queue_len
        self.queue_rate = (1 - EMA_ALPHA) * self.queue_rate + EMA_ALPHA * queue_diff
        self.last_queue_len = len(self.queue)

        if self.rng_arrival.random() < self._current_arrival_prob():
            self.queue.append(self._new_job())
            self.jobs_arrived += 1

        self._execute_strategy()

        for server in self.servers:
            # A failed server makes no progress on its in-flight job. It used
            # to keep decrementing work_remaining and completing normally.
            if server.busy and not server.failed:
                server.work_remaining -= 1
                if server.work_remaining <= 0:
                    self._complete_job(server)

        self.max_queue_len = max(self.max_queue_len, len(self.queue))
        self._check_starvation()

        if self.record_history:
            self.metrics_history.append({
                "time": self.time_step,
                "queue_len": len(self.queue),
                "completed_total": self.jobs_completed,
                "fairness_std": self.fairness_std(),
                "strategy": self.strategy,
                "num_failed": sum(1 for s in self.servers if s.failed),
            })

    def _process_failures(self):
        for server in self.servers:
            if server.failed:
                server.failure_duration -= 1
                if server.failure_duration <= 0:
                    server.failed = False
            elif self.rng_failure.random() < FAILURE_PROB:
                server.failed = True
                server.failure_duration = self.rng_failure.randint(*FAILURE_DURATION)
                if server.busy:
                    # Preempt: the job goes back to the front of the queue and
                    # loses the work already done on it.
                    self.queue.appendleft(server.current_job)
                    server.busy = False
                    server.current_job = None
                    server.work_remaining = 0

    def _assign_job(self, server: Server, job: Job):
        job.start_step = self.time_step
        self.total_wait += self.time_step - job.arrival_time
        self.jobs_assigned += 1
        server.busy = True
        server.current_job = job
        server.work_remaining = job.work_required

    def _complete_job(self, server: Server):
        job = server.current_job
        server.busy = False
        server.current_job = None
        server.completed_count += 1

        self.jobs_completed += 1
        self.total_turnaround += self.time_step - job.arrival_time
        self.last_completion_step = self.time_step

        self.completed_jobs.append(JobLog(
            run_id=self.run_id,
            job_internal_id=job.id,
            arrival_step=job.arrival_time,
            completion_step=self.time_step,
            processed_by=server.sid,
        ))

    def _check_starvation(self):
        """Backlog present but nothing finishing.

        This is starvation/livelock detection, not deadlock detection — there
        is no circular resource dependency in this model. `starving` now
        reflects the CURRENT state instead of latching to True forever after a
        single transient trip.
        """
        idle_for = self.time_step - self.last_completion_step
        self.starving = idle_for > STARVATION_THRESHOLD and len(self.queue) > STARVATION_MIN_QUEUE
        if self.starving:
            self.starvation_steps += 1

    # --- Strategies (the only implementation of these in the codebase) ---

    def _execute_strategy(self):
        {
            "baseline": self._strategy_baseline,
            "random_backoff": self._strategy_random_backoff,
            "consistent_hash": self._strategy_consistent_hash,
            "token_ring": self._strategy_token_ring,
            "leader_election": self._strategy_leader_election,
        }[self.strategy]()

    def _strategy_baseline(self):
        """Lowest server ID claims the head of the queue first."""
        for server in self.servers:
            if not self.queue:
                break
            if server.available:
                self._assign_job(server, self.queue.popleft())

    def _strategy_random_backoff(self):
        """Contention with randomised retry, in the spirit of CSMA/CD.

        When more servers are ready than there are jobs, exactly one wins and
        the losers sit out a random number of steps.
        """
        ready = [s for s in self.servers if s.available and self.time_step >= s.backoff_until]
        if not ready or not self.queue:
            return

        if len(ready) > 1 and len(self.queue) < len(ready):
            self.rng_strategy.shuffle(ready)
            winner, losers = ready[0], ready[1:]
            self._assign_job(winner, self.queue.popleft())
            for loser in losers:
                loser.backoff_until = self.time_step + self.rng_strategy.randint(*BACKOFF_DURATION)
        else:
            for server in ready:
                if not self.queue:
                    break
                self._assign_job(server, self.queue.popleft())

    def _strategy_consistent_hash(self):
        """Each job hashes to a preferred server, probing forward on collision."""
        if not self.queue:
            return

        remaining = deque()
        for job in self.queue:
            preferred = job.hash_id % self.num_servers
            for offset in range(self.num_servers):
                server = self.servers[(preferred + offset) % self.num_servers]
                if server.available:
                    self._assign_job(server, job)
                    break
            else:
                remaining.append(job)
        # Rebuilding the deque once is O(n). The old version called
        # deque.remove() inside the loop, which is a linear scan per removal.
        self.queue = remaining

    def _strategy_token_ring(self):
        """A token rotates one position every 2 steps; only the holder may claim."""
        self.token_position = (self.time_step // 2) % self.num_servers
        holder = self.servers[self.token_position]
        if holder.available and self.queue:
            self._assign_job(holder, self.queue.popleft())

    def _strategy_leader_election(self):
        """Leader re-elected every epoch; it dispatches to workers, then itself."""
        if self.time_step % LEADER_EPOCH_LEN == 0:
            # Most completions wins. sorted() is stable, so equal counts
            # resolve to the lowest sid — deterministic, despite the old
            # comment claiming random tie-breaking.
            self.leader_id = max(
                self.servers,
                key=lambda s: (s.completed_count, -s.sid),
            ).sid

        leader = self.servers[self.leader_id]
        workers = [s for s in self.servers if s.available and s.sid != leader.sid]

        for worker in workers:
            if not self.queue:
                break
            self._assign_job(worker, self.queue.popleft())

        if self.queue and leader.available:
            self._assign_job(leader, self.queue.popleft())

    # --- Metrics ---

    def fairness_std(self) -> float:
        counts = [s.completed_count for s in self.servers]
        return float(np.std(counts)) if counts else 0.0

    def avg_wait(self) -> float:
        """Mean steps spent queued before a server picked the job up.

        Counts every assignment, so a job preempted by a server failure and
        later re-queued contributes each time it waits.
        """
        return self.total_wait / self.jobs_assigned if self.jobs_assigned else 0.0

    def avg_turnaround(self) -> float:
        """Mean steps from arrival to completion."""
        return self.total_turnaround / self.jobs_completed if self.jobs_completed else 0.0

    def throughput(self) -> float:
        return self.jobs_completed / self.time_step if self.time_step else 0.0

    def avg_queue_len(self) -> float:
        if not self.metrics_history:
            return 0.0
        return sum(m["queue_len"] for m in self.metrics_history) / len(self.metrics_history)

    def get_metrics(self) -> dict:
        completed_counts = [s.completed_count for s in self.servers]
        return {
            "run_id": self.run_id,
            "payload": {
                "time": self.time_step,
                "queue_len": len(self.queue),
                "queue_rate": round(self.queue_rate, 3),
                "num_failed": sum(1 for s in self.servers if s.failed),
                "completed_total": sum(completed_counts),
                "deadlock_detected": self.starving,
                "strategy": self.strategy,
                "fairness_std": self.fairness_std(),
                "avg_wait": round(self.avg_wait(), 2),
                "servers": [
                    {
                        "sid": s.sid,
                        "busy": s.busy,
                        "completed": s.completed_count,
                        "failed": s.failed,
                    }
                    for s in self.servers
                ],
            },
        }
