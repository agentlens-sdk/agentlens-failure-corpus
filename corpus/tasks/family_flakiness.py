"""Family C: ~20 short deterministic coding tasks, each run k times per night.

Pass rate for one task over weeks is the flakiness index: the tasks never change, so any movement
is the model or the serving stack, not the benchmark.

Half are small algorithmic prompts, half are fix-this / rewrite-this prompts. Submitted code is
executed in a subprocess with a timeout: unattended nights must survive a submission that loops
forever, and nothing the model writes should touch the runner's process.
"""
import json
import subprocess
import sys

from .base import Task

TIMEOUT_SECONDS = 10

_HARNESS = r"""
import json, sys
p = json.loads(sys.stdin.read())
ns = {}
exec(p["code"], ns)
fn = ns[p["fn"]]
print("PASS" if all(fn(*a) == e for a, e in p["cases"]) else "FAIL")
"""


def run_cases(code, fn, cases):
    """True only if every case matches. Any crash, timeout or stray output is a failure."""
    if not code or not isinstance(code, str):
        return False
    payload = json.dumps({"code": code, "fn": fn, "cases": [[list(a), e] for a, e in cases]})
    try:
        r = subprocess.run([sys.executable, "-c", _HARNESS], input=payload, capture_output=True,
                           text=True, timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return False
    return r.returncode == 0 and r.stdout.strip().endswith("PASS")


class Python(Task):
    family = "flakiness"
    system = ("You are a careful Python engineer. Write correct, self-contained Python 3. "
              "Do not import anything you do not need. Submit exactly one function with the requested "
              "name by calling the submit tool with the full source. Do not explain the code.")
    tools = [{"name": "submit", "description": "Submit final code",
              "input_schema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}}]

    def __init__(self):
        self.code = None

    def execute(self, name, inp):
        if name != "submit":
            return "unknown tool"
        self.code = inp.get("code")
        return "received"

    def check(self):
        return run_cases(self.code, self.fn, self.cases)

    @property
    def solution(self):
        """The hand-written correct submission, in the tool-sequence shape tests expect."""
        return [("submit", {"code": self.answer})]


# ======================================================================
# Algorithmic
# ======================================================================
class RLE(Python):
    task_id = "rle_encode"; fn = "rle"
    prompt = "Write rle(s) returning run-length encoding like 'aaabcc' -> 'a3b1c2'. Empty string -> ''. Call submit with the code."
    cases = [(("aaabcc",), "a3b1c2"), (("",), ""), (("z",), "z1"), (("aabbaa",), "a2b2a2")]
    answer = """
def rle(s):
    if not s:
        return ""
    out, prev, n = [], s[0], 1
    for ch in s[1:]:
        if ch == prev:
            n += 1
        else:
            out.append(prev + str(n)); prev, n = ch, 1
    out.append(prev + str(n))
    return "".join(out)
"""


class Interval(Python):
    task_id = "merge_intervals"; fn = "merge"
    prompt = "Write merge(intervals) that merges overlapping [start,end] lists and returns them sorted. Call submit with the code."
    cases = [(([[1, 3], [2, 6], [8, 10]],), [[1, 6], [8, 10]]), (([],), []), (([[1, 4], [4, 5]],), [[1, 5]]),
             (([[5, 6], [1, 2]],), [[1, 2], [5, 6]])]
    answer = """
def merge(intervals):
    out = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out
"""


class Brackets(Python):
    task_id = "balanced_brackets"; fn = "balanced"
    prompt = ("Write balanced(s) returning True if every (), [] and {} in s is correctly nested and closed, "
              "else False. Other characters are ignored. Call submit with the code.")
    cases = [(("([]{})",), True), (("(]",), False), (("",), True), (("a(b[c]d)e",), True), ((")(",), False),
             (("((",), False)]
    answer = """
def balanced(s):
    pairs = {")": "(", "]": "[", "}": "{"}
    stack = []
    for ch in s:
        if ch in "([{":
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return False
    return not stack
"""


class RomanToInt(Python):
    task_id = "roman_to_int"; fn = "from_roman"
    prompt = "Write from_roman(s) converting an uppercase Roman numeral (I V X L C D M, subtractive form) to an int. Call submit with the code."
    cases = [(("III",), 3), (("IX",), 9), (("MCMXCIV",), 1994), (("LVIII",), 58), (("IV",), 4)]
    answer = """
def from_roman(s):
    v = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    for i, ch in enumerate(s):
        if i + 1 < len(s) and v[ch] < v[s[i + 1]]:
            total -= v[ch]
        else:
            total += v[ch]
    return total
"""


class IntToRoman(Python):
    task_id = "int_to_roman"; fn = "to_roman"
    prompt = "Write to_roman(n) converting an int from 1 to 3999 into an uppercase Roman numeral in subtractive form. Call submit with the code."
    cases = [((3,), "III"), ((9,), "IX"), ((1994,), "MCMXCIV"), ((58,), "LVIII"), ((3999,), "MMMCMXCIX")]
    answer = """
def to_roman(n):
    table = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
             (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = []
    for value, sym in table:
        while n >= value:
            out.append(sym); n -= value
    return "".join(out)
"""


class TwoSum(Python):
    task_id = "two_sum"; fn = "two_sum"
    prompt = ("Write two_sum(nums, target) returning the two indices whose values add to target, as a list "
              "in ascending index order. Exactly one answer exists. Call submit with the code.")
    cases = [(([2, 7, 11, 15], 9), [0, 1]), (([3, 2, 4], 6), [1, 2]), (([3, 3], 6), [0, 1])]
    answer = """
def two_sum(nums, target):
    seen = {}
    for i, n in enumerate(nums):
        if target - n in seen:
            return [seen[target - n], i]
        seen[n] = i
    return []
"""


class CommonPrefix(Python):
    task_id = "longest_common_prefix"; fn = "lcp"
    prompt = "Write lcp(words) returning the longest common prefix of a list of strings, or '' if there is none. Call submit with the code."
    cases = [((["flower", "flow", "flight"],), "fl"), ((["dog", "racecar"],), ""), (([],), ""),
             ((["same", "same"],), "same"), ((["a"],), "a")]
    answer = """
def lcp(words):
    if not words:
        return ""
    first = words[0]
    for i, ch in enumerate(first):
        for w in words[1:]:
            if i >= len(w) or w[i] != ch:
                return first[:i]
    return first
"""


class Spiral(Python):
    task_id = "spiral_order"; fn = "spiral"
    prompt = "Write spiral(matrix) returning the elements of a rectangular matrix in clockwise spiral order as a flat list. Call submit with the code."
    cases = [(([[1, 2, 3], [4, 5, 6], [7, 8, 9]],), [1, 2, 3, 6, 9, 8, 7, 4, 5]),
             (([[1, 2], [3, 4]],), [1, 2, 4, 3]), (([],), []), (([[1, 2, 3]],), [1, 2, 3])]
    answer = """
def spiral(matrix):
    out = []
    m = [list(r) for r in matrix]
    while m:
        out += m.pop(0)
        m = [list(r) for r in zip(*m)][::-1]
    return out
"""


class TopWords(Python):
    task_id = "top_k_words"; fn = "top_k"
    prompt = ("Write top_k(text, k) returning the k most frequent whitespace-separated words as a list, "
              "most frequent first, ties broken alphabetically. Call submit with the code.")
    cases = [(("a b a c b a", 2), ["a", "b"]), (("x y z", 2), ["x", "y"]), (("", 3), []),
             (("dog cat dog cat bird", 3), ["cat", "dog", "bird"])]
    answer = """
def top_k(text, k):
    counts = {}
    for w in text.split():
        counts[w] = counts.get(w, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]
"""


class BinarySearch(Python):
    task_id = "binary_search"; fn = "bsearch"
    prompt = "Write bsearch(sorted_nums, target) returning the index of target by binary search, or -1 if absent. Call submit with the code."
    cases = [(([1, 3, 5, 7, 9], 7), 3), (([1, 3, 5], 2), -1), (([], 1), -1), (([4], 4), 0),
             (([1, 2, 3, 4, 5, 6], 1), 0)]
    answer = """
def bsearch(sorted_nums, target):
    lo, hi = 0, len(sorted_nums) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if sorted_nums[mid] == target:
            return mid
        if sorted_nums[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
"""


class Flatten(Python):
    task_id = "flatten_nested"; fn = "flatten"
    prompt = "Write flatten(items) that flattens arbitrarily nested lists into one flat list, preserving order. Call submit with the code."
    cases = [(([1, [2, [3, 4]], 5],), [1, 2, 3, 4, 5]), (([],), []), (([[[[1]]]],), [1]),
             (([1, [], [2]],), [1, 2])]
    answer = """
def flatten(items):
    out = []
    for x in items:
        if isinstance(x, list):
            out.extend(flatten(x))
        else:
            out.append(x)
    return out
"""


class CompressRanges(Python):
    task_id = "compress_ranges"; fn = "compress"
    prompt = ("Write compress(nums) turning a sorted list of distinct ints into a comma-separated range string: "
              "[1,2,3,7,8,10] -> '1-3,7-8,10'. Single values stay bare. Empty list -> ''. Call submit with the code.")
    cases = [(([1, 2, 3, 7, 8, 10],), "1-3,7-8,10"), (([],), ""), (([5],), "5"), (([1, 3, 5],), "1,3,5"),
             (([1, 2],), "1-2")]
    answer = """
def compress(nums):
    if not nums:
        return ""
    out, start, prev = [], nums[0], nums[0]
    for n in nums[1:] + [None]:
        if n is not None and n == prev + 1:
            prev = n; continue
        out.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = n
    return ",".join(out)
"""


# ======================================================================
# Fix / rewrite
# ======================================================================
class FixChunk(Python):
    task_id = "fix_chunk_tail"; fn = "chunk"
    prompt = """This function should split a list into consecutive chunks of size n, but it loses the
final partial chunk. Fix it and submit the whole corrected function as chunk.

def chunk(lst, n):
    out = []
    for i in range(0, len(lst) - n + 1, n):
        out.append(lst[i:i + n])
    return out
"""
    cases = [(([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]), (([1, 2, 3, 4], 2), [[1, 2], [3, 4]]),
             (([], 3), []), (([1], 5), [[1]])]
    answer = """
def chunk(lst, n):
    return [lst[i:i + n] for i in range(0, len(lst), n)]
"""


class RefactorGrade(Python):
    task_id = "refactor_grade_table"; fn = "grade"
    prompt = """Rewrite this function using a table or loop instead of nested conditionals. Behaviour must
be identical. Submit the whole rewritten function as grade.

def grade(score):
    if score >= 90:
        return "A"
    else:
        if score >= 80:
            return "B"
        else:
            if score >= 70:
                return "C"
            else:
                if score >= 60:
                    return "D"
                else:
                    return "F"
"""
    cases = [((95,), "A"), ((90,), "A"), ((85,), "B"), ((70,), "C"), ((60,), "D"), ((0,), "F"), ((59,), "F")]
    answer = """
def grade(score):
    for cutoff, letter in ((90, "A"), (80, "B"), (70, "C"), (60, "D")):
        if score >= cutoff:
            return letter
    return "F"
"""


class FixMutableDefault(Python):
    task_id = "fix_mutable_default"; fn = "add_item"
    prompt = """This helper is meant to return a new bag each call when no bag is passed, but state leaks
between calls. Fix it and submit the whole corrected function as add_item.

def add_item(item, bag=[]):
    bag.append(item)
    return bag
"""
    cases = [(("x",), ["x"]), (("y",), ["y"]), (("z", ["a"]), ["a", "z"])]
    answer = """
def add_item(item, bag=None):
    bag = [] if bag is None else bag
    bag.append(item)
    return bag
"""


class Dedupe(Python):
    task_id = "dedupe_preserve_order"; fn = "dedupe"
    prompt = ("Write dedupe(seq) returning the items of seq with duplicates removed, keeping the first "
              "occurrence of each in original order. Call submit with the code.")
    cases = [(([1, 2, 1, 3, 2],), [1, 2, 3]), (([],), []), ((["b", "a", "b"],), ["b", "a"]), (([7, 7, 7],), [7])]
    answer = """
def dedupe(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x); out.append(x)
    return out
"""


class FixCounter(Python):
    task_id = "fix_char_counter"; fn = "count_chars"
    prompt = """This function should return a dict of character counts, but it raises KeyError on the
first occurrence of each character. Fix it and submit the whole corrected function as count_chars.

def count_chars(s):
    counts = {}
    for ch in s:
        counts[ch] += 1
    return counts
"""
    cases = [(("aab",), {"a": 2, "b": 1}), (("",), {}), (("zzz",), {"z": 3})]
    answer = """
def count_chars(s):
    counts = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    return counts
"""


class RefactorJoin(Python):
    task_id = "refactor_string_join"; fn = "join_words"
    prompt = """Rewrite this so it builds the result without repeated string concatenation in a loop.
Behaviour, including the trailing-separator handling, must be identical. Submit the whole rewritten
function as join_words.

def join_words(words, sep):
    out = ""
    for w in words:
        out = out + w + sep
    if out:
        out = out[:-len(sep)]
    return out
"""
    cases = [((["a", "b", "c"], "-"), "a-b-c"), (([], ","), ""), ((["solo"], "::"), "solo"),
             ((["a", "b"], ""), "ab")]
    answer = """
def join_words(words, sep):
    return sep.join(words)
"""


class FixSortByKey(Python):
    task_id = "fix_sort_by_key"; fn = "sort_people"
    prompt = """This should sort people by age ascending, then by name alphabetically for equal ages, but
it sorts by name only. Fix it and submit the whole corrected function as sort_people. Each person is a
dict with 'name' and 'age'; return the sorted list.

def sort_people(people):
    return sorted(people, key=lambda p: p["name"])
"""
    cases = [(([{"name": "bo", "age": 30}, {"name": "al", "age": 25}],),
              [{"name": "al", "age": 25}, {"name": "bo", "age": 30}]),
             (([{"name": "zed", "age": 20}, {"name": "amy", "age": 20}],),
              [{"name": "amy", "age": 20}, {"name": "zed", "age": 20}]),
             (([],), [])]
    answer = """
def sort_people(people):
    return sorted(people, key=lambda p: (p["age"], p["name"]))
"""


class FirstEven(Python):
    task_id = "refactor_first_even"; fn = "first_even"
    prompt = """Rewrite this to return as soon as it finds a match rather than scanning the whole list.
Behaviour must be identical, including returning None when there is no even number. Submit the whole
rewritten function as first_even.

def first_even(nums):
    found = None
    for n in nums:
        if n % 2 == 0 and found is None:
            found = n
    return found
"""
    cases = [(([1, 3, 4, 6],), 4), (([1, 3],), None), (([],), None), (([0, 2],), 0)]
    answer = """
def first_even(nums):
    for n in nums:
        if n % 2 == 0:
            return n
    return None
"""


TASKS = [RLE(), Interval(), Brackets(), RomanToInt(), IntToRoman(), TwoSum(), CommonPrefix(), Spiral(),
         TopWords(), BinarySearch(), Flatten(), CompressRanges(),
         FixChunk(), RefactorGrade(), FixMutableDefault(), Dedupe(), FixCounter(), RefactorJoin(),
         FixSortByKey(), FirstEven()]
