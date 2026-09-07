"""Nightly entrypoint. Computes tonight's budget, runs episodes, labels, publishes. Fails toward NOT spending."""
import datetime, time, random, sys, traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from . import ledger, labeler, publisher
from .ledger import CFG
from .runner import run_episode, Terminal
from .tasks import load_family

ROOT = Path(__file__).parent.parent
STOP = ROOT / "STOPPED"
DEFAULT_UNIT = {"swebench": 0.70, "tools": 0.30, "flakiness": 0.06}   # USD/episode until 10 observed

def stop(reason):
    STOP.write_text(f"{datetime.datetime.now(datetime.timezone.utc).isoformat()} {reason}\n")
    publisher.write_stats(); publisher.git_push(f"STOPPED: {reason}")
    print("STOPPED:", reason); sys.exit(0)

def tonight_budget():
    b = CFG["budget"]; spent = ledger.spent_total()
    days_left = max(1, (datetime.date.fromisoformat(b["end_date"]) - datetime.date.today()).days)
    remaining = b["total_cap_usd"] - spent
    if remaining <= 0: stop("total cap reached")
    return min(b["daily_cap_usd"], remaining / days_left * 1.1)

def deadman_check():
    d = CFG["deadman"]; nights = ledger.recent_nights(max(d["zero_trace_nights"], d["failed_push_nights"]))
    if len(nights) >= d["zero_trace_nights"] and all(n[4] == 0 for n in nights[:d["zero_trace_nights"]]):
        stop("zero valid traces for consecutive nights")
    if len(nights) >= d["failed_push_nights"] and all(n[5] == 0 for n in nights[:d["failed_push_nights"]]):
        stop("push failed for consecutive nights")

def plan(budget):
    """Fill budget by family weight using observed avg cost. Flakiness repeats absorb slack."""
    fams = {k: v for k, v in CFG["families"].items() if v["enabled"]}
    wsum = sum(v["weight"] for v in fams.values()); queue = []
    for name, f in fams.items():
        tasks = load_family(name)
        if not tasks: continue
        avg, n = ledger.avg_cost(name); unit = avg if n >= 10 else DEFAULT_UNIT.get(name, 0.30)
        count = max(1, int(budget * f["weight"] / wsum / max(unit, 0.01)))
        if name == "flakiness":
            reps = max(f.get("repeats", 1), count // len(tasks))
            queue += [t for t in tasks for _ in range(reps)]
        else:
            queue += [random.choice(tasks) for _ in range(count)]
    random.shuffle(queue); return queue

def main():
    if STOP.exists(): print("STOPPED flag present, exiting"); return
    deadman_check()
    budget = tonight_budget()
    if budget < CFG["budget"]["min_nightly_usd"]: print("budget too small, exiting"); return
    date = datetime.date.today().isoformat(); t0 = time.time(); traces = []
    # A night that stalls must not eat the following nights: run_nightly.sh holds a lock, so an
    # overrunning run blocks its successors. Spend is capped by budget; this caps wall clock.
    deadline = t0 + CFG["budget"].get("nightly_deadline_seconds", 18000)
    queue = plan(budget)
    print(f"{date}: budget ${budget:.2f}, {len(queue)} episodes planned")

    def collect(batch):
        """One bad episode must not abandon the rest of the night."""
        for f in batch:
            try: traces.append(f.result())
            except Terminal: raise
            except Exception: traceback.print_exc()

    try:
        with ThreadPoolExecutor(CFG["episode"]["concurrency"]) as ex:
            batch = []
            for task in queue:
                if ledger.spent_since(t0) >= budget: break
                if time.time() > deadline:
                    print("nightly deadline reached, stopping submission"); break
                batch.append(ex.submit(run_episode, task))
                if len(batch) >= CFG["episode"]["concurrency"]:
                    collect(batch); batch = []
            collect(batch)
    except Terminal as e:
        stop(f"terminal API error: {e}")
    except Exception:
        traceback.print_exc()
    try: labeler.label_traces(traces)
    except Exception: traceback.print_exc()
    # Record the night BEFORE writing stats, or the dashboard's nightly-spend chart is always one
    # night behind. record_night is INSERT OR REPLACE on date, so the second call just fixes `pushed`.
    valid = sum(1 for t in traces if t["outcome"] in ("pass", "fail", "runaway"))
    night = dict(budget_usd=budget, spent_usd=ledger.spent_since(t0), episodes=len(traces),
                 valid_traces=valid)
    ledger.record_night(date, pushed=0, **night)
    publisher.write_stats()
    pushed = publisher.git_push(f"nightly {date}: {len(traces)} episodes")
    ledger.record_night(date, pushed=int(pushed), **night)
    if datetime.date.today().weekday() == 6:
        try: publisher.hf_snapshot()
        except Exception: traceback.print_exc()
    print(f"done: spent ${ledger.spent_since(t0):.2f}, {valid} valid traces, pushed={pushed}")

if __name__ == "__main__": main()
