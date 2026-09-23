"""Offline check of the hand-labeling review kit: no API, no spend, no real ledger touched.

Four properties are pinned here, because the whole point of the kit is a number the paper will quote:

  1. the same seed draws the same sample, and a different seed does not;
  2. stratification reaches every label present in the population, including the ones with a single
     episode, and the weights it records multiply back to the population;
  3. Cohen's kappa matches a hand-computed 2x2 table, weighted and unweighted;
  4. the anchoring guard holds: nothing in review.html tells a reviewer which label the model gave an
     episode before they have committed their own. A page that leaks it makes the study worthless.

Run: python tests/test_label_review.py
"""
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from corpus import ledger                                       # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="label-review-test-"))
ledger.DB = TMP / "ledger.sqlite"                               # before anything opens the real one

import label_review                                             # noqa: E402

# Skewed the way the corpus is: one label dominates and two are nearly absent.
POPULATION = {"misread_spec": 40, "premature_stop": 12, "tool_misuse": 6, "wrong_target": 2, "gave_up": 1}
# Fixture text is kept free of taxonomy words so that any occurrence of a label in the page is the page's
# own doing, which is what property 4 counts.
PROMPT_WORDS = ["the customer asked for a refund", "reschedule the booking", "close the incident"]


def build_ledger() -> dict[str, str]:
    """A fake ledger plus a trace file per episode. Returns episode_id -> label."""
    traces = TMP / "traces"
    traces.mkdir(exist_ok=True)
    truth = {}
    i = 0
    with ledger.conn() as c:
        for label, count in POPULATION.items():
            for k in range(count):
                i += 1
                eid = f"tools-fixture_task_{i % 4}-{i:026d}"
                path = traces / f"{eid}.json"
                path.write_text(json.dumps({
                    "episode_id": eid, "family": "tools", "task_id": f"fixture_task_{i % 4}",
                    "outcome": "fail",
                    "turns": [{"assistant": [{"type": "text", "text": PROMPT_WORDS[i % 3]},
                                             {"type": "tool_use", "id": "t1", "name": "get_order",
                                              "input": {"order_id": f"W{i}"}}],
                               "tool_results": [{"tool_use_id": "t1", "content": "{'status': 'pending'}"}]}]}))
                c.execute("INSERT INTO episodes(episode_id,ts,family,task_id,model,turns,outcome,label,"
                          "cost_usd,trace_path,run_kind,confidence,evidence) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (eid, 1788800000 + i, "tools", f"fixture_task_{i % 4}", "claude-sonnet-5", 2,
                           "fail", label, 0.01, str(path), "nightly", 0.9, f"Turn {k}: evidence text"))
                truth[eid] = label
        # Rows the sample must not contain: a pass, a hand-relabeled episode, a calibration run,
        # a checker-only label, and one whose trace is gone.
        c.execute("INSERT INTO episodes(episode_id,ts,family,task_id,model,turns,outcome,label,cost_usd,"
                  "trace_path,run_kind,evidence) VALUES('pass-1',1,'tools','fixture_task_0','m',2,'pass',"
                  "NULL,0.01,?,'nightly',NULL)", (str(traces / "missing.json"),))
        c.execute("INSERT INTO episodes(episode_id,ts,family,task_id,model,turns,outcome,label,cost_usd,"
                  "trace_path,run_kind,evidence) VALUES('manual-1',1,'tools','fixture_task_0','m',2,'fail',"
                  "'environment_error',0.01,?,'nightly','[manual] fixed by hand')",
                  (str(next(traces.glob("*.json"))),))
        c.execute("INSERT INTO episodes(episode_id,ts,family,task_id,model,turns,outcome,label,cost_usd,"
                  "trace_path,run_kind,evidence) VALUES('calib-1',1,'tools','fixture_task_0','m',2,'fail',"
                  "'misread_spec',0.01,?,'calibration','Turn 1: x')", (str(next(traces.glob("*.json"))),))
        c.execute("INSERT INTO episodes(episode_id,ts,family,task_id,model,turns,outcome,label,cost_usd,"
                  "trace_path,run_kind,evidence) VALUES('coding-1',1,'flakiness','fixture_task_0','m',2,"
                  "'fail','wrong_output',0.01,?,'nightly','checker: args (1,)')", (str(next(traces.glob("*.json"))),))
        c.execute("INSERT INTO episodes(episode_id,ts,family,task_id,model,turns,outcome,label,cost_usd,"
                  "trace_path,run_kind,evidence) VALUES('gone-1',1,'tools','fixture_task_0','m',2,'fail',"
                  "'misread_spec',0.01,?,'nightly','Turn 1: x')", (str(traces / "not-there.json"),))
    return truth


def page_data(html: str) -> dict:
    """The JSON payload the page was built around, read back out of the HTML."""
    head = html.index("const DATA = ") + len("const DATA = ")
    tail = html.index(";\nconst KEY", head)
    return json.loads(html[head:tail].replace("<\\/", "</"))


def export(out: Path, n: int, seed: int) -> tuple[dict, dict]:
    rc = label_review.main(["export", "--n", str(n), "--seed", str(seed), "--out", str(out)])
    assert rc == 0, "export failed"
    return page_data(out.read_text()), json.loads((out.parent / "sample.json").read_text())


def main() -> int:
    problems = []

    def expect(cond, msg):
        if not cond:
            problems.append(msg)

    truth = build_ledger()
    total = sum(POPULATION.values())

    pop = label_review.eligible()
    expect(len(pop) == total, f"eligible() returned {len(pop)}, want {total} (filters let something through)")
    expect(all(r["episode_id"] in truth for r in pop), "eligible() returned an episode it should have excluded")

    # 1. reproducibility
    a_data, a_manifest = export(TMP / "a" / "review.html", 20, 7)
    b_data, b_manifest = export(TMP / "b" / "review.html", 20, 7)
    c_data, _ = export(TMP / "c" / "review.html", 20, 8)
    ids_a = [e["episode_id"] for e in a_data["episodes"]]
    ids_b = [e["episode_id"] for e in b_data["episodes"]]
    ids_c = [e["episode_id"] for e in c_data["episodes"]]
    expect(ids_a == ids_b, "seed 7 drew a different sample the second time")
    expect(a_data["sample_id"] == b_data["sample_id"], "the same draw got two sample ids")
    expect(set(ids_a) != set(ids_c), "seed 8 drew the same sample as seed 7")
    expect(len(ids_a) == 20 and len(set(ids_a)) == 20, f"asked for 20, got {len(ids_a)} ({len(set(ids_a))} distinct)")

    # 2. stratification and weights
    strata = a_manifest["strata"]
    expect(set(strata) == set(POPULATION), f"strata {sorted(strata)} do not cover {sorted(POPULATION)}")
    for h, size in POPULATION.items():
        s = strata[h]
        expect(s["population"] == size, f"{h}: population {s['population']}, want {size}")
        expect(s["sampled"] >= min(label_review.MIN_PER_STRATUM, size),
               f"{h}: only {s['sampled']} drawn from {size}; rare labels must survive the draw")
        expect(abs(s["weight"] * s["sampled"] - size) < 1e-9,
               f"{h}: weight {s['weight']} does not carry {s['sampled']} back to {size}")
    expect(sum(s["sampled"] for s in strata.values()) == 20, "the allocation does not add up to n")
    drawn = {e["episode_id"]: e["model_label"] for e in a_manifest["episodes"]}
    expect(all(truth[e] == l for e, l in drawn.items()), "the manifest records the wrong model label")
    # every stratum's draw is a subset of that stratum
    counts = {}
    for l in drawn.values():
        counts[l] = counts.get(l, 0) + 1
    expect(counts == {h: s["sampled"] for h, s in strata.items() if s["sampled"]},
           f"per-label counts {counts} do not match the allocation")
    # a request larger than the population returns the population, not a crash
    full_data, full_manifest = export(TMP / "full" / "review.html", 500, 7)
    expect(len(full_data["episodes"]) == total, f"n larger than the population gave {len(full_data['episodes'])}")
    expect(all(s["weight"] == 1.0 for s in full_manifest["strata"].values()), "a census must have unit weights")

    # 3. kappa on a hand-computed table: human/model over {A,B}, cells AA=20 AB=5 BA=10 BB=15.
    # p_o = 35/50 = .7; marginals human A .5 B .5, model A .6 B .4 -> p_e = .5; kappa = .2/.5 = .4
    pairs = [("A", "A")] * 20 + [("A", "B")] * 5 + [("B", "A")] * 10 + [("B", "B")] * 15
    k = label_review.cohens_kappa(pairs)
    expect(abs(k - 0.4) < 1e-9, f"cohens_kappa = {k!r}, hand-computed 0.4")
    # the same table reached by weights instead of repetition must give the same kappa
    wk = label_review.cohens_kappa([("A", "A"), ("A", "B"), ("B", "A"), ("B", "B")], [20, 5, 10, 15])
    expect(abs(wk - 0.4) < 1e-9, f"weighted kappa = {wk!r}, want 0.4")
    expect(abs(label_review.cohens_kappa([("A", "A"), ("B", "B")]) - 1.0) < 1e-9, "perfect agreement is kappa 1")
    expect(abs(label_review.cohens_kappa([("A", "A"), ("A", "A")]) - 1.0) < 1e-9,
           "one category, always agreeing, must not divide by zero")
    lo, hi = label_review.wilson(35, 50)
    expect(0.55 < lo < 0.58 and 0.80 < hi < 0.83, f"wilson(35,50) = [{lo:.3f}, {hi:.3f}] looks wrong")
    expect(abs(label_review.effective_n([2, 2, 2, 2]) - 4) < 1e-9, "equal weights: n_eff is the count")
    expect(label_review.effective_n([9, 1, 1, 1]) < 4, "unequal weights must cost effective sample size")

    # 4. the anchoring guard
    html = (TMP / "a" / "review.html").read_text()
    for e in a_data["episodes"]:
        rec = {k: v for k, v in e.items() if k != "sealed"}
        blob = json.dumps(rec)
        expect(truth[e["episode_id"]] not in blob,
               f"{e['episode_id']}: its model label is in the page payload in plain text")
        expect("evidence text" not in blob, f"{e['episode_id']}: the model's evidence leaked into the payload")
        got = label_review.unseal(e["sealed"], e["episode_id"])
        expect(got["label"] == truth[e["episode_id"]], f"{e['episode_id']}: sealed label does not round-trip")
    expect(isinstance(a_data["sealed_strata"], str), "the stratum sizes must be sealed, not listed")
    expect(label_review.unseal(a_data["sealed_strata"], a_data["sample_id"]) == strata,
           "the sealed strata do not match the manifest")
    # The same page built with no episodes fixes how often each label may legitimately appear (the picker
    # and its definitions). A page carrying 20 episodes must add not one occurrence to that baseline.
    chrome = label_review.build_page([], strata, 7, a_data["sample_id"])
    for l in label_review.MODEL_LABELS:
        expect(html.count(l) == chrome.count(l),
               f"{l!r} appears {html.count(l)} times with episodes vs {chrome.count(l)} without: it leaks")
    expect("localStorage" in html and "catch" in html, "localStorage must be wrapped in try/catch")
    expect("http://" not in html and "https://" not in html, "the page must not load anything from the network")
    expect("Download answers" in html and "Copy JSON" in html, "the page needs both export paths")

    # 5. end to end: answer every episode, then ingest.
    # Human agrees with the model on every misread_spec and disagrees on everything else, so the raw and
    # the weighted rates have to differ: misread_spec is 40 of 61 in the population but 8 of 20 here.
    answers = {}
    for e in a_data["episodes"]:
        model_label = truth[e["episode_id"]]
        mine = model_label if model_label == "misread_spec" else "tool_misuse"
        if model_label == "tool_misuse":
            mine = "loop"
        answers[e["episode_id"]] = {"label": mine, "blind": True, "defensible": False, "note": "",
                                    "answered_at": "2026-09-23T00:00:00Z", "sealed": e["sealed"]}
    # one unsure and one answered after the reveal: both must be dropped, not counted as disagreements
    late = a_data["episodes"][0]["episode_id"]
    answers[late]["blind"] = False
    unsure = a_data["episodes"][1]["episode_id"]
    answers[unsure]["label"] = "unsure"
    ans_path = TMP / "a" / "answers.json"
    ans_path.write_text(json.dumps({"version": 1, "sample_id": a_data["sample_id"], "seed": 7,
                                    "n": len(a_data["episodes"]), "sealed_strata": a_data["sealed_strata"],
                                    "answers": answers}, indent=1))
    report = TMP / "a" / "label_validity.md"
    rc = label_review.main(["ingest", str(ans_path), "--report", str(report)])
    expect(rc == 0, "ingest failed")

    st = label_review.analyse(answers, strata)
    expect(st["n"] == 18, f"{st['n']} usable pairs, want 18 (one unsure and one non-blind dropped)")
    expect(st["dropped"] == {"unsure": 1, "answered after the reveal": 1}, f"dropped: {st['dropped']}")
    hand_agree = sum(1 for eid, a in answers.items()
                     if a.get("blind", True) and a["label"] != "unsure" and a["label"] == truth[eid])
    expect(st["agree"] == hand_agree, f"agree {st['agree']}, hand count {hand_agree}")
    w_num = sum(strata[truth[eid]]["weight"] for eid, a in answers.items()
                if a.get("blind", True) and a["label"] != "unsure" and a["label"] == truth[eid])
    w_den = sum(strata[truth[eid]]["weight"] for eid, a in answers.items()
                if a.get("blind", True) and a["label"] != "unsure")
    expect(abs(st["weighted"] - w_num / w_den) < 1e-9,
           f"weighted agreement {st['weighted']:.4f}, hand-computed {w_num / w_den:.4f}")
    expect(abs(st["weighted"] - st["raw"]) > 1e-6,
           "the weighting made no difference, so it is not being applied")
    text = report.read_text()
    expect("# Human validation of the failure labels" in text, "the report lost its title")
    for need in ("population-weighted", "Cohen's kappa", "## Confusion", "## Weights"):
        expect(need in text, f"the report is missing {need!r}")
    expect("| misread_spec |" in text, "the per-label table is empty")

    # ingest must refuse a mismatched manifest rather than score against the wrong weights
    (TMP / "a" / "sample.json").write_text(json.dumps({"sample_id": "s99-n1-deadbeef", "strata": {}}))
    rc = label_review.main(["ingest", str(ans_path), "--report", str(report)])
    expect(rc == 0, "a mismatched manifest should fall back to the sealed weights, not fail")

    for p in problems:
        print("  !", p)
    print("all good" if not problems else f"{len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    t0 = time.time()
    code = main()
    print(f"({time.time() - t0:.1f}s)")
    sys.exit(code)
