# The decision boundary the model implements

Generated 2026-09-22 18:00:22 UTC by `backend/eval_probe.py`.

Model `gpt-oss:120b-cloud` via `ollama`, temperature 0.7, 5 repeats per point.

Every input is held fixed but one. Where the answer changes as that one varies is the boundary the model is implementing. Asking the identical state several times measures how much of that answer is judgement and how much is sampling noise.

Base state (the pinned values):

```json
{
  "time": 150,
  "queue_len": 10,
  "queue_rate": 0.0,
  "num_failed": 0,
  "fairness_std": 2.0,
  "completed_total": 80,
  "avg_wait": 4.0,
  "strategy": "baseline"
}
```

## Headline

- **Schema-valid responses:** 155/155 (100.0%)
- **Self-consistency on identical input:** 85.2% mean; 17/31 states answered the same way every time
- **Agreement with the 12-line rule table:** 61.3%
- **Latency:** 8.371s median, 13.989s p95 per decision

## Does the model read each input?

| Input | distinct answers across its range | reads it? |
|---|---|---|
| `queue_len` | 1 | **no — answer never moved** |
| `queue_rate` | 2 | yes |
| `num_failed` | 2 | yes |
| `fairness_std` | 2 | yes |
| `strategy` | 5 | yes |

An input the answer never responds to is one the model is not using, whatever its stated reasoning says.

## Sweeping `queue_len`

| value | model picks | consistency | held current | rule table picks | agree |
|---|---|---|---|---|---|
| 0 | `baseline` | 100% | 5/5 | `baseline` | yes |
| 5 | `baseline` | 100% | 5/5 | `baseline` | yes |
| 10 | `baseline` | 100% | 5/5 | `baseline` | yes |
| 20 | `baseline` <sub>baselinex4, random_backoffx1</sub> | 80% | 4/5 | `baseline` | yes |
| 30 | `baseline` | 100% | 5/5 | `baseline` | yes |
| 45 | `baseline` <sub>baselinex4, consistent_hashx1</sub> | 80% | 4/5 | `random_backoff` | no |
| 60 | `baseline` | 100% | 5/5 | `random_backoff` | no |
| 80 | `baseline` <sub>baselinex4, random_backoffx1</sub> | 80% | 4/5 | `random_backoff` | no |

## Sweeping `queue_rate`

| value | model picks | consistency | held current | rule table picks | agree |
|---|---|---|---|---|---|
| -3.0 | `baseline` <sub>baselinex4, token_ringx1</sub> | 80% | 4/5 | `baseline` | yes |
| -1.0 | `baseline` <sub>baselinex3, token_ringx2</sub> | 60% | 3/5 | `baseline` | yes |
| 0.0 | `baseline` | 100% | 5/5 | `baseline` | yes |
| 1.0 | `random_backoff` <sub>leader_electionx1, random_backoffx4</sub> | 80% | 0/5 | `baseline` | no |
| 2.0 | `random_backoff` <sub>leader_electionx1, random_backoffx4</sub> | 80% | 0/5 | `baseline` | no |
| 4.0 | `random_backoff` <sub>leader_electionx2, random_backoffx3</sub> | 60% | 0/5 | `leader_election` | no |
| 6.0 | `random_backoff` <sub>leader_electionx2, random_backoffx3</sub> | 60% | 0/5 | `leader_election` | no |

## Sweeping `num_failed`

| value | model picks | consistency | held current | rule table picks | agree |
|---|---|---|---|---|---|
| 0 | `baseline` | 100% | 5/5 | `baseline` | yes |
| 1 | `baseline` | 100% | 5/5 | `baseline` | yes |
| 2 | `baseline` | 100% | 5/5 | `consistent_hash` | no |
| 3 | `consistent_hash` | 100% | 0/5 | `consistent_hash` | yes |
| 5 | `consistent_hash` | 100% | 0/5 | `consistent_hash` | yes |

## Sweeping `fairness_std`

| value | model picks | consistency | held current | rule table picks | agree |
|---|---|---|---|---|---|
| 0.0 | `baseline` | 100% | 5/5 | `baseline` | yes |
| 1.0 | `baseline` | 100% | 5/5 | `baseline` | yes |
| 3.0 | `baseline` | 100% | 5/5 | `baseline` | yes |
| 6.0 | `token_ring` <sub>baselinex1, random_backoffx1, token_ringx3</sub> | 60% | 1/5 | `token_ring` | yes |
| 9.0 | `token_ring` <sub>baselinex1, random_backoffx1, token_ringx3</sub> | 60% | 1/5 | `token_ring` | yes |
| 14.0 | `token_ring` <sub>baselinex1, random_backoffx2, token_ringx2</sub> | 40% | 1/5 | `token_ring` | yes |

## Sweeping `strategy`

| value | model picks | consistency | held current | rule table picks | agree |
|---|---|---|---|---|---|
| baseline | `baseline` | 100% | 5/5 | `baseline` | yes |
| random_backoff | `random_backoff` <sub>baselinex2, random_backoffx3</sub> | 60% | 3/5 | `baseline` | no |
| consistent_hash | `consistent_hash` | 100% | 5/5 | `baseline` | no |
| token_ring | `token_ring` | 100% | 5/5 | `baseline` | no |
| leader_election | `leader_election` <sub>leader_electionx3, random_backoffx2</sub> | 60% | 3/5 | `baseline` | no |

## How to read this

- **Consistency below 100%** is the cost of putting a sampled model in a control loop: the same system state can produce different actions. Any outcome difference smaller than this variance cannot be attributed to the model's judgement.
- **High rule agreement** means the model is reproducing a rule table that runs in microseconds for free. **Low agreement** is only interesting if the outcome numbers in `EVAL_oracle.md` show the disagreement paid off.
- **An input the answer never moves with** is an input the model is ignoring, regardless of what its `message` field claims to have considered.
