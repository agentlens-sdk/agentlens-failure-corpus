# arXiv submission metadata

Everything the submission form asks for. The paper body is `draft.md`; convert it to PDF (pandoc or Overleaf)
once the text is final. Nothing here should be edited independently of `draft.md`.

## Title

Same Prompt, Different Outcome: A Paired, Continuously Published Failure Corpus for Tool-Using Agents

## Authors

ArkFelix7 (aivialabs@gmail.com). *Fill in the legal name and affiliation the submission should carry; arXiv
requires a real name on the account, and the paper's byline should match how you want to be cited.*

## Abstract (1,661 characters, within arXiv's 1,920 limit)

We release a corpus of 5,647 agent episodes: two Claude models, the same 22 tasks, run over eight unattended
batches between 2026-09-07 and 2026-09-22. Each episode's full trace is published in an open span format, and
every failure carries a label from a fixed taxonomy. Every task is scored by a deterministic state or equality
checker, with no LLM judge, so a change in outcome can only come from the model or the serving stack, never the
benchmark. Tasks are run in pairs across models and repeatedly within a batch. This makes two questions
answerable that single-shot benchmarks cannot address: how often does the same prompt both pass and fail on the
same model on the same night, and which failures separate a frontier model from a small one? On tasks built to
be hard for the stronger model, Claude Sonnet 5 passes 91.6% of tool-use episodes and Claude Haiku 4.5 passes
45.4%. But within a single batch, 24-67% of task-model cells with repeated episodes contain both a pass and a
failure, so a single measurement of these tasks reports pass or fail partly at random. The dominant failure is
misapplying a stated rule, not tool hallucination or looping: across 497 labeled tool failures there is no
hallucinated-tool label at all. We also report the economics of retrying: the smaller model, at half the pass
rate, is the cheaper route to a passing episode wherever a checker can verify one. We describe the task design
process, in which most tasks we first wrote never failed, and a label audit showing that a small labeler model
agrees with a large one on only 64% of tool failures. Data are CC-BY-4.0, code is MIT, and the corpus grows
with each run.

## Primary category

cs.SE (Software Engineering) — the contribution is a measurement instrument and a released artifact.

## Cross-lists

- cs.AI (Artificial Intelligence)
- cs.LG (Machine Learning)

## Comments field

15 pages. Data: https://huggingface.co/datasets/ArkFelix7/agentlens-failure-corpus. Code, traces and a live
dashboard: https://github.com/agentlens-sdk/agentlens-failure-corpus. Every figure is regenerated from the
released ledger by `paper/numbers.py`.

## License

CC BY 4.0, matching the data license.

## Checklist before submitting

- [ ] Byline: legal name and affiliation decided.
- [ ] `draft.md` read end to end by a human; the results text still matches `numbers.md`.
- [ ] Rerun `python paper/numbers.py` and confirm no figure in the paper changed.
- [ ] PDF built, tables render, links resolve.
- [ ] The Hugging Face dataset and the GitHub repo are public and current.
- [ ] Decide whether to freeze a versioned snapshot (a git tag and a HF revision) so the paper cites a fixed
      state of a corpus that keeps growing.
