# How the evaluation is built, and why

This replaces a 1,000-line code map that had drifted out of date. The code is
commented; what is worth writing down separately is the reasoning behind the
measurements, because that is the part that is not obvious from reading it.

---

## 1. The original question was unanswerable

"Does AI-guided switching beat a static strategy?" cannot be answered as posed,
because the answer depends entirely on which static strategy is chosen as the
opponent. Against `token_ring` the improvement is large. Against
`consistent_hash` it is nothing. Both comparisons are honest. Only one gets
put in a README.

Three substitutions make it answerable:

| Instead of | Ask |
|---|---|
| "does it beat a static strategy?" | "how much was available to win, and who captured it?" |
| one metric at a time | both axes at once — a policy that wins on fairness by tanking backlog has not won |
| agent vs static | a ladder: static, random, rule table, oracle, agent |

The ladder is the important part. A policy that cannot beat `random` has not
demonstrated judgement. A policy that cannot beat `rule` has not justified an
API call. Without those rungs, any number is unfalsifiable.

---

## 2. Common Random Numbers

Two policies can only be compared if they met the same workload. `SimEngine`
derives three independent streams from one seed:

```python
self.rng_arrival  = random.Random(seed * 1_000_003 + 1)
self.rng_failure  = random.Random(seed * 1_000_003 + 2)
self.rng_strategy = random.Random(seed * 1_000_003 + 3)
```

The split matters because of one strategy. `random_backoff` is the only one
that draws randomness — it shuffles contenders and assigns backoff durations.
On a single shared stream, every draw it made would shift the *next* arrival
and failure value in its own arm. The two arms would then face different job
arrivals and different failures, which is precisely the confound the comparison
exists to remove. The effect is silent: nothing errors, the numbers just stop
meaning what they claim to.

Split by concern, arrival and failure sequences are identical across any two
engines built from the same seed, whatever strategies they run. This is
asserted at runtime (`crn_verified` in the comparison output) and pinned by
`test_arrivals_and_failures_are_strategy_independent`.

CRN also makes **paired** statistics valid: on each seed both policies met the
identical workload, so the per-seed difference cancels seed-to-seed variation.
`eval_oracle.py` reports 95% intervals on those paired differences. An interval
spanning 0 means the difference is not distinguishable from seed noise, however
large the percentage looks.

---

## 3. Forking, and the oracle it enables

`SimEngine.fork()` deep-copies the live state with all three RNG streams
intact. Five forks from one state, each running a different strategy, therefore
see an identical future — they differ by strategy and nothing else.

That makes a lookahead possible: at each decision point, fork once per
candidate, run each forward `horizon` steps, take the best. The result is a
policy with perfect foresight of arrivals and failures.

Three honest caveats, stated because an interviewer will find them:

1. **It is greedy over one horizon, not globally optimal.** A cleverer policy
   could in principle beat it. It is a strong reference, not a proven ceiling —
   and at `mean_service=12` it measures *worse* than the best fixed strategy on
   queue length, which is what greedy myopia looks like in practice.
2. **It cheats deliberately.** Perfect foresight is not available to any
   deployable policy. Its job is to size the prize, not to be a fair opponent.
3. **Its ranking depends on its objective**, which is a judgement call. Hence
   three of them.

`fork()` drops the per-job audit log (SQLModel rows headed for the database; a
fork is never persisted) and starts `metrics_history` empty, so a fork's own
metrics describe the lookahead window rather than the run so far. Four tests
pin this: that a fork continues the parent exactly, that forks see identical
workloads, that forking does not mutate the parent, and that fork history
covers only the window.

---

## 4. Three objectives, because one would be a thumb on the scale

| Objective | Maximises | Why it exists |
|---|---|---|
| `queue` | −mean queue length | The project's original headline metric |
| `fairness` | −fairness std | The axis that turns out to have headroom |
| `balanced` | −(queue + w · fairness) | What the prompt actually asks the agent to trade off |

Scoring the agent purely on queue length while the prompt instructs it to weigh
fairness would measure the gap between the prompt and the metric, not the
agent. The weight `w = 1.0` in `balanced` is a judgement call and is documented
as one. Where the objectives disagree about which policy is best, the choice of
objective is doing the work — that disagreement is a result, not a defect.

---

## 5. Normalising against headroom, and refusing to when it is meaningless

A raw "−88% queue length" says nothing until you know whether 88% was most of
what existed or a rounding error against a badly chosen opponent. So each
metric is normalised:

```
share captured = (policy − best_static) / (oracle − best_static)
```

This breaks when the denominator is near zero, which is exactly the case that
occurred: the oracle's edge on queue length is ~4% of the best static value.
Dividing by it turned rounding noise into four-digit percentages
(`static:token_ring` scored −22,295%).

The fix is a **relative** negligibility guard: headroom must exceed 5% of the
best static value before anything is normalised against it. Below that the
report says "no meaningful headroom" and explains what that means, rather than
printing a ratio. Reporting the absence of headroom *is* the finding — it says
no switching policy, LLM or otherwise, had much to win on that metric.

---

## 6. Why per-metric headroom still misleads, and the Pareto fix

Judged one metric at a time, the best fixed strategy for fairness is
`token_ring` — which is also the worst for backlog by more than 10x. So
"14% better fairness than `token_ring`" flatters any policy that merely
declines to use it.

Judged on backlog **and** fairness together, the question becomes the one that
matters: is there a switching policy no single fixed strategy can match?

The fixed-strategy frontier turns out to hold only two members,
`consistent_hash` (2.60 / 2.61) and `token_ring` (31.81 / 1.60). Against it:

- `oracle:balanced` (2.50 / 1.78) beats four of the five on both axes and is
  beaten by none. **Switching has genuine value.**
- `rule` (4.60 / 3.85) is beaten by three of the five. **The obvious heuristic
  destroys value.**

That pair is the whole setup for evaluating a model. The bar is not "beat a
static strategy" — it is "beat the rule table, and close some of the distance
to the oracle".

---

## 7. The probe: measuring the function, not the outcome

`eval_oracle.py` scores what a policy achieved. `eval_probe.py` asks what it
*is*: hold every input fixed but one, sweep that one, and watch where the
answer changes. What comes back is the decision boundary the model implements —
the if/else it is, whether or not it was written as one.

Four things get measured, and only the first is about being right:

- **Boundary.** Which strategy it picks as each metric varies. If the answer
  never moves as an input varies, the model is not using that input, whatever
  its stated reasoning claims.
- **Self-consistency.** The identical state, asked N times. Anything below 100%
  is variance a scheduler would have to absorb, and it bounds how much of an
  outcome difference can be attributed to judgement rather than sampling.
- **Rule agreement.** How often it lands where the 12-line rule table lands.
  This is the "expensive if/else" question answered with a number. High
  agreement means it is reproducing something that runs in microseconds for
  free; low agreement is only interesting if the outcome numbers show the
  disagreement paid off.
- **Cost.** Schema-validity rate, latency percentiles, tokens per decision.

Probe states are assembled from exactly the keys the prompt promises
(`agent_prompt.METRIC_KEYS`, asserted at construction), so the model cannot
distinguish a probe from a live snapshot.

**What it cannot show:** a synthetic state has no history, so the prompt's
hysteresis instruction ("hold 20–30 steps before switching") has nothing to
bind to. The `strategy` sweep — same state, different current strategy — is the
closest available proxy and measures stickiness, not hysteresis.

---

## 7b. Ablations: which component is deciding?

The probe says what the model does. It does not say why it underperforms, and
"the model is bad at this" is a shrug rather than a finding. `eval_ablation.py`
removes one component at a time across 8 fixed states — two of which
deliberately pit fairness against throughput, because that is the only place a
real judgement call exists.

**Inputs.** Drop one metric from the state entirely. Removing `queue_len` or
`avg_wait` changed **no decision at all**; removing `queue_rate`, `num_failed`
or `fairness_std` each changed two states. Two of five inputs are dead weight —
a 40% reduction in state payload available for free, and independent
confirmation that the probe's `queue_len` result was deliberate ordering rather
than inattention.

**Prompt.** The shipped prompt is 5,093 characters and does a great deal of the
work: it hands over `token_ring`'s throughput ceiling outright. A 517-character
variant carrying only strategy names and the output contract agrees with it on
just **37.5%** of states. The prompt, not the model, is carrying most of the
decision-making. Removing only the ceiling hint (`no_ceiling`, 75% agreement)
flips the `unfair_calm` state, so part of the fairness → `token_ring` boundary
the probe found was recitation rather than a judgement about fairness.

**Temperature.** Self-consistency is **90.0% at temperature 0.0 and 90.0% at
0.7** — identical. Determinism is not available at the call site, so the
variance cannot be removed by setting `temperature=0`; majority-vote sampling
over repeated calls is the mitigation that remains, and its cost is measurable
in the units already reported.

The reason this matters more than the outcome numbers: the agent result is a
verdict on *one prompt with one model*, and the ablations say which parts of
that setup were load-bearing. Without them, "the LLM underperformed" would be
an unactionable dead end.

## 8. Validating the harness before trusting it

A measurement that reports disagreement where none exists is worse than no
measurement. So `agent_service` ships a `mock` provider: a deterministic rule
table, no network.

Run the probe against it and it must report 100% self-consistency, 100% rule
agreement, and zero schema violations. It does, and it recovers the rule
table's exact thresholds from black-box sweeps alone (`fairness_std > 5 →
token_ring`). The ablation harness gets the same treatment: because `mock`
ignores both prompt and temperature by design, every condition must agree with
every other at 100%. It does. If either ever reported otherwise, the harness
would be wrong rather than the model.

```bash
AGENT_PROVIDER=mock python eval_probe.py --repeats 3
AGENT_PROVIDER=mock python eval_ablation.py --mode prompt --repeats 2
```

---

## 9. Threats to validity

| Threat | Status |
|---|---|
| Opponent selection inflating results | The original failure. Addressed by the ladder and the Pareto framing. |
| Oracle is greedy, not optimal | Acknowledged; it is a reference, not a ceiling. |
| Fairness weight is arbitrary | Acknowledged; three objectives reported. |
| Small n | 10 seeds for the oracle, 5 for the mechanism. Paired CIs reported so the reader can see what that buys. |
| Simulation ≠ production | No real workers, network, or compute. |
| Prompt leaks the answer | Confirmed by ablation: removing the `token_ring` ceiling hint moves 25% of decisions. The hint is load-bearing, and agreement figures should be read accordingly. |
| Prompt is doing the model's job | Confirmed by ablation: a 10x shorter prompt changes 62.5% of decisions. The agent result is a verdict on this prompt, not on the idea. |
| Provider differences | The decision contract is shared and validated identically across providers, so a score is comparable across them. |

---

## 10. What would make this stronger

In rough priority order:

1. **A second prompt, built from the ablation results.** The current one is
   5,093 characters, two of its five inputs are never read, and its
   `token_ring` hint is load-bearing. A version built around the three inputs
   that measurably matter is the single highest-value change available, and the
   harness would score it against the same bound.
2. **Majority voting.** Self-consistency is 90% and temperature 0 does not fix
   it, so three samples and a vote is the obvious mitigation. Its cost is
   already measurable in the units reported.
3. **More seeds and more models.** 10 seeds and one model is enough for the
   paired intervals reported and not enough to generalise. The provider layer
   already supports the swap.
4. **A non-greedy oracle.** Beam search or dynamic programming over the
   decision sequence would turn the reference into something much closer to a
   true ceiling.
5. **A load profile where fairness is worth paying for.** The current profile
   never punishes imbalance directly; adding per-server queues or tail-latency
   scoring would make the fairness axis matter for a reason beyond its own sake.
