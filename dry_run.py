"""Step 11 of BUILD.md: 3 episodes per enabled family, no scheduler, prints ledger math to compare with Console."""
from corpus import ledger
from corpus.runner import run_episode
from corpus.tasks import load_family
from corpus.ledger import CFG
for fam, cfg in CFG["families"].items():
    if not cfg["enabled"]: continue
    for t in load_family(fam)[:3]:
        tr = run_episode(t); print(fam, tr["task_id"], tr["outcome"], f"${tr['cost_usd']:.4f}", len(tr["turns"]), "turns")
print("ledger total:", round(ledger.spent_total(), 4), "-> compare against Console usage for today")
