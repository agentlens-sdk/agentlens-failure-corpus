# Build checklist (13.5h budget)

Work top to bottom. Nothing after step 11 requires you.

| # | Item | Time | Done when |
|---|------|------|-----------|
| 1 | `git init`, push to public repo `agentlens-failure-corpus`; `uv pip install -e .`; set `budget.end_date` in config.yaml to first-run + 56 days | 0.5h | `python -c "import corpus.scheduler"` runs |
| 2 | Ledger: read `corpus/ledger.py`, run `python -m corpus.ledger` mentally through one fake usage dict | 0.5h | you trust the price math |
| 3 | Runner: wire the real AgentLens SDK into `run_episode` (replace the `agentlens` stub key in the trace with an actual `agentlens.trace()` span per turn). This is the marketing; do it properly | 2h | trace opens in AgentLens |
| 4 | Family B: grow `family_tools.py` to ~40 tasks. Fastest path: port scenarios from an open tau-bench-style set into the `Task` shape. Checkers must be deterministic | 2.5h | 40 tasks, each passes with a hand-written correct tool sequence |
| 5 | Family C: grow `family_flakiness.py` to ~20 tasks (small algorithmic + small refactor prompts) | 1h | 20 tasks |
| 6 | Family A (optional): on the box, pull 50 SWE-bench Lite instances, confirm prebuilt images run; implement `family_swebench.py` with read/write/shell tools exec'd inside the container; `enabled: true` | 2h | 3 instances run end to end. Skip entirely if Docker fights you |
| 7 | Labeler: sanity-run `label_traces` on 5 failed traces from step 4 | 0.5h | labels are non-`unclassified` on most |
| 8 | Publisher: deploy key with write access on the repo, `git config` on the box, Pages set to serve `/site`; set `publish.hf_dataset` and `huggingface-cli login` if using HF | 1h | manual `git_push` lands and Pages renders |
| 9 | Guardrails: in Anthropic Console set workspace spend limit = credit balance. This is the cap you don't control at runtime; the ledger is the second | 0.25h | limit visible in Console |
| 10 | Ops: `~/.corpus.env` with `ANTHROPIC_API_KEY`; crontab `0 2 * * * . ~/.corpus.env && /path/run_nightly.sh`; Docker set to start on boot; UPS if the box is at home | 0.5h | `crontab -l` shows it |
| 11 | Dry run: `python dry_run.py`, compare `ledger total` to Console usage (should match within 5%); then run `python -m corpus.scheduler` once by hand and check the push | 0.75h | numbers agree, commit landed |
| 12 | Walk away | — | — |

Two hours you should still spend (violating your own constraint 3, deliberately):
- **Week 4:** post the flakiness chart + dataset link, AgentLens angle.
- **Week 8:** write up the failure taxonomy numbers, cite the dataset.

## Throttle behavior you should understand once
`tonight_budget = min(daily_cap, remaining / days_left * 1.1)`. First 10 episodes per family use a
default cost; after that the observed average drives episode counts. Flakiness repeats scale up to
absorb slack, so undershoot self-corrects within ~3 nights. Overshoot is bounded by `daily_cap`
and by the in-loop `spent_since(t0) >= budget` check (worst case: `concurrency` extra episodes).

## What stops it
`STOPPED` file in repo root. Written by: total cap, 3 zero-trace nights, 3 failed-push nights,
billing/auth error. Delete the file to resume. Nothing else resumes automatically, on purpose.

## Kill criteria (from the plan)
End of week 2: valid-trace yield < 60%, or you touched the host > 2 times, or spend < 40% of target
and not converging. End of week 4: dashboard shows nothing a competent engineer would find surprising.
