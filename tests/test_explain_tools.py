"""Offline check of explain_tool_failure: no API, no spend.

Replays each stacked tool task's planted mistake (from test_stacked_tasks.py) as if it were a recorded
episode, and checks the explanation names the thing that actually went wrong, while the reference
solution is reported as passing and every task's free-text wording is ignored.

Run: python tests/test_explain_tools.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpus.tasks import family_tools_stack as TS               # noqa: E402
from corpus.tasks.explain_tools import explain_tool_failure      # noqa: E402
from test_stacked_tasks import wrong_tools                        # noqa: E402

# What each planted mistake's explanation must mention.
MUST_NAME = {
    "retail_stack_ticket_queue": ["O-7102", "O-7303", "exchanges"],
    "retail_stack_flaky_backend": ["O-7106", "refunds"],
    "air_stack_disruption": ["R-3002", "R-3005", "AL706"],
    "ops_stack_night_shift": ["pages", "tickets", "INC-24"],
    "cal_stack_week_planner": ["hiring sync", "wed"],
}


def as_trace(steps):
    return {"turns": [{"assistant": [{"type": "tool_use", "id": f"t{i}", "name": n, "input": a}]}
                      for i, (n, a) in enumerate(steps)]}


def main():
    problems = []
    for proto in TS.TASKS:
        ok = explain_tool_failure(proto, as_trace(proto.solution))
        if "passes the checker" not in ok:
            problems.append(f"{proto.task_id}: the reference solution should replay as passing, got {ok[:120]!r}")

        # The reference solution with every free-text field reworded must still explain as passing.
        reworded = [(n, {k: ("different words" if k in ("text", "title", "resolution", "reason") and n != "create_event" else v)
                         for k, v in a.items()}) for n, a in proto.solution]
        # Some checkers require an id or amount inside a message, so rewording may fail them, but it must
        # never show up as a state difference.
        again = explain_tool_failure(proto, as_trace(reworded))
        if "passes the checker" not in again and "apart from wording" not in again:
            problems.append(f"{proto.task_id}: rewording free text produced a state diff: {again[:160]!r}")

        why = explain_tool_failure(proto, as_trace(wrong_tools(proto)))
        missing = [w for w in MUST_NAME[proto.task_id] if w not in why]
        if not why.startswith("end state differs") or missing:
            problems.append(f"{proto.task_id}: explanation lacks {missing}: {why[:300]!r}")
        print(f"  {'ok  ' if not missing else 'BAD '}{proto.task_id}: {why[:150]}")

    for p in problems:
        print("  !", p)
    print("all good" if not problems else f"{len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
