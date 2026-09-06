"""Offline regression for every task family: no API, no spend.

Three properties, for each task:
  1. the hand-written `solution` tool sequence makes check() true;
  2. a task that was never touched fails, so no checker is trivially true;
  3. every tool named in the solution exists, and the arguments satisfy its input_schema.

Run: python tests/test_tasks.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corpus.tasks import load_family
from corpus.ledger import CFG

TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
         "object": dict, "array": list}


def check_schema(task, name, args):
    spec = next((t for t in task.tools if t["name"] == name), None)
    assert spec is not None, f"{task.task_id}: solution calls unknown tool {name!r}"
    props = spec["input_schema"]["properties"]
    for r in spec["input_schema"]["required"]:
        assert r in args, f"{task.task_id}: {name} missing required arg {r!r}"
    for k, v in args.items():
        assert k in props, f"{task.task_id}: {name} got undeclared arg {k!r}"
        want = TYPES[props[k]["type"]]
        assert isinstance(v, want), f"{task.task_id}: {name} arg {k!r} should be {props[k]['type']}"


def run_solution(proto):
    t = proto.fresh()
    outs = []
    for name, args in proto.solution:
        check_schema(t, name, args)
        out = t.execute(name, args)
        outs.append(f"    {name}({json.dumps(args)[:70]}) -> {str(out)[:70]}")
    return t, outs


def main():
    families = [f for f, c in CFG["families"].items() if c["enabled"]]
    failures, total = [], 0
    for fam in families:
        tasks = load_family(fam)
        print(f"\n{fam}: {len(tasks)} tasks")
        for proto in tasks:
            total += 1
            assert hasattr(proto, "solution"), f"{proto.task_id}: no hand-written solution"
            # 2. untouched task must not already pass
            try:
                if proto.fresh().check():
                    failures.append(f"{proto.task_id}: check() passes on an untouched task")
                    print(f"  TRIVIAL {proto.task_id}")
                    continue
            except Exception as e:
                failures.append(f"{proto.task_id}: check() raised on an untouched task: {e}")
                print(f"  RAISED  {proto.task_id}: {e}")
                continue
            # 1. solution must pass
            t, outs = run_solution(proto)
            ok = t.check()
            print(f"  {'ok     ' if ok else 'FAIL   '}{proto.task_id}")
            if not ok:
                failures.append(f"{proto.task_id}: hand-written solution does not pass check()")
                print("\n".join(outs))
    print(f"\n{total - len(failures)}/{total} tasks verified")
    for f in failures:
        print("  !", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
