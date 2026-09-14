"""Family C, stacked tier: small stateful simulations where several exact rules interact.

Calibration on 2026-09-13 (calibrate.py, 5 runs each on claude-sonnet-5): nine of the ten single-trap
tasks in family_flakiness_hard.py passed 5/5. The one that failed for its intended reason,
hard_ttl_lru_cache (3/5), was the one where two rules interact: expiry changes what eviction sees. These
scale that up: an order book where price-time priority meets three order types and cancels, recurrence
expansion where count, until, skipped months and exdates interact, a limiter combining per-client token
buckets with a global sliding window, and path resolution where symlinks change what '..' means.

As in the hard tier every prompt states every rule, and tests/test_stacked_tasks.py checks each expected
value against an independently written oracle and on random inputs.
"""
from .family_flakiness import Python


class OrderBook(Python):
    task_id = "stack_order_book"; fn = "match"
    prompt = ("Write match(orders) that simulates a price-time priority limit order book for one instrument and "
              "returns the trades. orders is a list in arrival order, each one of: ['limit', id, side, price, qty], "
              "['ioc', id, side, price, qty], ['market', id, side, qty], ['cancel', id]. side is 'buy' or 'sell', "
              "ids are unique strings, price and qty are positive ints.\n"
              "An incoming buy matches resting sells priced at or below its price (any price, for a market order): "
              "lowest price first, and among equal prices the earliest-arrived first. An incoming sell matches "
              "resting buys priced at or above its price: highest price first, then earliest-arrived. Each match "
              "trades the smaller of the two remaining quantities at the resting order's price. A partially filled "
              "resting order keeps its place in the queue.\n"
              "After matching, a limit order's remaining quantity rests in the book with its original arrival time; "
              "the remainder of an ioc or market order is discarded. cancel removes a resting order; cancelling an "
              "unknown, filled or already-cancelled id does nothing.\n"
              "Return the trades in execution order, each as [buy_id, sell_id, price, qty]. Call submit with the code.")
    cases = [
        (([["limit", "s1", "sell", 101, 5], ["limit", "s2", "sell", 100, 3], ["limit", "s3", "sell", 100, 4],
           ["limit", "b1", "buy", 101, 10]],),
         [["b1", "s2", 100, 3], ["b1", "s3", 100, 4], ["b1", "s1", 101, 3]]),
        (([["limit", "b1", "buy", 99, 5], ["limit", "b2", "buy", 99, 5], ["limit", "s1", "sell", 99, 3],
           ["cancel", "b1"], ["limit", "s2", "sell", 98, 4]],),
         [["b1", "s1", 99, 3], ["b2", "s2", 99, 4]]),
        (([["limit", "s1", "sell", 50, 2], ["limit", "s2", "sell", 52, 2], ["ioc", "b1", "buy", 51, 5],
           ["market", "b2", "buy", 3], ["limit", "b3", "buy", 60, 1]],),
         [["b1", "s1", 50, 2], ["b2", "s2", 52, 2]]),
        (([["limit", "b1", "buy", 10, 1], ["limit", "b2", "buy", 12, 1], ["limit", "b3", "buy", 12, 1],
           ["cancel", "zz"], ["market", "s1", "sell", 2], ["cancel", "b2"], ["limit", "s2", "sell", 9, 5]],),
         [["b2", "s1", 12, 1], ["b3", "s1", 12, 1], ["b1", "s2", 10, 1]]),
        (([],), []),
        (([["limit", "s1", "sell", 5, 5], ["limit", "b1", "buy", 5, 2], ["limit", "s2", "sell", 5, 5],
           ["limit", "b2", "buy", 5, 6]],),
         [["b1", "s1", 5, 2], ["b2", "s1", 5, 3], ["b2", "s2", 5, 3]]),
        (([["ioc", "b1", "buy", 10, 3], ["limit", "s1", "sell", 9, 1]],), []),
        (([["limit", "b1", "buy", 8, 2], ["limit", "b2", "buy", 9, 1], ["market", "s1", "sell", 5],
           ["limit", "b3", "buy", 7, 1], ["limit", "s2", "sell", 7, 2]],),
         [["b2", "s1", 9, 1], ["b1", "s1", 8, 2], ["b3", "s2", 7, 1]]),
    ]
    answer = """
def match(orders):
    book = {"buy": [], "sell": []}
    trades = []
    for seq, o in enumerate(orders):
        if o[0] == "cancel":
            for side in book:
                book[side] = [r for r in book[side] if r[1] != o[1]]
            continue
        if o[0] == "market":
            _, oid, side, qty = o
            price = None
        else:
            _, oid, side, price, qty = o
        other = "sell" if side == "buy" else "buy"
        while qty > 0:
            if side == "buy":
                cands = [r for r in book["sell"] if price is None or r[2] <= price]
                key = lambda r: (r[2], r[0])
            else:
                cands = [r for r in book["buy"] if price is None or r[2] >= price]
                key = lambda r: (-r[2], r[0])
            if not cands:
                break
            best = min(cands, key=key)
            q = min(qty, best[3])
            trades.append([oid, best[1], best[2], q] if side == "buy" else [best[1], oid, best[2], q])
            qty -= q
            best[3] -= q
            if best[3] == 0:
                book[other].remove(best)
        if o[0] == "limit" and qty > 0:
            book[side].append([seq, oid, price, qty])
    return trades
"""


class Recurrence(Python):
    task_id = "stack_recurrence"; fn = "occurrences"
    prompt = ("Write occurrences(start, freq, interval, count, until, byweekday, exdates) returning a sorted list of "
              "'YYYY-MM-DD' strings. Every argument is passed positionally; count, until and byweekday may be None.\n"
              "- start is 'YYYY-MM-DD' and interval is a positive int.\n"
              "- 'daily': candidates are start plus k*interval days, for k = 0, 1, 2, ...\n"
              "- 'weekly': weeks start on Monday. The week containing start is week 0 and only weeks 0, interval, "
              "2*interval, ... are used. In a used week the candidates are the days whose weekday (0 = Monday ... "
              "6 = Sunday) is in byweekday, a non-empty list that may be unsorted or repeat values, or start's own "
              "weekday if byweekday is None. Days before start are never candidates.\n"
              "- 'monthly': candidates fall on start's day of the month in the months start, start + interval "
              "months, ... A month that has no such day produces no candidate (it is skipped, not moved).\n"
              "- until, if given, is an inclusive 'YYYY-MM-DD' limit. count, if given, is the maximum number of "
              "candidates, counted before exdates are removed. At least one of count and until is given; if both "
              "are, stop at whichever is reached first.\n"
              "- Finally remove every date that appears in the exdates list.\n"
              "Call submit with the code.")
    cases = [
        (("2026-01-31", "monthly", 1, 5, None, None, []),
         ["2026-01-31", "2026-03-31", "2026-05-31", "2026-07-31", "2026-08-31"]),
        (("2026-09-02", "weekly", 2, 5, None, [0, 2, 4], []),
         ["2026-09-02", "2026-09-04", "2026-09-14", "2026-09-16", "2026-09-18"]),
        (("2026-09-01", "daily", 3, 4, None, None, ["2026-09-04"]), ["2026-09-01", "2026-09-07", "2026-09-10"]),
        (("2026-02-27", "daily", 2, None, "2026-03-05", None, []),
         ["2026-02-27", "2026-03-01", "2026-03-03", "2026-03-05"]),
        (("2025-11-30", "monthly", 3, None, "2026-12-31", None, []),
         ["2025-11-30", "2026-05-30", "2026-08-30", "2026-11-30"]),
        (("2026-09-13", "weekly", 1, 10, "2026-10-01", None, ["2026-09-20"]), ["2026-09-13", "2026-09-27"]),
        (("2026-09-03", "weekly", 1, 4, None, [4, 3, 4], []),
         ["2026-09-03", "2026-09-04", "2026-09-10", "2026-09-11"]),
        (("2024-02-29", "monthly", 12, 3, None, None, []), ["2024-02-29", "2028-02-29", "2032-02-29"]),
    ]
    answer = """
from datetime import date, timedelta

def occurrences(start, freq, interval, count, until, byweekday, exdates):
    d0 = date.fromisoformat(start)
    end = date.fromisoformat(until) if until else None

    def candidates():
        k = 0
        while True:
            if freq == "daily":
                yield d0 + timedelta(days=k * interval)
            elif freq == "weekly":
                days = sorted(set(byweekday)) if byweekday is not None else [d0.weekday()]
                week = d0 - timedelta(days=d0.weekday()) + timedelta(weeks=k * interval)
                for wd in days:
                    d = week + timedelta(days=wd)
                    if d >= d0:
                        yield d
            else:
                m = d0.month - 1 + k * interval
                try:
                    yield date(d0.year + m // 12, m % 12 + 1, d0.day)
                except ValueError:
                    pass
            k += 1

    out = []
    for d in candidates():
        if (end is not None and d > end) or (count is not None and len(out) >= count):
            break
        out.append(d.isoformat())
    skip = set(exdates)
    return [d for d in out if d not in skip]
"""


class RateLimiter(Python):
    task_id = "stack_rate_limiter"; fn = "admit"
    prompt = ("Write admit(requests, capacity, refill_every, window, window_max) returning a list of booleans, one "
              "per request, saying whether it is admitted. requests is a list of [t, client, cost] with integer t "
              "in non-decreasing order; requests with the same t are handled in list order.\n"
              "- Every client has its own token bucket. It holds capacity tokens at time 0 and gains one token at "
              "each time that is a positive multiple of refill_every, but never holds more than capacity: a token "
              "that arrives while the bucket is full is lost.\n"
              "- Across all clients, at most window_max admitted requests may fall in the half-open interval "
              "(t - window, t].\n"
              "- A request is admitted only if its client's bucket holds at least cost tokens and fewer than "
              "window_max requests were already admitted in (t - window, t]. An admitted request removes cost "
              "tokens. A rejected request changes nothing.\n"
              "Call submit with the code.")
    cases = [
        (([[0, "a", 1], [0, "a", 1], [0, "a", 1], [9, "a", 1], [10, "a", 1], [25, "a", 2], [40, "a", 2]], 2, 10, 100, 100),
         [True, True, False, False, True, False, True]),
        (([[0, "a", 1], [1, "b", 1], [2, "a", 1], [3, "b", 1], [3, "a", 1], [4, "c", 1]], 5, 1, 3, 2),
         [True, True, False, True, False, True]),
        (([[0, "a", 1], [5, "b", 1], [20, "b", 1]], 1, 100, 10, 1), [True, False, True]),
        (([[0, "a", 2], [5, "a", 1], [30, "a", 2], [30, "a", 1]], 2, 5, 1000, 1000), [True, True, True, False]),
        (([[0, "z", 4], [100, "z", 3]], 3, 1, 5, 5), [False, True]),
        (([], 1, 1, 1, 1), []),
        (([[7, "a", 1], [7, "b", 1], [7, "c", 1]], 3, 1, 1, 2), [True, True, False]),
    ]
    answer = """
def admit(requests, capacity, refill_every, window, window_max):
    buckets = {}
    admitted = []
    out = []
    for t, client, cost in requests:
        tick = t // refill_every
        tokens, last = buckets.get(client, (capacity, 0))
        tokens = min(capacity, tokens + tick - last)
        recent = sum(1 for a in admitted if t - window < a <= t)
        ok = tokens >= cost and recent < window_max
        if ok:
            tokens -= cost
            admitted.append(t)
        buckets[client] = (tokens, tick)
        out.append(ok)
    return out
"""


LINKS = {"/a/l1": "/b", "/b/up": "..", "/loop1": "/loop2", "/loop2": "/loop1",
         "/home/u/docs": "shared/docs", "/home/u/shared/docs": "/srv/docs"}
CHAIN = {**{f"/c{i}": f"/c{i + 1}" for i in range(9)}, "/c9": "/end"}


class ResolvePath(Python):
    task_id = "stack_resolve_path"; fn = "resolve"
    prompt = ("Write resolve(path, cwd, links) returning the canonical absolute path that path refers to, or None on "
              "error. cwd is a canonical absolute path such as '/home/u'; a path that does not start with '/' is "
              "relative to cwd. links maps canonical absolute paths to symlink targets; a target that does not "
              "start with '/' is relative to the directory containing the link.\n"
              "Resolve components left to right. Empty components and '.' are skipped. '..' moves to the parent of "
              "the directory resolved so far ('/' stays '/'). Any other name is appended; if the resulting path is "
              "a key in links, it is replaced by resolving the link's target, and resolution continues with the "
              "remaining components from there. Following more than 8 links in total during one call is an error. "
              "The result has no trailing slash, except '/' itself. Call submit with the code.")
    cases = [
        (("/a/l1/c", "/", LINKS), "/b/c"),
        (("/a/l1/../x", "/", LINKS), "/x"),
        (("docs/readme", "/home/u", LINKS), "/srv/docs/readme"),
        (("/b/up/z", "/", LINKS), "/z"),
        (("/loop1/x", "/", LINKS), None),
        (("../../..", "/home/u", LINKS), "/"),
        (("./a//./", "/", LINKS), "/a"),
        (("l1", "/a", LINKS), "/b"),
        (("/c2", "/", CHAIN), "/end"),
        (("/c1", "/", CHAIN), None),
    ]
    answer = """
def resolve(path, cwd, links):
    hops = [0]

    def walk(parts, rel):
        for comp in rel.split("/"):
            if comp in ("", "."):
                continue
            if comp == "..":
                parts = parts[:-1]
                continue
            key = "/" + "/".join(parts + [comp])
            if key not in links:
                parts = parts + [comp]
                continue
            hops[0] += 1
            if hops[0] > 8:
                return None
            target = links[key]
            parts = walk([] if target.startswith("/") else parts, target)
            if parts is None:
                return None
        return parts

    start = [] if path.startswith("/") else [p for p in cwd.split("/") if p]
    parts = walk(start, path)
    return None if parts is None else "/" + "/".join(parts)
"""


TASKS = [OrderBook(), Recurrence(), RateLimiter(), ResolvePath()]
