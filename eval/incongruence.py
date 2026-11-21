"""Find incongruences: cases where the team label, the blind model label and the system disagree.

python3 eval/incongruence.py [--model anthropic_claude-sonnet-5.5] [--json out.json]

Reads the blind model's cached answers (eval/drafts/llm/<institution>/<model>/*.json, from eval/llm_label.py),
the team labels (eval/labels/) and the latest system traces (system/traces/). Reports, per institution:
  label vs model    labelled cases where the blind model's verdict differs from ours (a label worth a second look)
  shape conflict    unlabelled cases where the model's verdict differs from the verdict our labels give that case
                    shape (either the shape hides a second story, or the model is wrong)
  model vs system   cases where the model and our labels agree but the system says otherwise (a rule to fix)
"""

import argparse
import json
import os
from collections import Counter, defaultdict

from _common import INSTITUTIONS, ROOT, bundles, shape


def load_model(inst: str, model: str) -> dict:
    d = os.path.join(ROOT, "eval", "drafts", "llm", inst, model)
    out = {}
    if os.path.isdir(d):
        for name in os.listdir(d):
            try:
                r = json.load(open(os.path.join(d, name)))
            except Exception:
                continue
            if isinstance(r, dict) and r.get("valid", True) and r.get("verdict"):
                out[r["case_id"]] = r
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="anthropic_claude-sonnet-5.5")
    ap.add_argument("--json")
    a = ap.parse_args()
    found = []
    for inst in INSTITUTIONS:
        labels = {json.loads(line)["case_id"]: json.loads(line) for line in open(os.path.join(ROOT, "eval", "labels", f"{inst}.jsonl"))}
        model = load_model(inst, a.model)
        system = {}
        tpath = os.path.join(ROOT, "system", "traces", f"{inst}.jsonl")
        for line in open(tpath):
            r = json.loads(line)
            system[r["case_id"]] = r
        shapes, shape_verdict = {}, {}
        votes = defaultdict(Counter)
        for b in bundles(inst):
            shapes[b.case["case_id"]] = shape(b)
        for cid, lab in labels.items():
            votes[shapes[cid]][lab["verdict"]] += 1
        for sh, c in votes.items():
            shape_verdict[sh] = c.most_common(1)[0][0] if len(c) == 1 else None  # mixed shapes give no expectation

        n_lab = n_new = 0
        for cid, m in sorted(model.items()):
            sys_v = system.get(cid, {}).get("verdict")
            if cid in labels:
                n_lab += 1
                lab = labels[cid]
                if m["verdict"] != lab["verdict"]:
                    found.append({"institution": inst, "case_id": cid, "kind": "label vs model", "team": lab["verdict"],
                                  "team_code": lab["reason_code"], "model": m["verdict"], "model_code": m.get("reason_code"),
                                  "system": sys_v, "model_says": m.get("rationale", "")[:400], "team_says": lab.get("note", "")})
                elif sys_v != lab["verdict"] and system.get(cid, {}).get("trace", {}).get("alerts") and \
                        any(x["path"] != "fallback" for x in system[cid]["trace"]["alerts"]):
                    found.append({"institution": inst, "case_id": cid, "kind": "model vs system", "team": lab["verdict"],
                                  "team_code": lab["reason_code"], "model": m["verdict"], "model_code": m.get("reason_code"),
                                  "system": sys_v, "model_says": m.get("rationale", "")[:400], "team_says": lab.get("note", "")})
            else:
                n_new += 1
                expect = shape_verdict.get(shapes.get(cid))
                if expect and m["verdict"] != expect:
                    found.append({"institution": inst, "case_id": cid, "kind": "shape conflict", "team": expect,
                                  "team_code": "", "model": m["verdict"], "model_code": m.get("reason_code"),
                                  "system": sys_v, "model_says": m.get("rationale", "")[:400],
                                  "team_says": f"Every labelled case of this shape is {expect}."})
        mine = [f for f in found if f["institution"] == inst]
        print(f"{inst}: model answered {n_lab} labelled + {n_new} new cases -> "
              f"{sum(f['kind'] == 'label vs model' for f in mine)} label vs model, "
              f"{sum(f['kind'] == 'shape conflict' for f in mine)} shape conflicts, "
              f"{sum(f['kind'] == 'model vs system' for f in mine)} model vs system")
    for f in found:
        print(f"  [{f['kind']}] {f['case_id']}: team {f['team']} {f['team_code']} | model {f['model']} {f['model_code']} | system {f['system']}")
    if a.json:
        json.dump(found, open(a.json, "w"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
