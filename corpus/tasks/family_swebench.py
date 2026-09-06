"""Family A: SWE-bench Lite subset. NOT IMPLEMENTED — `swebench.enabled` is false in config.yaml.

Deliberately skipped (BUILD.md step 6 is optional: "Skip entirely if Docker fights you"). On this box
the Docker daemon was not running and the prebuilt images are multi-GB, so implementing it blind was
not worth the 2h. Families B and C fill the nightly budget on their own: the scheduler splits by
weight over *enabled* families only, so nothing is left unspent.

TO TURN THIS ON LATER
---------------------
1. Docker up, then confirm one prebuilt image runs:
       docker run --rm ghcr.io/epoch-research/swe-bench.eval.x86_64.<instance_id> true
   If that fights you for more than an hour, stop; the corpus is fine without this family.
2. Pin the instance list. Do not resolve it at runtime — a nightly run must be reproducible:
       from datasets import load_dataset
       rows = load_dataset("princeton-nlp/SWE-bench_Lite", split="test").select(range(50))
   Write the 50 instance_ids to a checked-in JSON file next to this module and read that.
3. One Task subclass, instantiated once per instance:
       family = "swebench"; task_id = instance_id
       tools  = read_file(path), write_file(path, content), run_shell(cmd)
       every tool is `docker exec <container> ...` inside that instance's container
       prompt = the instance's problem_statement
4. `fresh()` must start a *new* container from the image and `check()` must stop it. The base
   Task.fresh() returns a bare instance, so override it here; a leaked container per episode will
   fill the disk inside a week. Wrap teardown in try/finally.
5. check(): apply the instance's test_patch, run FAIL_TO_PASS and PASS_TO_PASS, require both. Keep it
   deterministic — no LLM judge, same rule as every other family.
6. Budget: these episodes are ~10x a tools episode. DEFAULT_UNIT in scheduler.py already carries
   0.70 USD/episode for swebench until 10 real episodes are observed; check that against reality
   before leaving it unattended.
7. Only then set `families.swebench.enabled: true`. Weight 0.40 is already in config.yaml, so the
   nightly mix shifts the same night.

Costs of leaving it off: the corpus covers tool-use and short-code flakiness, not repository-scale
edits. Say so in the dataset card rather than implying broader coverage.
"""
TASKS = []
