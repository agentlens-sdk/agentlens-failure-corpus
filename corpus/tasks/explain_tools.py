"""Why a failed tool-use episode failed, recomputed from its trace, for the failure labeler.

Tool calls against the mock APIs are deterministic, so replaying an episode's own calls on a fresh task
rebuilds its final state exactly. Diffing that against the reference solution's final state names what
the agent got wrong, the way explain_failure names a coding task's failing case. The reference is one
correct end state, not necessarily the only one, so the line says "differs from the reference".
"""
import json
from collections import Counter

FREE_TEXT = frozenset({"text", "resolution", "reason", "cancel_reason"})
MAX_LINES = 12


def _norm(x, parent=None):
    """Drop wording the checkers never compare, so the diff shows state, not phrasing."""
    if isinstance(x, dict):
        if parent == "resolved":
            return {k: "resolved" for k in x}
        out = {}
        for k, v in x.items():
            if k in FREE_TEXT or (k == "title" and parent == "tickets"):
                continue
            out[k] = v.strip().lower() if k == "title" and isinstance(v, str) else _norm(v, k)
        return out
    if isinstance(x, list):
        return [_norm(v, parent) for v in x]
    return x


def _key(x):
    return json.dumps(x, sort_keys=True, default=str)


def _diff(got, want, path, out):
    if isinstance(got, dict) and isinstance(want, dict):
        for k in sorted(set(got) | set(want), key=str):
            p = f"{path}.{k}" if path else str(k)
            if k not in got:
                out.append(f"{p}: missing (reference has {want[k]!r})")
            elif k not in want:
                out.append(f"{p}: unexpected {got[k]!r}")
            else:
                _diff(got[k], want[k], p, out)
    elif isinstance(got, list) and isinstance(want, list):
        # Order-insensitive, like the checkers, and only the entries that differ: a calendar day or a flight
        # list printed whole buries the one booking that is wrong.
        g, w = Counter(map(_key, got)), Counter(map(_key, want))
        extra, missing = list((g - w).elements()), list((w - g).elements())
        if extra or missing:
            parts = ([f"unexpected {', '.join(extra)}"] if extra else []) + ([f"missing {', '.join(missing)}"] if missing else [])
            out.append(f"{path}: " + "; ".join(parts))
    elif got != want:
        out.append(f"{path}: {got!r} (reference {want!r})")


def _replay(proto, steps):
    task, errors = proto.fresh(), []
    for name, args in steps:
        try:
            result = task.execute(name, args)
        except Exception as e:                                   # the runner reports these as tool errors too
            result = f"tool error: {e}"
        if str(result).startswith(("error", "unknown tool", "bad arguments", "tool error")):
            errors.append(f"{name}: {str(result)[:90]}")
    return task, errors


def explain_tool_failure(proto, trace):
    """One line naming how a failed episode's end state differs from the reference solution's."""
    steps = [(b["name"], b.get("input") or {}) for t in trace.get("turns", []) for b in t.get("assistant", [])
             if b.get("type") == "tool_use"]
    agent, errors = _replay(proto, steps)
    ref, _ = _replay(proto, proto.solution)
    if agent.check():
        return "replaying the agent's tool calls passes the checker, so the recorded failure did not reproduce"

    lines = []
    _diff(_norm(agent.db), _norm(ref.db), "", lines)
    got_to = sorted({str(i["user_id"]) for i in agent.did("send_message") if "user_id" in i})
    want_to = sorted({str(i["user_id"]) for i in ref.did("send_message") if "user_id" in i})
    if got_to != want_to:
        lines.append(f"messaged customers {got_to} (reference {want_to})")
    if ref.did("send_message") and not agent.did("send_message"):
        lines.append("never called send_message (the policy requires a final message)")
    if not lines:
        lines.append("end state matches the reference apart from wording, so a required amount, id or "
                     "phrase is missing from a message or note")

    text = (f"end state differs from the reference solution in {len(lines)} place(s): "
            + "; ".join(lines[:MAX_LINES]) + (f"; and {len(lines) - MAX_LINES} more" if len(lines) > MAX_LINES else ""))
    if errors:
        text += ". Tool errors the agent received: " + "; ".join(errors[:4])
    return text[:1500]
