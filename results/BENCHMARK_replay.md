# Benchmark Results

Generated 2026-09-22 12:01:26 UTC by `backend/benchmark.py`.

**Mode:** `replay` — treatment arm is **real logged Gemini decisions**.

Replaying the decision log of run #43 (14 decisions) against each static strategy.

> Single seed. A decision log is tied to the run that produced it, so this cannot be replicated across seeds. It shows what the agent's *actual* choices did under CRN-controlled load — not a statistically powered result.

Config: seed `1`, 202 steps, arrival_prob `0.6`, mean_service `8.0`.

**CRN verified:** yes — both arms saw identical arrivals and failures in every pair.

## vs static `baseline`

| Metric | Static | Agent-guided | Change | Seeds better |
|---|---|---|---|---|
| `avg_queue_len` <sub>(lower is better)</sub> | 4.842 | 6.312 | +30.4% | 0/1 |
| `avg_wait` <sub>(lower is better)</sub> | 7.866 | 10.293 | +30.9% | 0/1 |
| `avg_turnaround` <sub>(lower is better)</sub> | 14.271 | 16.496 | +15.6% | 0/1 |
| `throughput` <sub>(higher is better)</sub> | 0.5842 | 0.5594 | -4.2% | 0/1 |
| `jobs_completed` <sub>(higher is better)</sub> | 118.0 | 113.0 | -4.2% | 0/1 |
| `max_queue_len` <sub>(lower is better)</sub> | 17.0 | 20.0 | +17.6% | 0/1 |
| `avg_fairness_std` <sub>(lower is better)</sub> | 3.037 | 2.435 | -19.8% | 1/1 |
| `starvation_steps` <sub>(lower is better)</sub> | 0.0 | 0.0 | — | 0/1 |

Treatment arm ran a different strategy than `baseline` for 182 steps; strategies used: `baseline`, `consistent_hash`, `leader_election`, `random_backoff`, `token_ring`.

## vs static `random_backoff`

| Metric | Static | Agent-guided | Change | Seeds better |
|---|---|---|---|---|
| `avg_queue_len` <sub>(lower is better)</sub> | 5.47 | 6.312 | +15.4% | 0/1 |
| `avg_wait` <sub>(lower is better)</sub> | 8.897 | 10.293 | +15.7% | 0/1 |
| `avg_turnaround` <sub>(lower is better)</sub> | 15.175 | 16.496 | +8.7% | 0/1 |
| `throughput` <sub>(higher is better)</sub> | 0.5644 | 0.5594 | -0.9% | 0/1 |
| `jobs_completed` <sub>(higher is better)</sub> | 114.0 | 113.0 | -0.9% | 0/1 |
| `max_queue_len` <sub>(lower is better)</sub> | 19.0 | 20.0 | +5.3% | 0/1 |
| `avg_fairness_std` <sub>(lower is better)</sub> | 1.908 | 2.435 | +27.6% | 0/1 |
| `starvation_steps` <sub>(lower is better)</sub> | 0.0 | 0.0 | — | 0/1 |

Treatment arm ran a different strategy than `random_backoff` for 160 steps; strategies used: `baseline`, `consistent_hash`, `leader_election`, `random_backoff`, `token_ring`.

## vs static `consistent_hash`

| Metric | Static | Agent-guided | Change | Seeds better |
|---|---|---|---|---|
| `avg_queue_len` <sub>(lower is better)</sub> | 5.653 | 6.312 | +11.7% | 0/1 |
| `avg_wait` <sub>(lower is better)</sub> | 9.189 | 10.293 | +12.0% | 0/1 |
| `avg_turnaround` <sub>(lower is better)</sub> | 15.321 | 16.496 | +7.7% | 0/1 |
| `throughput` <sub>(higher is better)</sub> | 0.5545 | 0.5594 | +0.9% | 1/1 |
| `jobs_completed` <sub>(higher is better)</sub> | 112.0 | 113.0 | +0.9% | 1/1 |
| `max_queue_len` <sub>(lower is better)</sub> | 21.0 | 20.0 | -4.8% | 1/1 |
| `avg_fairness_std` <sub>(lower is better)</sub> | 2.284 | 2.435 | +6.6% | 0/1 |
| `starvation_steps` <sub>(lower is better)</sub> | 0.0 | 0.0 | — | 0/1 |

Treatment arm ran a different strategy than `consistent_hash` for 152 steps; strategies used: `baseline`, `consistent_hash`, `leader_election`, `random_backoff`, `token_ring`.

## vs static `token_ring`

| Metric | Static | Agent-guided | Change | Seeds better |
|---|---|---|---|---|
| `avg_queue_len` <sub>(lower is better)</sub> | 18.604 | 6.312 | -66.1% | 1/1 |
| `avg_wait` <sub>(lower is better)</sub> | 25.038 | 10.293 | -58.9% | 1/1 |
| `avg_turnaround` <sub>(lower is better)</sub> | 29.055 | 16.496 | -43.2% | 1/1 |
| `throughput` <sub>(higher is better)</sub> | 0.3614 | 0.5594 | +54.8% | 1/1 |
| `jobs_completed` <sub>(higher is better)</sub> | 73.0 | 113.0 | +54.8% | 1/1 |
| `max_queue_len` <sub>(lower is better)</sub> | 53.0 | 20.0 | -62.3% | 1/1 |
| `avg_fairness_std` <sub>(lower is better)</sub> | 1.135 | 2.435 | +114.5% | 0/1 |
| `starvation_steps` <sub>(lower is better)</sub> | 0.0 | 0.0 | — | 0/1 |

Treatment arm ran a different strategy than `token_ring` for 162 steps; strategies used: `baseline`, `consistent_hash`, `leader_election`, `random_backoff`, `token_ring`.

## vs static `leader_election`

| Metric | Static | Agent-guided | Change | Seeds better |
|---|---|---|---|---|
| `avg_queue_len` <sub>(lower is better)</sub> | 5.292 | 6.312 | +19.3% | 0/1 |
| `avg_wait` <sub>(lower is better)</sub> | 8.816 | 10.293 | +16.8% | 0/1 |
| `avg_turnaround` <sub>(lower is better)</sub> | 14.887 | 16.496 | +10.8% | 0/1 |
| `throughput` <sub>(higher is better)</sub> | 0.5693 | 0.5594 | -1.7% | 0/1 |
| `jobs_completed` <sub>(higher is better)</sub> | 115.0 | 113.0 | -1.7% | 0/1 |
| `max_queue_len` <sub>(lower is better)</sub> | 20.0 | 20.0 | +0.0% | 0/1 |
| `avg_fairness_std` <sub>(lower is better)</sub> | 2.743 | 2.435 | -11.2% | 1/1 |
| `starvation_steps` <sub>(lower is better)</sub> | 0.0 | 0.0 | — | 0/1 |

Treatment arm ran a different strategy than `leader_election` for 152 steps; strategies used: `baseline`, `consistent_hash`, `leader_election`, `random_backoff`, `token_ring`.
