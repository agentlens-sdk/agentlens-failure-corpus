"""Offline check of what the failure labeler is shown: no API, no spend.

Until 2026-09-14 the labeler saw only the first 300 characters of each tool call, so every submitted
function longer than that looked truncated and got labeled premature_stop. This pins the fix: submitted
code arrives whole, coding failures carry the first case the checker rejected, and tool tasks do not.

Run: python tests/test_labeler_offline.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corpus.labeler import _compact                         # noqa: E402
from corpus.tasks.family_flakiness import explain_failure    # noqa: E402
from corpus.tasks.family_flakiness_hard import CsvLine       # noqa: E402

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


def trace(family, task_id, code=None):
    turns = [{"assistant": [{"type": "tool_use", "id": "t1", "name": "submit", "input": {"code": code}}],
              "tool_results": [{"tool_use_id": "t1", "content": "received"}]}] if code else [
             {"assistant": [{"type": "text", "text": "done"}]}]
    return {"episode_id": "x", "family": family, "task_id": task_id, "outcome": "fail", "turns": turns}


def main():
    problems = []
    task = CsvLine()

    def expect(cond, msg):
        if not cond:
            problems.append(msg)

    expect(len(LONG_WRONG) > 300, "the fixture must be longer than the old 300-char cutoff")
    expect(explain_failure(task.answer, task.fn, task.cases) == "all cases pass", "reference answer should pass")
    expect(explain_failure(None, task.fn, task.cases) == "no code submitted", "missing code")
    expect(explain_failure("def split_csv(:", task.fn, task.cases).startswith("code does not load"), "syntax error")
    detail = explain_failure(LONG_WRONG, task.fn, task.cases)
    expect(detail.startswith("args") and "expected None" in detail, f"wrong code should name its failing case, got {detail!r}")

    text = _compact(trace("flakiness", task.task_id, LONG_WRONG))
    expect("rows[0] if rows else" in text, "the labeler must see the end of the submitted code")
    expect("[cut for labeling]" not in text, "a normal submission must not be cut")
    expect(f"checker: {detail}" in text, "coding failures must carry the checker line")
    expect("checker:" not in _compact(trace("tools", "cal_no_double_book")), "tool tasks get no checker line")

    for p in problems:
        print("  !", p)
    print("all good" if not problems else f"{len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
