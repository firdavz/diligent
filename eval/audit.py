"""Print one case's audit trail, from the last run's trace.   python3 eval/audit.py <case_id>

Shows: the decision, each alert's path through the rulebook, the SOP clauses it rests on (quoted from the
institution's POLICY.md), the facts and evidence behind it, any model answers, and the fingerprints that make it
reproducible.
"""

import json
import os
import sys
import textwrap

from _common import ROOT, institution_of

case_id = sys.argv[1]
inst = institution_of(case_id)
tdir = os.path.join(ROOT, "system", "traces")
row = next(r for r in map(json.loads, open(os.path.join(tdir, f"{inst}.jsonl"))) if r["case_id"] == case_id)
man = json.load(open(os.path.join(tdir, f"{inst}.manifest.json")))
w = lambda s, ind="      ": textwrap.fill(s, 110, initial_indent=ind, subsequent_indent=ind)  # noqa: E731

print(f"CASE {case_id}  [{inst}]\n")
print(f"  DECISION  {row['verdict']}  {row['reason_code']}")
print(w(row["reason"]))
print(f"      evidence: {', '.join(row['evidence'])}\n")

PATH = {"red_flag": "red flag found → ESCALATE", "explained": "explained by hard evidence → CLOSE",
        "partial": "partly explained, one item missing → RFI", "soft_only": "explained only by a model answer → RFI",
        "fallback": "no explainer and no red flag → the rule's default", "held_payment_invoice": "SOP invoice rule → RFI"}
tr = row["trace"]
for i, a in enumerate(tr["alerts"], 1):
    print(f"  STEP {i}  alert {a['alert_id']} ({a['rule_id']})  →  {a['verdict']}   [{PATH.get(a['path'], a['path'])}]")
    for s in a.get("sop", []):
        print(w("SOP: " + s.replace("**", "")))
    for src, code, fact in zip(a["deciding"], a.get("codes", []), a.get("facts", [])):
        print(w(f"{code} ({src}): {fact}"))
    print()

if tr.get("answers"):
    print("  MODEL ANSWERS (read prose only; never choose the verdict)")
    for ans in tr["answers"]:
        print(w(f"tier {ans.get('tier')} {ans.get('model')}: {ans.get('question')} → {ans.get('value')}  “{ans.get('quote', '')}”"))
    print()

worst = max(tr["alerts"], key=lambda a: {"CLOSE": 0, "RFI": 1, "ESCALATE": 2}[a["verdict"]])["verdict"] if tr["alerts"] else "-"
print(f"  CASE RULE  worst alert wins → {worst}; CLOSE needs hard evidence on every alert\n")
au = tr.get("audit", {})
print("  REPRODUCIBILITY")
print(f"      input_fp {au.get('input_fp')}   policy_fp {au.get('policy_fp')}   code_fp {man.get('code_fp')}")
print(f"      decision_fp {au.get('decision_fp')}   models: {man.get('models')}")
print("      Same input + same policy + same code ⇒ same decision_fp, every run.")
