"""SQLite ledger: every API response's usage lands here. Single source of truth for spend."""
import sqlite3, time, yaml
from pathlib import Path

CFG = yaml.safe_load(open(Path(__file__).parent.parent / "config.yaml"))
DB = Path(__file__).parent.parent / "data" / "ledger.sqlite"
# Stamped on every episode: "nightly" (the scheduler), "calibration" (calibrate.py), or "aborted" (backfilled
# for the 2026-09-13 run that was stopped by hand). Pass rates in stats() count nightly episodes only:
# calibration runs every task, including retired ones, and would skew the per-model comparison.
RUN_KIND = "nightly"
NIGHTLY = "COALESCE(run_kind, 'nightly') = 'nightly'"

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls(
  ts REAL, episode_id TEXT, model TEXT,
  input_tokens INT, output_tokens INT, cache_read INT, cache_write INT, cost_usd REAL);
CREATE TABLE IF NOT EXISTS episodes(
  episode_id TEXT PRIMARY KEY, ts REAL, family TEXT, task_id TEXT, model TEXT,
  turns INT, outcome TEXT, label TEXT, cost_usd REAL, trace_path TEXT);
CREATE TABLE IF NOT EXISTS nights(
  date TEXT PRIMARY KEY, budget_usd REAL, spent_usd REAL, episodes INT, valid_traces INT, pushed INT);
"""

def _migrate(c):
    """Columns added after the first nights ran. Idempotent, so an existing ledger just gains them."""
    cols = {r[1] for r in c.execute("PRAGMA table_info(episodes)")}
    for name, decl in (("confidence", "REAL"), ("evidence", "TEXT"), ("run_kind", "TEXT")):
        if name not in cols:
            c.execute(f"ALTER TABLE episodes ADD COLUMN {name} {decl}")

def conn():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, check_same_thread=False); c.executescript(SCHEMA); _migrate(c); return c

def price(model, usage):
    p = CFG["prices"][model]
    return (usage.get("input_tokens", 0) * p["input"]
            + usage.get("output_tokens", 0) * p["output"]
            + (usage.get("cache_read_input_tokens") or 0) * p["cache_read"]
            + (usage.get("cache_creation_input_tokens") or 0) * p["cache_write"]) / 1e6

def record_call(episode_id, model, usage):
    cost = price(model, usage)
    with conn() as c:
        c.execute("INSERT INTO calls VALUES(?,?,?,?,?,?,?,?)",
                  (time.time(), episode_id, model, usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                   usage.get("cache_read_input_tokens") or 0, usage.get("cache_creation_input_tokens") or 0, cost))
    return cost

def record_episode(**row):
    row.setdefault("run_kind", RUN_KIND)
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO episodes"
                  "(episode_id,ts,family,task_id,model,turns,outcome,label,cost_usd,trace_path,run_kind)"
                  " VALUES(:episode_id,:ts,:family,:task_id,:model,:turns,:outcome,:label,:cost_usd,:trace_path,:run_kind)", row)

def spent_total():
    return conn().execute("SELECT COALESCE(SUM(cost_usd),0) FROM calls").fetchone()[0]

def spent_since(ts):
    return conn().execute("SELECT COALESCE(SUM(cost_usd),0) FROM calls WHERE ts>=?", (ts,)).fetchone()[0]

def avg_cost(family, model=None, task_ids=None):
    """Mean episode cost, optionally for one model and a task subset (retired tasks are often far cheaper)."""
    q, args = "SELECT AVG(cost_usd), COUNT(*) FROM episodes WHERE family=?", [family]
    if model:
        q += " AND model=?"; args.append(model)
    if task_ids:
        q += f" AND task_id IN ({','.join('?' * len(task_ids))})"; args += list(task_ids)
    r = conn().execute(q, args).fetchone()
    return (r[0], r[1]) if r and r[1] else (None, 0)

def recent_nights(n):
    return conn().execute("SELECT * FROM nights ORDER BY date DESC LIMIT ?", (n,)).fetchall()

def night(date):
    """Totals already recorded for a date, so a second run the same day adds to them instead of replacing them."""
    r = conn().execute("SELECT budget_usd, spent_usd, episodes, valid_traces FROM nights WHERE date=?", (date,)).fetchone()
    return dict(zip(["budget_usd", "spent_usd", "episodes", "valid_traces"], r or (0, 0, 0, 0)))

def record_night(date, **kw):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO nights VALUES(?,?,?,?,?,?)",
                  (date, kw["budget_usd"], kw["spent_usd"], kw["episodes"], kw["valid_traces"], kw["pushed"]))

def stats():
    """Dashboard numbers. Episode and spend totals cover everything; pass rates and labels count nightly runs only."""
    c = conn()
    out = {"spent_total": round(spent_total(), 2), "episodes": c.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]}
    out["by_run_kind"] = [dict(zip(["run_kind", "n"], r)) for r in c.execute(
        "SELECT COALESCE(run_kind, 'nightly'), COUNT(*) FROM episodes GROUP BY 1 ORDER BY 1")]
    out["by_family"] = [dict(zip(["family", "n", "pass_rate", "avg_cost"], r)) for r in c.execute(
        f"SELECT family, COUNT(*), AVG(outcome='pass'), AVG(cost_usd) FROM episodes WHERE {NIGHTLY} GROUP BY family")]
    out["labels"] = [dict(zip(["label", "n"], r)) for r in c.execute(
        f"SELECT COALESCE(label,'unclassified'), COUNT(*) FROM episodes WHERE outcome!='pass' AND {NIGHTLY} "
        "GROUP BY 1 ORDER BY 2 DESC")]
    out["nightly"] = [dict(zip(["date", "budget", "spent", "episodes", "valid", "pushed"], r)) for r in c.execute(
        "SELECT * FROM nights ORDER BY date")]
    out["tasks"] = [dict(zip(["task_id", "family", "n", "pass_rate", "avg_turns", "avg_cost"], r)) for r in c.execute(
        f"SELECT task_id, family, COUNT(*), AVG(outcome='pass'), AVG(turns), AVG(cost_usd) "
        f"FROM episodes WHERE {NIGHTLY} GROUP BY task_id ORDER BY 4 ASC, 3 DESC")]
    out["task_count"] = len(out["tasks"])
    out["flakiness"] = [dict(zip(["week", "task_id", "pass_rate", "n"], r)) for r in c.execute(
        f"SELECT strftime('%Y-%W', ts, 'unixepoch'), task_id, AVG(outcome='pass'), COUNT(*) "
        f"FROM episodes WHERE family='flakiness' AND {NIGHTLY} GROUP BY 1,2 ORDER BY 1")]
    # Per-model views: the keys above blend every agent model together.
    out["by_model"] = [dict(zip(["model", "family", "n", "pass_rate", "avg_cost"], r)) for r in c.execute(
        f"SELECT model, family, COUNT(*), AVG(outcome='pass'), AVG(cost_usd) FROM episodes WHERE {NIGHTLY} "
        "GROUP BY 1, 2 ORDER BY 1, 2")]
    out["tasks_by_model"] = [dict(zip(["task_id", "model", "n", "pass_rate"], r)) for r in c.execute(
        f"SELECT task_id, model, COUNT(*), AVG(outcome='pass') FROM episodes WHERE {NIGHTLY} "
        "GROUP BY 1, 2 ORDER BY 1, 2")]
    return out
