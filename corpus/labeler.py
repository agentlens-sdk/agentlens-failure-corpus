"""Failure taxonomy. Coding failures are labeled from the checker; everything else via Haiku on the Batch API.

A failed coding submission's cause is already known exactly: explain_failure reruns it and reports the
first wrong case, a crash, a timeout or a missing submission. Asking a model to name that only added
noise (on 2026-09-14 one identical bug drew four different labels), so those labels are assigned
directly. Tool-use failures need judgment and go to Haiku, with a definition for every label.
Invalid model output -> 'unclassified'. Never retried.
"""
import json, time
import anthropic, jsonschema
from . import ledger
from .ledger import CFG

LABEL_DEFINITIONS = {
    "loop": "repeated the same calls or steps without making progress",
    "hallucinated_tool": "called a tool or argument that does not exist, or relied on data no tool returned",
    "wrong_target": "acted on the wrong entity: order, line, reservation, flight, service, incident or time slot",
    "premature_stop": "ended before finishing a required step, including the required final message or note",
    "misread_spec": "misapplied or misunderstood a rule or requirement stated in the policy or prompt",
    "tool_misuse": "called a real tool with wrong arguments, or in a way its description rules out",
    "environment_error": "the task or its tools made success impossible",
    "gave_up": "stopped and said it could not proceed although the tools allowed it",
    "other": "none of the above",
}
CHECKER_LABELS = ["wrong_output", "crashed", "timed_out"]   # coding tasks only, assigned from the checker
TAXONOMY = list(LABEL_DEFINITIONS) + CHECKER_LABELS
SCHEMA = {"type": "object", "required": ["label", "confidence", "evidence"],
          "properties": {"label": {"enum": list(LABEL_DEFINITIONS)}, "confidence": {"type": "number"},
                         "evidence": {"type": "string"}}}
SYSTEM = ("You label failed AI-agent traces. Return ONLY a JSON object {label, confidence, evidence}. "
          "label must be one of the following, chosen by its definition:\n"
          + "\n".join(f"- {k}: {v}" for k, v in LABEL_DEFINITIONS.items())
          + "\nReply with the JSON object only: no analysis before or after it. "
          "evidence is <=200 chars citing the turn number. "
          "A 'checker:' line, when present, is ground truth about why the final output failed. "
          "Text marked [cut for labeling] was shortened here only; the agent sent it in full.")

# Until 2026-09-14 tool inputs were cut at 300 chars, so every submitted function longer than that looked
# truncated and was labeled premature_stop or tool_misuse. Submitted code must arrive whole.
TEXT_CHARS, TOOL_INPUT_CHARS, RESULT_CHARS = 1500, 4000, 1000

def _cut(s, n):
    return s if len(s) <= n else s[:n] + " [cut for labeling]"

def _checker_detail(trace):
    """What the checker saw, recomputed from the trace. Coding tasks: the first case the submission got wrong,
    run in a subprocess. Tool tasks: how the replayed end state differs from the reference solution's."""
    from .tasks import load_family
    if trace.get("family") == "tools":
        from .tasks.explain_tools import explain_tool_failure
        proto = next((t for t in load_family("tools") if t.task_id == trace["task_id"]), None)
        return explain_tool_failure(proto, trace) if proto else None
    if trace.get("family") != "flakiness":
        return None
    from .tasks.family_flakiness import explain_failure
    task = next((t for t in load_family("flakiness") if t.task_id == trace["task_id"]), None)
    if task is None:
        return None
    code = next((b["input"].get("code") for t in trace["turns"] for b in t["assistant"]
                 if b.get("type") == "tool_use" and b.get("name") == "submit"), None)
    return explain_failure(code, task.fn, task.cases)

def label_from_checker(detail):
    """The label a checker detail settles on its own, or None when it does not."""
    if not detail:
        return None
    if detail == "no code submitted":
        return "premature_stop"
    if detail.startswith("timed out"):
        return "timed_out"
    if detail.startswith(("code does not load", "harness exited")):
        return "crashed"
    if detail.startswith("args "):
        return "crashed" if ": raised " in detail else "wrong_output"
    return None

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

def _parse(text):
    """The first JSON object anywhere in a reply. Replies arrive fenced, or after a paragraph of analysis;
    until 2026-09-14 both became 'unclassified'."""
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                obj, _ = dec.raw_decode(text, i)
                if isinstance(obj, dict):
                    return obj
            except ValueError:
                continue
    raise ValueError("no JSON object in reply")

def _custom_id(episode_id):
    """Batch custom_ids are capped at 64 chars; episode_ids run to ~70. The trailing ULID is unique
    on its own, so key the batch by that and map back. Truncating instead silently loses labels."""
    return episode_id.rsplit("-", 1)[-1][:64]

def _record(episode_id, label, confidence, evidence):
    with ledger.conn() as c:
        c.execute("UPDATE episodes SET label=?, confidence=?, evidence=? WHERE episode_id=?",
                  (label, confidence, evidence, episode_id))

def label_traces(traces, wait_seconds=7200):
    labels, for_model = {}, []
    for t in (t for t in traces if t["outcome"] != "pass"):
        detail = _checker_detail(t) if t["outcome"] == "fail" else None
        lab = label_from_checker(detail)
        if lab:
            labels[t["episode_id"]] = lab
            _record(t["episode_id"], lab, 1.0, f"checker: {detail}"[:400])
        else:
            for_model.append(t)
    if not for_model: return labels
    by_cid = {_custom_id(t["episode_id"]): t["episode_id"] for t in for_model}
    if len(by_cid) != len(for_model):
        print(f"labeler: {len(for_model) - len(by_cid)} episode ids collided, labeling the survivors")
    client = anthropic.Anthropic(); model = CFG["models"]["labeler"]
    reqs = [{"custom_id": _custom_id(t["episode_id"]),
             "params": {"model": model, "max_tokens": 600, "system": SYSTEM,
                        "messages": [{"role": "user", "content": _compact(t)}]}} for t in for_model]
    batch = client.messages.batches.create(requests=reqs)
    t0 = time.time()
    while client.messages.batches.retrieve(batch.id).processing_status != "ended":
        if time.time() - t0 > wait_seconds: return {**labels, **{e: "unclassified" for e in by_cid.values()}}
        time.sleep(60)
    for r in client.messages.batches.results(batch.id):
        episode_id = by_cid.get(r.custom_id, r.custom_id)
        lab, conf, ev = "unclassified", None, None
        if r.result.type == "succeeded":
            msg = r.result.message
            ledger.record_call(episode_id, model, msg.usage.model_dump())
            try:
                obj = _parse(msg.content[0].text)
                jsonschema.validate(obj, SCHEMA); lab = obj["label"]
                conf, ev = obj.get("confidence"), obj.get("evidence")
            except Exception: pass
        labels[episode_id] = lab
        # evidence is the part a reader actually wants: which turn went wrong and why.
        _record(episode_id, lab, conf, ev)
    return labels
