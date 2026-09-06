"""AgentLens tracing for corpus episodes.

Emits an `agentlens/v1` envelope: one root `agent` span per episode, one `llm` span per turn,
one `tool` span per tool call, parented into a tree the AgentLens dashboard can render. IDs are
ULIDs (time-sortable), timestamps are ISO-8601 UTC, per AgentLens conventions.

There is no `agentlens` package on this box yet, so the format is produced directly. When the real
Python SDK lands, `_Span` maps 1:1 onto `agentlens.trace()` spans and only this file changes.

Nothing in here may raise into the agent loop: every public entry point is guarded. A dead or
absent AgentLens server costs one connect timeout and is otherwise invisible.
"""
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .ledger import CFG
from .redact import redact, redact_deep

_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford, ULID alphabet


def ulid(ts=None):
    """26-char ULID: 48-bit ms timestamp + 80 random bits. Lexicographic order == time order."""
    ms = int((time.time() if ts is None else ts) * 1000)
    n = int.from_bytes(ms.to_bytes(6, "big") + os.urandom(10), "big")
    return "".join(_B32[(n >> (5 * i)) & 31] for i in range(25, -1, -1))


def iso(ts):
    """ISO-8601 UTC with a Z suffix, which is what the AgentLens API expects."""
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


class _Span:
    """One node in the trace tree. Used as a context manager; exceptions mark it errored."""

    def __init__(self, trace_id, parent_id, name, kind, attributes=None):
        self.d = {
            "span_id": ulid(), "trace_id": trace_id, "parent_span_id": parent_id,
            "name": name, "type": kind, "status": "ok",
            "started_at": None, "ended_at": None, "duration_ms": None,
            "attributes": redact_deep(attributes or {}),
            "input": None, "output": None,
            "tokens": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0},
            "cost_usd": 0.0,
        }
        self._t0 = None

    # -- lifecycle -------------------------------------------------------
    def __enter__(self):
        self._t0 = time.time()
        self.d["started_at"] = iso(self._t0)
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is not None:
            self.d["status"] = "error"
            self.d["attributes"]["error"] = redact(f"{exc_type.__name__}: {exc}")[:2000]
        self.end()
        return False  # never swallow

    def end(self):
        if self.d["ended_at"] is not None:
            return
        t1 = time.time()
        self.d["ended_at"] = iso(t1)
        self.d["duration_ms"] = round((t1 - (self._t0 or t1)) * 1000, 3)

    # -- payload ---------------------------------------------------------
    def set_input(self, value):
        self.d["input"] = redact_deep(value)
        return self

    def set_output(self, value):
        self.d["output"] = redact_deep(value)
        return self

    def set_status(self, status):
        self.d["status"] = status
        return self

    def annotate(self, **kw):
        self.d["attributes"].update(redact_deep(kw))
        return self

    def record_usage(self, usage, cost_usd):
        self.d["tokens"] = {
            "input": usage.get("input_tokens") or 0,
            "output": usage.get("output_tokens") or 0,
            "cache_read": usage.get("cache_read_input_tokens") or 0,
            "cache_write": usage.get("cache_creation_input_tokens") or 0,
        }
        self.d["cost_usd"] = round(cost_usd, 6)
        return self


class EpisodeTrace:
    """Root of one episode. `.llm_span()` / `.tool_span()` open children; `.finish()` seals it."""

    def __init__(self, episode_id, family, task_id, model, prompt="", system=""):
        self.trace_id = ulid()
        self.episode_id = episode_id
        self._t0 = time.time()
        self.root = _Span(self.trace_id, None, f"episode:{family}/{task_id}", "agent", {
            "episode_id": episode_id, "family": family, "task_id": task_id,
            "model": model, "corpus": "agentlens-failure-corpus",
        })
        self.root.__enter__()
        self.root.set_input({"system": system, "prompt": prompt})
        self.spans = [self.root]
        self._turn_span = None

    def llm_span(self, index):
        """A model turn. Becomes the parent of that turn's tool calls."""
        s = _Span(self.trace_id, self.root.d["span_id"], f"turn {index}", "llm", {"turn": index})
        self.spans.append(s)
        self._turn_span = s
        return s

    def tool_span(self, name, tool_input, turn=None):
        parent = self._turn_span.d["span_id"] if self._turn_span else self.root.d["span_id"]
        s = _Span(self.trace_id, parent, name, "tool", {"tool": name, "turn": turn})
        s.set_input(tool_input)
        self.spans.append(s)
        return s

    def finish(self, outcome, cost_usd, error=None):
        """Close every open span and return the agentlens/v1 envelope."""
        self.root.annotate(outcome=outcome)
        if error:
            self.root.d["attributes"]["error"] = redact(str(error))[:2000]
        self.root.set_status("ok" if outcome == "pass" else "error")
        self.root.set_output({"outcome": outcome})
        for s in self.spans:
            s.end()
        t1 = time.time()
        tok = {k: sum(s.d["tokens"][k] for s in self.spans) for k in ("input", "output", "cache_read", "cache_write")}
        return {
            "format": "agentlens/v1",
            "trace_id": self.trace_id,
            "name": self.root.d["name"],
            "started_at": iso(self._t0),
            "ended_at": iso(t1),
            "duration_ms": round((t1 - self._t0) * 1000, 3),
            "status": self.root.d["status"],
            "attributes": dict(self.root.d["attributes"]),
            "cost_usd": round(cost_usd, 6),
            "tokens": tok,
            "spans": [s.d for s in self.spans],
        }


def export(envelope):
    """Fire-and-forget POST to a locally running AgentLens server. Always returns a bool, never raises."""
    cfg = CFG.get("agentlens") or {}
    if not cfg.get("enabled"):
        return False
    try:
        body = json.dumps(envelope, default=str).encode()
        req = urllib.request.Request(
            cfg.get("endpoint", "http://localhost:8766/api/v1/traces"),
            data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=cfg.get("timeout_seconds", 2)) as r:
            return 200 <= r.status < 300
    except (urllib.error.URLError, OSError, ValueError, TypeError):
        return False   # server absent or unhappy: the local trace file is still authoritative
    except Exception:
        return False
