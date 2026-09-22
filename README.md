# SchedulerAI

A student project. It simulates a distributed job scheduler across 8 servers,
lets a language model pick the scheduling strategy at runtime, and — the part
worth reading — measures whether letting it do that is worth anything.

The interesting result is mostly negative, and finding it is what the project
is actually about.

---

## What this started as, and what it became

The original version of this README claimed that AI-guided switching cut queue
length 88% and raised throughput 41%. Those numbers were real outputs of a
working comparison. They were also an artifact of which fixed strategy had been
picked as the opponent, and I could not have told you that without building
something to check.

So I built the check. It says:

- **Throughput headroom from switching strategies is 0.0%.** Not small —
  zero. Three of the five strategies are perfectly work-conserving and produce
  byte-identical throughput. No switching policy can improve on that, because
  there is nothing there to improve.
- **A +41% throughput figure is still obtainable** — by comparing against
  `token_ring`, which declines ~86% of its chances to dispatch a job by design.
  That number measures the opponent, not the agent.
- **Fairness is the one axis with real headroom,** and switching genuinely
  helps there: a policy with foresight beats *four of the five* fixed
  strategies on backlog *and* fairness simultaneously, which no single fixed
  strategy manages.
- **A 12-line rule table is worse than not switching at all.** It is dominated
  by three of the five fixed strategies.

That last pair is the setup: switching has real value, and the obvious cheap
heuristic fails to capture it. Whether a language model can is the open
question the harness exists to answer.

---

## The measurements

Three scripts, one question each. All three run offline with no API key; only
the `agent` policy needs a model.

| Script | Question |
|---|---|
| `backend/eval_mechanism.py` | Why can't strategy choice move throughput? |
| `backend/eval_oracle.py` | Who captures the value that *is* available? |
| `backend/eval_probe.py` | What decision function is the model implementing? |
| `backend/eval_ablation.py` | Which component is actually producing the decisions? |

641 live model calls back the results below, all against
`gpt-oss:120b` via Ollama.

### 1. Why throughput is closed

Cluster capacity is `num_servers / mean_service` jobs per step and owes nothing
to the scheduling strategy. A strategy is **work-conserving** if it never
leaves a server idle beside a queued job; the engine counts the assignments
each strategy could have made against the ones it made.

5 seeds x 600 steps, 8 servers, `mean_service=12`, **failures disabled**:

| Strategy | work conservation | throughput | fairness std |
|---|---|---|---|
| `baseline` | **1.0000** | **0.606000** | 8.28 |
| `consistent_hash` | **1.0000** | **0.606000** | 6.66 |
| `leader_election` | **1.0000** | **0.606000** | 5.99 |
| `random_backoff` | 0.9100 | 0.603667 | 6.18 |
| `token_ring` | 0.1320 | 0.413667 | 3.27 |

Identical to the last bit, while fairness varies. Work-conserving strategies
dispatch on exactly the same steps; all they vary is *which* server gets the
job.

With failures enabled a spread of ~1% appears, and that is a second-order
effect of the same thing: a failure discards the in-flight job's progress, and
which job is in flight is precisely what the strategies disagree about. Across
utilisation 0.71 to 1.90, throughput spread among work-conserving strategies
stays between 0.000 and 0.009 while the fairness spread runs from 2.4 to 21.7.

`results/EVAL_mechanism.md`

### 2. Who captures the available value

Every policy faces the same decision every 20 steps, from the same
CRN-controlled workload, differing only in how it chooses:

- `static:*` — never switches. Five of these; the best is the bar.
- `random` — uniform choice. The "better than noise?" control.
- `rule` — the 12-line rule table. The "expensive if/else?" control.
- `oracle:*` — forks the live state once per candidate strategy, runs each
  forward 40 steps under the identical arrival and failure sequence, takes the
  best. It sees the future. It is not deployable and is not meant to be; it
  exists to size the prize.
- `agent` — the model.

10 seeds x 300 steps, decisions every 20 steps:

| | best fixed | lookahead oracle | headroom |
|---|---|---|---|
| throughput | 0.6283 | 0.6283 | **0.0%** |
| avg queue length | 2.600 | 2.491 | 4.2% — negligible |
| fairness std | 1.599 | 1.369 | **14.4%**, CI [−0.354, −0.107] |

Judged on both axes at once, where both are lower-is-better:

| Policy | avg queue | fairness std | fixed strategies it beats on both | beaten by |
|---|---|---|---|---|
| `oracle:balanced` | 2.50 | 1.78 | **4 of 5** | none |
| `oracle:fairness` | 24.10 | 1.37 | `token_ring` | none |
| `oracle:queue` | 2.49 | 4.33 | none | none |
| `rule` | 4.60 | 3.85 | none | 3 of 5 |
| `agent` (`gpt-oss:120b`) | 5.59 | 3.67 | none | 3 of 5 |
| `random` | 7.87 | 2.63 | none | `consistent_hash` |

The fixed-strategy frontier is just `consistent_hash` (2.60 / 2.61) and
`token_ring` (31.81 / 1.60). `oracle:balanced` beats `consistent_hash` on
*both* axes — **switching has genuine value, and it is worth 14.4%**.

Neither `rule` nor `agent` captures it. Both are dominated by the same three
fixed strategies, and they do not dominate each other: the agent is better on
fairness (3.67 vs 3.85), worse on backlog (5.59 vs 4.60). The agent held its
strategy on 89 of 150 decisions and switched on 61, at 8.4s and ~1,600 tokens
per decision against the rule table's microseconds.

150/150 agent calls returned a schema-valid decision, with zero transport or
parse failures.

> One number not to over-read: agreement with the lookahead was 14.7% for the
> agent and 22.0% for `random`. The reference there is the *fairness* oracle,
> and the agent mostly holds `baseline` — so this says "it is not chasing
> fairness", not "it decides worse than chance". The Pareto row is the honest
> summary.

`results/EVAL_oracle.md`

### 3. What function the model implements

Hold every input fixed but one, sweep that one, and watch where the answer
changes. That is the decision boundary the model implements — the if/else it
*is*, whether or not it was written as one. Asking the identical state several
times measures how much of the answer is judgement and how much is sampling
noise.

`gpt-oss:120b` via Ollama, 31 states x 5 repeats = 155 calls, temperature 0.7:

| | |
|---|---|
| Schema-valid responses | **155/155 (100%)** |
| Self-consistency on identical input | **85.2%** — 17/31 states answered identically all 5 times |
| Agreement with the 12-line rule table | **61.3%** |
| Latency per decision | **8.4s median, 14.0s p95** |
| Tokens per decision | ~1,251 in / ~354 out |

**Which inputs it actually uses:**

| Input | answer moves? |
|---|---|
| `queue_len` (0 → 80) | **no — `baseline` at every point** |
| `queue_rate` (−3 → +6) | yes — switches to `random_backoff` at ≥ +1 |
| `num_failed` (0 → 5) | yes — switches to `consistent_hash` at ≥ 3 |
| `fairness_std` (0 → 14) | yes — switches to `token_ring` at ≥ 6 |
| current `strategy` | yes — holds whatever is running, in all 5 cases |

The `queue_len` result is the interesting one, and it is not inattention. At
`queue_len=80` the model names the backlog and reasons past it:

> "The queue is stable (queue_rate = 0) with 80 jobs waiting... throughput is
> already matching the incoming rate... Keeping baseline preserves the current
> throughput."

It treats queue **level** as informational and queue **rate** as actionable.
That happens to be right, and the mechanism measurement is what shows it:
backlog is set by capacity against offered load, so switching cannot drain it.
The rule table does the naive thing instead — `queue_len > 30 → random_backoff`
— and that is a plausible reason it ends up Pareto-dominated by three fixed
strategies.

Two independent measurements agreeing is the strongest thing in this project.

Against the deterministic `mock` provider the same harness reports 100%
consistency and 100% rule agreement, and recovers the rule table's exact
thresholds from black-box sweeps alone — so the 85.2% above is the model's
variance, not the harness's.

`results/EVAL_probe.md`

### 4. Which component is actually deciding?

The probe says *what* the model does; it does not say *why* it underperforms,
and "the model is bad at this" is a shrug rather than a finding. Each ablation
removes one component and measures what changes, over 8 fixed states — two of
which deliberately pit fairness against throughput.

**Inputs — drop one metric from the state entirely:**

| Removed | decisions changed | reading |
|---|---|---|
| `queue_len` | **0 of 8** | never used it — confirms the probe |
| `avg_wait` | **0 of 8** | never used it |
| `queue_rate` | 2 of 8 | load in use |
| `num_failed` | 2 of 8 | in use |
| `fairness_std` | 2 of 8 | in use |

**Two of five metrics are dead weight.** The state schema can lose 40% of its
payload with no behavioural change — a real token saving, and independent
confirmation that the `queue_len` result was deliberate ordering rather than
inattention.

**Prompt — how much is the model, how much is the brief:**

| Variant | size | agrees with `full` |
|---|---|---|
| `full` (shipped) | 5,093 chars | — |
| `no_ceiling` (token_ring's throughput ceiling removed) | 4,725 | 75% |
| `minimal` (strategy names + output contract only) | 517 | **37.5%** |

A 10x shorter prompt changes **62.5% of decisions**, so the prompt is carrying
most of the decision-making. Removing just the token_ring ceiling hint flips
`unfair_calm` — meaning part of the fairness → `token_ring` boundary the probe
found was the hint being recited, not fairness being weighed.

**Temperature — is the variance fixable at the call site?**

| Temperature | self-consistency | agrees with 0.7 |
|---|---|---|
| 0.0 | **90.0%** | 62.5% |
| 0.7 | **90.0%** | — |
| 1.0 | 82.5% | 87.5% |

**Temperature 0 buys no determinism** — identical consistency to 0.7, on
identical inputs. The variance does not come from sampling temperature, so it
cannot be removed by setting `temperature=0`; majority-vote sampling over
several calls is the mitigation that remains.

`results/EVAL_ablation_inputs.md`, `EVAL_ablation_prompt.md`,
`EVAL_ablation_temperature.md`

---

## What I would say about this in an interview

The defensible claim is not "an LLM made scheduling faster". It is:

> I built a scheduling simulator with an LLM choosing dispatch strategy at
> runtime. To find out whether that helped, I built a lookahead oracle — fork
> the live state with the RNG streams intact, roll every candidate strategy
> forward against an identical future. It proved dynamic switching genuinely
> beats every fixed strategy on backlog *and* fairness at once, worth 14.4%
> with the confidence interval excluding zero. It also proved throughput
> headroom was exactly zero — three of the five strategies are perfectly
> work-conserving and produce identical throughput — so I stopped optimising
> there. Then 641 live model calls showed 40% of my input schema was never
> read, and that temperature 0 buys no determinism. The first prompt does not
> capture the headroom yet, but I know how much there is and which inputs
> matter.

The parts I would expect to be pushed on, and would concede:

- The lookahead oracle is **greedy over one horizon, not globally optimal**, so
  it is a strong reference and not a proven ceiling. At one load it scores
  *worse* than the best fixed strategy on queue length, which is what greedy
  myopia looks like.
- Which policy the oracle prefers **depends on the objective it maximises**,
  and the fairness weight in the balanced objective is a judgement call, not a
  derived constant. That is why results are reported under three objectives;
  where they disagree, the choice of objective is doing the work, not the
  policy.
- It is a **simulation**. No real workers, no network, no real compute.
- **n=10 seeds** for the oracle results, and **one model**. Enough for the
  paired intervals reported and to falsify my own earlier claim; not enough to
  generalise. Scaling seeds and comparing model sizes is the obvious next step,
  and the provider layer already supports it.
- The ablations show the **prompt is carrying most of the decision-making**, so
  the agent result is a verdict on this prompt with this model — not on the
  idea. The next version would be built around the three inputs that measurably
  matter.

---

## Architecture

```
React dashboard  ──WebSocket──►  FastAPI  ──►  SimEngine (8 servers, seeded)
       │                            │
       └────POST /agent/decide──────┘──►  agent_service ──► Ollama / Gemini / mock
                                    │
                                    └──►  SQLite (run configs, decision log)
```

The API key stays server-side; nothing model-related reaches the browser
bundle.

**Common Random Numbers.** Comparing two scheduling policies is only
meaningful if they met the same workload. `SimEngine` splits its randomness
into three independent streams derived from one seed — arrivals, failures, and
strategy-internal draws. Because `random_backoff` is the only strategy that
draws randomness, a single shared stream would let it shift every subsequent
arrival and failure in its own arm, so the two arms would face different
workloads. That is exactly the confound the comparison exists to remove. The
split is asserted at runtime (`crn_verified`) and pinned by tests.

**Forking.** `SimEngine.fork()` deep-copies the live state, RNG streams
included, so N candidate strategies can be rolled forward from one state
against an identical future. This is what makes the lookahead oracle possible,
and `test_engine.py` pins the property it depends on.

### The five strategies

| Strategy | Primitive | Work-conserving |
|---|---|---|
| `baseline` | lowest-ID-first dispatch | yes |
| `random_backoff` | randomised retry, CSMA/CD-style | mostly (~0.91) |
| `consistent_hash` | hash ring with forward probing | yes |
| `token_ring` | rotating token, mutual exclusion | **no (~0.13)** |
| `leader_election` | elected coordinator dispatches | yes |

---

## Running it

### Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env        # then fill in a key if you want the agent
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Tests

```bash
cd backend && python test_engine.py     # 30 tests, no dependencies
```

They pin the properties the results depend on: CRN, fork fidelity, failure
semantics, replay timing, and the work-conservation finding itself. If
`test_work_conserving_strategies_share_one_throughput_absent_failures` ever
fails, the headline result needs revisiting.

### Running the evaluation

```bash
cd backend

# No API key needed:
python eval_mechanism.py --seeds 5 --steps 600
python eval_oracle.py --policies static,random,rule,oracle --seeds 10

# Validate the harnesses against the deterministic mock first — against `mock`
# they must report 100% consistency and zero divergence between conditions,
# or the measurement code is wrong rather than the model:
AGENT_PROVIDER=mock python eval_probe.py --repeats 3
AGENT_PROVIDER=mock python eval_ablation.py --mode prompt --repeats 2

# Then with a real model (set AGENT_PROVIDER and a key in .env):
python eval_probe.py --repeats 5 --concurrency 4
python eval_oracle.py --policies all --seeds 10
python eval_ablation.py --mode inputs --repeats 3
python eval_ablation.py --mode prompt --repeats 3
python eval_ablation.py --mode temperature --repeats 5
```

`AGENT_PROVIDER` selects `ollama`, `gemini`, or `mock`. Ollama is the default
because the harness makes hundreds of calls per sweep and Gemini's free tier
has a per-day quota that one sweep exhausts. The decision contract is identical
across providers, so which one produced a decision never changes how it is
scored.

---

## Layout

```
backend/
  app/
    scheduler_engine.py   SimEngine, 5 strategies, CRN streams, fork()
    agent_prompt.py       prompt + variants + response schema + validation
    agent_service.py      ollama / gemini / mock behind one contract
    api.py                routes, WebSocket, comparison pipeline
    models.py             Run, JobLog, GeminiDecision
    config.py, database.py, main.py
  eval_mechanism.py       why throughput is closed
  eval_oracle.py          policy ladder, headroom, Pareto, paired CIs
  eval_probe.py           decision-boundary probe
  eval_ablation.py        prompt / input / temperature ablations
  test_engine.py          30 invariant tests
frontend/                 App.tsx, components/, services/  (flat, no src/)
results/                  generated reports, regenerable from the scripts
```

---

## Known limitations

1. **Simulation, not production.** Discrete-event; no real workers or I/O.
2. **n=10 seeds** for the oracle results, 5 for the mechanism results, and a
   single model (`gpt-oss:120b`). Enough to bound the headroom, not to
   generalise across models.
3. **The oracle is greedy, not optimal** (see above).
4. **Synthetic probe and ablation states have no history**, so the prompt's
   hysteresis instruction has nothing to bind to; the `strategy` sweep is a
   proxy for stickiness, not a test of hysteresis.
5. **The prompt tells the model about `token_ring`'s throughput ceiling**, and
   the `no_ceiling` ablation shows that hint is load-bearing — part of the
   fairness → `token_ring` boundary is recitation rather than judgement.
6. **The agent result is a verdict on one prompt**, not on the idea. The
   ablations show the prompt carries most of the decision-making, and point at
   what a second version should be built around.

---

## License

MIT

*Built by [Ashmeen Kaur](https://github.com/ashmeenkhaira) — B.E. Electronics
and Computer Engineering, Thapar Institute of Engineering and Technology*
