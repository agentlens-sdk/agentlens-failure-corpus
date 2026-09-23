"""Nightly entrypoint. Computes tonight's budget, runs episodes, labels, publishes. Fails toward NOT spending."""
import datetime, time, random, sys, traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from . import ledger, labeler, publisher, runstate
from .ledger import CFG
from .runner import run_episode, Terminal
from .tasks import load_family

ROOT = Path(__file__).parent.parent
STOP = ROOT / "STOPPED"
DEFAULT_UNIT = {"swebench": 0.70, "tools": 0.30, "flakiness": 0.06}   # USD/episode until 10 observed

# Block-buffered stdout made the 2026-09-16 log unreadable: every line landed at process exit, so it
# sat out of order against the unbuffered stderr tracebacks, and a 17h night could not be told from a
# 2h one. Line buffering here covers both entry points — run_nightly.sh and a hand-run
# `python -m corpus.scheduler` — and it fixes the prints in labeler and publisher too.
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(line_buffering=True)
    except AttributeError: pass                  # not a TextIOWrapper (test capture, some pipe wrappers)

def log(*args):
    """Timestamped and flushed. A night is read days later, and the ordering of its log is the only
    evidence of what happened when."""
    print(datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), *args, flush=True)

def log_exc(what):
    """A bare traceback carries no time and no context, which is nearly useless inside a 5h log."""
    log(f"{what}:")
    traceback.print_exc()
    sys.stderr.flush()

def stop(reason):
    STOP.write_text(f"{datetime.datetime.now(datetime.timezone.utc).isoformat()} {reason}\n")
    publisher.write_stats(); publisher.git_push(f"STOPPED: {reason}")
    runstate.run_end(stopped=reason)
    log("STOPPED:", reason); sys.exit(0)

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
    """Fill budget by family weight using observed avg cost. Flakiness repeats absorb slack.
    Each pick runs once per model in models.agents, kept adjacent so a budget cutoff splits at most one
    pair. Tasks listed under a family's `retired` are skipped: no model fails them. Returns (task, model)."""
    models = CFG["models"].get("agents") or [CFG["models"]["agent"]]
    fams = {k: v for k, v in CFG["families"].items() if v["enabled"]}
    wsum = sum(v["weight"] for v in fams.values()); picks = []
    for name, f in fams.items():
        retired = set(f.get("retired") or [])
        tasks = [t for t in load_family(name) if t.task_id not in retired]
        if not tasks: continue
        unit = 0.0                                  # cost of one pick = one episode on every model
        for m in models:
            avg, n = ledger.avg_cost(name, m, [t.task_id for t in tasks])
            unit += avg if n >= 10 else DEFAULT_UNIT.get(name, 0.30)
        count = max(1, int(budget * f["weight"] / wsum / max(unit, 0.01)))
        if name == "flakiness":
            reps = max(f.get("repeats", 1), count // len(tasks))
            picks += [t for t in tasks for _ in range(reps)]
        else:
            picks += [random.choice(tasks) for _ in range(count)]
        # Control tier: a few retired (saturated) tasks, queued on purpose. Retirement selects the active
        # set for tasks whose pass rates sit away from the extremes, which is where a repeated task produces
        # mixed results anyway, so without a control the within-night variation cannot be told apart from
        # that selection. Each control task is queued control_repeats times so its cell can be mixed at all.
        n_ctl, reps_ctl = f.get("control_sample", 0), f.get("control_repeats", 3)
        if n_ctl and retired:
            pool = [t for t in load_family(name) if t.task_id in retired]
            picks += [t for t in random.sample(pool, min(n_ctl, len(pool))) for _ in range(reps_ctl)]
    random.shuffle(picks); return [(t, m) for t in picks for m in models]

def main():
    if STOP.exists(): log("STOPPED flag present, exiting"); return
    deadman_check()
    budget = tonight_budget()
    if budget < CFG["budget"]["min_nightly_usd"]: log("budget too small, exiting"); return
    date = datetime.date.today().isoformat(); t0 = time.time(); traces = []
    # A night that stalls must not eat the following nights: run_nightly.sh holds a lock, so an
    # overrunning run blocks its successors. Spend is capped by budget; this caps wall clock.
    deadline = t0 + CFG["budget"].get("nightly_deadline_seconds", 18000)
    queue = plan(budget)
    # The deadline is logged as a clock time so a later "deadline reached" line can be checked against it.
    log(f"{date}: budget ${budget:.2f}, {len(queue)} episodes planned, deadline "
        f"{datetime.datetime.fromtimestamp(deadline, datetime.timezone.utc).strftime('%H:%M:%SZ')}")
    # Same three facts, published for the live watcher (site/live.html). Best-effort throughout.
    runstate.run_start(date, budget, [(t.family, t.task_id, m) for t, m in queue], deadline)

    # The deadline above is only tested between submissions, so an episode that never returns used to
    # hold the loop past it indefinitely. Bound the wait: the episode's own caps plus a little slack.
    ep_cap = CFG["episode"]["wall_clock_seconds"] + CFG["episode"]["request_timeout_seconds"] + 120

    last_beat = t0

    def collect(batch):
        """One bad episode must not abandon the rest of the night."""
        nonlocal last_beat
        for f in batch:
            try: traces.append(f.result(timeout=ep_cap))
            except Terminal: raise
            except FutureTimeout: log(f"episode still running after {ep_cap}s, abandoning it")
            except Exception: log_exc("episode failed")
        runstate.heartbeat(spent_usd=ledger.spent_since(t0))
        # A heartbeat, so a stalling night is visible while it stalls rather than reconstructed from
        # the ledger afterwards: 2026-09-16 logged nothing between its first line and its last.
        if time.time() - last_beat >= 300:
            last_beat = time.time()
            log(f"{len(traces)}/{len(queue)} episodes, ${ledger.spent_since(t0):.2f} of ${budget:.2f}, "
                f"{(deadline - time.time()) / 60:.0f} min to deadline")

    ex = ThreadPoolExecutor(CFG["episode"]["concurrency"])
    try:
        batch = []
        reason = "queue exhausted"
        for task, model in queue:
            if ledger.spent_since(t0) >= budget: reason = "budget reached"; break
            if time.time() > deadline: reason = "deadline reached"; break
            batch.append(ex.submit(run_episode, task, model))
            if len(batch) >= CFG["episode"]["concurrency"]:
                collect(batch); batch = []
        collect(batch)
        # Which of the three ended submission went unrecorded, so 2026-09-16 could not be explained.
        log(f"submission stopped: {reason}")
        runstate.heartbeat(spent_usd=ledger.spent_since(t0), note=f"submission stopped: {reason}")
    except Terminal as e:
        stop(f"terminal API error: {e}")
    except Exception:
        log_exc("submission loop failed")
    finally:
        # wait=False: a thread wedged in a socket read must not block process exit either.
        ex.shutdown(wait=False, cancel_futures=True)
    # Bracketed on both sides: the labeler polls its batch for up to 2h, which is long enough to look
    # like a hang, and on 2026-09-16 there was no way to tell that from the log.
    log(f"labeling {len(traces)} traces")
    runstate.labeling_start(len(traces))
    try: labeler.label_traces(traces)
    except Exception: log_exc("labeling failed")
    log("labeling finished")
    runstate.labeling_end()
    # Record the night BEFORE writing stats, or the dashboard's nightly-spend chart is always one
    # night behind. record_night is INSERT OR REPLACE on date, so the second call just fixes `pushed`.
    valid = sum(1 for t in traces if t["outcome"] in ("pass", "fail", "runaway"))
    # A second run on the same date adds to that date's row; record_night alone would overwrite it.
    prior = ledger.night(date)
    night = dict(budget_usd=prior["budget_usd"] + budget, spent_usd=prior["spent_usd"] + ledger.spent_since(t0),
                 episodes=prior["episodes"] + len(traces), valid_traces=prior["valid_traces"] + valid)
    ledger.record_night(date, pushed=0, **night)
    publisher.write_stats()
    log("publishing")
    pushed = publisher.git_push(f"nightly {date}: {len(traces)} episodes")
    ledger.record_night(date, pushed=int(pushed), **night)
    if datetime.date.today().weekday() == 6:
        try: publisher.hf_snapshot()
        except Exception: log_exc("hf snapshot failed")
    # The elapsed hours are on the done: line because a 17h night and a 2h one otherwise look identical.
    log(f"done: spent ${ledger.spent_since(t0):.2f}, {valid} valid traces, pushed={pushed}, "
        f"ran {(time.time() - t0) / 3600:.2f}h")
    runstate.run_end(spent_usd=ledger.spent_since(t0), episodes=len(traces), valid_traces=valid,
                     pushed=int(pushed), seconds=time.time() - t0)

if __name__ == "__main__": main()
