"""Agent loop with hard caps. Every response's usage goes to the ledger before anything else happens.

Each episode also produces an AgentLens trace (see agentlens_export): a root agent span, an llm span
per turn, a tool span per tool call. The envelope is embedded in the saved trace JSON under
"agentlens" and, if a local AgentLens server is running, POSTed to it.
"""
import json, time
from pathlib import Path
import anthropic
from . import ledger
from .agentlens_export import EpisodeTrace, export, ulid
from .ledger import CFG
from .redact import redact

TRACES = Path(__file__).parent.parent / "data" / "traces"

class Runaway(Exception): pass
class Terminal(Exception): pass  # billing/auth: stop everything

def call_with_backoff(client, **kw):
    delay = 1
    for _ in range(5):
        try:
            return client.messages.create(**kw)
        except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError):
            time.sleep(delay); delay = min(delay * 2, 64)
        except anthropic.AuthenticationError as e:
            raise Terminal(str(e))
        except anthropic.PermissionDeniedError as e:
            raise Terminal(str(e))
        except anthropic.BadRequestError as e:
            if "credit" in str(e).lower() or "billing" in str(e).lower(): raise Terminal(str(e))
            raise
    raise RuntimeError("rate limited 5x")

def run_episode(proto, model=None, client=None):
    """proto: Task prototype; .fresh() gives a clean instance with .system .prompt .tools .execute() .check()"""
    task = proto.fresh()
    ep = CFG["episode"]; model = model or CFG["models"]["agent"]
    client = client or anthropic.Anthropic()
    episode_id = f"{task.family}-{task.task_id}-{ulid()}"
    al = EpisodeTrace(episode_id, task.family, task.task_id, model, prompt=task.prompt, system=task.system)
    trace = {"episode_id": episode_id, "family": task.family, "task_id": task.task_id, "model": model,
             "started": time.time(), "turns": [], "trace_id": al.trace_id}
    messages = [{"role": "user", "content": task.prompt}]
    system = [{"type": "text", "text": task.system, "cache_control": {"type": "ephemeral"}}]
    cost, total_tokens, outcome, t0 = 0.0, 0, "error", time.time()
    err = None
    try:
        for i in range(ep["max_turns"]):
            if time.time() - t0 > ep["wall_clock_seconds"]: raise Runaway("wall clock")
            if total_tokens > ep["max_total_tokens"]: raise Runaway("token cap")
            with al.llm_span(i) as span:
                resp = call_with_backoff(client, model=model, system=system, messages=messages,
                                         tools=task.tools, max_tokens=ep["max_tokens_per_turn"])
                usage = resp.usage.model_dump()
                cost += ledger.record_call(episode_id, model, usage)
                total_tokens += (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0) + (usage.get("cache_read_input_tokens") or 0)
                content = [b.model_dump() for b in resp.content]
                span.record_usage(usage, ledger.price(model, usage))
                span.set_output(content).annotate(stop_reason=resp.stop_reason)
            trace["turns"].append({"assistant": content, "usage": usage})
            messages.append({"role": "assistant", "content": content})
            if resp.stop_reason != "tool_use":
                break
            results = []
            for b in resp.content:
                if b.type == "tool_use":
                    with al.tool_span(b.name, b.input, turn=i) as tspan:
                        try: out = task.execute(b.name, b.input)
                        except Exception as e:
                            out = f"tool error: {e}"; tspan.set_status("error")
                        payload = redact(str(out))[:20000]
                        tspan.set_output(payload)
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": payload})
            trace["turns"][-1]["tool_results"] = results
            messages.append({"role": "user", "content": results})
        else:
            raise Runaway("max turns")
        outcome = "pass" if task.check() else "fail"
    except Runaway as e:
        outcome = "runaway"; err = str(e); trace["runaway_reason"] = str(e)
    except Terminal:
        al.finish("error", cost, error="terminal API error")
        raise
    except Exception as e:
        outcome = "error"; err = redact(str(e))[:2000]; trace["error"] = err
    trace["agentlens"] = al.finish(outcome, cost, error=err)
    trace["agentlens_exported"] = export(trace["agentlens"])
    trace.update(outcome=outcome, cost_usd=round(cost, 4), ended=time.time())
    path = TRACES / task.family / f"{episode_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trace, default=str))
    ledger.record_episode(episode_id=episode_id, ts=t0, family=task.family, task_id=task.task_id, model=model,
                          turns=len(trace["turns"]), outcome=outcome, label=None, cost_usd=cost, trace_path=str(path))
    return trace
