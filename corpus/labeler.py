"""Failure taxonomy via Haiku on the Batch API. Invalid output -> 'unclassified'. Never retried."""
import json, time
import anthropic, jsonschema
from . import ledger
from .ledger import CFG

TAXONOMY = ["loop", "hallucinated_tool", "wrong_target", "premature_stop", "misread_spec",
            "tool_misuse", "environment_error", "gave_up", "other"]
SCHEMA = {"type": "object", "required": ["label", "confidence", "evidence"],
          "properties": {"label": {"enum": TAXONOMY}, "confidence": {"type": "number"}, "evidence": {"type": "string"}}}
SYSTEM = ("You label failed AI-agent traces. Return ONLY a JSON object {label, confidence, evidence}. "
          f"label must be one of {TAXONOMY}. evidence is <=200 chars citing the turn number. "
          "A 'checker:' line, when present, is ground truth about why the final output failed. "
          "Text marked [cut for labeling] was shortened here only; the agent sent it in full.")

# Until 2026-09-14 tool inputs were cut at 300 chars, so every submitted function longer than that looked
# truncated and was labeled premature_stop or tool_misuse. Submitted code must arrive whole.
TEXT_CHARS, TOOL_INPUT_CHARS, RESULT_CHARS = 1500, 4000, 1000

def _cut(s, n):
    return s if len(s) <= n else s[:n] + " [cut for labeling]"

def _checker_detail(trace):
    """The first case a failed coding submission got wrong, recomputed in a subprocess. None for other families."""
    if trace.get("family") != "flakiness":
        return None
    from .tasks import load_family
    from .tasks.family_flakiness import explain_failure
    task = next((t for t in load_family("flakiness") if t.task_id == trace["task_id"]), None)
    if task is None:
        return None
    code = next((b["input"].get("code") for t in trace["turns"] for b in t["assistant"]
                 if b.get("type") == "tool_use" and b.get("name") == "submit"), None)
    return explain_failure(code, task.fn, task.cases)

def _compact(trace):
    lines = []
    for i, t in enumerate(trace["turns"]):
        for b in t["assistant"]:
            if b["type"] == "text": lines.append(f"[{i}] assistant: {_cut(b['text'], TEXT_CHARS)}")
            if b["type"] == "tool_use": lines.append(f"[{i}] tool_use {b['name']}({_cut(json.dumps(b['input']), TOOL_INPUT_CHARS)})")
        for r in t.get("tool_results", []): lines.append(f"[{i}] result: {_cut(str(r['content']), RESULT_CHARS)}")
    head = f"outcome={trace['outcome']} task={trace['task_id']}"
    detail = _checker_detail(trace)
    if detail:
        head += f"\nchecker: {detail}"
    return head + "\n" + "\n".join(lines)[:60000]

def _custom_id(episode_id):
    """Batch custom_ids are capped at 64 chars; episode_ids run to ~70. The trailing ULID is unique
    on its own, so key the batch by that and map back. Truncating instead silently loses labels."""
    return episode_id.rsplit("-", 1)[-1][:64]

def label_traces(traces, wait_seconds=7200):
    failed = [t for t in traces if t["outcome"] != "pass"]
    if not failed: return {}
    by_cid = {_custom_id(t["episode_id"]): t["episode_id"] for t in failed}
    if len(by_cid) != len(failed):
        print(f"labeler: {len(failed) - len(by_cid)} episode ids collided, labeling the survivors")
    client = anthropic.Anthropic(); model = CFG["models"]["labeler"]
    reqs = [{"custom_id": _custom_id(t["episode_id"]),
             "params": {"model": model, "max_tokens": 300, "system": SYSTEM,
                        "messages": [{"role": "user", "content": _compact(t)}]}} for t in failed]
    batch = client.messages.batches.create(requests=reqs)
    t0 = time.time()
    while client.messages.batches.retrieve(batch.id).processing_status != "ended":
        if time.time() - t0 > wait_seconds: return {e: "unclassified" for e in by_cid.values()}
        time.sleep(60)
    labels = {}
    for r in client.messages.batches.results(batch.id):
        episode_id = by_cid.get(r.custom_id, r.custom_id)
        lab, conf, ev = "unclassified", None, None
        if r.result.type == "succeeded":
            msg = r.result.message
            ledger.record_call(episode_id, model, msg.usage.model_dump())
            try:
                txt = msg.content[0].text.strip().strip("`")
                obj = json.loads(txt[4:] if txt.startswith("json") else txt)
                jsonschema.validate(obj, SCHEMA); lab = obj["label"]
                conf, ev = obj.get("confidence"), obj.get("evidence")
            except Exception: pass
        labels[episode_id] = lab
        # evidence is the part a reader actually wants: which turn went wrong and why.
        with ledger.conn() as c:
            c.execute("UPDATE episodes SET label=?, confidence=?, evidence=? WHERE episode_id=?",
                      (lab, conf, ev, episode_id))
    return labels
