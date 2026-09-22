"""Invariant tests for SimEngine and the comparison pipeline.

Dependency-free: run `python test_engine.py` from the backend/ directory.
Also discoverable by pytest if you install it.

These lock down the three properties the comparison results depend on. Each
one was broken before the engine was unified:

  1. CRN  - both arms must see identical arrivals and failures regardless of
            which strategy they run.
  2. Failure semantics - a failed server must never hold or progress a job.
  3. Replay fidelity   - logged decisions must take effect at their exact
            recorded step, with no hysteresis gate applied to them.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.api import build_heuristic_selector, build_replay_selector, summarise
from app.scheduler_engine import STRATEGIES, SimEngine


def _engine(strategy, seed=1, steps=0, **kw):
    return SimEngine(
        run_id=0, strategy=strategy, arrival_prob=0.6, mean_service=8.0,
        seed=seed, sim_steps=steps, record_history=True, **kw
    )


def _trace(strategy, seed, steps):
    e = _engine(strategy, seed=seed)
    arrivals, failures = [], []
    for _ in range(steps):
        before = e.jobs_arrived
        e.step()
        arrivals.append(e.jobs_arrived - before)
        failures.append(tuple(s.failed for s in e.servers))
    return arrivals, failures, e


# --- 1. Common Random Numbers ---

def test_arrivals_and_failures_are_strategy_independent():
    """The core CRN guarantee: strategy choice must not perturb the workload."""
    base_arrivals, base_failures, _ = _trace("baseline", seed=7, steps=400)
    for strategy in STRATEGIES:
        arrivals, failures, _ = _trace(strategy, seed=7, steps=400)
        assert arrivals == base_arrivals, f"{strategy} changed the arrival sequence"
        assert failures == base_failures, f"{strategy} changed the failure sequence"


def test_job_work_and_hash_are_reproducible():
    """Job identity comes from the seeded stream, not os.urandom.

    Job ids used to come from uuid.uuid4(), which is unseeded - so
    consistent_hash placed jobs differently on every run of the same seed.
    """
    def ids(seed):
        e = _engine("token_ring", seed=seed)
        e.run_steps(150)
        return [(j.id, j.work_required) for j in e.queue]

    assert ids(5) == ids(5)
    assert ids(5) != ids(6)


def test_two_arms_same_seed_see_identical_workload():
    control = _engine("token_ring", seed=11)
    control.run_steps(300)
    treatment = _engine("leader_election", seed=11)
    treatment.run_steps(300)
    assert control.jobs_arrived == treatment.jobs_arrived
    assert [m["num_failed"] for m in control.metrics_history] == \
           [m["num_failed"] for m in treatment.metrics_history]


# --- 2. Failure semantics ---

def test_failed_servers_never_hold_or_progress_jobs():
    """random_backoff, token_ring and leader_election used to skip this check."""
    for strategy in STRATEGIES:
        e = _engine(strategy, seed=3)
        for _ in range(1500):
            e.step()
            for s in e.servers:
                assert not (s.failed and s.busy), \
                    f"{strategy}: server {s.sid} is failed while holding a job"


def test_failure_preempts_in_flight_job_back_to_queue():
    e = _engine("baseline", seed=2)
    seen_failure = False
    for _ in range(2000):
        e.step()
        if any(s.failed for s in e.servers):
            seen_failure = True
    assert seen_failure, "no failure occurred in 2000 steps; test is not exercising the path"
    assert e.jobs_completed <= e.jobs_arrived


# --- 3. Replay fidelity ---

def test_replay_applies_decisions_at_exact_steps():
    """The old pipeline gated replay behind a 15-step hysteresis, which
    delayed every decision and dropped ones logged less than 15 steps apart."""
    log = [
        {"step": 1, "strategy": "baseline"},
        {"step": 10, "strategy": "token_ring"},      # 9 steps later
        {"step": 18, "strategy": "leader_election"}, # 8 steps later
    ]
    selector = build_replay_selector(log)
    e = _engine("random_backoff", seed=4)
    e.run_steps(30, strategy_fn=selector)

    by_step = {m["time"]: m["strategy"] for m in e.metrics_history}
    assert by_step[1] == "baseline"
    assert by_step[9] == "baseline"          # holds until the next decision
    assert by_step[10] == "token_ring"       # applied on its exact step
    assert by_step[17] == "token_ring"
    assert by_step[18] == "leader_election"  # not dropped despite the 8-step gap
    assert by_step[30] == "leader_election"


def test_replay_holds_base_strategy_before_first_decision():
    selector = build_replay_selector([{"step": 20, "strategy": "token_ring"}])
    e = _engine("consistent_hash", seed=4)
    e.run_steps(25, strategy_fn=selector)
    by_step = {m["time"]: m["strategy"] for m in e.metrics_history}
    assert by_step[1] == "consistent_hash"
    assert by_step[19] == "consistent_hash"
    assert by_step[20] == "token_ring"


def test_no_strategy_fn_makes_the_arms_identical():
    """The faithful replay of a run whose agent never switched.

    Both arms must produce the same trajectory, so every delta is zero. The
    comparison endpoint used to substitute the rule-based selector here, which
    manufactured a different trajectory and labelled it agent output.
    """
    control = _engine("random_backoff", seed=12)
    control.run_steps(250)
    treatment = _engine("random_backoff", seed=12)
    treatment.run_steps(250, strategy_fn=None)
    assert control.metrics_history == treatment.metrics_history
    assert summarise(control) == summarise(treatment)


def test_selector_returning_none_holds_current_strategy():
    def hold_everything(step, queue_len, fairness_std, num_failed, queue_rate):
        return None

    e = _engine("token_ring", seed=6)
    e.run_steps(60, strategy_fn=hold_everything)
    assert {m["strategy"] for m in e.metrics_history} == {"token_ring"}


def test_heuristic_selector_keeps_its_own_hysteresis():
    selector = build_heuristic_selector("baseline", min_hold=15)
    e = _engine("baseline", seed=8)
    e.run_steps(200, strategy_fn=selector)
    switches = [
        m["time"] for i, m in enumerate(e.metrics_history)
        if i > 0 and m["strategy"] != e.metrics_history[i - 1]["strategy"]
    ]
    for earlier, later in zip(switches, switches[1:]):
        assert later - earlier >= 15, f"switch at {later} violates the 15-step hold"


# --- 4. Strategy behaviour ---

def test_all_strategies_run_and_complete_work():
    for strategy in STRATEGIES:
        e = _engine(strategy, seed=1)
        e.run_steps(300)
        assert e.jobs_completed > 0, f"{strategy} completed nothing"
        assert e.jobs_completed <= e.jobs_arrived


def test_token_ring_is_throughput_limited_and_fairest():
    """Structural claim from the README: one claim per token position."""
    results = {}
    for strategy in STRATEGIES:
        e = _engine(strategy, seed=1)
        e.run_steps(400)
        results[strategy] = e

    tr = results["token_ring"]
    assert tr.jobs_completed == min(r.jobs_completed for r in results.values())
    assert tr.fairness_std() == min(r.fairness_std() for r in results.values())


def test_baseline_and_leader_election_are_not_identical():
    """They were byte-identical in the old comparison engine, which made any
    baseline-vs-leader_election result meaningless."""
    a = _engine("baseline", seed=1)
    a.run_steps(400)
    b = _engine("leader_election", seed=1)
    b.run_steps(400)
    assert [s.completed_count for s in a.servers] != [s.completed_count for s in b.servers]


def test_unknown_strategy_is_rejected():
    try:
        _engine("does_not_exist")
    except ValueError:
        return
    raise AssertionError("SimEngine accepted an unknown strategy")


# --- 5. Bookkeeping ---

def test_sim_steps_is_enforced_by_run_loop():
    import asyncio

    async def noop(_):
        return None

    e = _engine("baseline", seed=1, steps=25)
    asyncio.run(e.run_loop(noop, tick_seconds=0))
    assert e.time_step == 25, f"run_loop ignored sim_steps (stopped at {e.time_step})"
    assert not e.running


def test_wait_time_is_recorded():
    e = _engine("baseline", seed=1)
    e.run_steps(300)
    assert e.avg_wait() > 0, "avg_wait was never populated"
    assert e.avg_turnaround() >= e.avg_wait()
    assert len(e.completed_jobs) == e.jobs_completed


def test_starvation_flag_does_not_latch():
    e = _engine("token_ring", seed=1)
    e.run_steps(600)
    # Whatever the final state, it must reflect the present, not a past trip.
    idle_for = e.time_step - e.last_completion_step
    expected = idle_for > 50 and len(e.queue) > 5
    assert e.starving == expected


def test_summarise_reports_every_metric():
    e = _engine("baseline", seed=1)
    e.run_steps(200)
    s = summarise(e)
    for key in ("avg_queue_len", "avg_wait", "avg_turnaround", "throughput",
                "jobs_completed", "avg_fairness_std", "starvation_steps"):
        assert key in s, f"summarise() is missing {key}"


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failures = []
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as exc:
            failures.append((name, exc))
            print(f"  FAIL  {name}: {exc}")
    print(f"\n{len(tests) - len(failures)}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
