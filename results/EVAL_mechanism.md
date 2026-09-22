# Why strategy choice cannot move throughput

Generated 2026-09-22 17:07:32 UTC by `backend/eval_mechanism.py`.

5 seeds x 600 steps, 8 servers, `arrival_prob=0.6`.

Cluster capacity is `num_servers / mean_service` jobs per step and owes nothing to the scheduling strategy. A strategy is **work-conserving** if it never leaves a server idle beside a queued job; the engine counts the assignments each strategy could have made against the ones it made. Work-conserving strategies dispatch on the same steps and therefore cannot differ in throughput — they vary only in *which* server receives each job.

## mean_service = 6.0 (capacity 1.3333 jobs/step, peak load 0.95, utilisation 0.71)

| Strategy | work conservation | throughput | avg queue | fairness std |
|---|---|---|---|---|
| `baseline` ✓ | 1.0000 | 0.6640 | 0.30 | 24.94 |
| `random_backoff` | 0.8064 | 0.6630 | 0.46 | 7.24 |
| `consistent_hash` ✓ | 1.0000 | 0.6640 | 0.27 | 5.69 |
| `token_ring` | 0.1217 | 0.5013 | 43.78 | 3.24 |
| `leader_election` ✓ | 1.0000 | 0.6640 | 0.27 | 15.99 |

Work-conserving ( ✓ ): `baseline`, `consistent_hash`, `leader_election`. Throughput spread among them: **0.0**. Fairness spread across all five: **21.7064** (7.708x between best and worst).

## mean_service = 8.0 (capacity 1.0 jobs/step, peak load 0.95, utilisation 0.95)

| Strategy | work conservation | throughput | avg queue | fairness std |
|---|---|---|---|---|
| `baseline` ✓ | 1.0000 | 0.6553 | 1.99 | 13.08 |
| `random_backoff` | 0.8276 | 0.6533 | 2.54 | 7.57 |
| `consistent_hash` ✓ | 1.0000 | 0.6567 | 1.96 | 5.46 |
| `token_ring` | 0.1253 | 0.4430 | 57.30 | 3.58 |
| `leader_election` ✓ | 1.0000 | 0.6547 | 2.02 | 7.34 |

Work-conserving ( ✓ ): `baseline`, `consistent_hash`, `leader_election`. Throughput spread among them: **0.002**. Fairness spread across all five: **9.4962** (3.649x between best and worst).

## mean_service = 12.0 (capacity 0.6667 jobs/step, peak load 0.95, utilisation 1.43)

| Strategy | work conservation | throughput | avg queue | fairness std |
|---|---|---|---|---|
| `baseline` ✓ | 1.0000 | 0.5677 | 21.57 | 6.83 |
| `random_backoff` | 0.9528 | 0.5593 | 24.14 | 6.94 |
| `consistent_hash` ✓ | 1.0000 | 0.5667 | 22.16 | 6.71 |
| `token_ring` | 0.1315 | 0.3593 | 78.95 | 3.53 |
| `leader_election` ✓ | 1.0000 | 0.5663 | 22.48 | 5.31 |

Work-conserving ( ✓ ): `baseline`, `consistent_hash`, `leader_election`. Throughput spread among them: **0.0014**. Fairness spread across all five: **3.4123** (1.967x between best and worst).

## mean_service = 16.0 (capacity 0.5 jobs/step, peak load 0.95, utilisation 1.90)

| Strategy | work conservation | throughput | avg queue | fairness std |
|---|---|---|---|---|
| `baseline` ✓ | 1.0000 | 0.4303 | 58.79 | 5.75 |
| `random_backoff` | 0.9689 | 0.4273 | 58.71 | 5.21 |
| `consistent_hash` ✓ | 1.0000 | 0.4313 | 58.94 | 4.73 |
| `token_ring` | 0.1296 | 0.2940 | 95.66 | 3.36 |
| `leader_election` ✓ | 1.0000 | 0.4227 | 59.27 | 5.25 |

Work-conserving ( ✓ ): `baseline`, `consistent_hash`, `leader_election`. Throughput spread among them: **0.0086**. Fairness spread across all five: **2.3921** (1.712x between best and worst).

## Control: the same comparison with failures switched off

At `mean_service=12.0`, with `FAILURE_PROB = 0`:

| Strategy | work conservation | throughput | fairness std |
|---|---|---|---|
| `baseline` ✓ | 1.0000 | 0.606000 | 8.28 |
| `random_backoff` | 0.9100 | 0.603667 | 6.18 |
| `consistent_hash` ✓ | 1.0000 | 0.606000 | 6.66 |
| `token_ring` | 0.1320 | 0.413667 | 3.27 |
| `leader_election` ✓ | 1.0000 | 0.606000 | 5.99 |

Throughput spread among the work-conserving strategies: **0.0** — identical to the last bit, while fairness still varies severalfold.

This locates the small residual spread seen above. A failure preempts the job a server is holding and discards the work done on it, and *which* job is in flight depends on which server received it — the one thing work-conserving strategies disagree about. The leftover throughput difference is therefore a downstream consequence of the fairness difference, not a second axis a switching policy could aim at.

## What this means for the agent

- **Throughput is closed.** Every work-conserving strategy returns the same throughput at every load measured. An agent cannot improve it by switching between them, and the only way to produce a large throughput 'gain' is to pick a non-work-conserving opponent — `token_ring`, which declines roughly 86% of its dispatch opportunities by design — and beat that. This is exactly how the project's original +41% throughput figure arose.
- **Queue length is closed for the same reason.** Backlog is set by offered load against capacity. Below capacity it stays short under any conserving strategy; above capacity it grows under all of them.
- **Fairness is open.** Which server receives each job is genuinely the strategy's choice, and the spread across strategies is severalfold at every load. That is the axis where a switching decision has something to decide, so it is the axis `eval_oracle.py` scores policies on.

The honest form of the original claim is not 'the agent made scheduling faster'. It is: throughput was never available to win, and the number that said otherwise was measuring the opponent, not the agent.
