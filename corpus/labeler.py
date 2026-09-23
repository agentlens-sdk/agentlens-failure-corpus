"""Failure taxonomy. Coding failures are labeled from the checker; tool failures by a model on the Batch API.

A failed coding submission's cause is already known exactly: explain_failure reruns it and reports the
first wrong case, a crash, a timeout or a missing submission, so those labels are assigned directly.
Tool-use failures need judgment. They carry a replay diff (explain_tools) and go to the labeler model
in config.yaml, which gets a definition for every label. On 2026-09-14 Haiku agreed with Opus on only
64% of tool failures, and Opus was right on every disagreement checked, so the labeler is Opus.
A reply without a usable label -> 'unclassified'. Never retried.
"""
import json, time
import anthropic, jsonschema
from . import ledger, runstate
from .ledger import CFG

LABEL_DEFINITIONS = {
    "loop": "repeated the same calls or steps without making progress",
    "hallucinated_tool": "called a tool or argument that does not exist, or relied on data no tool returned",
    "wrong_target": ("acted on a different entity than the one the task named or meant, such as the wrong order, "
                     "customer, reservation or incident id; not a wrong choice made by misapplying a rule"),
    "premature_stop": "ended before finishing a required step, including the required final message or note",
    "misread_spec": ("misapplied or misunderstood a rule or requirement stated in the policy or prompt, including "
                     "choosing the wrong slot, flight, amount or deploy because a rule was applied wrongly"),
    "tool_misuse": "called a real tool with wrong arguments, or in a way its description rules out",
    "environment_error": "the task or its tools made success impossible",
    "gave_up": "stopped and said it could not proceed although the tools allowed it",
    "other": "none of the above",
}
CHECKER_LABELS = ["wrong_output", "crashed", "timed_out"]   # coding tasks only, assigned from the checker
TAXONOMY = list(LABEL_DEFINITIONS) + CHECKER_LABELS
# Only the label is validated. Until 2026-09-14 confidence had to be a JSON number, and replies giving
# "high" or "0.95" were thrown away whole: 29 of 101 reference labels and 2 Haiku labels.
SCHEMA = {"type": "object", "required": ["label"], "properties": {"label": {"enum": list(LABEL_DEFINITIONS)}}}
SYSTEM = ("You label failed AI-agent traces. Return ONLY a JSON object {label, confidence, evidence}. "
          "label must be one of the following, chosen by its definition:\n"
          + "\n".join(f"- {k}: {v}" for k, v in LABEL_DEFINITIONS.items())
          + "\nconfidence is a number between 0 and 1. evidence is <=200 chars citing the turn number. "
          "Reply with the JSON object only: no analysis before or after it. "
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
    """The label a coding checker detail settles on its own, or None when it does not."""
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

def _confidence(x):
    """A number in [0, 1] from whatever the model wrote there, or None."""
    words = {"high": 0.9, "medium": 0.6, "low": 0.3}
    if isinstance(x, str) and x.strip().lower() in words:
        return words[x.strip().lower()]
    try:
        return min(1.0, max(0.0, float(x)))
    except (TypeError, ValueError):
        return None

def read_label(message):
    """(label, confidence, evidence) from a labeler reply; 'unclassified' when it carries no valid label.
    The text block is looked up by type: with thinking on, it is not the first content block."""
    if message.stop_reason == "refusal":
        return "unclassified", None, None
    try:
        obj = _parse(next(b.text for b in message.content if b.type == "text"))
        jsonschema.validate(obj, SCHEMA)
    except (StopIteration, ValueError, jsonschema.ValidationError):
        return "unclassified", None, None
    return obj["label"], _confidence(obj.get("confidence")), (str(obj["evidence"]) if obj.get("evidence") else None)

def _custom_id(episode_id):
    """Batch custom_ids are capped at 64 chars; episode_ids run to ~70. The trailing ULID is unique
    on its own, so key the batch by that and map back. Truncating instead silently loses labels."""
    return episode_id.rsplit("-", 1)[-1][:64]

def _record(episode_id, label, confidence, evidence):
    with ledger.conn() as c:
        c.execute("UPDATE episodes SET label=?, confidence=?, evidence=? WHERE episode_id=?",
                  (label, confidence, evidence, episode_id))
    runstate.label(episode_id, label, confidence, evidence)   # best-effort, see runstate

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
    lb = CFG.get("labeler") or {}
    client = anthropic.Anthropic(timeout=lb.get("request_timeout_seconds", 120), max_retries=2)
    model = CFG["models"]["labeler"]
    reqs = [{"custom_id": _custom_id(t["episode_id"]),
             "params": {"model": model, "max_tokens": 16000, "system": SYSTEM,
                        "messages": [{"role": "user", "content": _compact(t)}]}} for t in for_model]
    batch = client.messages.batches.create(requests=reqs)
    # Logged so that labels from a batch this night stopped waiting for can still be fetched with collect_batch.
    print(f"labeler: batch {batch.id}, {len(reqs)} requests", flush=True)
    if not _wait(client, batch.id, wait_seconds):
        return {**labels, **{e: "unclassified" for e in by_cid.values()}}
    return {**labels, **collect_batch(client, batch.id, by_cid, model)}

# Worth waiting out. Anything else (a bad key, a batch that does not exist) will not fix itself in a minute.
TRANSIENT = (anthropic.APIConnectionError, anthropic.InternalServerError, anthropic.RateLimitError)

def _wait(client, batch_id, wait_seconds, poll_seconds=60):
    """True once the batch has ended, False after wait_seconds. A failed status check is retried at the next
    poll. On 2026-09-18 a single DNS failure here ended labeling for the night while the batch itself was
    unaffected, and 2026-09-16 lost its tool-failure labels to the same error."""
    t0 = time.time()
    while True:
        try:
            if client.messages.batches.retrieve(batch_id).processing_status == "ended":
                return True
        except TRANSIENT as e:
            print(f"labeler: status check for {batch_id} failed, retrying: {e}", flush=True)
        if time.time() - t0 > wait_seconds:
            return False
        time.sleep(poll_seconds)

def collect_batch(client, batch_id, by_cid, model):
    """Record the labels in an ended batch. by_cid maps each request's custom_id back to its episode_id."""
    labels = {}
    for r in client.messages.batches.results(batch_id):
        episode_id = by_cid.get(r.custom_id, r.custom_id)
        lab, conf, ev = "unclassified", None, None
        if r.result.type == "succeeded":
            msg = r.result.message
            ledger.record_call(episode_id, model, msg.usage.model_dump())
            lab, conf, ev = read_label(msg)
        labels[episode_id] = lab
        # evidence is the part a reader actually wants: which turn went wrong and why.
        _record(episode_id, lab, conf, ev)
    return labels
