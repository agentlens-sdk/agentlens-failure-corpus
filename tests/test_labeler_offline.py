"""Offline check of the failure labeler: no API, no spend.

Two fixes are pinned here. Until 2026-09-14 the labeler saw only the first 300 characters of each tool
call, so every submitted function longer than that looked truncated. And coding failures were labeled
by a model that could not agree with itself: one identical bug drew four different labels. Now coding
failures are labeled straight from the checker, without an API call, and tool failures reach the
model whole, with a definition for every label it may use.

Run: python tests/test_labeler_offline.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corpus import ledger                                     # noqa: E402

ledger.DB = Path(tempfile.mkdtemp(prefix="labeler-test-")) / "ledger.sqlite"

from corpus import labeler                                    # noqa: E402
from corpus.tasks.family_flakiness import explain_failure     # noqa: E402
from corpus.tasks.family_flakiness_hard import CsvLine        # noqa: E402

# csv.reader is lenient about a quote inside an unquoted field, which this task rejects.
LONG_WRONG = '''
import csv

def split_csv(line):
    """Parse one CSV line into fields. Padded well past 300 characters, like a real submission,
    so the old cutoff would have hidden everything after the docstring from the labeler."""
    if line == "":
        return [""]
    rows = list(csv.reader([line]))
    return rows[0] if rows else [""]
'''
RAISES = 'def split_csv(line):\n    raise ValueError("nope")\n'


def trace(family, task_id, code=None, outcome="fail", episode_id="x"):
    turns = [{"assistant": [{"type": "tool_use", "id": "t1", "name": "submit", "input": {"code": code}}],
              "tool_results": [{"tool_use_id": "t1", "content": "received"}]}] if code else [
             {"assistant": [{"type": "text", "text": "done"}]}]
    return {"episode_id": episode_id, "family": family, "task_id": task_id, "outcome": outcome, "turns": turns}


class NoApi:
    def __init__(self, *a, **k):
        raise AssertionError("coding failures must be labeled without calling the API")


def main():
    problems = []
    task = CsvLine()

    def expect(cond, msg):
        if not cond:
            problems.append(msg)

    # explain_failure covers every way a submission can fail
    expect(len(LONG_WRONG) > 300, "the fixture must be longer than the old 300-char cutoff")
    expect(explain_failure(task.answer, task.fn, task.cases) == "all cases pass", "reference answer should pass")
    wrong = explain_failure(LONG_WRONG, task.fn, task.cases)
    raised = explain_failure(RAISES, task.fn, task.cases)
    broken = explain_failure("def split_csv(:", task.fn, task.cases)
    expect(wrong.startswith("args") and "expected None" in wrong, f"wrong code should name its failing case: {wrong!r}")
    expect(": raised ValueError" in raised, f"a crash should say so: {raised!r}")
    expect(broken.startswith("code does not load"), f"a syntax error should say so: {broken!r}")

    # every checker detail maps to exactly one label
    for detail, want in [(wrong, "wrong_output"), (raised, "crashed"), (broken, "crashed"),
                         ("no code submitted", "premature_stop"), ("timed out after 10s", "timed_out"),
                         ("all cases pass", None), (None, None)]:
        got = labeler.label_from_checker(detail)
        expect(got == want, f"label_from_checker({detail!r}) = {got!r}, want {want!r}")

    # coding failures never reach the API; the label and evidence come from the checker
    labeler.anthropic.Anthropic = NoApi
    try:
        got = labeler.label_traces([trace("flakiness", task.task_id, LONG_WRONG, episode_id="a"),
                                    trace("flakiness", task.task_id, RAISES, episode_id="b"),
                                    trace("flakiness", task.task_id, task.answer, outcome="pass", episode_id="c")])
        expect(got == {"a": "wrong_output", "b": "crashed"}, f"checker labels: {got!r}")
    except AssertionError as e:
        problems.append(str(e))

    # what the model sees for anything it does label
    text = labeler._compact(trace("flakiness", task.task_id, LONG_WRONG))
    expect("rows[0] if rows else" in text, "the labeler must see the end of the submitted code")
    expect("[cut for labeling]" not in text, "a normal submission must not be cut")
    expect(f"checker: {wrong}" in text, "coding traces must carry the checker line")
    expect("checker:" not in labeler._compact(trace("tools", "cal_no_double_book")), "tool tasks get no checker line")
    expect(all(f"- {k}: {v}" in labeler.SYSTEM for k, v in labeler.LABEL_DEFINITIONS.items()),
           "every label the model may use must be defined in its prompt")
    expect(not set(labeler.CHECKER_LABELS) & set(labeler.SCHEMA["properties"]["label"]["enum"]),
           "checker-only labels must not be offered to the model")

    # replies that became 'unclassified' before 2026-09-14: fenced, or after a paragraph of analysis
    want = {"label": "misread_spec", "confidence": 0.9, "evidence": "Turn 2: {braces} in text"}
    body = '{"label": "misread_spec", "confidence": 0.9, "evidence": "Turn 2: {braces} in text"}'
    for reply in [body, f"```json\n{body}\n```", f"Looking at turn {{2}} first.\n\n{body}\nThat is the label."]:
        try:
            expect(labeler._parse(reply) == want, f"_parse did not recover the object from {reply[:40]!r}")
        except ValueError:
            problems.append(f"_parse raised on {reply[:40]!r}")
    try:
        labeler._parse("I'll analyze this trace for failures. The assistant claims Lee is free")
        problems.append("_parse must raise when a reply holds no JSON object")
    except ValueError:
        pass

    for p in problems:
        print("  !", p)
    print("all good" if not problems else f"{len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
