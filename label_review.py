"""Hand-label a sample of tool-use failures, then turn the answers into a validity statistic.

Every tool failure in the corpus carries one model's label (Opus 5). The 2026-09-14 audit only compared
two models to each other: 64% agreement says the labels are reproducible, not that the taxonomy is
applied correctly. Nothing here has ever been checked by a human, which is the paper's largest validity
gap. This script closes it without spending anything:

    python label_review.py export --n 100 --seed 7     # -> review/review.html + review/sample.json
    open review/review.html                            # label by hand, download review/answers.json
    python label_review.py ingest review/answers.json  # -> paper/label_validity.md

The sample is stratified by the model's label, because three of the five labels in the population are
too rare to survive a simple random draw. Stratification distorts the marginals, so every stratum also
carries its weight N_h/n_h and the headline numbers are the population-corrected ones.

The reviewer must not see the model's label until their own is committed, or the study measures
deference rather than validity. The model's label, confidence and evidence are therefore sealed in the
page (XOR + base64) and unsealed by the page only after an answer is recorded.

Stdlib only, read-only on the ledger, no API calls.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from corpus import labeler                                      # noqa: E402
from corpus import ledger                                       # noqa: E402
from corpus import publisher                                    # noqa: E402

# Only labels a model may assign are reviewable. Coding failures are labeled from the checker and are not
# judgment calls, so they are not part of the question this study asks.
MODEL_LABELS: list[str] = list(labeler.LABEL_DEFINITIONS)
MIN_PER_STRATUM = 3
REVIEW_DIR = ROOT / "review"
REPORT = ROOT / "paper" / "label_validity.md"
UNSURE = "unsure"


# ---------------------------------------------------------------------------- statistics

def wilson(k: float, n: float, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for k successes in n trials. k and n may be non-integer: a weighted estimate
    is passed through here as (p * n_eff, n_eff)."""
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def effective_n(weights: Sequence[float]) -> float:
    """Kish's effective sample size. Unequal weights buy less precision than their count suggests, so the
    weighted intervals are computed on this rather than on len(weights)."""
    if not weights:
        return 0.0
    s = sum(weights)
    sq = sum(w * w for w in weights)
    return (s * s / sq) if sq else 0.0


def cohens_kappa(pairs: Sequence[tuple[str, str]], weights: Sequence[float] | None = None) -> float:
    """Cohen's kappa for (human, model) label pairs, optionally weighted.

    Chance agreement uses each rater's own marginals, so the stratified sample must be weighted back to
    the population before kappa means anything: oversampling a rare label changes the model's marginal,
    and with it p_e.
    """
    if not pairs:
        return float("nan")
    w = list(weights) if weights is not None else [1.0] * len(pairs)
    total = sum(w)
    if total <= 0:
        return float("nan")
    cats = sorted({c for pair in pairs for c in pair})
    po = sum(wi for (a, b), wi in zip(pairs, w) if a == b) / total
    marg_a = {c: sum(wi for (a, _), wi in zip(pairs, w) if a == c) / total for c in cats}
    marg_b = {c: sum(wi for (_, b), wi in zip(pairs, w) if b == c) / total for c in cats}
    pe = sum(marg_a[c] * marg_b[c] for c in cats)
    if abs(1 - pe) < 1e-12:                                     # both raters constant and identical
        return 1.0 if abs(po - 1) < 1e-12 else 0.0
    return (po - pe) / (1 - pe)


# ---------------------------------------------------------------------------- sealing

def seal(obj: Any, key: str) -> str:
    """Reversible obfuscation of the model's verdict: XOR against the episode id, then base64.

    Not encryption, and not meant to be. The requirement is only that a reviewer cannot read the label
    off the screen, or trip over it in view-source, before committing their own. json.dumps is ASCII-only
    here, so the page can undo this with atob() and charCodeAt() and no library.
    """
    raw = json.dumps(obj, separators=(",", ":")).encode("ascii", "backslashreplace")
    kb = key.encode("ascii", "replace") or b"k"
    return base64.b64encode(bytes(b ^ kb[i % len(kb)] for i, b in enumerate(raw))).decode()


def unseal(blob: str, key: str) -> Any:
    """Inverse of seal(); used by ingest and by the tests."""
    raw = base64.b64decode(blob)
    kb = key.encode("ascii", "replace") or b"k"
    return json.loads(bytes(b ^ kb[i % len(kb)] for i, b in enumerate(raw)).decode("ascii"))


# ---------------------------------------------------------------------------- sampling

def eligible(nightly_only: bool = True) -> list[dict[str, Any]]:
    """Every tool-use failure whose label came from the labeler model and whose trace is still on disk.

    Excluded: checker-assigned labels (not judgment calls), the fourteen episodes already relabeled by
    hand (evidence '[manual]', same exclusion label_audit.py uses), and anything without a trace, since
    a reviewer cannot judge what they cannot read.
    """
    rows = ledger.conn().execute(
        "SELECT episode_id, ts, task_id, model, COALESCE(run_kind,'nightly'), outcome, turns, label, "
        "confidence, evidence, trace_path FROM episodes "
        "WHERE family='tools' AND outcome!='pass' AND label IS NOT NULL "
        "AND COALESCE(evidence,'') NOT LIKE '[manual]%' ORDER BY episode_id").fetchall()
    out = []
    for (eid, ts, task, model, run_kind, outcome, turns, label, conf, ev, path) in rows:
        if label not in MODEL_LABELS:
            continue
        if nightly_only and run_kind != "nightly":
            continue
        if not path or not Path(path).exists():
            continue
        out.append({"episode_id": eid, "ts": ts, "task_id": task, "model": model, "run_kind": run_kind,
                    "outcome": outcome, "turns": turns, "label": label, "confidence": conf,
                    "evidence": ev, "trace_path": path})
    return out


def allocate(sizes: dict[str, int], n: int, min_per: int = MIN_PER_STRATUM) -> dict[str, int]:
    """How many to draw from each stratum: a floor of min_per (or the whole stratum if smaller), then
    highest-averages (D'Hondt) for the rest, so the bulk of the sample still tracks the population.

    The floor is what makes the rare labels reviewable at all — wrong_target and gave_up have two and one
    episode in the whole corpus, and a proportional draw of 100 would miss both every time.
    """
    take = {h: min(min_per, sizes[h]) for h in sizes}
    # A sample smaller than the floors: give the units back, largest allocation first, keeping >=1 each.
    while sum(take.values()) > n:
        h = max(sorted(take), key=lambda k: (take[k], sizes[k]))
        if take[h] <= 1:
            drop = min(sorted(take), key=lambda k: (sizes[k], k))
            take.pop(drop)
            continue
        take[h] -= 1
    for _ in range(n - sum(take.values())):
        room = [h for h in sorted(take) if take[h] < sizes[h]]
        if not room:
            break
        take[max(room, key=lambda h: sizes[h] / (take[h] + 1))] += 1
    return take


def draw(pop: list[dict[str, Any]], n: int, seed: int) -> tuple[list[dict[str, Any]], dict[str, dict[str, float]]]:
    """A reproducible stratified sample and its stratum weights.

    Each stratum is drawn from its own seeded RNG so that adding data to one label does not reshuffle the
    others, and the presentation order is shuffled: episodes grouped by label would leak the stratum, and
    the stratum is the model's label.
    """
    by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in pop:
        by_label[row["label"]].append(row)
    sizes = {h: len(v) for h, v in by_label.items()}
    take = allocate(sizes, min(n, len(pop)))

    sample: list[dict[str, Any]] = []
    strata: dict[str, dict[str, float]] = {}
    for h in sorted(take):
        ids = sorted(r["episode_id"] for r in by_label[h])
        chosen = set(random.Random(f"{seed}|{h}").sample(ids, take[h]))
        sample += [r for r in by_label[h] if r["episode_id"] in chosen]
        # weight = how many population episodes each sampled one stands for.
        strata[h] = {"population": sizes[h], "sampled": take[h], "weight": sizes[h] / take[h]}
    for h, size in sizes.items():
        strata.setdefault(h, {"population": size, "sampled": 0, "weight": 0.0})
    random.Random(f"{seed}|order").shuffle(sample)
    return sample, strata


# ---------------------------------------------------------------------------- what a reviewer sees

def review_payload(sample: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Everything needed to judge an episode, and nothing that gives the model's answer away."""
    from corpus.tasks import load_family

    prompts = publisher._task_prompts()
    try:
        protos = {t.task_id: t for t in load_family("tools")}
    except Exception:                                           # a task module that will not import
        protos = {}

    out = []
    for row in sample:
        try:
            trace = json.loads(Path(row["trace_path"]).read_text())
        except Exception:
            trace = {}
        proto = protos.get(row["task_id"])
        try:
            checker = labeler._checker_detail(trace) if trace else None
        except Exception as e:                                  # a replay that blows up is worth seeing
            checker = f"replay failed: {e}"
        out.append({
            "episode_id": row["episode_id"],
            "task_id": row["task_id"],
            "model": row["model"],
            "outcome": row["outcome"],
            "turns": row["turns"],
            "when": datetime.datetime.fromtimestamp(row["ts"] or 0, datetime.timezone.utc).strftime("%Y-%m-%d %H:%MZ"),
            "prompt": prompts.get(row["task_id"], ""),
            "policy": getattr(proto, "system", "") if proto else "",
            "checker": checker or "",
            "shown_turns": publisher._compact_turns(trace),
            "sealed": seal({"label": row["label"], "confidence": row["confidence"],
                            "evidence": row["evidence"] or ""}, row["episode_id"]),
        })
    return out


# ---------------------------------------------------------------------------- the page

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Label review</title>
<style>
:root{--bg:#0b0d11;--panel:#131720;--line:#232a36;--fg:#d7dde7;--dim:#7c869a;--acc:#8ab4ff;--ok:#7ddc9a;--warn:#ffcf6b;--bad:#ff8f8f}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
header{position:sticky;top:0;z-index:5;background:var(--panel);border-bottom:1px solid var(--line);padding:10px 16px;
 display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{font-size:13px;margin:0;font-weight:600;letter-spacing:.04em}
.bar{flex:1;min-width:140px;height:5px;background:#000;border:1px solid var(--line);border-radius:3px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--acc)}
button{background:#1b2130;color:var(--fg);border:1px solid var(--line);border-radius:4px;padding:4px 9px;
 font:inherit;cursor:pointer}
button:hover{border-color:var(--acc)}
main{max-width:1080px;margin:0 auto;padding:16px}
.meta{color:var(--dim);display:flex;gap:14px;flex-wrap:wrap;margin-bottom:10px}
.meta b{color:var(--fg);font-weight:600}
section{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:12px 14px;margin-bottom:12px}
section>h2{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--dim);margin:0 0 8px}
pre{margin:0;white-space:pre-wrap;word-break:break-word}
.checker{color:var(--warn)}
.turn{border-top:1px solid var(--line);padding:8px 0}
.turn:first-of-type{border-top:0}
.tn{color:var(--dim)}
.call{margin:3px 0 3px 14px}
.call .nm{color:var(--acc)}
.call .res{color:var(--dim)}
.opts{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:6px}
.opt{display:flex;gap:8px;text-align:left;align-items:baseline;padding:6px 8px;width:100%}
.opt kbd{background:#000;border:1px solid var(--line);border-radius:3px;padding:0 5px;color:var(--acc)}
.opt .d{color:var(--dim);font-weight:400}
.opt.picked{border-color:var(--ok);color:var(--ok)}
.reveal{border-color:#33405a}
.hide{display:none}
.agree{color:var(--ok)}.dis{color:var(--bad)}
textarea{width:100%;background:#000;color:var(--fg);border:1px solid var(--line);border-radius:4px;
 font:inherit;padding:6px;resize:vertical}
footer{color:var(--dim);padding:0 16px 40px;max-width:1080px;margin:0 auto}
kbd{font:inherit}
</style></head>
<body>
<header>
  <h1>LABEL REVIEW</h1>
  <span id="pos" class="tn"></span>
  <div class="bar"><i id="fill" style="width:0"></i></div>
  <span id="count" class="tn"></span>
  <button id="prev">&larr; prev</button><button id="next">next &rarr;</button>
  <button id="dl">Download answers</button><button id="cp">Copy JSON</button>
  <span id="save" class="tn"></span>
</header>
<main>
  <div class="meta" id="meta"></div>
  <section><h2>Task prompt</h2><pre id="prompt"></pre></section>
  <section id="policybox"><h2>Policy / system</h2><pre id="policy"></pre></section>
  <section><h2>Checker replay</h2><pre id="checker" class="checker"></pre></section>
  <section><h2>Turns</h2><div id="turns"></div></section>
  <section><h2>Your label &mdash; press a number key</h2><div class="opts" id="opts"></div></section>
  <section id="revealbox" class="reveal hide">
    <h2>Model label (revealed after your answer)</h2>
    <pre id="reveal"></pre>
    <div style="margin-top:8px">
      <button id="defbtn"></button>
      <span class="tn"> &mdash; <kbd>a</kbd> marks the model's label defensible; it never replaces your own.</span>
    </div>
  </section>
  <section><h2>Note (optional)</h2><textarea id="note" rows="2"></textarea></section>
</main>
<footer>
  <p><kbd>1</kbd>..<kbd>9</kbd> pick a label &middot; <kbd>u</kbd> unsure &middot; <kbd>a</kbd> model's label was
  defensible (after the reveal) &middot; <kbd>x</kbd> clear this answer &middot; <kbd>&larr;</kbd> <kbd>&rarr;</kbd>
  move &middot; <kbd>n</kbd> next unanswered.</p>
  <p>Answers are kept in this browser as you go. Download <code>answers.json</code> into
  <code>review/</code> and run <code>python label_review.py ingest review/answers.json</code>.
  An answer given after you revealed the label is recorded as not blind and is left out of the headline
  number, so clearing and re-answering an episode does not quietly repair the statistic.</p>
</footer>
<script>
const DATA = __DATA__;
const KEY = "label-review:" + DATA.sample_id;
let answers = {}, idx = 0, shownAt = Date.now();

// localStorage throws in a private window and comes back empty after a clear; the review must survive both.
try { const raw = localStorage.getItem(KEY); if (raw) answers = JSON.parse(raw) || {}; } catch (e) { answers = {}; }
function save() {
  try { localStorage.setItem(KEY, JSON.stringify(answers)); el("save").textContent = ""; }
  catch (e) { el("save").textContent = "not saved in browser - download before closing"; }
}
function el(id) { return document.getElementById(id); }
function esc(s) { return String(s == null ? "" : s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }

function unseal(blob, key) {
  const raw = atob(blob); let out = "";
  for (let i = 0; i < raw.length; i++) out += String.fromCharCode(raw.charCodeAt(i) ^ key.charCodeAt(i % key.length));
  return JSON.parse(out);
}

function cur() { return DATA.episodes[idx]; }
function ans(e) { return answers[e.episode_id]; }

function renderTurns(e) {
  let h = "";
  for (const t of e.shown_turns) {
    h += '<div class="turn"><span class="tn">[' + t.i + ']</span> ' + esc(t.text);
    for (const c of t.calls) {
      h += '<div class="call"><span class="nm">' + esc(c.name) + '</span>(' + esc(c.input) + ')' +
           '<br><span class="res">&rarr; ' + esc(c.result) + '</span></div>';
    }
    h += "</div>";
  }
  if (e.turns > e.shown_turns.length) h += '<div class="turn tn">... ' + (e.turns - e.shown_turns.length) + ' further turns not shown</div>';
  return h || '<span class="tn">no turns recorded</span>';
}

function render() {
  const e = cur(), a = ans(e);
  shownAt = Date.now();
  el("pos").textContent = (idx + 1) + " / " + DATA.episodes.length;
  const done = Object.keys(answers).length;
  el("count").textContent = done + " answered";
  el("fill").style.width = (100 * done / DATA.episodes.length) + "%";
  el("meta").innerHTML = "<span><b>" + esc(e.task_id) + "</b></span><span>agent " + esc(e.model) +
    "</span><span>" + esc(e.outcome) + "</span><span>" + e.turns + " turns</span><span>" + esc(e.when) +
    "</span><span>" + esc(e.episode_id) + "</span>";
  el("prompt").textContent = e.prompt || "(prompt not found for this task)";
  el("policy").textContent = e.policy || "(no policy text)";
  el("policybox").style.display = e.policy ? "" : "none";
  el("checker").textContent = e.checker || "(no replay diff)";
  el("turns").innerHTML = renderTurns(e);

  let opts = "";
  DATA.labels.forEach((l, i) => {
    const picked = a && a.label === l.name ? " picked" : "";
    opts += '<button class="opt' + picked + '" data-label="' + l.name + '"><kbd>' + (i + 1) + '</kbd>' +
            '<span><b>' + l.name + '</b><br><span class="d">' + esc(l.definition) + '</span></span></button>';
  });
  opts += '<button class="opt' + (a && a.label === "unsure" ? " picked" : "") + '" data-label="unsure">' +
          '<kbd>u</kbd><span><b>unsure</b><br><span class="d">cannot tell from the trace; left out of the statistic</span></span></button>';
  el("opts").innerHTML = opts;
  for (const b of el("opts").children) b.onclick = () => choose(b.dataset.label);

  el("note").value = (a && a.note) || "";
  if (a) {
    const m = unseal(e.sealed, e.episode_id);
    const same = m.label === a.label;
    el("reveal").innerHTML = '<span class="' + (same ? "agree" : "dis") + '">' + esc(m.label) + "</span>" +
      (m.confidence == null ? "" : '  <span class="tn">confidence ' + esc(m.confidence) + "</span>") +
      "\n" + esc(m.evidence) + "\n\n" + (same ? "you agreed" : "you said " + esc(a.label)) +
      (a.blind ? "" : "\n(answered after the label was revealed - not counted as blind)");
    el("defbtn").textContent = a.defensible ? "[x] model's label defensible" : "[ ] model's label defensible";
    el("revealbox").classList.remove("hide");
  } else {
    el("revealbox").classList.add("hide");
  }
}

function choose(label) {
  const e = cur(), prev = ans(e);
  answers[e.episode_id] = {
    label: label,
    // An answer typed after the reveal is still worth keeping, but it is not blind and the report says so.
    blind: !prev,
    defensible: (prev && prev.defensible) || false,
    seconds: Math.round((Date.now() - shownAt) / 100) / 10,
    note: el("note").value,
    answered_at: new Date().toISOString(),
    sealed: e.sealed
  };
  save(); render();
}

function move(d) { idx = Math.min(DATA.episodes.length - 1, Math.max(0, idx + d)); render(); }
function nextUnanswered() {
  for (let i = 1; i <= DATA.episodes.length; i++) {
    const j = (idx + i) % DATA.episodes.length;
    if (!answers[DATA.episodes[j].episode_id]) { idx = j; render(); return; }
  }
}

function payload() {
  return JSON.stringify({
    version: 1, sample_id: DATA.sample_id, seed: DATA.seed, n: DATA.episodes.length,
    generated: DATA.generated, finished: new Date().toISOString(),
    sealed_strata: DATA.sealed_strata, answers: answers
  }, null, 1);
}

el("dl").onclick = () => {
  const b = new Blob([payload()], {type: "application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(b); a.download = "answers.json"; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
};
el("cp").onclick = async () => {
  const text = payload();
  try { await navigator.clipboard.writeText(text); el("save").textContent = "copied"; }
  catch (err) {
    // No clipboard permission (or a file:// page): fall back to something selectable.
    const w = window.open("", "_blank");
    if (w) { w.document.write("<pre></pre>"); w.document.querySelector("pre").textContent = text; }
    else { el("save").textContent = "copy blocked - use Download"; }
  }
};
el("prev").onclick = () => move(-1);
el("next").onclick = () => move(1);
el("note").onchange = () => { const a = ans(cur()); if (a) { a.note = el("note").value; save(); } };
el("defbtn").onclick = () => { const a = ans(cur()); if (a) { a.defensible = !a.defensible; save(); render(); } };

document.addEventListener("keydown", ev => {
  if (ev.target.tagName === "TEXTAREA" || ev.metaKey || ev.ctrlKey || ev.altKey) return;
  const k = ev.key;
  if (k >= "1" && k <= "9") { const l = DATA.labels[+k - 1]; if (l) { choose(l.name); ev.preventDefault(); } }
  else if (k === "u") choose("unsure");
  else if (k === "a") el("defbtn").click();
  else if (k === "x") { delete answers[cur().episode_id]; save(); render(); }
  else if (k === "ArrowLeft") move(-1);
  else if (k === "ArrowRight") move(1);
  else if (k === "n") nextUnanswered();
});

render();
</script>
</body></html>
"""


def build_page(episodes: list[dict[str, Any]], strata: dict[str, dict[str, float]],
               seed: int, sample_id: str) -> str:
    """The self-contained review page. The strata are sealed too: their sizes would tell a reviewer how
    common each label is in the sample, which is a softer version of the same anchoring problem."""
    data = {
        "sample_id": sample_id,
        "seed": seed,
        "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "labels": [{"name": k, "definition": v} for k, v in labeler.LABEL_DEFINITIONS.items()],
        "sealed_strata": seal(strata, sample_id),
        "episodes": episodes,
    }
    # "</" inside a <script> would close it early; json.dumps does not escape it.
    blob = json.dumps(data, indent=1).replace("</", "<\\/")
    return PAGE.replace("__DATA__", blob)


def sample_id(seed: int, n: int, episodes: Iterable[dict[str, Any]]) -> str:
    """Identifies one draw, so the page's saved answers cannot be mixed into another sample's.
    Hashed over the episode ids rather than seed alone: the same seed against a grown ledger is a
    different sample, and its localStorage key has to differ."""
    ids = ",".join(sorted(e["episode_id"] for e in episodes))
    return f"s{seed}-n{n}-{hashlib.sha256(ids.encode()).hexdigest()[:10]}"


# ---------------------------------------------------------------------------- commands

def cmd_export(args: argparse.Namespace) -> int:
    pop = eligible(nightly_only=not args.all_runs)
    if not pop:
        print("no labeled tool failures with a trace on disk; nothing to review")
        return 1
    sample, strata = draw(pop, args.n, args.seed)
    sid = sample_id(args.seed, len(sample), sample)
    episodes = review_payload(sample)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_page(episodes, strata, args.seed, sid))
    manifest = {
        "sample_id": sid, "seed": args.seed, "n": len(sample),
        "population": len(pop), "nightly_only": not args.all_runs,
        "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "strata": strata,
        # The model labels live here, not in the page: this file is the audit trail, and the reviewer
        # is not meant to open it until they are done.
        "episodes": [{"episode_id": r["episode_id"], "task_id": r["task_id"], "agent_model": r["model"],
                      "model_label": r["label"]} for r in sample],
    }
    Path(args.manifest or out.parent / "sample.json").write_text(json.dumps(manifest, indent=1))

    print(f"population {len(pop)} labeled tool failures"
          f"{' (nightly only)' if not args.all_runs else ''}, sampled {len(sample)} [{sid}]")
    for h in sorted(strata, key=lambda k: -strata[k]["population"]):
        s = strata[h]
        print(f"  {h:<18} {s['sampled']:>3} of {s['population']:>4}   weight {s['weight']:.2f}")
    print(f"wrote {out} and {args.manifest or out.parent / 'sample.json'}")
    return 0


def _pairs(answers: dict[str, Any], strata: dict[str, dict[str, float]],
           blind_only: bool = True) -> tuple[list[tuple[str, str]], list[float], dict[str, int]]:
    """(human, model) pairs, their weights, and what was dropped and why."""
    pairs: list[tuple[str, str]] = []
    weights: list[float] = []
    dropped = Counter()
    for eid, a in sorted(answers.items()):
        if not a.get("sealed"):
            dropped["no sealed model label"] += 1
            continue
        model_label = unseal(a["sealed"], eid)["label"]
        if a.get("label") == UNSURE:
            dropped["unsure"] += 1
            continue
        if blind_only and not a.get("blind", True):
            dropped["answered after the reveal"] += 1
            continue
        pairs.append((a["label"], model_label))
        weights.append(strata.get(model_label, {}).get("weight", 1.0))
    return pairs, weights, dict(dropped)


def analyse(answers: dict[str, Any], strata: dict[str, dict[str, float]]) -> dict[str, Any]:
    """Every number in the report: agreement raw and population-weighted, per label, kappa, confusion."""
    pairs, weights, dropped = _pairs(answers, strata)
    n = len(pairs)
    agree = sum(1 for a, b in pairs if a == b)
    raw_lo, raw_hi = wilson(agree, n)

    tot_w = sum(weights) or 1.0
    w_agree = sum(w for (a, b), w in zip(pairs, weights) if a == b)
    p_w = w_agree / tot_w
    n_eff = effective_n(weights)
    w_lo, w_hi = wilson(p_w * n_eff, n_eff)

    per: list[dict[str, Any]] = []
    for h in sorted({b for _, b in pairs} | set(strata)):
        sub = [(a, b) for a, b in pairs if b == h]
        k = sum(1 for a, b in sub if a == b)
        lo, hi = wilson(k, len(sub))
        pop = strata.get(h, {}).get("population", 0)
        per.append({"label": h, "n": len(sub), "agree": k, "population": pop,
                    "rate": (k / len(sub)) if sub else float("nan"), "lo": lo, "hi": hi})

    confusion = Counter((a, b) for a, b in pairs)
    disagreements = Counter(f"{b} -> {a}" for a, b in pairs if a != b)
    # Only counted where the human had already chosen something else: "defensible" on an episode they
    # agreed with anyway says nothing.
    defensible = sum(1 for eid, a in answers.items()
                     if a.get("defensible") and a.get("sealed")
                     and a.get("label") != unseal(a["sealed"], eid)["label"])
    return {
        "n": n, "agree": agree, "raw": (agree / n if n else float("nan")), "raw_ci": (raw_lo, raw_hi),
        "weighted": p_w, "weighted_ci": (w_lo, w_hi), "n_eff": n_eff,
        "kappa": cohens_kappa(pairs), "kappa_weighted": cohens_kappa(pairs, weights),
        "per_label": per, "confusion": confusion, "disagreements": dict(disagreements.most_common()),
        "dropped": dropped, "defensible": defensible, "answered": len(answers),
        "human_labels": Counter(a for a, _ in pairs), "model_labels": Counter(b for _, b in pairs),
    }


def _pct(p: float, lo: float, hi: float) -> str:
    if p != p:                                                  # NaN
        return "n/a"
    return f"{100 * p:.1f}% [{100 * lo:.1f}, {100 * hi:.1f}]"


def render_report(st: dict[str, Any], meta: dict[str, Any], strata: dict[str, dict[str, float]]) -> str:
    L = [
        "# Human validation of the failure labels",
        "",
        "Generated by `python label_review.py ingest review/answers.json`. One human relabeled a stratified",
        "sample of tool-use failures without seeing the labeler model's answer; the model is Opus 5.",
        "95% Wilson intervals in brackets.",
        "",
        "## Sample",
        "",
        "|  | value |",
        "|---|---|",
        f"| sample id | `{meta.get('sample_id', '?')}` |",
        f"| population (labeled tool failures) | {meta.get('population', '?')} |",
        f"| drawn | {meta.get('n', '?')} |",
        f"| answered | {st['answered']} |",
        f"| usable pairs (blind, not unsure) | {st['n']} |",
        f"| effective n after weighting | {st['n_eff']:.1f} |",
        "",
    ]
    if st["dropped"]:
        L += ["Dropped: " + ", ".join(f"{v} {k}" for k, v in sorted(st["dropped"].items())) + ".", ""]
    L += [
        "## Agreement",
        "",
        "| estimate | value |",
        "|---|---|",
        f"| in-sample | {st['agree']}/{st['n']} = {_pct(st['raw'], *st['raw_ci'])} |",
        f"| population-weighted | {_pct(st['weighted'], *st['weighted_ci'])} |",
        f"| Cohen's kappa (in-sample) | {st['kappa']:.3f} |",
        f"| Cohen's kappa (weighted) | {st['kappa_weighted']:.3f} |",
        "",
        "The weighted row is the one to quote. The sample is stratified by the model's label, so the",
        "in-sample rate over-represents the rare labels; the weights (N_h/n_h) put the population back.",
        "Kappa's chance term is built from each rater's marginals, so it is distorted the same way and the",
        "weighted kappa is likewise the one that describes the corpus.",
        "",
        "## Per model label",
        "",
        "Read a row as: of the failures the model called X, how often the human agreed.",
        "",
        "| model label | population | reviewed | agreed | rate |",
        "|---|---|---|---|---|",
    ]
    for r in st["per_label"]:
        if not r["n"] and not r["population"]:
            continue
        rate = _pct(r["rate"], r["lo"], r["hi"]) if r["n"] else "n/a"
        L.append(f"| {r['label']} | {r['population']} | {r['n']} | {r['agree']} | {rate} |")
    L += ["", "## Confusion", "", "Rows: the human's label. Columns: the model's.", ""]
    cols = sorted({b for _, b in st["confusion"]})
    rows = sorted({a for a, _ in st["confusion"]})
    L += ["| human \\ model | " + " | ".join(cols) + " |", "|---" * (len(cols) + 1) + "|"]
    for a in rows:
        L.append(f"| {a} | " + " | ".join(str(st["confusion"].get((a, b), 0) or "") for b in cols) + " |")
    L += ["", "Disagreements, model -> human: " + (str(st["disagreements"]) if st["disagreements"] else "none") + ".", ""]
    L += [
        "## Weights",
        "",
        "| stratum | population | sampled | weight |",
        "|---|---|---|---|",
    ]
    for h in sorted(strata, key=lambda k: -strata[k]["population"]):
        s = strata[h]
        L.append(f"| {h} | {int(s['population'])} | {int(s['sampled'])} | {s['weight']:.2f} |")
    L += [
        "",
        "## Reading this",
        "",
        f"Of the episodes the human labeled differently, {st['defensible']} were marked 'model's label",
        "defensible' once it was revealed. That is a softer standard than agreement and is reported only as",
        "context; the headline numbers use the blind answer alone.",
        "",
        "One reviewer, so this measures whether the taxonomy is applied correctly, not whether it is",
        "applied consistently between people. An answer given after the label was revealed is excluded",
        "rather than corrected, and 'unsure' is dropped rather than counted as a disagreement, which makes",
        "both numbers slightly optimistic.",
        "",
    ]
    return "\n".join(L)


def cmd_ingest(args: argparse.Namespace) -> int:
    path = Path(args.answers)
    doc = json.loads(path.read_text())
    answers = doc.get("answers") or {}
    if not answers:
        print(f"{path} has no answers")
        return 1

    strata: dict[str, dict[str, float]] = {}
    meta: dict[str, Any] = {"sample_id": doc.get("sample_id"), "n": doc.get("n", len(answers))}
    manifest_path = Path(args.manifest) if args.manifest else path.parent / "sample.json"
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text())
        # The manifest is authoritative when it matches: it also carries the population size.
        if not doc.get("sample_id") or m.get("sample_id") == doc.get("sample_id"):
            strata, meta = m.get("strata", {}), {**meta, **{k: m[k] for k in ("sample_id", "n", "population") if k in m}}
        else:
            print(f"warning: {manifest_path} is sample {m.get('sample_id')}, answers are {doc.get('sample_id')}; "
                  "using the weights carried in the answers file")
    if not strata and doc.get("sealed_strata"):
        strata = unseal(doc["sealed_strata"], doc.get("sample_id", ""))
    if not strata:
        print("no stratum weights found: the answers carry none and sample.json is missing or mismatched")
        return 1

    st = analyse(answers, strata)
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(st, meta, strata))

    print(f"{st['answered']} answers, {st['n']} usable pairs"
          + (f" (dropped {st['dropped']})" if st["dropped"] else ""))
    print(f"in-sample agreement {st['agree']}/{st['n']} = {_pct(st['raw'], *st['raw_ci'])}")
    print(f"population-weighted  {_pct(st['weighted'], *st['weighted_ci'])}  (effective n {st['n_eff']:.1f})")
    print(f"kappa {st['kappa']:.3f} in-sample, {st['kappa_weighted']:.3f} weighted")
    if st["disagreements"]:
        print("model -> human:", st["disagreements"])
    print(f"wrote {out}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", help="ledger to read (default data/ledger.sqlite)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ex = sub.add_parser("export", help="draw a stratified sample and write the review page")
    ex.add_argument("--n", type=int, default=100)
    ex.add_argument("--seed", type=int, default=7)
    ex.add_argument("--out", default=str(REVIEW_DIR / "review.html"))
    ex.add_argument("--manifest", help="where to write the sample manifest (default alongside --out)")
    ex.add_argument("--all-runs", action="store_true", help="include calibration and aborted runs")
    ex.set_defaults(fn=cmd_export)

    ing = sub.add_parser("ingest", help="score the answers and write paper/label_validity.md")
    ing.add_argument("answers")
    ing.add_argument("--manifest", help="sample manifest (default sample.json beside the answers)")
    ing.add_argument("--report", default=str(REPORT))
    ing.set_defaults(fn=cmd_ingest)

    args = ap.parse_args(argv)
    if args.db:
        ledger.DB = Path(args.db)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
