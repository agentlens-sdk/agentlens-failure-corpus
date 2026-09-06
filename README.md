# AgentLens Failure Corpus

Unattended nightly runs of a tool-using agent against fixed tasks. Every trace is captured in
AgentLens format, every failure is labeled with a fixed taxonomy, everything is published here
and (weekly) as a parquet dataset. Budget-capped, dead-man-switched, no human in the loop.

- `corpus/scheduler.py` nightly entrypoint and throttle
- `corpus/runner.py` agent loop with turn/token/wall-clock caps
- `corpus/tasks/` three task families with deterministic checkers
- `corpus/labeler.py` Haiku batch labeling, schema-validated
- `corpus/ledger.py` SQLite spend ledger, single source of truth
- `site/` static dashboard served by GitHub Pages
- `BUILD.md` the setup checklist

Data license: CC-BY-4.0. Code: MIT.
