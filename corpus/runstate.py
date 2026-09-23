"""Live run state for the watcher page. Best-effort, stdlib only, never raises into the harness.

The nightly log is a transcript of what happened; this is a statement of what is happening. The
scheduler and the runner call in here at run start, episode start and end, labeling and run end, and
two files appear under data/:

    runstate.jsonl  every event, newline-delimited, truncated at each run start so it cannot grow
    runstate.json   a compact snapshot of now, written to a temp file and os.replace()d, so a reader
                    polling it never sees half of one

`site/live.html` polls the snapshot. Nothing here is on the critical path of a run: every public
function is wrapped whole and a failure is dropped silently, because instrumentation that can break
a $10 unattended night is worse than no instrumentation at all.

Inert until run_start(): calibrate.py and the offline tests go through run_episode() too, and they
have no run to publish, so they write nothing.
"""
import json, os, threading, time
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
SNAPSHOT = DATA / "runstate.json"
EVENTS = DATA / "runstate.jsonl"

RECENT_EPISODES = 25        # the tail the page shows under OUTPUT
RECENT_FAILURES = 8         # failures kept with their checker evidence
RECENT_ERRORS = 8
MAX_PLAN_ROWS = 200         # the queue breakdown is for reading, not for completeness

_lock = threading.Lock()
_run = None                 # None until run_start(); every other call is then a no-op


def _guard(fn):
    """One lock, one try/except and one snapshot write per public call. The harness never sees a
    failure in here: a watcher going blind is not a reason to lose a night's episodes."""
    def wrapped(*args, **kwargs):
        try:
            with _lock:
                if _run is None and fn.__name__ != "run_start":
                    return
                fn(*args, **kwargs)
                _publish()
        except Exception:
            pass
    wrapped.__name__, wrapped.__doc__ = fn.__name__, fn.__doc__
    return wrapped


def _emit(kind, **fields):
    with EVENTS.open("a") as f:
        f.write(json.dumps({"ts": time.time(), "kind": kind, **fields}, default=str) + "\n")


def _publish():
    tmp = SNAPSHOT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(_snapshot(), default=str))
    os.replace(tmp, SNAPSHOT)   # atomic: the poller sees the old file or the new one, never a partial


def _tally(rows, key):
    out = {}
    for r in rows:
        out[r[key]] = out.get(r[key], 0) + 1
    return [{key: k, "n": v} for k, v in sorted(out.items(), key=lambda kv: (-kv[1], kv[0]))]


def _snapshot():
    r, now = _run, time.time()
    flight = [dict(e, elapsed=now - e["started"]) for e in
              sorted(r["in_flight"].values(), key=lambda e: e["started"])]
    done = r["finished"]
    return {
        "schema": "runstate/v1",
        "status": r["status"],                       # running | labeling | publishing | finished | stopped
        "updated": now,
        "run": {"date": r["date"], "started": r["started"], "ended": r["ended"],
                "budget_usd": r["budget_usd"], "deadline": r["deadline"], "queued": r["queued"],
                "models": r["models"], "families": r["families"], "plan": r["plan"],
                "note": r["note"], "summary": r["summary"]},
        "counts": {"queued": r["queued"], "started": r["started_count"], "finished": done,
                   "in_flight": len(flight), "outcomes": r["outcomes"],
                   "turns": r["turns"], "labeled": len(r["labels"])},
        "spend": {"usd": r["spend_usd"], "budget_usd": r["budget_usd"],
                  "elapsed": now - r["started"], "source": r["spend_source"]},
        "in_flight": flight,
        "recent": list(reversed(r["recent"])),       # newest first, the way the page reads it
        "failures": list(reversed(r["failures"])),
        "labels": _tally(list(r["labels"].values()), "label"),
        "errors": list(reversed(r["errors"])),
        "labeling": r["labeling"],
    }


@_guard
def run_start(date, budget_usd, plan, deadline):
    """plan: (family, task_id, model) per queued episode, in the order they will be submitted."""
    global _run
    plan = [tuple(p) for p in plan]
    rows = [{"family": f, "task_id": t, "model": m} for f, t, m in plan]
    _run = {
        "date": date, "started": time.time(), "ended": None, "status": "running",
        "budget_usd": budget_usd, "deadline": deadline, "queued": len(plan),
        "models": _tally(rows, "model"), "families": _tally(rows, "family"),
        "plan": _tally(rows, "task_id")[:MAX_PLAN_ROWS],
        "started_count": 0, "finished": 0, "outcomes": {}, "turns": 0,
        "spend_usd": 0.0, "spend_source": "episodes",
        "in_flight": {}, "recent": [], "failures": [], "errors": [], "labels": {},
        "labeling": None, "note": None, "summary": None,
    }
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    EVENTS.write_text("")       # one run per file: the tail of last night is not this night's state
    _emit("run_start", date=date, budget_usd=budget_usd, queued=len(plan), deadline=deadline)


@_guard
def episode_start(episode_id, family, task_id, model):
    _run["in_flight"][episode_id] = {"episode_id": episode_id, "family": family,
                                     "task_id": task_id, "model": model, "started": time.time()}
    _run["started_count"] += 1
    _emit("episode_start", episode_id=episode_id, family=family, task_id=task_id, model=model)


@_guard
def episode_turn(episode_id, turns):
    """Turn counter for an episode still in flight, so the page shows what a long episode is doing
    rather than only that it is still going. No jsonl line: one per turn would bury the run."""
    e = _run["in_flight"].get(episode_id)
    if e:
        e["turns"] = turns


@_guard
def episode_end(episode_id, outcome, turns, cost_usd, error=None):
    started = _run["in_flight"].pop(episode_id, {})
    row = {"episode_id": episode_id, "family": started.get("family"),
           "task_id": started.get("task_id"), "model": started.get("model"),
           "outcome": outcome, "turns": turns, "cost_usd": cost_usd, "ended": time.time(),
           "seconds": time.time() - started["started"] if started.get("started") else None,
           "error": error, "label": None, "evidence": None}
    _run["finished"] += 1
    _run["turns"] += turns or 0
    _run["outcomes"][outcome] = _run["outcomes"].get(outcome, 0) + 1
    if _run["spend_source"] == "episodes":
        _run["spend_usd"] += cost_usd or 0.0
    _run["recent"] = (_run["recent"] + [row])[-RECENT_EPISODES:]
    if outcome != "pass":
        _run["failures"] = (_run["failures"] + [row])[-RECENT_FAILURES:]
    if error:
        _run["errors"] = (_run["errors"] + [{"ts": row["ended"], "task_id": row["task_id"],
                                             "outcome": outcome, "error": error}])[-RECENT_ERRORS:]
    _emit("episode_end", episode_id=episode_id, outcome=outcome, turns=turns, cost_usd=cost_usd,
          error=error)


@_guard
def heartbeat(spent_usd=None, note=None):
    """Called from the submission loop. The ledger is the only real answer on spend, so once the
    scheduler passes it, episode costs stop being summed here."""
    if spent_usd is not None:
        _run["spend_usd"], _run["spend_source"] = spent_usd, "ledger"
    if note is not None:
        _run["note"] = note
    _emit("heartbeat", spent_usd=_run["spend_usd"], note=_run["note"])


@_guard
def labeling_start(n):
    _run["status"] = "labeling"
    _run["labeling"] = {"traces": n, "started": time.time(), "finished": None}
    _emit("labeling_start", traces=n)


@_guard
def label(episode_id, label, confidence=None, evidence=None):
    """One label, as it lands. Checker labels arrive first and carry their evidence verbatim; the
    batch-labeled ones follow when the batch returns."""
    _run["labels"][episode_id] = {"episode_id": episode_id, "label": label,
                                  "confidence": confidence, "evidence": evidence, "ts": time.time()}
    for row in _run["recent"] + _run["failures"]:
        if row["episode_id"] == episode_id:
            row["label"], row["evidence"] = label, evidence
    _emit("label", episode_id=episode_id, label=label, confidence=confidence, evidence=evidence)


@_guard
def labeling_end():
    if _run["labeling"]:
        _run["labeling"]["finished"] = time.time()
    _run["status"] = "publishing"
    _emit("labeling_end", labeled=len(_run["labels"]))


@_guard
def run_end(**summary):
    _run["status"] = "stopped" if summary.get("stopped") else "finished"
    _run["ended"] = time.time()
    _run["summary"] = summary
    _emit("run_end", **summary)
