"""Commit traces + stats to git; weekly parquet snapshot to HF. Failures here are cosmetic; data stays local."""
import datetime, json, subprocess
from pathlib import Path
from . import ledger
from .ledger import CFG

ROOT = Path(__file__).parent.parent
PUBLISHED = ("data/traces", "site/stats.json", "site/failures.json", "STOPPED")


def write_stats():
    s = ledger.stats()
    s["generated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    s["total_cap"] = CFG["budget"]["total_cap_usd"]
    stopped = ROOT / "STOPPED"
    s["stopped"] = stopped.read_text().strip() if stopped.exists() else None
    (ROOT / "site" / "stats.json").write_text(json.dumps(s, indent=1))
    write_failures()
    return s


def _task_prompts():
    """task_id -> prompt, so a reader can see what was actually asked."""
    from .tasks import load_family
    out = {}
    for fam in ("tools", "flakiness", "swebench"):
        try:
            for t in load_family(fam):
                out[t.task_id] = t.prompt
        except Exception:
            pass
    return out


def _compact_turns(trace, max_turns=14):
    """Turn-by-turn view: assistant text, the tool calls it made, and what came back."""
    turns = []
    for i, t in enumerate(trace.get("turns", [])[:max_turns]):
        text, calls = [], []
        results = {r.get("tool_use_id"): r.get("content") for r in t.get("tool_results", [])}
        for b in t.get("assistant", []):
            if b.get("type") == "text" and b.get("text", "").strip():
                text.append(b["text"][:600])
            elif b.get("type") == "tool_use":
                calls.append({"name": b.get("name"),
                              "input": json.dumps(b.get("input"), default=str)[:300],
                              "result": str(results.get(b.get("id"), ""))[:300]})
        turns.append({"i": i, "text": " ".join(text), "calls": calls})
    return turns


def write_failures(limit=40):
    """site/failures.json: the corpus is the traces, so the dashboard has to be able to show them.
    Pages serves only site/, so the relevant slice is copied here rather than linked into data/."""
    prompts = _task_prompts()
    rows = ledger.conn().execute(
        "SELECT episode_id, ts, family, task_id, outcome, turns, cost_usd, label, confidence, evidence, trace_path "
        "FROM episodes WHERE outcome!='pass' ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for (eid, ts, fam, task, outcome, turns, cost, label, conf, ev, path) in rows:
        item = {"episode_id": eid, "ts": ts, "family": fam, "task_id": task, "outcome": outcome,
                "turns": turns, "cost_usd": cost, "label": label, "confidence": conf,
                "evidence": ev, "prompt": prompts.get(task, ""), "trace": []}
        try:
            item["trace"] = _compact_turns(json.loads(Path(path).read_text()))
        except Exception:
            pass
        out.append(item)
    (ROOT / "site" / "failures.json").write_text(json.dumps(out, indent=1))
    return out


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def git_push(msg):
    """Stage whatever exists, commit, push. Returns True if the remote now has this commit.

    Paths are staged one at a time on purpose: `git add a b` stages *nothing* when b is missing,
    and STOPPED is missing on every healthy night.
    """
    staged = False
    for p in PUBLISHED:
        if (ROOT / p).exists() and _git("add", "--", p).returncode == 0:
            staged = True
    if not staged:
        return False

    c = _git("commit", "-qm", msg)
    if c.returncode and "nothing to commit" not in c.stdout + c.stderr:
        print("commit failed:", (c.stdout + c.stderr).strip()[:400])
        return False

    p = _git("push", "-q")
    if p.returncode and "no upstream branch" in (p.stdout + p.stderr):
        p = _git("push", "-q", "-u", "origin", "HEAD")
    if p.returncode:
        print("push failed:", (p.stdout + p.stderr).strip()[:400])
        return False
    return True


def hf_snapshot():
    repo = CFG["publish"]["hf_dataset"]
    if not repo:
        return
    import pyarrow as pa, pyarrow.parquet as pq
    from huggingface_hub import HfApi
    rows = [json.loads(p.read_text()) for p in (ROOT / "data" / "traces").rglob("*.json")]
    if not rows:
        return
    flat = [{k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in r.items()} for r in rows]
    # Traces carry optional keys (error, runaway_reason): pad to a single schema or pyarrow refuses.
    keys = sorted({k for r in flat for k in r})
    flat = [{k: r.get(k) for k in keys} for r in flat]
    out = ROOT / "data" / "traces.parquet"
    pq.write_table(pa.Table.from_pylist(flat), out)
    HfApi().upload_file(path_or_fileobj=str(out), path_in_repo="traces.parquet",
                        repo_id=repo, repo_type="dataset")
