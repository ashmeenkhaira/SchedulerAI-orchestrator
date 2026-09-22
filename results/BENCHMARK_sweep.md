# Benchmark Results

Generated 2026-09-22 12:01:35 UTC by `backend/benchmark.py`.

**Mode:** `sweep` — treatment arm is **rule-based selector (NOT Gemini)**.

30 seeds, 500 steps, arrival_prob `0.6`, mean_service `8.0`.

> The treatment arm here is a deterministic rule table, **not** the LLM. It answers "does dynamic switching help?", not "does Gemini help?".

**CRN verified:** yes — both arms saw identical arrivals and failures in every pair.

## vs static `baseline`

| Metric | Static | Agent-guided | Change | 95% CI of paired delta |
|---|---|---|---|---|
| `avg_queue_len` <sub>(lower is better)</sub> | 1.4297 | 5.6147 | +292.7% | [3.4043, 4.9657] |
| `avg_wait` <sub>(lower is better)</sub> | 2.4637 | 8.862 | +259.7% | [5.0815, 7.7152] |
| `avg_turnaround` <sub>(lower is better)</sub> | 8.7632 | 14.9562 | +70.7% | [4.8832, 7.5029] |
| `throughput` <sub>(higher is better)</sub> | 0.6144 | 0.5847 | -4.8% | [-0.0332, -0.0263] |
| `jobs_completed` <sub>(higher is better)</sub> | 307.2 | 292.3333 | -4.8% | [-16.6006, -13.1327] |
| `max_queue_len` <sub>(lower is better)</sub> | 12.4 | 23.5333 | +89.8% | [9.2711, 12.9956] |
| `avg_fairness_std` <sub>(lower is better)</sub> | 6.3273 | 4.6774 | -26.1% | [-2.0172, -1.2826] |
| `starvation_steps` <sub>(lower is better)</sub> | 0.0 | 0.0 | — | [0.0, 0.0] |

Treatment arm ran a different strategy than `baseline` for 305 steps; strategies used: `baseline`, `consistent_hash`, `token_ring`.

## vs static `random_backoff`

| Metric | Static | Agent-guided | Change | 95% CI of paired delta |
|---|---|---|---|---|
| `avg_queue_len` <sub>(lower is better)</sub> | 1.8339 | 5.1597 | +181.3% | [2.5721, 4.0795] |
| `avg_wait` <sub>(lower is better)</sub> | 3.1239 | 8.1169 | +159.8% | [3.7229, 6.2631] |
| `avg_turnaround` <sub>(lower is better)</sub> | 9.393 | 14.1892 | +51.1% | [3.5214, 6.0711] |
| `throughput` <sub>(higher is better)</sub> | 0.613 | 0.5855 | -4.5% | [-0.0316, -0.0234] |
| `jobs_completed` <sub>(higher is better)</sub> | 306.5 | 292.7333 | -4.5% | [-15.8133, -11.7201] |
| `max_queue_len` <sub>(lower is better)</sub> | 13.3 | 23.4333 | +76.2% | [8.0471, 12.2196] |
| `avg_fairness_std` <sub>(lower is better)</sub> | 3.4238 | 4.4565 | +30.2% | [0.734, 1.3314] |
| `starvation_steps` <sub>(lower is better)</sub> | 0.0 | 0.0 | — | [0.0, 0.0] |

Treatment arm ran a different strategy than `random_backoff` for 486 steps; strategies used: `baseline`, `consistent_hash`, `random_backoff`, `token_ring`.

## vs static `consistent_hash`

| Metric | Static | Agent-guided | Change | 95% CI of paired delta |
|---|---|---|---|---|
| `avg_queue_len` <sub>(lower is better)</sub> | 1.4517 | 5.3422 | +268.0% | [3.0179, 4.7631] |
| `avg_wait` <sub>(lower is better)</sub> | 2.4942 | 8.4033 | +236.9% | [4.4614, 7.3569] |
| `avg_turnaround` <sub>(lower is better)</sub> | 8.7856 | 14.532 | +65.4% | [4.2696, 7.2232] |
| `throughput` <sub>(higher is better)</sub> | 0.6143 | 0.5868 | -4.5% | [-0.0317, -0.0232] |
| `jobs_completed` <sub>(higher is better)</sub> | 307.1333 | 293.4 | -4.5% | [-15.8452, -11.6214] |
| `max_queue_len` <sub>(lower is better)</sub> | 12.8333 | 23.4667 | +82.9% | [8.4223, 12.8443] |
| `avg_fairness_std` <sub>(lower is better)</sub> | 3.326 | 4.4962 | +35.2% | [0.8764, 1.464] |
| `starvation_steps` <sub>(lower is better)</sub> | 0.0 | 0.0 | — | [0.0, 0.0] |

Treatment arm ran a different strategy than `consistent_hash` for 387 steps; strategies used: `baseline`, `consistent_hash`, `token_ring`.

## vs static `token_ring`

| Metric | Static | Agent-guided | Change | 95% CI of paired delta |
|---|---|---|---|---|
| `avg_queue_len` <sub>(lower is better)</sub> | 45.6575 | 5.4935 | -88.0% | [-42.1752, -38.1529] |
| `avg_wait` <sub>(lower is better)</sub> | 78.2802 | 8.6261 | -89.0% | [-72.961, -66.3473] |
| `avg_turnaround` <sub>(lower is better)</sub> | 83.8725 | 14.7163 | -82.5% | [-72.4597, -65.8527] |
| `throughput` <sub>(higher is better)</sub> | 0.4363 | 0.5839 | +33.8% | [0.1382, 0.157] |
| `jobs_completed` <sub>(higher is better)</sub> | 218.1333 | 291.9333 | +33.8% | [69.0942, 78.5058] |
| `max_queue_len` <sub>(lower is better)</sub> | 95.2 | 23.8333 | -75.0% | [-75.9734, -66.7599] |
| `avg_fairness_std` <sub>(lower is better)</sub> | 2.0618 | 4.49 | +117.8% | [2.2045, 2.6519] |
| `starvation_steps` <sub>(lower is better)</sub> | 0.0 | 0.0 | — | [0.0, 0.0] |

Treatment arm ran a different strategy than `token_ring` for 306 steps; strategies used: `baseline`, `consistent_hash`, `token_ring`.

## vs static `leader_election`

| Metric | Static | Agent-guided | Change | 95% CI of paired delta |
|---|---|---|---|---|
| `avg_queue_len` <sub>(lower is better)</sub> | 1.4571 | 5.6901 | +290.5% | [3.3037, 5.1622] |
| `avg_wait` <sub>(lower is better)</sub> | 2.5429 | 8.9887 | +253.5% | [4.9082, 7.9834] |
| `avg_turnaround` <sub>(lower is better)</sub> | 8.8326 | 15.0565 | +70.5% | [4.6684, 7.7795] |
| `throughput` <sub>(higher is better)</sub> | 0.6149 | 0.5848 | -4.9% | [-0.0334, -0.0268] |
| `jobs_completed` <sub>(higher is better)</sub> | 307.4333 | 292.4 | -4.9% | [-16.6871, -13.3796] |
| `max_queue_len` <sub>(lower is better)</sub> | 12.5667 | 23.8 | +89.4% | [9.1797, 13.287] |
| `avg_fairness_std` <sub>(lower is better)</sub> | 4.6139 | 4.6574 | +0.9% | [-0.2684, 0.3555] |
| `starvation_steps` <sub>(lower is better)</sub> | 0.0 | 0.0 | — | [0.0, 0.0] |

Treatment arm ran a different strategy than `leader_election` for 486 steps; strategies used: `baseline`, `consistent_hash`, `leader_election`, `token_ring`.

## Reading the CI column

Deltas are paired by seed, which is what CRN makes valid. A 95% interval that excludes 0 means the effect is consistent across seeds; one that spans 0 means it is not distinguishable from seed-to-seed variation, however large the percentage looks.
