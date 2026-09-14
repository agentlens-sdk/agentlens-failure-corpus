"""Measure pass rates of the active (non-retired) tasks before they get a nightly budget.

K runs per task, no scheduler: nothing is labeled, no night is recorded, nothing is pushed. Episodes
still go to the ledger and data/traces like any other, so their spend counts toward the total cap.
A task that passes every run is too easy to earn nightly spend; tune it before the next night.

Run: . ~/.corpus.env && .venv/bin/python calibrate.py [runs_per_task] [max_usd]
"""
import sys, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from corpus import ledger
from corpus.ledger import CFG
from corpus.runner import run_episode
from corpus.tasks import load_family

K = int(sys.argv[1]) if len(sys.argv) > 1 else 5
MAX_USD = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0

active = []
for fam, cfg in CFG["families"].items():
    if not cfg["enabled"]: continue
    retired = set(cfg.get("retired") or [])
    active += [t for t in load_family(fam) if t.task_id not in retired]
# Round-robin, so a spend cap cuts every task's sample evenly instead of dropping the last tasks entirely.
queue = [t for _ in range(K) for t in active]

t0, results = time.time(), defaultdict(list)
print(f"{len(queue)} episodes planned ({K} per task), stopping at ${MAX_USD:.2f}", flush=True)
with ThreadPoolExecutor(CFG["episode"]["concurrency"]) as ex:
    futures = []
    for task in queue:
        if ledger.spent_since(t0) >= MAX_USD:
            print("spend cap reached, not submitting more", flush=True); break
        futures.append((task, ex.submit(run_episode, task)))
        if len(futures) % CFG["episode"]["concurrency"] == 0:
            for tk, f in futures[-CFG["episode"]["concurrency"]:]:
                tr = f.result(); results[(tk.family, tk.task_id)].append((tr["outcome"], tr["cost_usd"]))
                print(f"  {tk.task_id:40} {tr['outcome']:8} ${tr['cost_usd']:.4f}", flush=True)
    for tk, f in futures[len(futures) - len(futures) % CFG["episode"]["concurrency"]:]:
        tr = f.result(); results[(tk.family, tk.task_id)].append((tr["outcome"], tr["cost_usd"]))
        print(f"  {tk.task_id:40} {tr['outcome']:8} ${tr['cost_usd']:.4f}", flush=True)

print(f"\n{'family':10} {'task':40} {'pass':>6} {'avg $':>8}  verdict")
for (fam, tid), rs in sorted(results.items()):
    passes = sum(o == "pass" for o, _ in rs)
    verdict = "too easy" if passes == len(rs) else ("never passes: check the task" if passes == 0 else "in band")
    print(f"{fam:10} {tid:40} {passes}/{len(rs):<4} {sum(c for _, c in rs) / len(rs):8.4f}  {verdict}")
print(f"\nspent ${ledger.spent_since(t0):.2f} in {(time.time() - t0) / 60:.1f} min")
