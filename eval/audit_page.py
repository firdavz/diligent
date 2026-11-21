"""Build the audit-trail viewer page from the latest traces.   python3 eval/audit_page.py <out.html> [runs_dir]

Picks example cases the system gets right (against eval/labels), several per institution across CLOSE / RFI / ESCALATE,
and lays each decision out as the yes/no questions the rulebook asks per alert, with the SOP clause, facts and evidence
behind each answer. If runs_dir holds r_<institution>_<n>.jsonl files from repeated runs, their fingerprints are shown
as the reproducibility proof.
"""

import glob
import hashlib
import json
import os
import sys

from _common import INSTITUTIONS, ROOT

NAME = {"bank": "Bank", "emoney": "E-money", "investment": "Investment", "payments_fx": "Payments and FX"}


def fp(path):
    return hashlib.sha256(open(path, encoding="utf-8").read().encode()).hexdigest()[:16]


def main(out, runs_dir=None):
    cases, repro, manifests = [], [], {}
    for inst in INSTITUTIONS:
        man = json.load(open(os.path.join(ROOT, "system", "traces", f"{inst}.manifest.json")))
        manifests[inst] = man
        labels = {json.loads(line)["case_id"]: json.loads(line) for line in open(os.path.join(ROOT, "eval", "labels", f"{inst}.jsonl"))}
        traces = [json.loads(line) for line in open(os.path.join(ROOT, "system", "traces", f"{inst}.jsonl"))]
        picked = {}
        for t in traces:
            lab = labels.get(t["case_id"])
            if not lab or lab["verdict"] != t["verdict"]:
                continue
            paths = {a["path"] for a in t["trace"].get("alerts", [])}
            key = t["verdict"]
            score = (len(paths - {"fallback"}) > 0, len(t["trace"].get("alerts", [])))
            if key not in picked or score > picked[key][0]:
                picked[key] = (score, t, lab)
        for verdict in ("CLOSE", "RFI", "ESCALATE"):
            if verdict in picked:
                _, t, lab = picked[verdict]
                cases.append({"institution": inst, "case_id": t["case_id"], "verdict": t["verdict"], "reason_code": t["reason_code"],
                              "reason": t["reason"], "evidence": t["evidence"], "alerts": t["trace"]["alerts"],
                              "audit": t["trace"].get("audit", {}), "label": {"verdict": lab["verdict"], "reason_code": lab["reason_code"]}})
        runs = sorted(glob.glob(os.path.join(runs_dir, f"r_{inst}_*.jsonl"))) if runs_dir else []
        repro.append({"institution": inst, "runs": [fp(p) for p in runs], "cases": man["cases"], "code_fp": man["code_fp"],
                      "policy_fp": man["policy_fp"], "models": man["models"]})
    data = json.dumps({"cases": cases, "repro": repro}, ensure_ascii=False).replace("</", "<\\/")
    html = open(os.path.join(ROOT, "eval", "audit_page_template.html"), encoding="utf-8").read().replace("__DATA__", data)
    open(out, "w", encoding="utf-8").write(html)
    print(f"{len(cases)} cases, {sum(len(r['runs']) for r in repro)} runs -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
