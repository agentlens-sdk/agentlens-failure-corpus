"""Family C, hard tier: coding tasks whose specs are exact but whose edge cases are easy to miss.

Calibration on 2026-09-13 (calibrate.py, 5 runs each on claude-sonnet-5): nine of ten passed 5/5 and are
retired in config.yaml. Only hard_ttl_lru_cache, where two rules interact, failed for its intended
reason (3/5). family_flakiness_stack.py builds on that. The notes below describe the original intent.

The original 20 tasks saturated (19 of 20 never failed across 451 runs), so their repeat counts
measure almost nothing. These keep the same shape (one function, run against fixed cases in a
subprocess) but each case list targets a known trap: truncating vs floor division, SemVer pre-release
ordering, expiry-aware eviction, textwrap's partial-line filling, half-open adjacency, non-canonical
numerals, duplicate edges, lenient CSV quoting, casefold vs lower, integer remainder ordering.

Every prompt states the full rule, so a failure is the model's, not the spec's. That lesson came from
refactor_string_join, whose first version contradicted itself. tests/test_hard_tasks.py checks every
expected value against an independent oracle, never against the reference answer alone.
"""
from .family_flakiness import Python


class Calc(Python):
    task_id = "hard_calc_truncating"; fn = "calc"
    prompt = ("Write calc(expr) that evaluates an integer arithmetic expression string and returns an int. "
              "Supported: non-negative integer literals, binary + - * /, unary minus (which may repeat, as in "
              "'--3'), parentheses, and spaces anywhere between tokens. Unary minus binds tighter than * and /, "
              "which bind tighter than + and -. Binary operators are left-associative. / is integer division "
              "that truncates toward zero, so -7/2 is -3 and 7/-2 is -3. Call submit with the code.")
    cases = [(("1 + 2 * 3",), 7), (("(1+2)*3",), 9), (("7/2",), 3), (("-7/2",), -3), (("7/-2",), -3),
             (("1-2-3",), -4), (("2*-3",), -6), (("--3",), 3), (("100/7/2",), 7), (("-(2+3)*4",), -20),
             ((" 8 - -2 ",), 10), (("-7/2*2",), -6), (("0",), 0)]
    answer = """
def calc(expr):
    s = expr.replace(" ", "")
    pos = 0

    def peek():
        return s[pos] if pos < len(s) else ""

    def parse_sum():
        nonlocal pos
        v = parse_product()
        while peek() in ("+", "-"):
            op = s[pos]
            pos += 1
            r = parse_product()
            v = v + r if op == "+" else v - r
        return v

    def parse_product():
        nonlocal pos
        v = parse_unary()
        while peek() in ("*", "/"):
            op = s[pos]
            pos += 1
            r = parse_unary()
            if op == "*":
                v = v * r
            else:
                q = abs(v) // abs(r)
                v = q if (v < 0) == (r < 0) else -q
        return v

    def parse_unary():
        nonlocal pos
        if peek() == "-":
            pos += 1
            return -parse_unary()
        if peek() == "(":
            pos += 1
            v = parse_sum()
            pos += 1
            return v
        start = pos
        while peek().isdigit():
            pos += 1
        return int(s[start:pos])

    return parse_sum()
"""


class SemverSort(Python):
    task_id = "hard_semver_sort"; fn = "semver_sort"
    prompt = ("Write semver_sort(versions) returning the version strings sorted ascending by SemVer 2.0.0 "
              "precedence. A version is MAJOR.MINOR.PATCH, optionally followed by '-' and a pre-release, "
              "optionally followed by '+' and build metadata; the pre-release starts at the first '-' and may "
              "itself contain hyphens. Compare MAJOR, MINOR, PATCH numerically. A version with a pre-release "
              "sorts before the same version without one. Pre-release identifiers are separated by dots and "
              "compared left to right: all-digit identifiers compare numerically, other identifiers compare by "
              "ASCII order, and an all-digit identifier sorts before any other identifier. If every shared "
              "identifier is equal, fewer identifiers sorts first. Build metadata is ignored, and versions of "
              "equal precedence keep their input order. Call submit with the code.")
    cases = [((["1.0.0", "1.0.0-rc.1", "1.0.0-beta.11", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-alpha",
                "1.0.0-beta.2", "1.0.0-alpha.1"],),
              ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2",
               "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0"]),
             ((["2.0.0", "10.0.0", "1.10.0", "1.9.9"],), ["1.9.9", "1.10.0", "2.0.0", "10.0.0"]),
             ((["1.0.0+b2", "1.0.0-rc.1+x", "1.0.0+b1"],), ["1.0.0-rc.1+x", "1.0.0+b2", "1.0.0+b1"]),
             ((["1.0.0-rc-2", "1.0.0-rc.1", "1.0.0-rc-10"],), ["1.0.0-rc.1", "1.0.0-rc-10", "1.0.0-rc-2"]),
             ((["1.0.0-a", "1.0.0-10", "1.0.0-2"],), ["1.0.0-2", "1.0.0-10", "1.0.0-a"]),
             (([],), [])]
    answer = """
def semver_sort(versions):
    def key(v):
        core = v.split("+", 1)[0]
        main, _, pre = core.partition("-")
        nums = tuple(int(x) for x in main.split("."))
        if not pre:
            return (nums, 1, ())
        ids = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))
        return (nums, 0, ids)
    return sorted(versions, key=key)
"""


class TtlLru(Python):
    task_id = "hard_ttl_lru_cache"; fn = "cache_sim"
    prompt = ("Write cache_sim(capacity, ttl, ops) that simulates a least-recently-used cache whose entries "
              "expire, and returns the list of results of every get, in order. ops is a list in time order of "
              "['put', t, key, value] or ['get', t, key], with t a non-decreasing int. An entry written at time "
              "t expires at time t + ttl, and an expired entry counts as absent for every purpose. put stores "
              "the value, sets the entry's write time to t and makes it most recently used. If a put adds a key "
              "that is absent and the cache already holds capacity entries, the least recently used entry is "
              "evicted first. get returns the value and makes the entry most recently used, or returns -1 if "
              "the key is absent. Reading never changes an entry's expiry. capacity is at least 1. "
              "Call submit with the code.")
    cases = [((2, 10, [["put", 0, "a", 1], ["put", 1, "b", 2], ["get", 2, "a"], ["put", 3, "c", 3],
                       ["get", 4, "b"], ["get", 5, "a"], ["get", 5, "c"]]), [1, -1, 1, 3]),
             ((2, 5, [["put", 0, "a", 1], ["get", 4, "a"], ["get", 5, "a"], ["put", 6, "a", 9],
                      ["get", 10, "a"], ["get", 11, "a"]]), [1, -1, 9, -1]),
             ((2, 5, [["put", 0, "a", 1], ["put", 1, "b", 2], ["get", 2, "a"], ["put", 5, "c", 3],
                      ["get", 5, "b"], ["get", 5, "c"], ["get", 5, "a"]]), [1, 2, 3, -1]),
             ((2, 4, [["put", 0, "a", 1], ["put", 1, "b", 2], ["put", 2, "a", 5], ["put", 3, "c", 3],
                      ["get", 3, "b"], ["get", 5, "a"], ["get", 6, "a"], ["get", 6, "c"]]), [-1, 5, -1, 3]),
             ((1, 100, [["put", 0, "x", 1], ["put", 0, "y", 2], ["get", 0, "x"], ["get", 0, "y"]]), [-1, 2]),
             ((3, 1, [["put", 0, "k", 1]]), [])]
    answer = """
from collections import OrderedDict

def cache_sim(capacity, ttl, ops):
    store = OrderedDict()
    out = []
    for op in ops:
        t = op[1]
        for k in [k for k, (_, w) in store.items() if t >= w + ttl]:
            del store[k]
        if op[0] == "put":
            key, value = op[2], op[3]
            if key in store:
                del store[key]
            elif len(store) >= capacity:
                store.popitem(last=False)
            store[key] = (value, t)
        else:
            key = op[2]
            if key in store:
                store.move_to_end(key)
                out.append(store[key][0])
            else:
                out.append(-1)
    return out
"""


class Wrap(Python):
    task_id = "hard_wrap_text"; fn = "wrap"
    prompt = ("Write wrap(text, width) returning a list of lines. Split text into paragraphs on '\\n'. Within a "
              "paragraph, words are maximal runs of non-space characters (there are no tabs). A word longer than "
              "width is first cut into pieces of exactly width characters (the last piece may be shorter), and "
              "each piece is then treated as a separate word. Pack words greedily: each line holds as many words "
              "as fit, joined by single spaces, with length at most width. A paragraph with no words produces "
              "one empty line. width is at least 1. Call submit with the code.")
    cases = [(("the quick brown fox", 10), ["the quick", "brown fox"]), (("a  b   c", 3), ["a b", "c"]),
             (("", 5), [""]), (("abcdefghijk", 4), ["abcd", "efgh", "ijk"]), (("abcdefg hi", 5), ["abcde", "fg hi"]),
             (("one\n\ntwo three", 5), ["one", "", "two", "three"]), (("  lead", 10), ["lead"]),
             (("exact fit", 9), ["exact fit"]), (("ab abcdef", 4), ["ab", "abcd", "ef"]), (("hi\n", 5), ["hi", ""])]
    answer = """
def wrap(text, width):
    lines = []
    for para in text.split("\\n"):
        words = []
        for w in para.split(" "):
            if w:
                words += [w[i:i + width] for i in range(0, len(w), width)]
        if not words:
            lines.append("")
            continue
        cur = words[0]
        for w in words[1:]:
            if len(cur) + 1 + len(w) <= width:
                cur += " " + w
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines
"""


class IntervalSubtract(Python):
    task_id = "hard_interval_subtract"; fn = "subtract"
    prompt = ("Intervals are half-open [start, end) pairs of ints, given as 2-element lists. Write subtract(a, b) "
              "returning the points covered by some interval in a and by no interval in b, as a sorted list of "
              "disjoint [start, end) lists in which no two intervals touch (so [1,3) and [3,5) must come out as "
              "[1,5)). Inputs may be unsorted, may overlap, and may contain empty intervals (start >= end), "
              "which cover nothing. Call submit with the code.")
    cases = [(([[0, 10]], [[2, 4], [6, 8]]), [[0, 2], [4, 6], [8, 10]]), (([[5, 8], [1, 3]], []), [[1, 3], [5, 8]]),
             (([[1, 3], [3, 5]], []), [[1, 5]]), (([[0, 10]], [[0, 10]]), []),
             (([[0, 5], [3, 9]], [[4, 4], [8, 12]]), [[0, 8]]), (([[4, 2], [1, 2]], [[0, 1]]), [[1, 2]]),
             (([], [[1, 2]]), []), (([[0, 4], [6, 9]], [[3, 7]]), [[0, 3], [7, 9]]),
             (([[-5, -1], [-1, 2]], [[0, 1]]), [[-5, 0], [1, 2]])]
    answer = """
def subtract(a, b):
    a = [(s, e) for s, e in a if s < e]
    b = [(s, e) for s, e in b if s < e]
    xs = sorted({x for s, e in a + b for x in (s, e)})
    out = []
    for x, y in zip(xs, xs[1:]):
        if not any(s <= x < e for s, e in a) or any(s <= x < e for s, e in b):
            continue
        if out and out[-1][1] == x:
            out[-1][1] = y
        else:
            out.append([x, y])
    return out
"""


class RomanStrict(Python):
    task_id = "hard_roman_strict"; fn = "parse_roman"
    prompt = ("Write parse_roman(s) returning the integer value of s if s is the canonical uppercase Roman "
              "numeral of some integer from 1 to 3999, and None otherwise. Canonical means exactly the numeral "
              "the standard subtractive form produces: 4 is 'IV' and never 'IIII', 90 is 'XC', 1994 is "
              "'MCMXCIV'. Call submit with the code.")
    cases = [(("MCMXCIV",), 1994), (("IV",), 4), (("IIII",), None), (("VX",), None), (("IC",), None),
             (("",), None), (("MMMM",), None), (("MMMCMXCIX",), 3999), (("XIIX",), None), (("iv",), None),
             (("IXI",), None), (("CDXLIV",), 444), (("DCD",), None), (("XLIX",), 49), (("IL",), None)]
    answer = """
def parse_roman(s):
    table = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
             (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]

    def to_roman(n):
        out = []
        for value, sym in table:
            while n >= value:
                out.append(sym)
                n -= value
        return "".join(out)

    canon = {to_roman(n): n for n in range(1, 4000)}
    return canon.get(s)
"""


class TopoLex(Python):
    task_id = "hard_topo_lexicographic"; fn = "build_order"
    prompt = ("Write build_order(nodes, deps). nodes is a list of distinct names; deps is a list of [a, b] pairs "
              "meaning a must come before b. Return a list of all nodes that respects every dependency, choosing "
              "the alphabetically smallest available node at every step. Return None if no valid order exists. "
              "Every name in deps appears in nodes, and deps may contain duplicate pairs. "
              "Call submit with the code.")
    cases = [((["c", "b", "a"], []), ["a", "b", "c"]),
             ((["a", "b", "c", "d"], [["b", "a"], ["c", "a"], ["d", "c"]]), ["b", "d", "c", "a"]),
             ((["x", "y"], [["x", "y"], ["y", "x"]]), None), ((["p", "q"], [["q", "p"], ["q", "p"]]), ["q", "p"]),
             ((["a"], [["a", "a"]]), None), ((["m", "a", "z"], [["z", "a"]]), ["m", "z", "a"])]
    answer = """
import heapq

def build_order(nodes, deps):
    indeg = {n: 0 for n in nodes}
    after = {n: [] for n in nodes}
    for a, b in deps:
        after[a].append(b)
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
"""


class CsvLine(Python):
    task_id = "hard_csv_strict"; fn = "split_csv"
    prompt = ("Write split_csv(line) that parses one line of CSV and returns its fields as a list of strings, or "
              "None if the line is malformed. Fields are separated by commas. A field that starts with a double "
              "quote is quoted: it ends at the next double quote that is not part of a doubled pair, a doubled "
              "quote (\"\") inside it stands for one quote character, and commas inside it are literal. The "
              "closing quote must be followed by a comma or the end of the line. A field that does not start with "
              "a double quote runs to the next comma and must not contain a double quote. An unterminated quoted "
              "field is malformed. An empty line is one empty field. Call submit with the code.")
    cases = [(("a,b,c",), ["a", "b", "c"]), (("",), [""]), (("a,,c,",), ["a", "", "c", ""]),
             (('"x,y",z',), ["x,y", "z"]), (('"say ""hi""",2',), ['say "hi"', "2"]), (('"",""',), ["", ""]),
             (('"open,1',), None), (('"a"b,c',), None), (('ab"c,d',), None), ((' "a",b',), None),
             (('""""',), ['"'])]
    answer = """
def split_csv(line):
    fields, i, n = [], 0, len(line)
    while True:
        if i < n and line[i] == '"':
            i += 1
            buf = []
            while True:
                if i >= n:
                    return None
                if line[i] == '"':
                    if i + 1 < n and line[i + 1] == '"':
                        buf.append('"')
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(line[i])
                i += 1
            fields.append("".join(buf))
            if i == n:
                return fields
            if line[i] != ",":
                return None
            i += 1
        else:
            j = line.find(",", i)
            end = n if j == -1 else j
            field = line[i:end]
            if '"' in field:
                return None
            fields.append(field)
            if j == -1:
                return fields
            i = j + 1
"""


MERGE_NAMES_ORIGINAL = """
def merge_names(names):
    out = []
    for n in names:
        key = n.strip().lower()
        if not key:
            continue
        for i, existing in enumerate(out):
            if existing.strip().lower() == key:
                out[i] = n.strip()
                break
        else:
            out.append(n.strip())
    return out
"""


class RefactorMergeNames(Python):
    task_id = "hard_refactor_merge_names"; fn = "merge_names"
    prompt = ("Rewrite this as a single pass without the nested loop. Behaviour must be identical for every "
              "list of strings. Submit the whole rewritten function as merge_names.\n" + MERGE_NAMES_ORIGINAL)
    cases = [((["Ann", "bob", "ANN "],), ["ANN", "bob"]), ((["  ", "", "x"],), ["x"]), (([],), []),
             ((["a", "B", "A", "b", "c"],), ["A", "b", "c"]), ((["Straße", "STRASSE"],), ["Straße", "STRASSE"]),
             ((["  Zed", "zed  "],), ["zed"])]
    answer = """
def merge_names(names):
    index, out = {}, []
    for n in names:
        key = n.strip().lower()
        if not key:
            continue
        if key in index:
            out[index[key]] = n.strip()
        else:
            index[key] = len(out)
            out.append(n.strip())
    return out
"""


class FixSplitCents(Python):
    task_id = "hard_fix_split_cents"; fn = "split_cents"
    prompt = """This should split total cents among weights proportionally, returning integer cents that sum
exactly to total. Each share starts as floor(total * w / sum(weights)). The cents left over then go one each
to the shares with the largest remainders (total * w mod sum(weights)), ties going to the lower index. As
written it drops the leftover cents. total >= 0; weights are non-negative ints with a positive sum. Fix it
and submit the whole corrected function as split_cents.

def split_cents(total, weights):
    s = sum(weights)
    return [total * w // s for w in weights]
"""
    cases = [((100, [1, 1, 1]), [34, 33, 33]), ((10, [1, 2]), [3, 7]), ((7, [0, 5, 5]), [0, 4, 3]),
             ((0, [3, 4]), [0, 0]), ((101, [1, 1, 1, 1]), [26, 25, 25, 25]),
             ((5, [1, 1, 1, 1, 1, 1]), [1, 1, 1, 1, 1, 0]), ((1000, [333, 333, 334]), [333, 333, 334]),
             ((10, [3, 3, 3]), [4, 3, 3]), ((1, [1, 2, 4]), [0, 0, 1])]
    answer = """
def split_cents(total, weights):
    s = sum(weights)
    shares = [total * w // s for w in weights]
    left = total - sum(shares)
    order = sorted(range(len(weights)), key=lambda i: (-(total * weights[i] % s), i))
    for i in order[:left]:
        shares[i] += 1
    return shares
"""


TASKS = [Calc(), SemverSort(), TtlLru(), Wrap(), IntervalSubtract(), RomanStrict(), TopoLex(), CsvLine(),
         RefactorMergeNames(), FixSplitCents()]
