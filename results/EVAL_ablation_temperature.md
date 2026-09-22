# Ablation: `temperature`

Generated 2026-09-22 18:51:22 UTC by `backend/eval_ablation.py`.

Model `gpt-oss:120b-cloud` via `ollama`, 5 repeats per state, 8 fixed states.

Each column is a different sampling temperature over identical states. A control loop that takes different actions in identical states has a problem; this asks whether it is fixable at the call site.

## Modal choice per state

| State | `temp_0.0` | `temp_0.7` | `temp_1.0` |
|---|---|---|---|
| `idle` | `baseline` | `baseline` | `baseline` |
| `light_stable` | `baseline` | `baseline` | `baseline` |
| `deep_stable` | `random_backoff` <sub>60%</sub> | `baseline` | `baseline` <sub>60%</sub> |
| `growing` | `leader_election` <sub>60%</sub> | `random_backoff` | `random_backoff` <sub>60%</sub> |
| `draining` | `baseline` | `baseline` | `baseline` <sub>80%</sub> |
| `failures` | `consistent_hash` | `consistent_hash` | `consistent_hash` |
| `unfair_calm` | `token_ring` | `token_ring` <sub>60%</sub> | `token_ring` <sub>60%</sub> |
| `unfair_growing` | `random_backoff` | `leader_election` <sub>60%</sub> | `random_backoff` |

Superscript is self-consistency where it was below 100%.

## Divergence from `temp_0.7`

| Condition | agreement | states whose answer changed |
|---|---|---|
| `temp_0.0` | 62% | `deep_stable`, `growing`, `unfair_growing` |
| `temp_1.0` | 88% | `unfair_growing` |

## Mean self-consistency per condition

| Condition | mean consistency | fully consistent states |
|---|---|---|
| `temp_0.0` | 90.0% | 6/8 |
| `temp_0.7` | 90.0% | 6/8 |
| `temp_1.0` | 82.5% | 4/8 |

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
