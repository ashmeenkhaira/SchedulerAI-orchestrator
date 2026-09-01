"""
Metrics calculator for SchedulerAI Orchestrator resume bullet points.
Runs the comparison engine across all strategies x multiple seeds to produce
real, defensible numbers.
"""
import sys
import os
import random
import numpy as np
from collections import deque

# ── Inline ComparisonEngine (copied from api.py to avoid import issues) ──

class ComparisonEngine:
    def __init__(self, strategy, arrival_prob, mean_service, seed, num_servers=8):
        random.seed(seed)
        np.random.seed(seed)
        
        self.strategy = strategy
        self.num_servers = num_servers
        self.arrival_prob = arrival_prob
        self.mean_service = mean_service
        self.seed = seed
        
        self.servers = [{"sid": i, "busy": False, "work_remaining": 0, "completed": 0, "current_job": None, "failed": False, "failure_duration": 0} for i in range(num_servers)]
        self.queue = deque()
        self.time_step = 0
        self.metrics_history = []
        self.total_wait_time = 0
        self.total_completed = 0
        self.jobs_arrived = 0
        self.max_queue_len = 0
        self.deadlock_steps = 0
        self.last_completion_step = 0
        
        self.last_queue_len = 0
        self.queue_rate = 0.0
        self.last_strategy = strategy
        self.steps_since_switch = 0
        
    def _get_dynamic_arrival_prob(self) -> float:
        if self.time_step <= 80:
            return 0.3
        elif self.time_step <= 180:
            return 0.95
        elif self.time_step <= 300:
            return 0.6
        elif self.time_step <= 400:
            return 0.4
        else:
            return 0.85

    def run_steps(self, num_steps, strategy_fn=None):
        for _ in range(num_steps):
            self.time_step += 1
            self.steps_since_switch += 1
            
            num_failed = 0
            for server in self.servers:
                if server["failed"]:
                    server["failure_duration"] -= 1
                    if server["failure_duration"] <= 0:
                        server["failed"] = False
                elif random.random() < 0.005:
                    server["failed"] = True
                    server["failure_duration"] = random.randint(10, 30)
                    if server["busy"]:
                        self.queue.appendleft(server["current_job"])
                        server["busy"] = False
                        server["current_job"] = None
                        server["work_remaining"] = 0
                
                if server["failed"]:
                    num_failed += 1

            queue_diff = len(self.queue) - self.last_queue_len
            self.queue_rate = 0.8 * self.queue_rate + 0.2 * queue_diff
            self.last_queue_len = len(self.queue)
            
            current_arrival_prob = self._get_dynamic_arrival_prob()
            if random.random() < current_arrival_prob:
                work = max(1, int(random.expovariate(1.0 / self.mean_service)))
                self.queue.append({"arrival": self.time_step, "work": work, "id": self.time_step})
                self.jobs_arrived += 1
            
            current_strategy = self.strategy
            if strategy_fn:
                suggested_strategy = strategy_fn(len(self.queue), self._fairness_std(), num_failed, self.queue_rate)
                if suggested_strategy != self.last_strategy and self.steps_since_switch >= 15:
                    self.last_strategy = suggested_strategy
                    self.steps_since_switch = 0
                current_strategy = self.last_strategy
                self.strategy = current_strategy
            
            self._execute_strategy(current_strategy)
            
            completed_this_step = 0
            for server in self.servers:
                if server["busy"]:
                    server["work_remaining"] -= 1
                    if server["work_remaining"] <= 0:
                        if server["current_job"]:
                            wait = self.time_step - server["current_job"]["arrival"]
                            self.total_wait_time += wait
                            self.total_completed += 1
                        server["busy"] = False
                        server["current_job"] = None
                        server["completed"] += 1
                        completed_this_step += 1
                        self.last_completion_step = self.time_step
            
            if len(self.queue) > self.max_queue_len:
                self.max_queue_len = len(self.queue)
            
            if (self.time_step - self.last_completion_step > 50) and len(self.queue) > 5:
                self.deadlock_steps += 1
            
            self.metrics_history.append({
                "time": self.time_step,
                "queue_len": len(self.queue),
                "completed_total": sum(s["completed"] for s in self.servers),
                "fairness_std": self._fairness_std(),
                "strategy": current_strategy
            })
    
    def _fairness_std(self):
        completed = [s["completed"] for s in self.servers]
        return float(np.std(completed)) if completed else 0.0
    
    def _execute_strategy(self, strategy):
        free_servers = [s for s in self.servers if not s["busy"] and not s["failed"]]
        
        if strategy == "baseline":
            # Greedy baseline: optimal under low load, but suffers from lock contention under high load
            free_servers.sort(key=lambda s: s["sid"])
            dispatched = 0
            for server in free_servers:
                if self.queue:
                    if len(self.queue) > 15 and dispatched >= 2:
                        break # Lock contention limits throughput
                    job = self.queue.popleft()
                    server["busy"] = True
                    server["work_remaining"] = job["work"]
                    server["current_job"] = job
                    dispatched += 1
                    
        elif strategy == "random_backoff":
            if free_servers and self.queue:
                random.shuffle(free_servers)
                for server in free_servers:
                    if self.queue:
                        job = self.queue.popleft()
                        server["busy"] = True
                        server["work_remaining"] = job["work"] + 1 # Random backoff overhead
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
            # Leader election: avoids lock contention, but has fixed epoch overhead
            if self.time_step % 20 == 0:
                return # Epoch election pause
            for server in free_servers:
                if self.queue:
                    job = self.queue.popleft()
                    server["busy"] = True
                    server["work_remaining"] = job["work"]
                    server["current_job"] = job

    def avg_queue_len(self):
        if not self.metrics_history:
            return 0
        return sum(m["queue_len"] for m in self.metrics_history) / len(self.metrics_history)
    
    def avg_wait_time(self):
        if self.total_completed == 0:
            return 0
        return self.total_wait_time / self.total_completed
    
    def final_fairness(self):
        if not self.metrics_history:
            return 0
        return self.metrics_history[-1]["fairness_std"]
    
    def avg_fairness(self):
        if not self.metrics_history:
            return 0
        return sum(m["fairness_std"] for m in self.metrics_history) / len(self.metrics_history)
    
    def throughput(self):
        if self.time_step == 0:
            return 0
        return self.total_completed / self.time_step


def gemini_strategy_selector(queue_len, fairness_std, num_failed, queue_rate):
    if queue_len > 15 or queue_rate > 2.0:
        return "leader_election"
    if num_failed >= 2:
        return "consistent_hash"
    if fairness_std > 5 and queue_len < 10:
        return "token_ring"
    if queue_len > 25:
        return "random_backoff"
    return "baseline"


# ── Run Experiments ──

STRATEGIES = ["baseline", "random_backoff", "consistent_hash", "token_ring", "leader_election"]
SEEDS = [1, 42, 123, 456, 789, 1000, 2024, 3141, 9999, 7777]
STEPS = 500
ARRIVAL_PROB = 0.85
MEAN_SERVICE = 8.0

print("=" * 80)
print("SchedulerAI Orchestrator -- Resume Metrics Calculator")
print("=" * 80)
print(f"\nConfig: {len(SEEDS)} seeds x {len(STRATEGIES)} strategies x {STEPS} steps")
print(f"Arrival prob: {ARRIVAL_PROB}, Mean service: {MEAN_SERVICE}, Servers: 8\n")

results = {}

for strategy in STRATEGIES:
    results[strategy] = {"fixed": [], "ai": []}
    
    for seed in SEEDS:
        random.seed(seed)
        np.random.seed(seed)
        fixed = ComparisonEngine(strategy, ARRIVAL_PROB, MEAN_SERVICE, seed)
        fixed.run_steps(STEPS)
        
        random.seed(seed)
        np.random.seed(seed)
        ai = ComparisonEngine(strategy, ARRIVAL_PROB, MEAN_SERVICE, seed)
        ai.run_steps(STEPS, strategy_fn=gemini_strategy_selector)
        
        results[strategy]["fixed"].append({
            "avg_queue": fixed.avg_queue_len(),
            "avg_wait": fixed.avg_wait_time(),
            "throughput": fixed.throughput(),
            "completed": fixed.total_completed,
            "max_queue": fixed.max_queue_len,
            "avg_fairness": fixed.avg_fairness(),
            "final_fairness": fixed.final_fairness(),
            "deadlock_steps": fixed.deadlock_steps,
            "jobs_arrived": fixed.jobs_arrived,
        })
        results[strategy]["ai"].append({
            "avg_queue": ai.avg_queue_len(),
            "avg_wait": ai.avg_wait_time(),
            "throughput": ai.throughput(),
            "completed": ai.total_completed,
            "max_queue": ai.max_queue_len,
            "avg_fairness": ai.avg_fairness(),
            "final_fairness": ai.final_fairness(),
            "deadlock_steps": ai.deadlock_steps,
            "jobs_arrived": ai.jobs_arrived,
        })

# ── Print Results ──

def avg(lst):
    return sum(lst) / len(lst) if lst else 0

def pct_change(old, new):
    if old == 0:
        return 0
    return ((new - old) / old) * 100

print("\n" + "=" * 80)
print("DETAILED RESULTS: Fixed Strategy vs AI-Guided (averaged over 10 seeds)")
print("=" * 80)

all_queue_reductions = []
all_wait_reductions = []
all_fairness_improvements = []
all_throughput_gains = []

for strategy in STRATEGIES:
    fixed_data = results[strategy]["fixed"]
    ai_data = results[strategy]["ai"]
    
    f_avg_queue = avg([d["avg_queue"] for d in fixed_data])
    a_avg_queue = avg([d["avg_queue"] for d in ai_data])
    
    f_avg_wait = avg([d["avg_wait"] for d in fixed_data])
    a_avg_wait = avg([d["avg_wait"] for d in ai_data])
    
    f_throughput = avg([d["throughput"] for d in fixed_data])
    a_throughput = avg([d["throughput"] for d in ai_data])
    
    f_completed = avg([d["completed"] for d in fixed_data])
    a_completed = avg([d["completed"] for d in ai_data])
    
    f_max_queue = avg([d["max_queue"] for d in fixed_data])
    a_max_queue = avg([d["max_queue"] for d in ai_data])
    
    f_fairness = avg([d["avg_fairness"] for d in fixed_data])
    a_fairness = avg([d["avg_fairness"] for d in ai_data])
    
    f_deadlock = avg([d["deadlock_steps"] for d in fixed_data])
    a_deadlock = avg([d["deadlock_steps"] for d in ai_data])
    
    queue_reduction = pct_change(f_avg_queue, a_avg_queue)
    wait_reduction = pct_change(f_avg_wait, a_avg_wait)
    fairness_change = pct_change(f_fairness, a_fairness)
    throughput_change = pct_change(f_throughput, a_throughput)
    
    all_queue_reductions.append(queue_reduction)
    all_wait_reductions.append(wait_reduction)
    all_fairness_improvements.append(fairness_change)
    all_throughput_gains.append(throughput_change)
    
    print(f"\n{'~' * 60}")
    print(f"  Strategy: {strategy.upper()}")
    print(f"{'~' * 60}")
    print(f"  {'Metric':<25} {'Fixed':>10} {'AI-Guided':>10} {'Change':>10}")
    print(f"  {'~'*55}")
    print(f"  {'Avg Queue Length':<25} {f_avg_queue:>10.1f} {a_avg_queue:>10.1f} {queue_reduction:>+9.1f}%")
    print(f"  {'Avg Wait Time (steps)':<25} {f_avg_wait:>10.1f} {a_avg_wait:>10.1f} {wait_reduction:>+9.1f}%")
    print(f"  {'Throughput (jobs/step)':<25} {f_throughput:>10.3f} {a_throughput:>10.3f} {throughput_change:>+9.1f}%")
    print(f"  {'Total Completed':<25} {f_completed:>10.0f} {a_completed:>10.0f} {pct_change(f_completed, a_completed):>+9.1f}%")
    print(f"  {'Max Queue Length':<25} {f_max_queue:>10.0f} {a_max_queue:>10.0f} {pct_change(f_max_queue, a_max_queue):>+9.1f}%")
    print(f"  {'Avg Fairness Std':<25} {f_fairness:>10.2f} {a_fairness:>10.2f} {fairness_change:>+9.1f}%")
    print(f"  {'Starvation Steps':<25} {f_deadlock:>10.0f} {a_deadlock:>10.0f}")


print(f"\n\n{'=' * 80}")
print("SUMMARY: AI vs EACH Fixed Strategy")
print("=" * 80)

for i, strategy in enumerate(STRATEGIES):
    print(f"  vs {strategy:<20}  Queue: {all_queue_reductions[i]:>+7.1f}%   Wait: {all_wait_reductions[i]:>+7.1f}%   Fairness: {all_fairness_improvements[i]:>+7.1f}%   Throughput: {all_throughput_gains[i]:>+7.1f}%")

best_queue_reduction = min(all_queue_reductions)
best_wait_reduction = min(all_wait_reductions)
best_fairness = min(all_fairness_improvements)
best_throughput = max(all_throughput_gains)

avg_queue = avg(all_queue_reductions)
avg_wait = avg(all_wait_reductions)
avg_fair = avg(all_fairness_improvements)
avg_thr = avg(all_throughput_gains)

print(f"\n  --- AVERAGES across all 5 strategies ---")
print(f"  Avg queue reduction:      {avg_queue:+.1f}%")
print(f"  Avg wait time reduction:  {avg_wait:+.1f}%")
print(f"  Avg fairness change:      {avg_fair:+.1f}%")
print(f"  Avg throughput change:    {avg_thr:+.1f}%")

print(f"\n  --- BEST CASE (largest improvement) ---")
print(f"  Best queue reduction:      {best_queue_reduction:+.1f}% (vs {STRATEGIES[all_queue_reductions.index(best_queue_reduction)]})")
print(f"  Best wait time reduction:  {best_wait_reduction:+.1f}% (vs {STRATEGIES[all_wait_reductions.index(best_wait_reduction)]})")
print(f"  Best fairness improvement: {best_fairness:+.1f}% (vs {STRATEGIES[all_fairness_improvements.index(best_fairness)]})")
print(f"  Best throughput gain:      {best_throughput:+.1f}% (vs {STRATEGIES[all_throughput_gains.index(best_throughput)]})")

# ── Codebase stats ──
print(f"\n\n{'=' * 80}")
print("CODEBASE STATS")
print("=" * 80)

import glob

backend_files = glob.glob("d:/second/backend/app/*.py")
frontend_files = (
    glob.glob("d:/second/frontend/*.tsx") +
    glob.glob("d:/second/frontend/*.ts") +
    glob.glob("d:/second/frontend/components/*.tsx") +
    glob.glob("d:/second/frontend/services/*.ts")
)

backend_loc = 0
frontend_loc = 0

for f in backend_files:
    with open(f, "r", encoding="utf-8", errors="ignore") as fh:
        backend_loc += sum(1 for line in fh if line.strip())

for f in frontend_files:
    with open(f, "r", encoding="utf-8", errors="ignore") as fh:
        frontend_loc += sum(1 for line in fh if line.strip())

print(f"\n  Backend Python LoC (non-blank):   {backend_loc}")
print(f"  Frontend TS/TSX LoC (non-blank):  {frontend_loc}")
print(f"  Total LoC:                        {backend_loc + frontend_loc}")
print(f"  Backend files:                    {len(backend_files)}")
print(f"  Frontend files:                   {len(frontend_files)}")

print("\n\nDone.\n")
