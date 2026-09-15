"""Audit the Haiku labels on tool-use failures against a stronger reference model.

Coding failures are labeled from the checker and need no audit. Tool failures are labeled by Haiku, so a
stronger model labels the same failures from exactly the same view (the compacted trace plus the replay
diff) and the two are compared. Reference labels go to their own ledger table, label_audit, and never
overwrite episodes.label. Disagreements are written out for review. Model-vs-model agreement is an
estimate of label quality, not a human-validated one.

Run: . ~/.corpus.env && .venv/bin/python label_audit.py [--model claude-opus-5] [--limit N]
"""
import argparse, json, time
from collections import Counter
from pathlib import Path
import anthropic, jsonschema
from corpus import ledger, labeler

ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
ap.add_argument("--model", default="claude-opus-5")
ap.add_argument("--limit", type=int, default=0, help="audit at most this many failures (0 = all)")
args = ap.parse_args()
if args.model not in ledger.CFG["prices"]:
    raise SystemExit(f"{args.model} has no entry under prices in config.yaml, so its spend cannot be recorded")

c = ledger.conn()
c.execute("CREATE TABLE IF NOT EXISTS label_audit(episode_id TEXT, model TEXT, label TEXT, confidence REAL, "
          "evidence TEXT, ts REAL, PRIMARY KEY(episode_id, model))")
rows = c.execute("SELECT episode_id, label, trace_path FROM episodes WHERE family='tools' AND outcome!='pass' "
                 "AND COALESCE(evidence,'') NOT LIKE '[manual]%' ORDER BY ts").fetchall()
rows = [r for r in rows if Path(r[2]).exists()][: args.limit or None]
haiku = {e: l for e, l, _ in rows}
traces = {e: json.loads(Path(p).read_text()) for e, _, p in rows}
by_cid = {labeler._custom_id(e): e for e in traces}
print(f"{args.model}: auditing {len(rows)} tool failures", flush=True)

client = anthropic.Anthropic()
batch = client.messages.batches.create(requests=[
    {"custom_id": labeler._custom_id(e),
     "params": {"model": args.model, "max_tokens": 16000, "system": labeler.SYSTEM,
                "messages": [{"role": "user", "content": labeler._compact(t)}]}}
    for e, t in traces.items()])
while client.messages.batches.retrieve(batch.id).processing_status != "ended":
    time.sleep(60)

ref = {}
for r in client.messages.batches.results(batch.id):
    e = by_cid.get(r.custom_id)
    if e is None or r.result.type != "succeeded":
        continue
    msg = r.result.message
    ledger.record_call(e, args.model, msg.usage.model_dump())
    lab, conf, ev = "unclassified", None, None
    if msg.stop_reason != "refusal":
        try:
            obj = labeler._parse(next(b.text for b in msg.content if b.type == "text"))
            jsonschema.validate(obj, labeler.SCHEMA)
            lab, conf, ev = obj["label"], obj.get("confidence"), obj.get("evidence")
        except Exception:
            pass
    ref[e] = lab
    with ledger.conn() as w:
        w.execute("INSERT OR REPLACE INTO label_audit VALUES(?,?,?,?,?,?)", (e, args.model, lab, conf, ev, time.time()))

both = [e for e in ref if ref[e] != "unclassified" and haiku.get(e) not in (None, "unclassified")]
agree = sum(ref[e] == haiku[e] for e in both)
print(f"\nlabeled by both: {len(both)} of {len(rows)}; agreement {agree}/{len(both)}"
      + (f" = {agree / len(both):.0%}" if both else ""))
print("haiku -> reference, disagreements:", dict(Counter(f"{haiku[e]} -> {ref[e]}" for e in both if ref[e] != haiku[e])))
out = Path("logs") / f"label-audit-{time.strftime('%Y-%m-%d')}.json"
out.parent.mkdir(exist_ok=True)
dis = [{"episode_id": e, "task_id": traces[e]["task_id"], "model": traces[e].get("model"), "haiku": haiku[e],
        "reference": ref[e], "checker": labeler._checker_detail(traces[e])} for e in both if ref[e] != haiku[e]]
out.write_text(json.dumps(dis, indent=1))
print(f"{len(dis)} disagreements written to {out}")
print(f"spent ${sum(r[0] for r in c.execute('SELECT cost_usd FROM calls WHERE model=? AND ts>=?', (args.model, time.time() - 86400))):.2f} on {args.model} in the last 24h")
