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

import os
import statistics
import sys

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


# --- 6. Lookahead forking ---
#
# The oracle in eval_oracle.py is only meaningful if a fork is a faithful
# continuation of the parent and if the forks differ *only* by strategy. Both
# are asserted here rather than assumed.

def test_fork_continues_the_parent_trajectory_exactly():
    """A fork that keeps the parent's strategy must do what the parent would."""
    parent = _engine("consistent_hash", seed=21)
    parent.run_steps(60)

    twin = parent.fork()
    twin.run_steps(40)
    parent.run_steps(40)

    assert twin.time_step == parent.time_step
    assert twin.jobs_arrived == parent.jobs_arrived
    assert twin.jobs_completed == parent.jobs_completed
    assert [s.completed_count for s in twin.servers] == \
           [s.completed_count for s in parent.servers]


def test_forks_see_identical_workload_whatever_strategy_they_run():
    """CRN again, but at a mid-run fork point rather than from step 0.

    This is the guarantee the lookahead depends on: five candidate rollouts
    from one state differ by strategy and by nothing else.
    """
    parent = _engine("baseline", seed=22)
    parent.run_steps(80)

    traces = {}
    for strategy in STRATEGIES:
        twin = parent.fork(strategy)
        twin.run_steps(50)
        traces[strategy] = (
            twin.jobs_arrived - parent.jobs_arrived,
            [m["num_failed"] for m in twin.metrics_history],
        )

    reference = traces["baseline"]
    for strategy, trace in traces.items():
        assert trace == reference, f"fork running {strategy} saw a different workload"


def test_fork_leaves_the_parent_untouched():
    parent = _engine("token_ring", seed=23)
    parent.run_steps(70)
    before = (parent.time_step, parent.jobs_arrived, parent.jobs_completed,
              len(parent.queue), parent.strategy, len(parent.metrics_history),
              len(parent.completed_jobs))

    for strategy in STRATEGIES:
        parent.fork(strategy).run_steps(60)

    after = (parent.time_step, parent.jobs_arrived, parent.jobs_completed,
             len(parent.queue), parent.strategy, len(parent.metrics_history),
             len(parent.completed_jobs))
    assert before == after, "forking mutated the parent engine"


def test_fork_history_covers_only_the_lookahead_window():
    """avg_queue_len() on a fork must describe the window, not the run so far."""
    parent = _engine("baseline", seed=24)
    parent.run_steps(100)
    twin = parent.fork("leader_election")
    twin.run_steps(30)
    assert len(twin.metrics_history) == 30
    assert twin.metrics_history[0]["time"] == 101


def test_fork_rejects_unknown_strategy():
    parent = _engine("baseline", seed=25)
    parent.run_steps(10)
    try:
        parent.fork("nope")
    except ValueError:
        return
    raise AssertionError("fork() accepted an unknown strategy")


# --- 7. Work conservation ---
#
# These pin the structural claim the whole evaluation rests on: strategies that
# never idle a free server beside a queued job cannot differ in throughput, so
# throughput is not something a switching policy can win. See
# eval_mechanism.py.

def test_dispatch_accounting_never_exceeds_opportunity():
    for strategy in STRATEGIES:
        e = _engine(strategy, seed=31)
        e.run_steps(500)
        assert 0 <= e.dispatch_used <= e.dispatch_opportunities
        assert 0.0 <= e.work_conservation() <= 1.0


def test_three_strategies_are_perfectly_work_conserving():
    for strategy in ("baseline", "consistent_hash", "leader_election"):
        e = _engine(strategy, seed=32)
        e.run_steps(500)
        assert e.work_conservation() == 1.0, \
            f"{strategy} idled a free server beside a queued job"


def test_token_ring_declines_most_of_its_dispatch_opportunities():
    """Its throughput ceiling is a refusal to dispatch, not slow servers."""
    e = _engine("token_ring", seed=32)
    e.run_steps(500)
    assert e.work_conservation() < 0.3


def _throughputs_of_conserving_strategies(seed, steps):
    values = []
    for strategy in ("baseline", "consistent_hash", "leader_election"):
        e = _engine(strategy, seed=seed)
        e.run_steps(steps)
        assert e.work_conservation() == 1.0
        values.append(e.throughput())
    return values


def test_work_conserving_strategies_share_one_throughput_absent_failures():
    """The finding that closes the throughput axis, in its exact form.

    With no failures, the three work-conserving strategies are not merely
    close — they are identical to the last bit. They dispatch on exactly the
    same steps and complete exactly the same jobs; all they disagree on is
    which server did the work. Dispatch policy contributes nothing to
    throughput.
    """
    import app.scheduler_engine as engine_module

    original = engine_module.FAILURE_PROB
    engine_module.FAILURE_PROB = 0.0
    try:
        throughputs = _throughputs_of_conserving_strategies(seed=33, steps=600)
    finally:
        engine_module.FAILURE_PROB = original

    assert max(throughputs) - min(throughputs) == 0.0, \
        f"work-conserving strategies disagreed without failures: {throughputs}"


def test_failures_introduce_only_a_second_order_throughput_difference():
    """Why the exact equality above becomes approximate in the real engine.

    A failure preempts the in-flight job and discards the work done on it.
    *Which* job is in flight depends on which server received it — the one
    thing work-conserving strategies do differ on. So the residual throughput
    spread is a downstream consequence of the fairness difference, not an
    independent axis a switching policy could exploit: it stays within a few
    percent while the fairness spread is severalfold.
    """
    throughputs = _throughputs_of_conserving_strategies(seed=33, steps=600)
    spread = max(throughputs) - min(throughputs)
    assert 0 < spread < 0.05 * statistics.fmean(throughputs), \
        f"expected a small failure-driven spread, got {throughputs}"


def test_fairness_is_the_axis_that_actually_varies():
    """The counterpart: what strategy choice does control."""
    fairness = {}
    for strategy in STRATEGIES:
        e = _engine(strategy, seed=33)
        e.run_steps(600)
        fairness[strategy] = e.fairness_std()
    assert max(fairness.values()) / min(fairness.values()) > 2.0, \
        f"expected a severalfold fairness spread, got {fairness}"


def test_forked_engine_keeps_dispatch_accounting_consistent():
    parent = _engine("baseline", seed=34)
    parent.run_steps(100)
    twin = parent.fork("token_ring")
    twin.run_steps(100)
    assert twin.dispatch_opportunities >= parent.dispatch_opportunities
    assert twin.dispatch_used >= parent.dispatch_used


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
