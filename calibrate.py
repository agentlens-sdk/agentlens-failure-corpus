"""Measure pass rates before tasks get a nightly budget.

K runs per task, no scheduler: nothing is labeled, no night is recorded, nothing is pushed. Episodes
still go to the ledger and data/traces like any other, so their spend counts toward the total cap.
Tasks run round-robin, so a spend cap cuts every task's sample evenly instead of dropping the last ones.
A task that passes every run is too easy to earn nightly spend on that model.

Run: . ~/.corpus.env && .venv/bin/python calibrate.py [--runs 5] [--max-usd 8] [--model M] [--all]
  --model  agent model to measure (default: models.agent in config.yaml)
  --all    include tasks listed under `retired`; retirement was measured on one model only
"""
import argparse, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from corpus import ledger
from corpus.ledger import CFG
from corpus.runner import run_episode
from corpus.tasks import load_family

ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
ap.add_argument("--runs", type=int, default=5)
ap.add_argument("--max-usd", type=float, default=8.0)
ap.add_argument("--model", default=CFG["models"]["agent"])
ap.add_argument("--all", action="store_true")
args = ap.parse_args()
ledger.RUN_KIND = "calibration"   # kept in the corpus, but out of the dashboard's pass rates
if args.model not in CFG["prices"]:
    raise SystemExit(f"{args.model} has no entry under prices in config.yaml, so its spend cannot be capped")

active = []
for fam, cfg in CFG["families"].items():
    if not cfg["enabled"]: continue
    retired = set() if args.all else set(cfg.get("retired") or [])
    active += [t for t in load_family(fam) if t.task_id not in retired]
queue = [t for _ in range(args.runs) for t in active]
conc = CFG["episode"]["concurrency"]

t0, results = time.time(), defaultdict(list)
print(f"{args.model}: {len(queue)} episodes planned ({args.runs} per task over {len(active)} tasks), "
      f"stopping at ${args.max_usd:.2f}", flush=True)

def collect(batch):
    for tk, f in batch:
        tr = f.result(); results[(tk.family, tk.task_id)].append((tr["outcome"], tr["cost_usd"]))
        print(f"  {tk.task_id:40} {tr['outcome']:8} ${tr['cost_usd']:.4f}", flush=True)

with ThreadPoolExecutor(conc) as ex:
    batch = []
    for task in queue:
        if ledger.spent_since(t0) >= args.max_usd:
            print("spend cap reached, not submitting more", flush=True); break
        batch.append((task, ex.submit(run_episode, task, args.model)))
        if len(batch) >= conc:
            collect(batch); batch = []
    collect(batch)

print(f"\n{args.model}")
print(f"{'family':10} {'task':40} {'pass':>6} {'avg $':>8}  verdict")
for (fam, tid), rs in sorted(results.items()):
    passes = sum(o == "pass" for o, _ in rs)
    verdict = "too easy" if passes == len(rs) else ("never passes: check the task" if passes == 0 else "in band")
    print(f"{fam:10} {tid:40} {passes}/{len(rs):<4} {sum(c for _, c in rs) / len(rs):8.4f}  {verdict}")
print(f"\nspent ${ledger.spent_since(t0):.2f} in {(time.time() - t0) / 60:.1f} min")
