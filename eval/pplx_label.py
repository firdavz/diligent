"""Label cases with a decision model (also: <institution> <name> ID,ID,... for explicit cases) (free pplx-decider): verdict, then reason code, as SOP-worded choice questions.

python3 eval/pplx_label.py <institution> labelled            # calibrate: label our labelled cases, report agreement
python3 eval/pplx_label.py <institution> new <n_per_shape>   # label n unlabelled cases per case shape

Option wording is the institution's own: verdict definitions from POLICY.md, reason codes from the code table. Output goes
to eval/labels_model/<institution>.jsonl (source "pplx-decider"), never to eval/labels/: model labels point at rule gaps
and incongruences; they become ground truth only when a human confirms them on the review desk. Answers are cached in
eval/drafts/pplx/ so re-runs are free and identical. Needs OPENROUTER_API_KEY.
"""

import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request
from collections import defaultdict

from _common import ROOT, bundles, shape

KEY = os.environ["OPENROUTER_API_KEY"]
URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = os.environ.get("PPLX_MODEL", "perplexity/pplx-decider-v1.3:free")
CODE_GROUP = {"CLOSE": "CLOSE", "RFI": "RFI", "ESCALATE": "ESCALATE"}


def code_table() -> dict[str, dict[str, str]]:
    """{verdict: {code: 'use it when' text}} from the README's code table."""
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for m in re.finditer(r"^\|\s*(CLOSE|RFI|ESCALATE)\s*\|\s*`(\w+)`\s*\|\s*(.+?)\s*\|\s*$", open(os.path.join(ROOT, "data", "README.md")).read(), re.M):
        out[m[1]][m[2]] = m[3]
    return out


def verdict_defs(policy: str) -> dict[str, str]:
    out = {}
    for v in ("CLOSE", "RFI", "ESCALATE"):
        m = re.search(rf"^- \*\*{v}\*\*[^:]*:\s*(.+)$", policy, re.M)
        out[v] = m[1].strip() if m else v
    return out


def ask(questions: dict, state: dict, cache_path: str) -> dict | None:
    if os.path.exists(cache_path):
        return json.load(open(cache_path))
    body = json.dumps({"model": MODEL, "questions": questions, "state": state}).encode()
    req = urllib.request.Request(URL, body, {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    for wait in (5, 15, 30, 0):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                j = json.load(r)
            ans = j.get("answers")
            if ans:
                json.dump(ans, open(cache_path, "w"))
            return ans
        except Exception:
            if not wait:
                return None
            time.sleep(wait)


def pick(ans: dict, qid: str) -> tuple[str | None, float]:
    """A choice answer as (option, probability). Accepts {choice: name} or a {option: prob} map."""
    a = (ans or {}).get(qid) or {}
    if isinstance(a.get("choice"), str):
        probs = a.get("probabilities") or a.get("probs") or {}
        return a["choice"], float(probs.get(a["choice"], 1.0)) if isinstance(probs, dict) else 1.0
    probs = a.get("choice") if isinstance(a.get("choice"), dict) else {k: v for k, v in a.items() if isinstance(v, (int, float))}
    if not probs:
        return None, 0.0
    best = max(sorted(probs), key=lambda k: probs[k])
    return best, round(float(probs[best]), 2)


def label(inst: str, cid: str, policy: str, codes: dict, vdefs: dict) -> dict | None:
    text = subprocess.run([sys.executable, os.path.join(ROOT, "eval", "view.py"), cid], capture_output=True, text=True).stdout
    cache = os.path.join(ROOT, "eval", "drafts", "pplx", inst)
    os.makedirs(cache, exist_ok=True)
    state = {"sop": policy, "case_file": text}
    q1 = {"verdict": {"type": "choice", "instructions": "Applying this institution's SOP to the case file, which verdict is right for the case as a whole?",
                      "criteria": vdefs}}
    a1 = ask(q1, state, os.path.join(cache, f"{cid}.verdict.json"))
    v, pv = pick(a1, "verdict")
    if v not in codes:
        return None
    q2 = {"code": {"type": "choice", "instructions": f"The verdict is {v}. Which reason code is the main ground for it?",
                   "criteria": codes[v]}}
    a2 = ask(q2, state, os.path.join(cache, f"{cid}.code.{v}.json"))
    c, pc = pick(a2, "code")
    return {"case_id": cid, "verdict": v, "reason_code": c if c in codes[v] else None, "p_verdict": pv, "p_code": pc,
            "source": "pplx-decider", "model": MODEL}


def main():
    inst, mode = sys.argv[1], sys.argv[2]
    policy = open(os.path.join(ROOT, "data", "institutions", inst, "POLICY.md")).read()
    codes, vdefs = code_table(), verdict_defs(policy)
    labels = {json.loads(line)["case_id"]: json.loads(line) for line in open(os.path.join(ROOT, "eval", "labels", f"{inst}.jsonl"))}
    if mode == "labelled":
        ids = sorted(labels)
    elif len(sys.argv) > 3 and "," in sys.argv[3] or (len(sys.argv) > 3 and sys.argv[3].count("-") == 1 and not sys.argv[3].isdigit()):
        ids = sys.argv[3].split(",")  # explicit case IDs: python3 eval/pplx_label.py <inst> <name> ID,ID,...
    else:
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 2
        groups = defaultdict(list)
        for b in bundles(inst):
            if b.case["case_id"] not in labels:
                groups[shape(b)].append(b.case["case_id"])
        ids = []
        for sh, members in sorted(groups.items()):
            ids += random.Random(f"pplx{inst}{sh}").sample(sorted(members), min(n, len(members)))
    out = []
    for cid in ids:
        r = label(inst, cid, policy, codes, vdefs)
        if r:
            out.append(r)
            if cid in labels:
                r["agrees"] = r["verdict"] == labels[cid]["verdict"]
                r["code_agrees"] = r["reason_code"] == labels[cid]["reason_code"]
            print(cid, r["verdict"], r["reason_code"], r.get("agrees", ""), flush=True)
    os.makedirs(os.path.join(ROOT, "eval", "labels_model"), exist_ok=True)
    path = os.path.join(ROOT, "eval", "labels_model", f"{inst}.{mode}.jsonl")
    with open(path, "w") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in out)
    if mode == "labelled":
        got = [r for r in out if "agrees" in r]
        wrongful = sum(r["verdict"] == "CLOSE" and labels[r["case_id"]]["verdict"] != "CLOSE" for r in got)
        print(f"{inst}: verdict agrees {sum(r['agrees'] for r in got)}/{len(got)}, code agrees {sum(r['code_agrees'] for r in got)}/{len(got)}, "
              f"would-be wrongful closes {wrongful}")
    else:
        print(f"{inst}: {len(out)} new cases labelled -> {path}")


if __name__ == "__main__":
    main()
