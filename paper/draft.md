# Same Prompt, Different Outcome: A Paired, Continuously Published Failure Corpus for Tool-Using Agents

**ArkFelix7** · aivialabs@gmail.com · https://github.com/agentlens-sdk/agentlens-failure-corpus

*Draft, 2026-09-22. Data frozen after the 2026-09-22 08:07Z run. Every number below comes from
`paper/numbers.md`, which `paper/numbers.py` regenerates from the ledger. Do not edit a number by hand.*

## Abstract

We release a corpus of 5,647 agent episodes: two Claude models, the same 22 tasks, run over eight unattended
batches between 2026-09-07 and 2026-09-22. Each episode's full trace is published in an open span format, and every failure carries a label
from a fixed taxonomy. Every task is scored by a deterministic state or equality checker, with no LLM judge,
so a change in outcome can only come from the model or the serving stack, never the benchmark. Tasks are run
in pairs across models and repeatedly within a night. This makes two questions answerable that single-shot
benchmarks cannot address: how often does the *same prompt* both pass and fail on the same model on the same
night, and which failures separate a frontier model from a small one? On tasks built to be hard for the stronger
model, Sonnet 5 passes 91.6% of tool-use episodes and Haiku 4.5 passes 45.4%. But within a single run,
24–67% of task-model cells with repeated episodes contain both a pass and a failure. The dominant failure
is misapplying a stated rule (`misread_spec`), not tool hallucination or looping. We describe the task
design process: most tasks we wrote at first never failed. We also describe a label audit showing that a
small model labeler agrees with a large one on only 64% of tool failures. Data are CC-BY-4.0, code is MIT, and
the corpus grows nightly.

## 1. Introduction

Agent benchmarks usually report one pass rate per model per task, measured once. Two things get lost that way.
The first is *nondeterminism*: at default sampling, the same prompt can pass on one attempt and fail on the
next, so a single measurement mixes capability with luck. The second is *failure structure*: a pass rate says
how often an agent fails, but not how. A failure caused by a misread policy calls for a different fix than one
caused by a malformed tool call or an early stop.

This corpus is built to measure both. Its design decisions are:

1. **Deterministic checkers.** Every task ends in a state assertion over a mock backend, or an equality check
   against expected outputs. Checkers do not drift, so the task set is a fixed instrument.
2. **Pairing.** Every queued task runs once on each agent model, adjacent in the queue, so a budget cutoff
   splits at most one pair.
3. **Repetition.** Coding tasks run *k* times per night by design. Tool tasks are sampled with replacement,
   so they also repeat within a night.
4. **Full traces.** Every episode is published as an `agentlens/v1` span tree: an agent root, one LLM span per
   turn, one tool span per call. Each turn records `stop_reason`, the `served_model` reported by the API, and
   the `request_id`.
5. **Unattended and budget-capped.** A spend ledger, a daily cap, a total cap and a dead-man switch let the
   corpus grow without a human in the loop.

## 2. Corpus design

### 2.1 Task families

**Tools** (`family_tools*.py`): policy-following tool use over four mock APIs: retail orders, an airline, an
incident-ops console and a calendar. Each task gives the agent a policy and a request. The checker compares the
backend's final state with the state produced by a hand-written reference solution. Examples: rebook a
passenger on the earliest flight after noon that satisfies fare rules; triage every open incident according
to a runbook during a night shift; book a series of meetings in Pacific time that spill across days.

**Flakiness** (`family_flakiness*.py`): short coding prompts. Some are write-this-function, some fix-this-bug,
some behaviour-preserving refactors, some small stateful simulations. Each is checked against fixed input and
output cases. Example: `refactor_string_join` asks for a rewrite without concatenation in a loop that must stay
"identical, including the trailing-separator handling". With an empty separator the original returns `""`,
because `out[:-0]` is `out[:0]`, so the obvious `sep.join(words)` changes the function's behaviour.

### 2.2 Making tasks hard enough to fail

The first 65 tasks saturated: 61 never failed in the first 787 episodes. A hard tier, with each task built
around one known trap, did not solve this either: in calibration, 18 of 20 hard tasks passed 5/5 on Sonnet 5.
What did work was *stacking* traps so they interact over a long episode (up to 47 tool calls) or a stateful
simulation. A second, smaller agent model gave the other lever: a task counts as saturated only if *no* listed
model fails it. Saturated tasks are *retired*. They stay in the code, the tests and the dashboard, but are no
longer queued. `calibrate.py` measures every new task and model before it gets a nightly budget.

**Consequence for interpretation.** The active set was selected to be the tasks on which at least one model
still fails. Pass rates on it are not estimates of general capability. They describe behaviour on the frontier
of difficulty for these models, and the gap between the two models is partly a product of that selection
(Section 6).

### 2.3 Harness

Each episode is capped at 80 turns, 600k tokens and 20 minutes of wall clock. Sampling uses the API defaults,
because `claude-sonnet-5` rejects `temperature`, so none is set for any model. The only retry layer is
exponential backoff on rate limits and overload errors. Billing or auth errors stop the night. Secrets
(`sk-ant-*`, `ghp_*`, `hf_*` …) are scrubbed from every trace before it is written. Nightly budget is
`min(daily_cap, remaining / days_left × 1.1)`, split across families by weight using observed per-episode cost.

## 3. Failure labeling

Coding failures are labeled from the checker, with no model involved: the failing submission is rerun, and the
first wrong case, crash or timeout decides the label (`wrong_output`, `crashed`, `timed_out`). Tool failures
need judgment. Each is replayed against the reference solution to produce a state diff (the `checker:` line),
and Claude Opus 5 labels it on the Batch API into one of nine defined labels (`misread_spec`, `premature_stop`,
`tool_misuse`, `wrong_target`, `hallucinated_tool`, `loop`, `gave_up`, `environment_error`, `other`). Replies
without a valid label are recorded as `unclassified` and are never retried.

**Labeler audit.** On 2026-09-14, Haiku 4.5 and Opus 5 both labeled the same 101 tool failures, and 70 received
a valid label from both. They agreed on 45 of 70 (64%, 95% CI [53, 74]). On every disagreement reviewed by
hand, Opus was right. The largest confusion was Haiku calling `wrong_target` what Opus called `misread_spec`
(16 of 25 disagreements): choosing the wrong flight *because a rule was misapplied*. That confusion led to the
current definitions, which separate the two explicitly. Labels in this corpus come from Opus, and we report
the audit because a cheaper labeler would have changed the headline failure distribution.

## 4. Results

*Paired runs only, meaning runs in which both models were queued: seven runs, 5,248 episodes. Episodes that
ended in a harness or network error, and the eight that were running when the 2026-09-22 freeze began
(Section 5), are excluded.*

### 4.1 The two models

| model | family | n | pass rate [95% CI] | USD / episode | USD / passing episode |
|---|---|---|---|---|---|
| Sonnet 5 | tools | 790 | 91.6% [89.5, 93.4] | 0.070 | 0.076 |
| Sonnet 5 | coding | 1835 | 88.8% [87.3, 90.2] | 0.032 | 0.036 |
| Haiku 4.5 | tools | 789 | 45.4% [41.9, 48.9] | 0.021 | 0.047 |
| Haiku 4.5 | coding | 1834 | 55.0% [52.7, 57.3] | 0.006 | 0.011 |

The last column divides total spend by the number of *passing* episodes, which is what a retry-until-success
caller pays. Even at less than half the pass rate, Haiku 4.5 is the cheaper route to a passing episode on both
families: $0.047 against $0.076 on tools, $0.011 against $0.036 on coding. That arithmetic only holds where
a checker can tell a pass from a failure and a retry is acceptable. On the five tasks where Haiku passes
almost never, no number of retries helps, and its expected cost is unbounded.

Sonnet 5's rate is higher on 19 of 22 tasks and Haiku 4.5's on 3 (exact sign test p = 0.00086). The gaps
are extreme and concentrated in specific tasks. Haiku passes 0 of 43 attempts at `ops_stack_night_shift`, 0 of
41 at `cal_stack_week_planner`, 1 of 57 at `air_rebook_earliest_after_noon`, 4 of 266 at `hard_csv_strict` and 0
of 261 at `refactor_string_join`, while Sonnet passes 67–100% of each. The reversals matter just as much. Haiku
is *better* on `retail_address_plus_capped_discount` (46/48 vs 36/48), `hard_ttl_lru_cache` (241/263 vs
196/263) and `cal_no_double_book` (49/54 vs 43/54), so the ordering is not uniform even between two models from
one family.

### 4.2 Same prompt, same night

A *cell* is one task on one model within one run, with two or more episodes. A cell is *mixed* if it contains
both a pass and a failure.

| model | family | cells | mixed |
|---|---|---|---|
| Sonnet 5 | tools | 91 | 22 (24%) |
| Sonnet 5 | coding | 49 | 25 (51%) |
| Haiku 4.5 | tools | 91 | 53 (58%) |
| Haiku 4.5 | coding | 49 | 33 (67%) |

Even for the stronger model, half of the repeated coding cells both pass and fail within a single night. A
single-shot evaluation of these tasks would report pass or fail at random for a large share of them.

**How much of this is task selection?** Most of it. Retirement (Section 2.2) removes tasks no model fails, so
the active set is by construction the set whose pass rates sit away from the extremes -- and a task near 50%
produces a mixed cell almost whenever it repeats. The retired tasks, run by the same harness on the same
nights, are the control: **0 of 57 retired cells are mixed, against 137 of 286 active ones (47.9%)**. The
within-night variation is therefore consistent with independent draws at each task's own pass rate, not
evidence of an extra instability in the models. What remains practically useful is narrower: on tasks at the
edge of a model's ability, one run is close to a coin flip, and the ordering of two models on such a task can
invert between runs.

### 4.3 Across nights

For each task-model pair seen in three or more runs with at least three episodes per run, we test whether its
pass rate is the same in every run (permutation test, uncorrected). Across 42 such pairs and seven paired runs,
three fall below p < 0.05: Sonnet 5 on `cal_no_double_book`, and Haiku 4.5 on `cal_hard_timezone_spill` and
`hard_csv_strict`. Chance alone would produce about 2.1. **The current data do not show night-to-night drift,
and we make no drift claim.** The instrument for detecting it is in place (served model and request id per turn
since 2026-09-15). What it lacks is nights.

### 4.4 How agents fail

Tool failures, Opus-labeled: Haiku 4.5's are dominated by `misread_spec` (350 of 431), followed by
`premature_stop` (48) and `tool_misuse` (30). Sonnet 5's tool failures are mostly `premature_stop` (49 of 66): it
finishes the actions and omits the required final message or note. There are only two `wrong_target` labels and
no `hallucinated_tool` at all. On these tasks, agents fail by applying the policy wrongly, not by inventing
tools. Coding failures are almost entirely `wrong_output` (992 of 1,030; the first failing case is recorded in
each trace). Crashes are rare, and 34 of the 35 are Haiku's.

## 5. Release

- **Traces:** one JSON file per episode under `data/traces/<family>/`, `agentlens/v1` envelope, ULID ids,
  ISO-8601 UTC timestamps. Episodes that never reached the model (zero turns) or ended in a harness error are
  kept in the data and excluded from every analysis here, as are episodes that were in flight when the harness
  was frozen by hand on 2026-09-22 (01:07–03:44Z, to survive a network outage); `paper/numbers.py` names that
  window explicitly.
- **Ledger:** `data/ledger.sqlite`. Every API call with its token counts and cost, every episode with outcome,
  label, evidence and `run_kind` (`nightly`, `calibration`, `aborted`).
- **Dashboard:** https://agentlens-sdk.github.io/agentlens-failure-corpus/
- **Snapshots:** weekly parquet export with labels joined in: https://huggingface.co/datasets/ArkFelix7/agentlens-failure-corpus
- **Reproducing every number here:** `python paper/numbers.py`.
- **Licenses:** data CC-BY-4.0, code MIT.

## 6. Threats to validity

- **Adversarial task selection.** Tasks were written and retired against these two models, so pass rates are
  conditional on a set chosen to make at least one of them fail. The size of the model gap is partly a
  consequence of that selection, and does not measure general capability. Section 4.2 quantifies the same
  effect for the mixed-cell rate against the retired-task control; the control is historical, since retired
  tasks stopped being queued on 2026-09-13, and a permanent control tier in the nightly queue would measure
  it continuously instead.
- **Short time span.** The corpus covers 2026-09-07 onward with a handful of paired runs. Within-run
  nondeterminism is well supported. Across-run stability is not yet testable at useful power.
- **Uneven time sampling.** On 2026-09-21/22 we ran two back-to-back runs of about $50 each to grow the sample.
  They contribute about 73% of the paired episodes, so pooled pass rates (4.1) lean heavily on one day's serving
  conditions. Per-run analyses (4.2, 4.3) treat each run separately and are not affected by this weighting.
- **One family of models, default sampling.** Both agents are Claude models at API-default sampling. We do not
  claim the rates generalize to other providers or temperatures.
- **Single labeler.** Tool labels come from one model (Opus 5), audited against a second model and by hand on
  disagreements only. There is no human inter-annotator study yet.
- **Mock environments.** The APIs are small deterministic simulators. Their policies are written to be
  unambiguous, and ambiguity found in calibration led to fixes or retirement (e.g.
  `retail_exchange_whichever_ships` was retired as invalid: no tool reveals the SKUs it needs).
- **Served-model logging** began on 2026-09-15. Earlier turns show "not recorded".

## 7. Limitations and next steps

Planned: a human-labeled subset to validate the Opus labels; a third agent model from a different provider;
repo-scale coding tasks (`family_swebench.py`, not yet enabled); and, with enough nights, a real test of
serving drift keyed on `served_model` and `request_id`.

## Appendix A: per-task table

See `paper/numbers.md` → "Per task, both models".
