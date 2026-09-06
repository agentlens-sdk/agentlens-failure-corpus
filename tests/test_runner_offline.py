"""End-to-end runner check with a scripted fake Anthropic client: no API key, no spend.

Replays each task's hand-written solution through the real run_episode(), then asserts the trace,
the AgentLens envelope and the ledger all agree. Ledger and trace directory are redirected to a
temp dir so this never touches real data.

Run: python tests/test_runner_offline.py
"""
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corpus import ledger

TMP = Path(tempfile.mkdtemp(prefix="corpus-test-"))
ledger.DB = TMP / "ledger.sqlite"

from corpus import runner                     # noqa: E402  (import after DB redirect)
from corpus.tasks import load_family          # noqa: E402

runner.TRACES = TMP / "traces"


class FakeUsage:
    def __init__(self, i=1200, o=90, cr=0, cw=0):
        self.d = {"input_tokens": i, "output_tokens": o,
                  "cache_read_input_tokens": cr, "cache_creation_input_tokens": cw}
    def model_dump(self):
        return dict(self.d)


class FakeBlock:
    def __init__(self, d):
        self.d = d
        self.__dict__.update(d)
    def model_dump(self):
        return dict(self.d)


class FakeResponse:
    def __init__(self, blocks, stop_reason):
        self.content = [FakeBlock(b) for b in blocks]
        self.stop_reason = stop_reason
        self.usage = FakeUsage()


class FakeMessages:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
    def create(self, **kw):
        self.calls += 1
        if self.script:
            name, args = self.script.pop(0)
            return FakeResponse([{"type": "tool_use", "id": f"tu_{self.calls}", "name": name, "input": args}], "tool_use")
        return FakeResponse([{"type": "text", "text": "All done."}], "end_turn")


class FakeClient:
    def __init__(self, script):
        self.messages = FakeMessages(script)


ISO = "%Y-%m-%dT%H:%M:%S.%f%z"


def parse_iso(s):
    return datetime.strptime(s.replace("Z", "+0000"), ISO)


def check_envelope(env, trace, problems, task_id):
    def bad(msg):
        problems.append(f"{task_id}: {msg}")

    if env.get("format") != "agentlens/v1":
        bad("envelope format is not agentlens/v1")
    spans = env["spans"]
    roots = [s for s in spans if s["parent_span_id"] is None]
    if len(roots) != 1:
        bad(f"expected exactly 1 root span, got {len(roots)}")
    ids = {s["span_id"] for s in spans}
    if len(ids) != len(spans):
        bad("duplicate span ids")
    for s in spans:
        if s["parent_span_id"] is not None and s["parent_span_id"] not in ids:
            bad(f"span {s['name']} points at a missing parent")
        if s["trace_id"] != env["trace_id"]:
            bad(f"span {s['name']} carries the wrong trace_id")
        if not (s["started_at"] and s["ended_at"]):
            bad(f"span {s['name']} left unclosed")
        else:
            parse_iso(s["started_at"]); parse_iso(s["ended_at"])
        if s["duration_ms"] is None or s["duration_ms"] < 0:
            bad(f"span {s['name']} has a bad duration")
        if len(s["span_id"]) != 26:
            bad(f"span {s['name']} id is not a ULID")

    llm = [s for s in spans if s["type"] == "llm"]
    tools = [s for s in spans if s["type"] == "tool"]
    if len(llm) != len(trace["turns"]):
        bad(f"{len(llm)} llm spans for {len(trace['turns'])} turns")
    llm_ids = {s["span_id"] for s in llm}
    for t in tools:
        if t["parent_span_id"] not in llm_ids:
            bad(f"tool span {t['name']} is not parented to a turn")
    n_results = sum(len(t.get("tool_results", [])) for t in trace["turns"])
    if len(tools) != n_results:
        bad(f"{len(tools)} tool spans for {n_results} tool results")
    if env["tokens"]["input"] != sum(s["tokens"]["input"] for s in spans):
        bad("envelope token total does not match its spans")


def main():
    problems = []
    families = ["tools", "flakiness"]
    for fam in families:
        tasks = load_family(fam)
        print(f"\n{fam}: replaying {len(tasks)} solutions through run_episode()")
        for proto in tasks:
            trace = runner.run_episode(proto, client=FakeClient(proto.solution))
            tag = f"{trace['outcome']:8}"
            if trace["outcome"] != "pass":
                problems.append(f"{proto.task_id}: replayed solution gave outcome={trace['outcome']} "
                                f"{trace.get('error') or trace.get('runaway_reason') or ''}")
            check_envelope(trace["agentlens"], trace, problems, proto.task_id)
            # trace file exists and round-trips
            row = ledger.conn().execute(
                "SELECT turns, outcome, cost_usd, trace_path FROM episodes WHERE episode_id=?",
                (trace["episode_id"],)).fetchone()
            if not row:
                problems.append(f"{proto.task_id}: no ledger row")
            else:
                saved = json.loads(Path(row[3]).read_text())
                if saved["episode_id"] != trace["episode_id"]:
                    problems.append(f"{proto.task_id}: trace file does not round-trip")
                if abs(row[2] - trace["cost_usd"]) > 0.001:
                    problems.append(f"{proto.task_id}: ledger cost {row[2]} != trace {trace['cost_usd']}")
            print(f"  {tag}{proto.task_id:38} {len(trace['agentlens']['spans']):3d} spans  ${trace['cost_usd']:.4f}")

    n_ep = ledger.conn().execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
    total = ledger.spent_total()
    per_ep = ledger.conn().execute("SELECT COALESCE(SUM(cost_usd),0) FROM episodes").fetchone()[0]
    print(f"\nledger: {n_ep} episodes, calls total ${total:.4f}, episodes total ${per_ep:.4f}")
    if abs(total - per_ep) > 0.01:
        problems.append(f"calls table (${total:.4f}) and episodes table (${per_ep:.4f}) disagree")
    print("stats() keys:", sorted(ledger.stats().keys()))
    print(f"\ntemp data: {TMP}")
    if problems:
        print(f"\n{len(problems)} problems:")
        for p in problems:
            print("  !", p)
        return 1
    print("\nall good")
    return 0


if __name__ == "__main__":
    sys.exit(main())
