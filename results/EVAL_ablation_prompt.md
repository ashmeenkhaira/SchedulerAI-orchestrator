# Ablation: `prompt`

Generated 2026-09-22 18:38:46 UTC by `backend/eval_ablation.py`.

Model `gpt-oss:120b-cloud` via `ollama`, 3 repeats per state, 8 fixed states.

Each column is the same model on the same states with a different system prompt. `full` is what the live system ships. `no_ceiling` describes `token_ring` without handing over its throughput ceiling. `minimal` gives strategy names and the output contract only. If `minimal` matches `full`, the prompt engineering is not what is producing the decisions.

## Modal choice per state

| State | `full` | `no_ceiling` | `minimal` |
|---|---|---|---|
| `idle` | `baseline` | `baseline` | `baseline` |
| `light_stable` | `baseline` | `baseline` | `token_ring` <sub>67%</sub> |
| `deep_stable` | `baseline` <sub>67%</sub> | `token_ring` <sub>67%</sub> | `consistent_hash` <sub>67%</sub> |
| `growing` | `random_backoff` | `random_backoff` | `consistent_hash` |
| `draining` | `baseline` | `baseline` | `baseline` |
| `failures` | `consistent_hash` | `consistent_hash` | `consistent_hash` |
| `unfair_calm` | `random_backoff` <sub>67%</sub> | `token_ring` | `consistent_hash` <sub>67%</sub> |
| `unfair_growing` | `random_backoff` | `random_backoff` | `consistent_hash` <sub>67%</sub> |

Superscript is self-consistency where it was below 100%.

## Divergence from `full`

| Condition | agreement | states whose answer changed |
|---|---|---|
| `no_ceiling` | 75% | `deep_stable`, `unfair_calm` |
| `minimal` | 38% | `deep_stable`, `growing`, `light_stable`, `unfair_calm`, `unfair_growing` |

## Mean self-consistency per condition

| Condition | mean consistency | fully consistent states |
|---|---|---|
| `full` | 91.7% | 6/8 |
| `no_ceiling` | 95.8% | 7/8 |
| `minimal` | 83.3% | 4/8 |

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
