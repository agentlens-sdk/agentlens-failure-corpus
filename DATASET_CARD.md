---
license: cc-by-4.0
pretty_name: AgentLens Failure Corpus
language: [en]
tags: [agents, tool-use, evaluation, failure-analysis, nondeterminism, traces]
task_categories: [text-generation]
size_categories: [1K<n<10K]
configs:
  - config_name: default
    data_files: traces.parquet
---

# AgentLens Failure Corpus

Nightly, unattended runs of tool-using agents against fixed tasks. Every episode is a full trace, and every
failure is labeled with a fixed taxonomy. Tasks are scored by deterministic state or equality checkers, with
no LLM judges, so an outcome can change only because of the model or its serving, never the benchmark.

- **Code, dashboard and paper draft:** https://github.com/agentlens-sdk/agentlens-failure-corpus
- **Live dashboard:** https://agentlens-sdk.github.io/agentlens-failure-corpus/
- **Updated:** weekly snapshot of a corpus that grows every night.

## Design

- **Paired:** every queued task runs once on each agent model (`claude-sonnet-5`, `claude-haiku-4-5-20251001`)
  in the same run.
- **Repeated:** coding tasks run several times per night, and tool tasks are sampled with replacement, so the
  same prompt appears many times per model per night.
- **Families:** `tools` (policy-following over mock retail, airline, incident-ops and calendar APIs; checked
  against the backend's final state) and `flakiness` (short coding, bug-fix, refactor and simulation prompts;
  checked against fixed cases).
- **Hard by construction:** tasks that no listed model fails are retired from the nightly queue. Pass rates
  on the active set therefore describe behaviour at the edge of these models' ability, not general capability.

## Fields

One row per episode.

| field | type | meaning |
|---|---|---|
| `episode_id` | string | `<family>-<task_id>-<ULID>` |
| `trace_id` | string | ULID of the root span |
| `family`, `task_id` | string | task identity |
| `model` | string | requested agent model |
| `outcome` | string | `pass`, `fail`, `runaway` (hit a turn, token or time cap), `error` (the episode itself errored) |
| `run_kind` | string | `nightly`, `calibration` or `aborted`. **Use `nightly` for pass rates.** |
| `label` | string | failure label, null for passes |
| `label_confidence`, `label_evidence` | double, string | labeler's confidence and a short cited reason |
| `turns` | JSON string | per turn: assistant content, usage, `stop_reason`, `served_model`, `request_id`, tool results |
| `agentlens` | JSON string | `agentlens/v1` span tree: agent root, one `llm` span per turn, one `tool` span per call |
| `started`, `ended` | double | Unix seconds |
| `cost_usd` | double | agent-side API cost of the episode |
| `error`, `runaway_reason` | string | present when relevant |

`served_model` and `request_id` are recorded from 2026-09-15 on. Episodes with zero turns never reached the
model (a network failure) and should be excluded from behavioural analysis.

## Labels

Coding failures are labeled from the checker by rerunning the submission: `wrong_output`, `crashed`,
`timed_out`. Tool failures are labeled by Claude Opus 5 from the trace plus a replay diff against the
reference solution: `misread_spec`, `premature_stop`, `tool_misuse`, `wrong_target`, `hallucinated_tool`,
`loop`, `gave_up`, `environment_error`, `other`. A reply without a valid label is recorded as
`unclassified`. In a 2026-09-14 audit, Haiku 4.5 agreed with Opus 5 on 45 of 70 tool failures (64%), and Opus
was right on every disagreement reviewed.

## Limitations

The tasks were selected adversarially against these two models, both agents are Claude models at API-default
sampling, the environments are small mock APIs, and tool labels come from a single model labeler. The time
span is short, so night-to-night drift is not yet measurable at useful power.

## License

Data: CC-BY-4.0. Code: MIT.
