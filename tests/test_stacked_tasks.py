"""Offline proof that the stacked tiers are hard for the right reasons: no API, no spend.

Same contract as test_hard_tasks.py, for family_tools_stack.py and family_flakiness_stack.py:
  1. coding: every expected value in `cases` matches an oracle written independently of the reference
     answer, the answer agrees with that oracle on random inputs, and a plausible wrong submission fails;
  2. tools: the reference solution passes, an untouched task fails, and the solution with the one
     interaction the task is built on done wrong also fails.

Run: python tests/test_stacked_tasks.py
"""
import calendar
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corpus.tasks import family_flakiness_stack as FS   # noqa: E402
from corpus.tasks import family_tools_stack as TS       # noqa: E402
from corpus.tasks.family_flakiness import run_cases      # noqa: E402

RNG = random.Random(20260914)
RANDOM_TRIALS = 300


def _load(src, name):
    ns = {}
    exec(src, ns)
    return ns[name]


# ======================================================================
# Independent oracles
# ======================================================================
def book_oracle(orders):
    resting, trades = [], []
    for t, o in enumerate(orders):
        if o[0] == "cancel":
            resting = [r for r in resting if r["id"] != o[1]]
            continue
        typ, oid, side = o[0], o[1], o[2]
        price, qty = (None, o[3]) if typ == "market" else (o[3], o[4])
        while qty:
            def crosses(r):
                if r["side"] == side:
                    return False
                if price is None:
                    return True
                return r["price"] <= price if side == "buy" else r["price"] >= price
            opp = sorted(filter(crosses, resting),
                         key=lambda r: (r["price"] if side == "buy" else -r["price"], r["t"]))
            if not opp:
                break
            r = opp[0]
            q = min(qty, r["qty"])
            trades.append([oid, r["id"], r["price"], q] if side == "buy" else [r["id"], oid, r["price"], q])
            qty -= q
            r["qty"] -= q
            if not r["qty"]:
                resting.remove(r)
        if typ == "limit" and qty:
            resting.append({"id": oid, "side": side, "price": price, "qty": qty, "t": t})
    return trades


def recurrence_oracle(start, freq, interval, count, until, byweekday, exdates):
    d0 = date.fromisoformat(start)
    end = date.fromisoformat(until) if until else d0 + timedelta(days=4000)
    days = set(byweekday) if byweekday is not None else {d0.weekday()}
    out, d = [], d0
    while d <= end and (count is None or len(out) < count):
        if freq == "daily":
            hit = (d - d0).days % interval == 0
        elif freq == "weekly":
            hit = ((d - d0).days + d0.weekday()) // 7 % interval == 0 and d.weekday() in days
        else:
            hit = ((d.year - d0.year) * 12 + d.month - d0.month) % interval == 0 and d.day == d0.day
        if hit:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return [x for x in out if x not in set(exdates)]


def admit_oracle(requests, capacity, refill_every, window, window_max):
    tokens, ticks, admitted, out = {}, {}, [], []
    for t, client, cost in requests:
        tokens.setdefault(client, capacity)
        ticks.setdefault(client, 0)
        while ticks[client] < t // refill_every:
            ticks[client] += 1
            tokens[client] = min(capacity, tokens[client] + 1)
        ok = tokens[client] >= cost and len([a for a in admitted if a > t - window]) < window_max
        if ok:
            tokens[client] -= cost
            admitted.append(t)
        out.append(ok)
    return out


def resolve_oracle(path, cwd, links):
    todo = path.split("/")[::-1]
    cur = [] if path.startswith("/") else [c for c in cwd.split("/") if c]
    hops = 0
    while todo:
        c = todo.pop()
        if c in ("", "."):
            continue
        if c == "..":
            if cur:
                cur.pop()
            continue
        full = "/" + "/".join(cur + [c])
        if full not in links:
            cur.append(c)
            continue
        hops += 1
        if hops > 8:
            return None
        target = links[full]
        if target.startswith("/"):
            cur = []
        todo.extend(target.split("/")[::-1])
    return "/" + "/".join(cur)


# ======================================================================
# Random inputs
# ======================================================================
def g_book():
    ops, ids = [], []
    for i in range(RNG.randint(0, 12)):
        r = RNG.random()
        if r < 0.15 and ids:
            ops.append(["cancel", RNG.choice(ids + ["nope"])])
            continue
        oid, side, qty = f"o{i}", RNG.choice(["buy", "sell"]), RNG.randint(1, 4)
        ids.append(oid)
        if r < 0.3:
            ops.append(["market", oid, side, qty])
        elif r < 0.45:
            ops.append(["ioc", oid, side, RNG.randint(1, 5), qty])
        else:
            ops.append(["limit", oid, side, RNG.randint(1, 5), qty])
    return (ops,)


def g_recurrence():
    y, m = RNG.randint(2024, 2027), RNG.randint(1, 12)
    d0 = date(y, m, RNG.randint(1, calendar.monthrange(y, m)[1]))
    freq = RNG.choice(["daily", "weekly", "monthly"])
    count = RNG.choice([None, RNG.randint(1, 8)])
    until = None if count is not None and RNG.random() < 0.5 else (d0 + timedelta(days=RNG.randint(0, 400))).isoformat()
    byweekday = RNG.choices(range(7), k=RNG.randint(1, 3)) if freq == "weekly" and RNG.random() < 0.6 else None
    exdates = [(d0 + timedelta(days=RNG.randint(0, 60))).isoformat() for _ in range(RNG.randint(0, 3))]
    return (d0.isoformat(), freq, RNG.randint(1, 3), count, until, byweekday, exdates)


def g_admit():
    t, reqs = 0, []
    for _ in range(RNG.randint(0, 12)):
        t += RNG.randint(0, 3)
        reqs.append([t, RNG.choice("abc"), RNG.randint(1, 3)])
    return (reqs, RNG.randint(1, 4), RNG.randint(1, 4), RNG.randint(1, 6), RNG.randint(1, 4))


def g_resolve():
    names = ["a", "b", "c"]
    def absolute(depth):
        return "/" + "/".join(RNG.choice(names) for _ in range(depth))
    links = {absolute(RNG.randint(1, 2)): RNG.choice(["/a", "b", "..", "/a/b", "c/..", ".", "/", "../c", "a/b"])
             for _ in range(RNG.randint(0, 4))}
    comps = [RNG.choice(names + ["..", ".", ""]) for _ in range(RNG.randint(0, 5))]
    path = ("/" if RNG.random() < 0.5 else "") + "/".join(comps)
    return (path, absolute(RNG.randint(0, 2)), links)


ORACLES = {
    "stack_order_book": (book_oracle, g_book),
    "stack_recurrence": (recurrence_oracle, g_recurrence),
    "stack_rate_limiter": (admit_oracle, g_admit),
    "stack_resolve_path": (resolve_oracle, g_resolve),
}

# ======================================================================
# Plausible wrong submissions: each must FAIL its task's cases
# ======================================================================
WRONG_CODE = {
    # Trades at the incoming order's price instead of the resting order's.
    "stack_order_book": FS.OrderBook.answer.replace(
        "[oid, best[1], best[2], q] if side", "[oid, best[1], price or best[2], q] if side"
    ).replace("[best[1], oid, best[2], q]", "[best[1], oid, price or best[2], q]"),
    # Moves a missing month-day to the month's last day instead of skipping it.
    "stack_recurrence": """
import calendar
from datetime import date, timedelta
def occurrences(start, freq, interval, count, until, byweekday, exdates):
    d0 = date.fromisoformat(start)
    end = date.fromisoformat(until) if until else None
    out, k = [], 0
    while True:
        if freq == "daily":
            ds = [d0 + timedelta(days=k * interval)]
        elif freq == "weekly":
            days = sorted(set(byweekday)) if byweekday is not None else [d0.weekday()]
            week = d0 - timedelta(days=d0.weekday()) + timedelta(weeks=k * interval)
            ds = [week + timedelta(days=wd) for wd in days if week + timedelta(days=wd) >= d0]
        else:
            m = d0.month - 1 + k * interval
            y, mo = d0.year + m // 12, m % 12 + 1
            ds = [date(y, mo, min(d0.day, calendar.monthrange(y, mo)[1]))]
        for d in ds:
            if (end and d > end) or (count is not None and len(out) >= count):
                return [x for x in out if x not in set(exdates)]
            out.append(d.isoformat())
        k += 1
""",
    # Takes the tokens even when the global window rejects the request.
    "stack_rate_limiter": """
def admit(requests, capacity, refill_every, window, window_max):
    buckets, admitted, out = {}, [], []
    for t, client, cost in requests:
        tick = t // refill_every
        tokens, last = buckets.get(client, (capacity, 0))
        tokens = min(capacity, tokens + tick - last)
        ok = tokens >= cost and sum(1 for a in admitted if a > t - window) < window_max
        if tokens >= cost:
            tokens -= cost
        if ok:
            admitted.append(t)
        buckets[client] = (tokens, tick)
        out.append(ok)
    return out
""",
    # Normalizes lexically first, so '..' after a symlink goes to the link's parent.
    "stack_resolve_path": """
import posixpath
def resolve(path, cwd, links):
    p = posixpath.normpath(posixpath.join(cwd, path))
    for _ in range(9):
        if p not in links:
            return p
        p = posixpath.normpath(posixpath.join(posixpath.dirname(p), links[p]))
    return None
""",
}


# ======================================================================
# Tool tasks: the solution with its central interaction done wrong
# ======================================================================
def _swap(solution, pairs):
    """The reference solution with each (old_step, new_step) replaced; every old step must exist."""
    out = list(solution)
    for old, new in pairs:
        i = out.index(old)
        out[i] = new
    return out


WRONG_SWAPS = {
    # Works tickets in list order, so TK-4's O-7102 takes the last sage duvet.
    "retail_stack_ticket_queue": [
        (("exchange_line", {"order_id": "O-7303", "sku": "SKU-201", "new_sku": "SKU-202"}),
         ("exchange_line", {"order_id": "O-7102", "sku": "SKU-201", "new_sku": "SKU-202"}))],
    # Refunds both plates on O-7106, ignoring the one already refunded.
    "retail_stack_flaky_backend": [
        (("refund_line", {"order_id": "O-7106", "sku": "SKU-102", "qty": 1}),
         ("refund_line", {"order_id": "O-7106", "sku": "SKU-102", "qty": 2}))],
    # Rebooks in reservation order instead of gold first.
    "air_stack_disruption": [
        (("change_flight", {"reservation_id": "R-3005", "flight": "AL712"}),
         ("change_flight", {"reservation_id": "R-3002", "flight": "AL712"})),
        (("change_flight", {"reservation_id": "R-3002", "flight": "AL706"}),
         ("change_flight", {"reservation_id": "R-3005", "flight": "AL706"}))],
    # Trusts list_incidents severities: pages INC-24, tickets INC-27.
    "ops_stack_night_shift": [
        (("create_ticket", {"service": "search-api", "title": "Slow reindex (INC-24)"}),
         ("page_oncall", {"service": "search-api", "incident_id": "INC-24"})),
        (("page_oncall", {"service": "billing-batch", "incident_id": "INC-27"}),
         ("create_ticket", {"service": "billing-batch", "title": "Invoice PDFs (INC-27)"}))],
    # Forgets its own roadmap booking, so hiring sync lands on top of it.
    "cal_stack_week_planner": [
        (("create_event", {"title": "hiring sync", "day": "wed", "hour": 15}),
         ("create_event", {"title": "hiring sync", "day": "wed", "hour": 12}))],
}


def wrong_tools(proto):
    return _swap(proto.solution, WRONG_SWAPS[proto.task_id])


def main():
    problems = []

    print("flakiness stacked: cases vs oracle, answer vs oracle on random inputs, wrong code fails")
    for task in FS.TASKS:
        oracle, gen = ORACLES[task.task_id]
        for args, expected in task.cases:
            got = oracle(*args)
            if got != expected:
                problems.append(f"{task.task_id}: case {args!r} expects {expected!r}, oracle says {got!r}")
        if not run_cases(task.answer, task.fn, task.cases):
            problems.append(f"{task.task_id}: reference answer fails its own cases")
        answer, mismatches = _load(task.answer, task.fn), 0
        for _ in range(RANDOM_TRIALS):
            args = gen()
            want, got = oracle(*args), answer(*args)
            if got != want:
                mismatches += 1
                if mismatches == 1:
                    problems.append(f"{task.task_id}: answer {got!r} != oracle {want!r} on {args!r}")
        if run_cases(WRONG_CODE[task.task_id], task.fn, task.cases):
            problems.append(f"{task.task_id}: the planted wrong submission passes, so the trap is not tested")
        print(f"  {'ok  ' if not mismatches else 'BAD '}{task.task_id}")

    print("\ntools stacked: solution passes, untouched fails, central interaction done wrong fails")
    for proto in TS.TASKS:
        def run(steps):
            t = proto.fresh()
            for name, args in steps:
                t.execute(name, args)
            return t.check()
        ok = run(proto.solution) and not proto.fresh().check() and not run(wrong_tools(proto))
        if not ok:
            problems.append(f"{proto.task_id}: solution={run(proto.solution)} untouched={proto.fresh().check()} "
                            f"wrong={run(wrong_tools(proto))}")
        print(f"  {'ok  ' if ok else 'BAD '}{proto.task_id}")

    if problems:
        print(f"\n{len(problems)} problems:")
        for p in problems:
            print("  !", p)
        return 1
    print("\nall good")
    return 0


if __name__ == "__main__":
    sys.exit(main())
