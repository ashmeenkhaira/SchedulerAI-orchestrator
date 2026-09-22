# Ablation: `inputs`

Generated 2026-09-22 18:45:25 UTC by `backend/eval_ablation.py`.

Model `gpt-oss:120b-cloud` via `ollama`, 3 repeats per state, 8 fixed states.

Each column removes one metric from the state entirely. `full` keeps all of them. The probe found the model acting on `queue_rate` while ignoring `queue_len`; if dropping `queue_rate` makes it start reacting to `queue_len`, that ordering was deliberate rather than inattention.

## Modal choice per state

| State | `full` | `drop_queue_len` | `drop_queue_rate` | `drop_num_failed` | `drop_fairness_std` | `drop_avg_wait` |
|---|---|---|---|---|---|---|
| `idle` | `baseline` | `baseline` | `baseline` | `baseline` | `baseline` | `baseline` |
| `light_stable` | `baseline` <sub>67%</sub> | `baseline` <sub>67%</sub> | `baseline` | `baseline` | `baseline` | `baseline` <sub>67%</sub> |
| `deep_stable` | `baseline` | `baseline` <sub>33%</sub> | `random_backoff` | `baseline` | `baseline` | `baseline` |
| `growing` | `random_backoff` <sub>67%</sub> | `random_backoff` <sub>67%</sub> | `baseline` <sub>67%</sub> | `random_backoff` <sub>67%</sub> | `leader_election` <sub>67%</sub> | `random_backoff` <sub>67%</sub> |
| `draining` | `baseline` | `baseline` <sub>67%</sub> | `baseline` | `baseline` <sub>67%</sub> | `baseline` | `baseline` |
| `failures` | `consistent_hash` | `consistent_hash` | `consistent_hash` | `random_backoff` <sub>67%</sub> | `consistent_hash` | `consistent_hash` |
| `unfair_calm` | `token_ring` <sub>67%</sub> | `token_ring` <sub>67%</sub> | `token_ring` | `random_backoff` <sub>67%</sub> | `baseline` <sub>67%</sub> | `token_ring` <sub>33%</sub> |
| `unfair_growing` | `random_backoff` | `random_backoff` <sub>67%</sub> | `random_backoff` | `random_backoff` <sub>67%</sub> | `random_backoff` <sub>67%</sub> | `random_backoff` |

Superscript is self-consistency where it was below 100%.

## Divergence from `full`

| Condition | agreement | states whose answer changed |
|---|---|---|
| `drop_queue_len` | 100% | none |
| `drop_queue_rate` | 75% | `deep_stable`, `growing` |
| `drop_num_failed` | 75% | `failures`, `unfair_calm` |
| `drop_fairness_std` | 75% | `growing`, `unfair_calm` |
| `drop_avg_wait` | 100% | none |

## Mean self-consistency per condition

| Condition | mean consistency | fully consistent states |
|---|---|---|
| `full` | 87.5% | 5/8 |
| `drop_queue_len` | 70.8% | 2/8 |
| `drop_queue_rate` | 95.8% | 7/8 |
| `drop_num_failed` | 79.2% | 3/8 |
| `drop_fairness_std` | 87.5% | 5/8 |
| `drop_avg_wait` | 83.3% | 5/8 |

## Rule table, for reference

| State | rule table picks |
|---|---|
| `idle` | `baseline` |
| `light_stable` | `baseline` |
| `deep_stable` | `random_backoff` |
| `growing` | `baseline` |
| `draining` | `baseline` |
| `failures` | `consistent_hash` |
| `unfair_calm` | `token_ring` |
| `unfair_growing` | `baseline` |
