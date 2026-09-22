# Who captures the value of switching?

Generated 2026-09-22 18:20:40 UTC by `backend/eval_oracle.py`.

10 seeds x 300 steps, one decision every 20 steps, starting from `baseline`. Lookahead horizon 40 steps. Agreement is scored against the `fairness` objective.

Agent: `gpt-oss:120b-cloud` via `ollama`.

Every policy faces the same decisions at the same cadence under Common Random Numbers. `oracle:*` forks the live state once per candidate strategy and looks ahead with perfect foresight of arrivals and failures — it is not deployable and is not meant to be. It exists to size the prize.

## Outcome per policy

| Policy | avg queue | avg wait | throughput | fairness std | switches | agrees with lookahead |
|---|---|---|---|---|---|---|
| `agent` | 5.59 | 8.94 | 0.6180 | 3.67 | 6.1 | 15% |
| `oracle:balanced` | 2.50 | 4.08 | 0.6273 | 1.78 | 8.8 | 55% |
| `oracle:fairness` | 24.10 | 37.31 | 0.4944 | 1.37 | 5.5 | 100% |
| `oracle:queue` | 2.49 | 4.08 | 0.6283 | 4.33 | 2.6 | 5% |
| `random` | 7.87 | 12.46 | 0.6127 | 2.63 | 10.8 | 22% |
| `rule` | 4.60 | 7.50 | 0.6117 | 3.85 | 4.6 | 15% |
| `static:baseline` | 2.63 | 4.30 | 0.6283 | 4.09 | 0.0 | 12% |
| `static:consistent_hash` | 2.60 | 4.25 | 0.6280 | 2.61 | 0.0 | 21% |
| `static:leader_election` | 2.62 | 4.35 | 0.6273 | 3.17 | 0.0 | 13% |
| `static:random_backoff` | 3.08 | 5.13 | 0.6260 | 2.75 | 0.0 | 17% |
| `static:token_ring` | 31.81 | 46.31 | 0.4113 | 1.60 | 0.0 | 66% |
## Does any switching policy beat every fixed strategy at once?

Judged one metric at a time, the best fixed strategy for fairness is `static:token_ring` — which is also the worst for backlog by a wide margin. "Better fairness than token_ring" therefore flatters any policy that merely declines to use it. Judged on backlog **and** fairness together, the question becomes the one that actually matters: is there a switching policy that no single fixed strategy can match?

Axes (both lower is better): `avg_queue_len`, `avg_fairness_std`. Fixed strategies on the frontier: `static:consistent_hash`, `static:token_ring`.

| Policy | avg queue | fairness std | fixed strategies it beats on both | beaten by |
|---|---|---|---|---|
| `agent` | 5.59 | 3.67 | — | `static:consistent_hash`, `static:leader_election`, `static:random_backoff` |
| `oracle:balanced` **✓** | 2.50 | 1.78 | `static:baseline`, `static:consistent_hash`, `static:leader_election`, `static:random_backoff` | — |
| `oracle:fairness` **✓** | 24.10 | 1.37 | `static:token_ring` | — |
| `oracle:queue` | 2.49 | 4.33 | — | — |
| `random` | 7.87 | 2.63 | — | `static:consistent_hash` |
| `rule` | 4.60 | 3.85 | — | `static:consistent_hash`, `static:leader_election`, `static:random_backoff` |

**✓ = beats at least one fixed strategy on both axes while being beaten by none.** `oracle:balanced`, `oracle:fairness` qualify.


## Share of available headroom captured

### `avg_queue_len`

**No meaningful headroom** (4.2%). The best static policy (`static:consistent_hash`, 2.6) is within 0.1093 of the lookahead oracle (`oracle:queue`, 2.4907), which sees every future arrival and failure. With foresight itself worth this little, no switching policy — LLM or otherwise — had much to win here. A large percentage against a *badly chosen* static opponent is still available; it just would not mean anything.

### `avg_wait`

**No meaningful headroom** (4.0%). The best static policy (`static:consistent_hash`, 4.2479) is within 0.1701 of the lookahead oracle (`oracle:balanced`, 4.0778), which sees every future arrival and failure. With foresight itself worth this little, no switching policy — LLM or otherwise — had much to win here. A large percentage against a *badly chosen* static opponent is still available; it just would not mean anything.

### `throughput`

**No meaningful headroom** (0.0%). The best static policy (`static:baseline`, 0.6283) is within 0.0 of the lookahead oracle (`oracle:queue`, 0.6283), which sees every future arrival and failure. With foresight itself worth this little, no switching policy — LLM or otherwise — had much to win here. A large percentage against a *badly chosen* static opponent is still available; it just would not mean anything.

### `avg_fairness_std`

Best static: `static:token_ring` at 1.5993. Lookahead oracle: `oracle:fairness` at 1.3691. Headroom = 0.2302.

| Policy | share of headroom captured |
|---|---|
| `oracle:fairness` | 100% |
| `static:token_ring` | 0% |
| `oracle:balanced` | -80% |
| `static:consistent_hash` | -437% |
| `random` | -447% |
| `static:random_backoff` | -499% |
| `static:leader_election` | -683% |
| `agent` | -901% |
| `rule` | -976% |
| `static:baseline` | -1081% |
| `oracle:queue` | -1184% |

## Is the difference real, or seed noise?

Per-seed paired differences against the best static policy. CRN makes the pairing valid: on each seed both policies met the identical arrival and failure sequence, so seed-to-seed variation cancels. An interval spanning 0 means the difference cannot be told apart from noise.

### `avg_queue_len` vs `static:consistent_hash`

| Policy | mean paired delta | 95% CI | distinguishable from noise |
|---|---|---|---|
| `agent` | 2.9893 | [1.5751, 4.4035] | yes |
| `oracle:balanced` | -0.0991 | [-0.275, 0.0768] | **no** |
| `oracle:fairness` | 21.4984 | [16.0929, 26.9039] | yes |
| `oracle:queue` | -0.1093 | [-0.326, 0.1074] | **no** |
| `random` | 5.2667 | [2.3936, 8.1398] | yes |
| `rule` | 2.0034 | [0.3994, 3.6074] | yes |
| `static:baseline` | 0.0277 | [-0.2079, 0.2633] | **no** |
| `static:leader_election` | 0.0208 | [-0.2631, 0.3047] | **no** |
| `static:random_backoff` | 0.4844 | [0.2066, 0.7622] | yes |
| `static:token_ring` | 29.209 | [28.1605, 30.2575] | yes |

### `avg_wait` vs `static:consistent_hash`

| Policy | mean paired delta | 95% CI | distinguishable from noise |
|---|---|---|---|
| `agent` | 4.6957 | [2.4154, 6.976] | yes |
| `oracle:balanced` | -0.1701 | [-0.44, 0.0998] | **no** |
| `oracle:fairness` | 33.0644 | [24.2142, 41.9146] | yes |
| `oracle:queue` | -0.1632 | [-0.5581, 0.2317] | **no** |
| `random` | 8.21 | [3.7307, 12.6893] | yes |
| `rule` | 3.2486 | [0.598, 5.8992] | yes |
| `static:baseline` | 0.0504 | [-0.3899, 0.4907] | **no** |
| `static:leader_election` | 0.1058 | [-0.5286, 0.7402] | **no** |
| `static:random_backoff` | 0.8811 | [0.1531, 1.6091] | yes |
| `static:token_ring` | 42.0641 | [39.6316, 44.4966] | yes |

### `throughput` vs `static:baseline`

| Policy | mean paired delta | 95% CI | distinguishable from noise |
|---|---|---|---|
| `agent` | -0.0103 | [-0.0164, -0.0042] | yes |
| `oracle:balanced` | -0.001 | [-0.0026, 0.0006] | **no** |
| `oracle:fairness` | -0.134 | [-0.1899, -0.0781] | yes |
| `oracle:queue` | 0.0 | [0.0, 0.0] | **no** |
| `random` | -0.0157 | [-0.0321, 0.0007] | **no** |
| `rule` | -0.0167 | [-0.0279, -0.0055] | yes |
| `static:consistent_hash` | -0.0003 | [-0.0017, 0.001] | **no** |
| `static:leader_election` | -0.001 | [-0.0033, 0.0013] | **no** |
| `static:random_backoff` | -0.0023 | [-0.0061, 0.0014] | **no** |
| `static:token_ring` | -0.217 | [-0.2385, -0.1955] | yes |

### `avg_fairness_std` vs `static:token_ring`

| Policy | mean paired delta | 95% CI | distinguishable from noise |
|---|---|---|---|
| `agent` | 2.074 | [1.7055, 2.4425] | yes |
| `oracle:balanced` | 0.1839 | [-0.0127, 0.3805] | **no** |
| `oracle:fairness` | -0.2302 | [-0.3536, -0.1068] | yes |
| `oracle:queue` | 2.7261 | [2.1513, 3.3009] | yes |
| `random` | 1.0289 | [0.6367, 1.4211] | yes |
| `rule` | 2.2464 | [1.8774, 2.6154] | yes |
| `static:baseline` | 2.4889 | [2.0307, 2.9471] | yes |
| `static:consistent_hash` | 1.0059 | [0.6809, 1.3309] | yes |
| `static:leader_election` | 1.5717 | [1.2801, 1.8633] | yes |
| `static:random_backoff` | 1.1481 | [0.8233, 1.4729] | yes |

## Cost of the agent

- 150 calls, 150 returning a schema-valid decision (100.0%)
- p95 latency 9.28s; 662s of wall clock spent waiting on the model
- the `rule` policy reaches its decision in microseconds, with no network and no key

## How to read this

- A policy that cannot beat `random` has not demonstrated judgement, no matter how large its improvement over a badly chosen static opponent.
- A policy that cannot beat `rule` has not justified an API call.
- The two `oracle:*` rows maximise different objectives (`queue` ignores fairness; `balanced` weighs it at 1.0). Where they disagree, the choice of objective is doing the work, not the policy.
- The oracle is greedy over one horizon, not globally optimal, so it is a strong reference rather than a proven ceiling.
