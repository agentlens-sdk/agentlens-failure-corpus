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
    tool_text = labeler._compact(trace("tools", "cal_no_double_book"))
    expect("checker: end state differs from the reference" in tool_text, "tool traces must carry the replay diff")
    tool_detail = labeler._checker_detail(trace("tools", "cal_no_double_book"))
    expect(labeler.label_from_checker(tool_detail) is None, "a tool diff must still go to the model for a label")
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

    # replies that became 'unclassified' before the fix, because confidence was not a JSON number
    for raw, want in [(0.95, 0.95), ("0.95", 0.95), ("high", 0.9), ("Low", 0.3), (7, 1.0), ("sure", None), (None, None)]:
        got = labeler._confidence(raw)
        expect(got == want, f"_confidence({raw!r}) = {got!r}, want {want!r}")

    class Block:
        def __init__(self, type, text=""):
            self.type, self.text = type, text

    class Reply:
        def __init__(self, blocks, stop_reason="end_turn"):
            self.content, self.stop_reason = blocks, stop_reason

    good = '{"label":"misread_spec","confidence":"high","evidence":"Turn 3: skipped the rollback"}'
    expect(labeler.read_label(Reply([Block("thinking"), Block("text", good)])) == ("misread_spec", 0.9, "Turn 3: skipped the rollback"),
           "a string confidence after a thinking block must still yield the label")
    expect(labeler.read_label(Reply([Block("text", '{"label":"wrong_output"}')]))[0] == "unclassified",
           "checker-only labels from the model must be rejected")
    expect(labeler.read_label(Reply([Block("text", good)], stop_reason="refusal"))[0] == "unclassified", "a refusal carries no label")

    # a failed status check while the batch runs is retried, not fatal (2026-09-16 and 2026-09-18)
    import httpx

    class Result:
        def __init__(self, custom_id):
            self.custom_id = custom_id
            self.result = type("R", (), {"type": "succeeded", "message": Reply([Block("text", good)])})()
            self.result.message.usage = type("U", (), {"model_dump": lambda self: {"input_tokens": 10, "output_tokens": 5}})()

    class Batches:
        def __init__(self):
            self.checks, self.requests = 0, []

        def create(self, requests):
            self.requests = requests
            return type("B", (), {"id": "msgbatch_test"})()

        def retrieve(self, batch_id):
            self.checks += 1
            if self.checks == 1:
                raise labeler.anthropic.APIConnectionError(request=httpx.Request("GET", "https://api.anthropic.com"))
            return type("S", (), {"processing_status": "ended"})()

        def results(self, batch_id):
            return [Result(r["custom_id"]) for r in self.requests]

    batches = Batches()

    class FlakyApi:
        def __init__(self, *a, **k):
            self.messages = type("M", (), {"batches": batches})()

    labeler.anthropic.Anthropic = FlakyApi
    sleep, labeler.time.sleep = labeler.time.sleep, lambda s: None
    try:
        eid = "tools-cal_no_double_book-01M2V4N5MYZ2JZFATAX0QPKC4W"
        got = labeler.label_traces([trace("tools", "cal_no_double_book", episode_id=eid)])
        expect(got == {eid: "misread_spec"}, f"a dropped status check must not lose the label: {got!r}")
        expect(batches.checks == 2, f"the status check should be retried once, was checked {batches.checks} times")
    except Exception as e:
        problems.append(f"label_traces raised on a transient status-check failure: {e!r}")
    finally:
        labeler.time.sleep = sleep

    for p in problems:
        print("  !", p)
    print("all good" if not problems else f"{len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
