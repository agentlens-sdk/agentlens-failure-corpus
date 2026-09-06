# AgentLens Failure Corpus

Unattended nightly runs of a tool-using agent against fixed tasks. Every trace is captured in
AgentLens format, every failure is labeled with a fixed taxonomy, everything is published here
and (weekly) as a parquet dataset. Budget-capped, dead-man-switched, no human in the loop.

**Dashboard:** https://agentlens-sdk.github.io/agentlens-failure-corpus/

## Layout

- `corpus/scheduler.py` nightly entrypoint, throttle, dead-man switch
- `corpus/runner.py` agent loop with turn/token/wall-clock caps
- `corpus/agentlens_export.py` agentlens/v1 span tree per episode, and the optional live push
- `corpus/tasks/` task families with deterministic checkers
- `corpus/labeler.py` Haiku batch labeling, schema-validated
- `corpus/ledger.py` SQLite spend ledger, single source of truth
- `corpus/redact.py` secret scrubbing on everything that leaves the process
- `site/` static dashboard, deployed to Pages by `.github/workflows/pages.yml`
- `SETUP.md` the host steps: key, deploy key, Pages, cron, spend limit
- `BUILD.md` the original build checklist

## Task families

| family | tasks | what it probes | enabled |
|---|---|---|---|
| `tools` | 40 | policy-following tool use over four mock APIs (retail, airline, ops, calendar) | yes |
| `flakiness` | 20 | short algorithmic and fix-this prompts, re-run k times a night | yes |
| `swebench` | — | repo-scale edits; not implemented, see `corpus/tasks/family_swebench.py` | no |

Every checker is a state or equality assertion. There are no LLM judges anywhere in a checker, so a
task's pass/fail cannot drift between nights — any movement in the flakiness chart is the model or
the serving stack, not the benchmark.

## Traces

One JSON file per episode under `data/traces/<family>/`, each carrying an `agentlens/v1` envelope:
a root `agent` span, an `llm` span per turn, a `tool` span per tool call, ULID ids, ISO-8601 UTC.
If an AgentLens server is running on `localhost:8766` the envelope is POSTed there too; if not, the
local file is authoritative and nothing blocks.

## Tests

Both run offline with no API key and no spend:

    python tests/test_tasks.py           # every task's hand-written solution passes its checker
    python tests/test_runner_offline.py  # replays those solutions through the real run_episode()
    node   tests/test_dashboard.js       # optional: the dashboard renders in every state

## Running it

Host setup is in `SETUP.md`. Once that is done, `run_nightly.sh` from cron is the whole operation.
A `STOPPED` file in the repo root halts everything; the file names the reason. Delete it to resume.

Data license: CC-BY-4.0. Code: MIT.
