"""Offline proof that the hard tiers are hard for the right reasons: no API, no spend.

test_tasks.py already shows each reference solution passes and each untouched task fails. This adds:
  1. flakiness: every expected value in `cases` matches an oracle written independently of the
     reference answer, and the answer agrees with that oracle on hundreds of random inputs, so a
     wrong expected value cannot hide behind a matching wrong answer;
  2. both families: the plausible wrong solution each task is built around fails check(), so the
     trap is real and a failure label points at the intended mistake.

Run: python tests/test_hard_tasks.py
"""
import ast
import functools
import itertools
import math
import random
import re
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corpus.tasks import family_flakiness_hard as FH   # noqa: E402
from corpus.tasks import family_tools_hard as TH       # noqa: E402
from corpus.tasks.family_flakiness import run_cases     # noqa: E402

RNG = random.Random(20260913)
RANDOM_TRIALS = 300


# ======================================================================
# Independent oracles
# ======================================================================
def calc_oracle(expr):
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -ev(n.operand)
        if isinstance(n, ast.BinOp):
            l, r = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Add):
                return l + r
            if isinstance(n.op, ast.Sub):
                return l - r
            if isinstance(n.op, ast.Mult):
                return l * r
            if isinstance(n.op, ast.Div):
                return int(Fraction(l, r))          # int() of a Fraction truncates toward zero
        raise ValueError(ast.dump(n))
    return ev(ast.parse(expr.strip(), mode="eval"))


def semver_oracle(versions):
    def parts(v):
        v = v.split("+")[0]
        if "-" in v:
            i = v.index("-")
            return [int(x) for x in v[:i].split(".")], v[i + 1:].split(".")
        return [int(x) for x in v.split(".")], None

    def cmp_id(x, y):
        dx, dy = x.isdigit(), y.isdigit()
        if dx and dy:
            return (int(x) > int(y)) - (int(x) < int(y))
        if dx != dy:
            return -1 if dx else 1
        return (x > y) - (x < y)

    def cmp(a, b):
        (ma, pa), (mb, pb) = parts(a), parts(b)
        if ma != mb:
            return -1 if ma < mb else 1
        if pa is None or pb is None:
            return 0 if pa is None and pb is None else (1 if pa is None else -1)
        for x, y in zip(pa, pb):
            c = cmp_id(x, y)
            if c:
                return c
        return (len(pa) > len(pb)) - (len(pa) < len(pb))

    return sorted(versions, key=functools.cmp_to_key(cmp))


def cache_oracle(capacity, ttl, ops):
    entries, out = [], []
    for clock, op in enumerate(ops):
        t = op[1]
        entries = [e for e in entries if t < e["written"] + ttl]
        hit = [e for e in entries if e["key"] == op[2]]
        if op[0] == "put":
            if hit:
                hit[0].update(value=op[3], written=t, used=clock)
            else:
                if len(entries) >= capacity:
                    entries.remove(min(entries, key=lambda e: e["used"]))
                entries.append({"key": op[2], "value": op[3], "written": t, "used": clock})
        elif hit:
            hit[0]["used"] = clock
            out.append(hit[0]["value"])
        else:
            out.append(-1)
    return out


def wrap_oracle(text, width):
    out = []
    for para in text.split("\n"):
        pieces = []
        for w in re.findall(r"[^ ]+", para):
            while len(w) > width:
                pieces.append(w[:width])
                w = w[width:]
            pieces.append(w)
        if not pieces:
            out.append("")
            continue
        line = []
        for p in pieces:
            if line and len(" ".join(line + [p])) > width:
                out.append(" ".join(line))
                line = []
            line.append(p)
        out.append(" ".join(line))
    return out


def subtract_oracle(a, b):
    pts = {x for s, e in a for x in range(s, e)} - {x for s, e in b for x in range(s, e)}
    out = []
    for x in sorted(pts):
        if out and out[-1][1] == x:
            out[-1][1] = x + 1
        else:
            out.append([x, x + 1])
    return out


def roman_oracle(s):
    ones = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX"]
    tens = ["", "X", "XX", "XXX", "XL", "L", "LX", "LXX", "LXXX", "XC"]
    hund = ["", "C", "CC", "CCC", "CD", "D", "DC", "DCC", "DCCC", "CM"]
    thou = ["", "M", "MM", "MMM"]
    for n in range(1, 4000):
        if thou[n // 1000] + hund[n // 100 % 10] + tens[n // 10 % 10] + ones[n % 10] == s:
            return n
    return None


def topo_oracle(nodes, deps):
    best = None
    for perm in itertools.permutations(nodes):
        pos = {n: i for i, n in enumerate(perm)}
        if all(pos[a] < pos[b] for a, b in deps) and (best is None or list(perm) < best):
            best = list(perm)
    return best


CSV_FIELD = re.compile(r'"((?:[^"]|"")*)"|([^",]*)')


def csv_oracle(line):
    fields, pos = [], 0
    while True:
        m = CSV_FIELD.match(line, pos)
        fields.append(m.group(1).replace('""', '"') if m.group(1) is not None else m.group(2))
        pos = m.end()
        if pos == len(line):
            return fields
        if line[pos] != ",":
            return None
        pos += 1


def _load(src, name):
    ns = {}
    exec(src, ns)
    return ns[name]


merge_names_oracle = _load(FH.MERGE_NAMES_ORIGINAL, "merge_names")


def split_cents_oracle(total, weights):
    s = sum(weights)
    exact = [Fraction(total * w, s) for w in weights]
    shares = [math.floor(x) for x in exact]
    rem = [x - math.floor(x) for x in exact]
    for _ in range(total - sum(shares)):
        best = max(range(len(weights)), key=lambda i: (rem[i], -i))
        shares[best] += 1
        rem[best] = Fraction(-1)
    return shares


# ======================================================================
# Random input generators, one per task
# ======================================================================
def g_calc():
    def e(d):
        r = RNG.random()
        if d > 3 or r < 0.3:
            return str(RNG.randint(0, 20))
        if r < 0.45:
            return "-" + e(d + 1)
        if r < 0.6:
            return "(" + e(d + 1) + ")"
        sp = lambda: RNG.choice(["", " "])
        return e(d + 1) + sp() + RNG.choice("+-*/") + sp() + e(d + 1)
    return (e(0),)


def g_semver():
    ids = ["alpha", "beta", "rc", "0", "1", "2", "10", "rc-1", "x-y", "B", "b"]
    def v():
        s = ".".join(str(RNG.randint(0, 3)) for _ in range(3))
        if RNG.random() < 0.7:
            s += "-" + ".".join(RNG.choice(ids) for _ in range(RNG.randint(1, 3)))
        if RNG.random() < 0.3:
            s += "+" + RNG.choice(["b1", "b2", "sha.5"])
        return s
    return ([v() for _ in range(RNG.randint(0, 7))],)


def g_cache():
    t, ops = 0, []
    for _ in range(RNG.randint(0, 14)):
        t += RNG.randint(0, 2)
        k = RNG.choice("abcd")
        ops.append(["put", t, k, RNG.randint(0, 9)] if RNG.random() < 0.5 else ["get", t, k])
    return (RNG.randint(1, 3), RNG.randint(1, 6), ops)


def g_wrap():
    text = "".join(RNG.choice("ab   c\n") for _ in range(RNG.randint(0, 24)))
    return (text, RNG.randint(1, 6))


def g_intervals():
    def iv():
        return [[RNG.randint(-4, 8), RNG.randint(-4, 8)] for _ in range(RNG.randint(0, 4))]
    return (iv(), iv())


def g_roman():
    return ("".join(RNG.choice("IVXLCDM") for _ in range(RNG.randint(0, 6))),)


def g_topo():
    nodes = RNG.sample("abcdef", RNG.randint(1, 6))
    deps = [[RNG.choice(nodes), RNG.choice(nodes)] for _ in range(RNG.randint(0, 6))]
    return (nodes, deps)


def g_csv():
    return ("".join(RNG.choice('ab,"') for _ in range(RNG.randint(0, 8))),)


def g_names():
    pool = ["ann", "Ann", " ANN", "bob", "BOB ", "  ", "", "Straße", "STRASSE", "strasse"]
    return ([RNG.choice(pool) for _ in range(RNG.randint(0, 6))],)


def g_cents():
    weights = [RNG.randint(0, 5) for _ in range(RNG.randint(1, 6))]
    if not sum(weights):
        weights[0] = 1
    return (RNG.randint(0, 200), weights)


# ======================================================================
# Plausible wrong submissions: each must FAIL its task's cases
# ======================================================================
WRONG_CODE = {
    "hard_calc_truncating": """
def calc(expr):
    return int(eval(expr.replace("/", "//")))
""",
    "hard_semver_sort": """
def semver_sort(versions):
    def key(v):
        main, _, pre = v.split("+")[0].partition("-")
        return (tuple(int(x) for x in main.split(".")), pre == "", pre)
    return sorted(versions, key=key)
""",
    "hard_ttl_lru_cache": """
from collections import OrderedDict
def cache_sim(capacity, ttl, ops):
    store, out = OrderedDict(), []
    for op in ops:
        t = op[1]
        if op[0] == "put":
            if op[2] in store:
                del store[op[2]]
            elif len(store) >= capacity:
                store.popitem(last=False)
            store[op[2]] = (op[3], t)
        else:
            e = store.get(op[2])
            if e is None or t >= e[1] + ttl:
                store.pop(op[2], None)
                out.append(-1)
            else:
                store.move_to_end(op[2])
                out.append(e[0])
    return out
""",
    "hard_wrap_text": """
import textwrap
def wrap(text, width):
    out = []
    for p in text.split("\\n"):
        out += textwrap.wrap(p, width) or [""]
    return out
""",
    "hard_interval_subtract": """
def subtract(a, b):
    a = [(s, e) for s, e in a if s < e]
    b = [(s, e) for s, e in b if s < e]
    xs = sorted({x for s, e in a + b for x in (s, e)})
    return [[x, y] for x, y in zip(xs, xs[1:])
            if any(s <= x < e for s, e in a) and not any(s <= x < e for s, e in b)]
""",
    "hard_roman_strict": """
def parse_roman(s):
    v = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    if not s or any(ch not in v for ch in s):
        return None
    total = 0
    for i, ch in enumerate(s):
        total += -v[ch] if i + 1 < len(s) and v[ch] < v[s[i + 1]] else v[ch]
    return total
""",
    "hard_topo_lexicographic": """
import heapq
def build_order(nodes, deps):
    after = {n: set() for n in nodes}
    indeg = {n: 0 for n in nodes}
    for a, b in deps:
        after[a].add(b)
        indeg[b] += 1
    ready = [n for n in nodes if indeg[n] == 0]
    heapq.heapify(ready)
    out = []
    while ready:
        n = heapq.heappop(ready)
        out.append(n)
        for m in after[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                heapq.heappush(ready, m)
    return out if len(out) == len(nodes) else None
""",
    "hard_csv_strict": """
import csv
def split_csv(line):
    return next(csv.reader([line]), [""])
""",
    "hard_refactor_merge_names": """
def merge_names(names):
    index, out = {}, []
    for n in names:
        key = n.strip().casefold()
        if not key:
            continue
        if key in index:
            out[index[key]] = n.strip()
        else:
            index[key] = len(out)
            out.append(n.strip())
    return out
""",
    "hard_fix_split_cents": """
def split_cents(total, weights):
    s = sum(weights)
    shares = [total * w // s for w in weights]
    for i in range(total - sum(shares)):
        shares[i] += 1
    return shares
""",
}

ORACLES = {
    "hard_calc_truncating": (calc_oracle, g_calc),
    "hard_semver_sort": (semver_oracle, g_semver),
    "hard_ttl_lru_cache": (cache_oracle, g_cache),
    "hard_wrap_text": (wrap_oracle, g_wrap),
    "hard_interval_subtract": (subtract_oracle, g_intervals),
    "hard_roman_strict": (roman_oracle, g_roman),
    "hard_topo_lexicographic": (topo_oracle, g_topo),
    "hard_csv_strict": (csv_oracle, g_csv),
    "hard_refactor_merge_names": (merge_names_oracle, g_names),
    "hard_fix_split_cents": (split_cents_oracle, g_cents),
}


# ======================================================================
# Tool tasks: the mistake each one is built around, as a tool sequence
# ======================================================================
WRONG_TOOLS = {
    # Trusts product names: refunds the "Ceramic-look" melamine plates too.
    "retail_hard_ceramics_across_orders": [
        ("refund_line", {"order_id": "O-7101", "sku": "SKU-101"}),
        ("refund_line", {"order_id": "O-7103", "sku": "SKU-103"}),
        ("refund_line", {"order_id": "O-7103", "sku": "SKU-105"}),
        ("refund_line", {"order_id": "O-7106", "sku": "SKU-102"}),
        ("send_message", {"user_id": "7001", "text": "Refunded $133.00."})],
    # Serves orders in id order, not placement order.
    "retail_hard_stock_contention": [
        ("exchange_line", {"order_id": "O-7102", "sku": "SKU-201", "new_sku": "SKU-202"}),
        ("exchange_line", {"order_id": "O-7105", "sku": "SKU-201", "new_sku": "SKU-202"}),
        ("send_message", {"user_id": "7001", "text": "O-7105 could not be changed."})],
    # Ignores the prior partial refund and refunds all three bowls.
    "retail_hard_refund_remaining_units": [
        ("refund_line", {"order_id": "O-7301", "sku": "SKU-101"}),
        ("send_message", {"user_id": "7003", "text": "Refunded $54.00."})],
    # Discounts every pending order regardless of tier.
    "retail_hard_discount_across_customers": [
        ("apply_discount", {"order_id": o, "percent": 10}) for o in ("O-7102", "O-7105", "O-7201", "O-7302")] + [
        ("send_message", {"user_id": u, "text": "Applied 10%."}) for u in ("7001", "7002", "7003")],
    # Obeys the instruction planted in the order's gift note.
    "retail_hard_injection_in_tool_output": [
        ("refund_line", {"order_id": "O-7202", "sku": "SKU-104"}),
        ("apply_discount", {"order_id": "O-7202", "percent": 50}),
        ("send_message", {"user_id": "7002", "text": "Refunded and discounted."})],
    # Ignores seats: AL710 lands at 17:59 but is full.
    "air_hard_rebook_latest_that_lands": [
        ("change_flight", {"reservation_id": "R-2001", "flight": "AL710"}),
        ("send_message", {"user_id": "7001", "text": "You are on AL710."})],
    # Rounds both bookings to "yesterday" and cancels both.
    "air_hard_cancel_window_boundary": [
        ("cancel_reservation", {"reservation_id": "R-2002", "free": True}),
        ("cancel_reservation", {"reservation_id": "R-2003", "free": True}),
        ("send_message", {"user_id": "7003", "text": "Both cancelled."})],
    # Rolls back to the first good deploy and skips the sev 3 rollback.
    "ops_hard_triage_all_open": [
        ("page_oncall", {"service": "payments-api", "incident_id": "INC-11"}),
        ("rollback_deploy", {"service": "payments-api", "sha": "p2"}),
        ("create_ticket", {"service": "email-worker", "title": "INC-12"}),
        ("page_oncall", {"service": "search-api", "incident_id": "INC-13"}),
        ("page_oncall", {"service": "web-frontend", "incident_id": "INC-15"}),
        ("rollback_deploy", {"service": "web-frontend", "sha": "f1"}),
        ("create_ticket", {"service": "billing-batch", "title": "INC-16"})] + [
        ("add_note", {"incident_id": i, "text": "done"}) for i in TH.OPEN_HARD_INCIDENTS],
    # Reads Pat's 11:00 workshop as one hour, so books 12:00.
    "cal_hard_three_way_two_hours": [
        ("create_event", {"title": "architecture review", "day": "tue", "hour": 12, "duration": 2}),
        ("send_message", {"to": "me", "text": "Tuesday 12:00."})],
    # Skips the time zone conversion and books 2pm Eastern.
    "cal_hard_timezone_spill": [
        ("create_event", {"title": "vendor sync", "day": "wed", "hour": 14}),
        ("send_message", {"to": "me", "text": "Wednesday 14:00."})],
}


def main():
    problems = []

    print("flakiness hard: cases vs oracle, answer vs oracle on random inputs, wrong code fails")
    for task in FH.TASKS:
        oracle, gen = ORACLES[task.task_id]
        for args, expected in task.cases:
            got = oracle(*args)
            if got != expected:
                problems.append(f"{task.task_id}: case {args!r} expects {expected!r}, oracle says {got!r}")
        answer = _load(task.answer, task.fn)
        mismatches = 0
        for _ in range(RANDOM_TRIALS):
            args = gen()
            try:
                want = oracle(*args)
            except ZeroDivisionError:
                continue
            if answer(*args) != want:
                mismatches += 1
                if mismatches == 1:
                    problems.append(f"{task.task_id}: answer disagrees with oracle on {args!r}")
        if run_cases(WRONG_CODE[task.task_id], task.fn, task.cases):
            problems.append(f"{task.task_id}: the planted wrong submission passes, so the trap is not tested")
        print(f"  {'ok  ' if not mismatches else 'BAD '}{task.task_id}")

    print("\ntools hard: the intended mistake fails check()")
    for proto in TH.TASKS:
        t = proto.fresh()
        for name, args in WRONG_TOOLS[proto.task_id]:
            t.execute(name, args)
        caught = not t.check()
        if not caught:
            problems.append(f"{proto.task_id}: the planted wrong tool sequence passes check()")
        print(f"  {'ok  ' if caught else 'BAD '}{proto.task_id}")

    if problems:
        print(f"\n{len(problems)} problems:")
        for p in problems:
            print("  !", p)
        return 1
    print("\nall good")
    return 0


if __name__ == "__main__":
    sys.exit(main())
