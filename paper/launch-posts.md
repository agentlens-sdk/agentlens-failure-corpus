# Launch posts

Drafts for announcing the first release. Every number here comes from `paper/numbers.md`; if the corpus
grows before posting, regenerate and update these. Post from your own accounts.

**Lead with the instrument and the null.** The mixed-cell rate is not the headline — the retired-task control
(0 of 57 vs 137 of 286) shows most of it is task selection, and the crowd that reads these posts will find
that hole in minutes if the post doesn't name it first.

**Never cite GitHub clone counts as interest.** 223 clones over 14 days are this repo's own CI runners.

---

## Hacker News (Show HN)

**Title** (76 chars):

    Show HN: Nightly agent-failure corpus – 5,647 traces, deterministic checkers

**URL:** https://agentlens-sdk.github.io/agentlens-failure-corpus/findings.html

**First comment (post immediately after submitting):**

I got tired of agent benchmarks that report one pass rate per model, measured once, scored by an LLM judge.
So I built the opposite and left it running: 22 tasks over four mock APIs (retail, airline, incident ops,
calendar) plus short coding tasks, every one scored by a deterministic state or equality check, no model in
the loop anywhere in a checker. Every queued task runs once on each of two Claude models in the same batch,
and tasks repeat within a batch. It runs unattended under a spend ledger with a nightly cap, a total cap and
a dead-man switch.

5,647 episodes so far, $145 of API spend, every trace and every failure label public.

The first read is a null: across 42 task-model pairs tested over 8 batches, 3 show a pass-rate change
significant at p<0.05, against 2.1 expected by chance. Nothing has drifted yet. That's the baseline any
future drift has to beat, and it's the point of running the same fixed instrument every night rather than
once.

Two things I found more interesting than the model scores:

- Across 497 labeled tool-use failures there is not one hallucinated tool call and not one loop. The dominant
  failure is misapplying a rule that was stated in the prompt (350 of Haiku 4.5's 431). Sonnet 5's
  characteristic failure is different: it does all the work, then stops before the confirmation message the
  task required (49 of its 66).
- Cost per *passing* episode, which is what you pay if you retry until a checker passes: Haiku 4.5 is cheaper
  than Sonnet 5 on both families ($0.047 vs $0.076 on tool tasks) despite half the pass rate — but only where
  a checker exists and retries converge. On the tasks it almost never passes, they never converge.

The honest caveats, before anyone else finds them: tasks were written and retired adversarially against these
two models, so the pass rates are not a capability estimate. Within a batch, ~48% of repeated task-model cells
both pass and fail — but the retired (saturated) tasks are the control, and 0 of 57 of those are mixed, so
most of that is my task selection putting tasks near a 50% pass rate, not a hidden instability. Both models
are Claude models at API-default sampling. Tool failure labels come from one model (Opus 5); a human-labeled
subset is next.

Data (CC-BY-4.0): https://huggingface.co/datasets/ArkFelix7/agentlens-failure-corpus
Code, traces, dashboard (MIT): https://github.com/agentlens-sdk/agentlens-failure-corpus

Every figure on the page regenerates from the released ledger with `python paper/numbers.py`. Happy to take
requests for tasks, models or cuts of the data.

---

## r/MachineLearning

**Title:**

    [P] A nightly agent-failure corpus: 5,647 paired episodes, deterministic checkers, every trace and failure label public (CC-BY-4.0)

**Body:**

Most agent evaluations are a single measurement with an LLM judge. I built a fixed instrument instead and let
it run unattended: 22 tasks (policy-following tool use over four mock APIs, plus short coding/refactor tasks),
each scored by a deterministic state or equality assertion, so a task's verdict cannot drift between nights.
Every queued task runs once per model (Claude Sonnet 5 and Haiku 4.5) in the same batch, tasks repeat within a
batch, and every turn records `stop_reason`, the `served_model` the API reported and the `request_id`.

**Current state:** 5,647 valid episodes across 8 batches (Sep 7–22), $145.60 of agent spend, 1,533 labeled
failures.

**Results so far:**

1. *No drift.* Of 42 task-model pairs with enough repeats, 3 show a between-batch pass-rate difference at
   p<0.05; chance gives 2.1. Two weeks is thin, and I say so — the instrument is built to answer this over
   months.
2. *Failure structure.* Across 497 labeled tool failures: 0 hallucinated tool calls, 0 loops. 363 are
   misapplying a stated rule. The stronger model's signature failure is stopping before the required final
   message.
3. *Selection matters, and I measured it.* ~48% of repeated task-model cells within a batch contain both a
   pass and a failure — but on tasks retired for being saturated, 0 of 57 cells are mixed. Since retirement
   removes tasks no model fails, the active set is concentrated near the middle of the pass-rate range, where
   mixed results are the expected outcome of independent draws. I'd rather publish that control than the
   scarier headline.

**Limitations:** adversarial task selection (not a capability benchmark), two models from one provider at
default sampling, mock environments, single-model failure labeler (64% agreement with a second model on a
101-failure audit; a human-labeled subset is in progress), and a short time span with one day contributing
~73% of the paired episodes.

Dataset: https://huggingface.co/datasets/ArkFelix7/agentlens-failure-corpus
Code + traces + dashboard: https://github.com/agentlens-sdk/agentlens-failure-corpus
Write-up: https://agentlens-sdk.github.io/agentlens-failure-corpus/findings.html

Every figure regenerates from the released SQLite ledger via one stdlib script. Task and model suggestions
welcome — measuring a new one before it gets a nightly budget is one command.

---

## X / Twitter thread

**1/**
I left an agent benchmark running unattended for two weeks: same 22 tasks, two Claude models, every task
scored by a deterministic checker with no LLM judge anywhere.

5,647 episodes. Every trace and every failure label is public.

The first result is a null, and that's the point. 🧵

**2/**
Across 42 task-model pairs over 8 batches, 3 showed a pass-rate change at p<0.05. Chance alone gives 2.1.

Nothing has drifted. That's the baseline any future "the model got worse" claim has to beat — and you can
only get it by running the same fixed instrument every night.

**3/**
The failure labels surprised me more than the scores.

497 labeled tool-use failures. Zero hallucinated tool calls. Zero loops.

These agents fail by misapplying a rule that was written in the prompt — 350 of one model's 431 failures.

**4/**
The other model's signature failure is its own: it completes every action correctly and then stops before the
confirmation message the task asked for. 49 of its 66 tool failures.

Different models fail in different shapes, not just different amounts.

**5/**
The tempting headline was "the same prompt passes and fails on the same night" — ~48% of repeated cells.

But on tasks retired for being too easy, 0 of 57 cells are mixed. My task selection puts tasks near 50% pass
rates, which is where that happens. Control > headline.

**6/**
Data (CC-BY-4.0): huggingface.co/datasets/ArkFelix7/agentlens-failure-corpus
Code + traces (MIT): github.com/agentlens-sdk/agentlens-failure-corpus
Write-up: agentlens-sdk.github.io/agentlens-failure-corpus/findings.html

Every figure regenerates from the released ledger with one script.

---

## Posting notes

- **Order:** Hacker News first (Tue–Thu, 8–10am ET is the usual sweet spot), then r/MachineLearning the same
  day, then X. Don't cross-post to HN and Reddit hours apart — comment threads feed each other.
- **Be around for 3–4 hours after posting.** Unanswered first comments kill both HN and Reddit threads.
- **The critique to expect:** "another agent benchmark" and "nondeterminism isn't news." Both are fair. The
  answer is the same in each case: the contribution is the *continuously running instrument* and the released
  ledger, not the individual numbers, and the null result is what a static dataset can't produce.
- **Don't** claim novelty for the nondeterminism finding. Prior work covers it (arXiv 2602.07150, 2506.09501,
  2509.09705). Cite it if it comes up; it makes the post stronger, not weaker.
- **Do** invite task and model suggestions. That is the cheapest path to contributors, and `calibrate.py`
  makes acting on them a one-liner.
