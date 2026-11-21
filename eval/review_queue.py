"""Build the review queue for the Label Review Desk artifact.

python3 eval/review_queue.py <out_dir>    -> one JSON file per case, ready for ArtifactData batch writes
python3 eval/review_queue.py --apply <decisions.json>   -> fold reviewers' decisions back into eval/labels/

A case is queued when its label is not high confidence ("doubtful label"), when a non-fallback rule in the system
disagrees with the label ("system disagrees": a rule bug or a wrong label), or when the system closes a case the
label says not to ("wrongful close"). Run system/run for all institutions first so the traces are current.
"""

import json
import os
import subprocess
import sys

from _common import INSTITUTIONS, PREFIX, ROOT


def queue(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    for name in os.listdir(out_dir):
        os.remove(os.path.join(out_dir, name))
    n = 0
    for inst in INSTITUTIONS:
        labels = [json.loads(line) for line in open(os.path.join(ROOT, "eval", "labels", f"{inst}.jsonl"))]
        traces = {}
        for line in open(os.path.join(ROOT, "system", "traces", f"{inst}.jsonl")):
            r = json.loads(line)
            traces[r["case_id"]] = r
        for lab in labels:
            t = traces[lab["case_id"]]
            paths = {a["path"] for a in t["trace"].get("alerts", [])}
            why = []
            if lab.get("confidence", "high") != "high":
                why.append("doubtful label")
            if t["verdict"] != lab["verdict"] and paths - {"fallback"}:
                why.append("system disagrees")
            if t["verdict"] == "CLOSE" and lab["verdict"] != "CLOSE":
                why.append("wrongful close")
            if not why:
                continue
            text = subprocess.run([sys.executable, os.path.join(ROOT, "eval", "view.py"), lab["case_id"]],
                                  capture_output=True, text=True, cwd=ROOT).stdout
            doc = {
                "case_id": lab["case_id"], "institution": inst, "why": why,
                "label": {k: lab.get(k) for k in ("verdict", "reason_code", "key_evidence", "confidence", "note")},
                "system": {"verdict": t["verdict"], "reason_code": t["reason_code"], "reason": t["reason"],
                           "path": sorted(paths)},
                "case_text": text,
            }
            with open(os.path.join(out_dir, f"{lab['case_id']}.json"), "w") as f:
                json.dump(doc, f, ensure_ascii=False)
            n += 1
    print(f"{n} cases queued in {out_dir}", file=sys.stderr)


def apply(decisions_path: str) -> None:
    """decisions.json: {case_id: {verdict, reason_code, note, agree}} as read from the artifact's decisions collection."""
    decisions = json.load(open(decisions_path))
    for inst in INSTITUTIONS:
        path = os.path.join(ROOT, "eval", "labels", f"{inst}.jsonl")
        labels = [json.loads(line) for line in open(path)]
        changed = 0
        for lab in labels:
            d = decisions.get(lab["case_id"])
            if not d:
                continue
            if not d.get("agree"):
                lab["verdict"], lab["reason_code"] = d["verdict"], d["reason_code"]
                changed += 1
            lab["confidence"] = "high"
            lab["reviewed"] = True
            if d.get("note"):
                lab["note"] = f"{lab.get('note', '')} [review: {d['note']}]".strip()
        known = {lab["case_id"] for lab in labels}
        added = 0
        for cid, d in sorted(decisions.items()):  # cases labelled for the first time on the desk ("Label new cases")
            if cid in known or d.get("institution", PREFIX.get(cid[:2])) != inst:
                continue
            labels.append({"case_id": cid, "verdict": d["verdict"], "reason_code": d["reason_code"], "key_evidence": [],
                           "confidence": "high", "note": d.get("note", ""), "source": "review desk", "reviewed": True})
            added += 1
        with open(path, "w") as f:
            f.writelines(json.dumps(lab, ensure_ascii=False) + "\n" for lab in labels)
        print(f"{inst}: {changed} labels changed, {added} new labels added", file=sys.stderr)


if __name__ == "__main__":
    if sys.argv[1] == "--apply":
        apply(sys.argv[2])
    else:
        queue(sys.argv[1])
