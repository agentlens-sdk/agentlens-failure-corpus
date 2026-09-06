"""SQLite ledger: every API response's usage lands here. Single source of truth for spend."""
import sqlite3, time, yaml
from pathlib import Path

CFG = yaml.safe_load(open(Path(__file__).parent.parent / "config.yaml"))
DB = Path(__file__).parent.parent / "data" / "ledger.sqlite"

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

def conn():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, check_same_thread=False); c.executescript(SCHEMA); return c

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
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO episodes VALUES(:episode_id,:ts,:family,:task_id,:model,:turns,:outcome,:label,:cost_usd,:trace_path)", row)

def spent_total():
    return conn().execute("SELECT COALESCE(SUM(cost_usd),0) FROM calls").fetchone()[0]

def spent_since(ts):
    return conn().execute("SELECT COALESCE(SUM(cost_usd),0) FROM calls WHERE ts>=?", (ts,)).fetchone()[0]

def avg_cost(family):
    r = conn().execute("SELECT AVG(cost_usd), COUNT(*) FROM episodes WHERE family=?", (family,)).fetchone()
    return (r[0], r[1]) if r and r[1] else (None, 0)

def recent_nights(n):
    return conn().execute("SELECT * FROM nights ORDER BY date DESC LIMIT ?", (n,)).fetchall()

def record_night(date, **kw):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO nights VALUES(?,?,?,?,?,?)",
                  (date, kw["budget_usd"], kw["spent_usd"], kw["episodes"], kw["valid_traces"], kw["pushed"]))

def stats():
    c = conn()
    out = {"spent_total": round(spent_total(), 2), "episodes": c.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]}
    out["by_family"] = [dict(zip(["family", "n", "pass_rate", "avg_cost"], r)) for r in c.execute(
        "SELECT family, COUNT(*), AVG(outcome='pass'), AVG(cost_usd) FROM episodes GROUP BY family")]
    out["labels"] = [dict(zip(["label", "n"], r)) for r in c.execute(
        "SELECT COALESCE(label,'unclassified'), COUNT(*) FROM episodes WHERE outcome!='pass' GROUP BY 1 ORDER BY 2 DESC")]
    out["nightly"] = [dict(zip(["date", "budget", "spent", "episodes", "valid", "pushed"], r)) for r in c.execute(
        "SELECT * FROM nights ORDER BY date")]
    out["flakiness"] = [dict(zip(["week", "task_id", "pass_rate", "n"], r)) for r in c.execute(
        "SELECT strftime('%Y-%W', ts, 'unixepoch'), task_id, AVG(outcome='pass'), COUNT(*) "
        "FROM episodes WHERE family='flakiness' GROUP BY 1,2 ORDER BY 1")]
    return out
