"""Score an output file against hand labels, with the brief's cost table.

python3 eval/score.py <institution> [output file]      (labels: eval/labels/<institution>.jsonl)
python3 eval/score.py --consistency <run1.jsonl> <run2.jsonl> ...

Label line: {"case_id": "...", "verdict": "CLOSE|RFI|ESCALATE", "reason_code": "...", "key_evidence": ["..."], "note": "..."}
"""

import json
import os
import sys

from _common import ROOT

COST = {  # (right, sent) -> cost
    ("CLOSE", "CLOSE"): 0, ("CLOSE", "RFI"): 3, ("CLOSE", "ESCALATE"): 3,
    ("RFI", "CLOSE"): 10, ("RFI", "RFI"): 0, ("RFI", "ESCALATE"): 2,
    ("ESCALATE", "CLOSE"): 10, ("ESCALATE", "RFI"): 3, ("ESCALATE", "ESCALATE"): 0,
}


def rows(path):
    with open(path) as f:
        return {r["case_id"]: r for r in (json.loads(line) for line in f if line.strip())}


def score(inst, out):
    labels = rows(os.path.join(ROOT, "eval", "labels", f"{inst}.jsonl"))
    preds = rows(out)
    n = len(labels)
    cost = base = wrongful = closable = closed = code_ok = ev_ok = 0
    misses = []
    for cid, lab in labels.items():
        right = lab["verdict"]
        p = preds.get(cid, {"verdict": "ESCALATE", "reason_code": "", "evidence": []})
        sent = p["verdict"]
        cost += COST[(right, sent)]
        base += COST[(right, "ESCALATE")]
        wrongful += sent == "CLOSE" and right != "CLOSE"
        closable += right == "CLOSE"
        closed += right == "CLOSE" and sent == "CLOSE"
        if right == sent:
            code_ok += p["reason_code"] == lab.get("reason_code")
            key = set(lab.get("key_evidence", []))
            ev_ok += bool(key) and key <= set(p.get("evidence", []))
        else:
            misses.append(f"  {cid}: right {right} ({lab.get('reason_code')}), sent {sent} ({p['reason_code']})"
                          + (f"  — {lab['note']}" if lab.get("note") else ""))
    saved = (base - cost) / base if base else 0
    right_n = n - len(misses)
    print(f"{inst}: {n} labelled  verdict score {saved:.0%} of escalate-all cost saved  cost/case {cost / max(n, 1):.2f}")
    print(f"  WRONGFUL CLOSES: {wrongful}   closable closed: {closed}/{closable}   "
          f"right verdicts: {right_n}/{n}   right code: {code_ok}/{right_n}   key evidence cited: {ev_ok}/{right_n}")
    print("\n".join(misses))


def consistency(paths):
    runs = [rows(p) for p in paths]
    ids = set().union(*runs)
    same = sum(1 for i in ids if len({(r.get(i, {}).get("verdict"), r.get(i, {}).get("reason_code")) for r in runs}) == 1)
    print(f"{same}/{len(ids)} cases identical (verdict + code) across {len(runs)} runs")


if __name__ == "__main__":
    if sys.argv[1] == "--consistency":
        consistency(sys.argv[2:])
    else:
        inst = sys.argv[1]
        score(inst, sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "output", f"{inst}.jsonl"))
