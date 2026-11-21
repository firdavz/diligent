"""BinEval-style labelling: ask the SOP's atomic yes/no questions, let a fixed table decide (andrei/DECISIONS.md D21).

python3 eval/bineval.py [n_per_institution] [--ids ID,ID]

All questions for a case go in ONE decisions request (pplx-decider, free; Jev as fallback). Answers are probabilities;
>= 0.7 counts as yes. The table below turns them into a verdict and reason code: red flags first (ESCALATE), then a
document that explains the alerted activity (CLOSE, with the code from which kind of explanation fired), else RFI.
The 5x own-account rule is computed in code from the TM01 alert, never asked.

Reports agreement with our human labels, compares with the holistic labeller (eval/labels_model/*.labelled.jsonl) on
the same cases, and for every miss prints the answers so the responsible question can be reworded (BinEval's
self-improvement loop). Answers are cached in eval/drafts/bineval/ keyed by the question-bank version.
"""

import hashlib
import json
import os
import random
import subprocess
import sys
import time
import urllib.request

from _common import INSTITUTIONS, ROOT, bundles

KEY = os.environ["OPENROUTER_API_KEY"]
URL = "https://openrouter.ai/api/alpha/decisions"
MODELS = ["perplexity/pplx-decider-v1.3:free", "typesafe/jev-1.13"]
YES = 0.7

YN = {"true": "Yes: the case file clearly shows this.", "false": "No: the case file does not show this, or shows the opposite."}
EXPLANATIONS = {
    "collection": "A documented collection made on behalf of named people explains the payments (COLLECTION_DOCUMENTED)",
    "business_records": "Business records, such as takings or collection reports, reconcile to the activity (BUSINESS_RECORDS_RECONCILE)",
    "one_off_event": "A documented one-off event, such as a sale, an inheritance or a payout, explains the funds (DOCUMENTED_EVENT)",
    "invoice": "An invoice, contract or payment file matches the amount, payee and date (INVOICE_MATCHES)",
    "own_account": "The money moved between accounts the customer holds (OWN_ACCOUNT)",
    "group_company": "The counterparty is a verified company in the same group (GROUP_COMPANY)",
    "third_party_relationship": "A documented relationship, such as a gift letter, explains a third-party payer (THIRD_PARTY_DOCUMENTED)",
    "refund": "The money is a refund or return of an earlier payment (REFUND_OF_EARLIER_PAYMENT)",
    "returning_customer": "A re-verified customer resumed using a dormant account (RETURNING_CUSTOMER)",
    "none": "Nothing on file explains the alerted activity",
}
CODE_OF = {"collection": "COLLECTION_DOCUMENTED", "business_records": "BUSINESS_RECORDS_RECONCILE", "one_off_event": "DOCUMENTED_EVENT",
           "invoice": "INVOICE_MATCHES", "own_account": "OWN_ACCOUNT", "group_company": "GROUP_COMPANY",
           "third_party_relationship": "THIRD_PARTY_DOCUMENTED", "refund": "REFUND_OF_EARLIER_PAYMENT", "returning_customer": "RETURNING_CUSTOMER"}

QUESTIONS = {
    # explains (CLOSE side)
    "e_kind": {"type": "choice", "instructions": "Which explanation, if any, does a DOCUMENT on file (not only a chat or the customer's word) give for the activity the alerts raised?", "criteria": EXPLANATIONS},
    "e_amount": {"type": "noul", "instructions": "Does a document on file state an amount equal, to the penny, to the alerted transaction or the alerted total?", "criteria": YN},
    "e_party": {"type": "noul", "instructions": "Does that document name the customer as the party to it (seller, beneficiary, policyholder, account holder, buyer or client)?", "criteria": YN},
    "e_dated": {"type": "noul", "instructions": "Is that document dated on or before the alerted transaction it explains?", "criteria": YN},
    "e_all": {"type": "noul", "instructions": "Do the documents on file explain EVERY alert in the case, not just one of them?", "criteria": YN},
    "own_holds": {"type": "noul", "instructions": "Does a statement or document on file show that the customer holds the other account the money came from or went to?", "criteria": YN},
    # red flags (ESCALATE side)
    "r_fraud": {"type": "noul", "instructions": "Does another bank report that money paid into this account came from fraud or a scam?", "criteria": YN},
    "r_threshold": {"type": "noul", "instructions": "Does a note or chat show the customer asking about, or acting to stay under, a reporting, ID-check or invoice threshold?", "criteria": YN},
    "r_passthrough": {"type": "noul", "instructions": "Did money from unrelated third parties come in and leave again within days, with no documented purpose?", "criteria": YN},
    "r_contradict": {"type": "noul", "instructions": "Does the customer's story (chat or note) contradict the documents, the register or the transactions?", "criteria": YN},
    "r_invoice_mismatch": {"type": "noul", "instructions": "Do invoices on file fail to support the payments (different amounts, dated after the payments, or goods unrelated to the business)?", "criteria": YN},
    "r_corridor": {"type": "noul", "instructions": "Did money move to or from a higher-risk country the customer did not declare, with no document explaining it?", "criteria": YN},
    # internal list
    "l_same": {"type": "noul", "instructions": "Does the evidence show the internal-list party is the counterparty, or still controlled it on the payment date (as director or person with significant control)?", "criteria": YN},
    "l_diff": {"type": "noul", "instructions": "Does the evidence show the counterparty is a different person from the internal-list party (different date of birth, unit or identity)?", "criteria": YN},
}
sys.path.insert(0, os.path.join(ROOT, "system"))
from tm.load import parse_policy  # noqa: E402


def _clause(text: str, *words: str) -> str:
    """The POLICY.md bullet that contains all the words, quoted verbatim ('' if none)."""
    for line in text.splitlines():
        s = line.strip().lstrip("- ").strip()
        if s and all(w.lower() in s.lower() for w in words):
            return s
    return ""


def build_questions(policy_text: str, alerts: list[dict]) -> dict:
    """The SOP's own questions for this case: the generic bank above, each question carrying the clause it tests,
    plus one question per alert asking whether the evidence explains exactly what that rule measured."""
    pol = parse_policy(policy_text)
    q = json.loads(json.dumps(QUESTIONS))
    add = {
        "own_holds": _clause(policy_text, "own name elsewhere"),
        "l_same": _clause(policy_text, "internal list", "escalate"),
        "l_diff": _clause(policy_text, "internal list", "different party"),
        "r_corridor": _clause(policy_text, "higher-risk countries"),
        "r_threshold": _clause(policy_text, "cash reporting threshold") + " " + " ".join(
            f"{r}: {pol['rules'][r]['fires_when']}" for r in ("TM03", "TM05") if r in pol["rules"]),
        "e_all": "SOP: Close only when the evidence explains the activity. One case gets one verdict, even when several rules fired.",
        "e_kind": "SOP: an earlier review covers only what it describes; it does not explain new or larger activity.",
    }
    inv = _clause(policy_text, "invoice or contract on file")
    if inv:
        add["e_amount"] = inv
    for k, clause in add.items():
        if clause.strip():
            q[k]["instructions"] += f" (SOP: {clause.strip()})"
    for a in alerts:
        rule = pol["rules"].get(a["rule_id"])
        if rule:
            q[f"alert_{a['rule_id']}"] = {"type": "noul", "criteria": YN, "instructions":
                f"Alert {a['rule_id']} ({rule['name']}) fired because: {a.get('message', '')} The SOP rule: {rule['fires_when']} "
                "Does a document on file explain exactly this activity (amount, counterparty and dates)?"}
    return q


BANK_VERSION = "sop-" + hashlib.sha256(json.dumps(QUESTIONS, sort_keys=True).encode()).hexdigest()[:8]
RED = [("r_fraud", "ESC_MULE_ACTIVITY"), ("r_threshold", "ESC_STRUCTURING"), ("l_same", "ESC_LISTED_PARTY"),
       ("r_invoice_mismatch", "ESC_INVOICE_MISMATCH"), ("r_contradict", "ESC_UNEXPLAINED_FUNDS"),
       ("r_passthrough", "ESC_PASS_THROUGH"), ("r_corridor", "ESC_HIGH_RISK_CORRIDOR")]


def ask(cid, inst, state, questions):
    cache = os.path.join(ROOT, "eval", "drafts", "bineval", BANK_VERSION, inst)
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, cid + ".json")
    if os.path.exists(path):
        return json.load(open(path))
    for model in MODELS:
        req = urllib.request.Request(URL, json.dumps({"model": model, "questions": questions, "state": state}).encode(),
                                     {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
        for wait in (5, 20, 0):
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    j = json.load(r)
                if j.get("answers"):
                    out = {"model": j.get("model", model), "answers": j["answers"]}
                    json.dump(out, open(path, "w"))
                    return out
                break
            except Exception:
                if not wait:
                    break
                time.sleep(wait)
    return None


def yes(ans, q):
    a = ans.get(q) or {}
    return float(a.get("noul", 0)) >= YES


def choice(ans, q):
    a = ans.get(q) or {}
    probs = a.get("probabilities") or {}
    c = a.get("choice")
    return c, round(float(probs.get(c, 0)), 2)


def tm01_multiple(b):
    m = [a.get("measured", {}).get("multiple") for a in b.alerts if a["rule_id"] == "TM01"]
    return max([x for x in m if x is not None], default=None)


def decide(ans, b):
    """The fixed table. Returns (verdict, code, which question decided it)."""
    per_alert = [q for q in ans if q.startswith("alert_")]
    if per_alert:  # "every alert explained" = every per-alert SOP question answered yes (or the holistic e_all)
        ans = dict(ans)
        if all(yes(ans, q) for q in per_alert):
            ans["e_all"] = {"noul": 1.0}
    for q, code in RED:
        if yes(ans, q):
            return "ESCALATE", code, q
    if yes(ans, "l_diff") and all(a["rule_id"] in ("TM22", "TM08", "TM01") for a in b.alerts):
        return "CLOSE", "LIST_MATCH_DIFFERENT_PARTY", "l_diff"
    kind, p = choice(ans, "e_kind")
    documented = kind in CODE_OF and p >= 0.5 and yes(ans, "e_amount") and yes(ans, "e_dated") and yes(ans, "e_all")
    if kind in ("own_account", "returning_customer"):
        mult = tm01_multiple(b)
        if not yes(ans, "own_holds"):
            return "RFI", "RFI_SOURCE_OF_FUNDS", "own_holds"
        if mult is not None and mult >= (b.policy.get("own_account_rfi_multiple") or 5):
            return "RFI", "RFI_UPDATED_PROFILE", "5x rule (code)"
        return ("CLOSE", CODE_OF[kind], "e_kind") if yes(ans, "e_all") else ("RFI", "RFI_SOURCE_OF_FUNDS", "e_all")
    if documented and (kind in ("collection", "business_records", "invoice", "group_company") or yes(ans, "e_party")):
        return "CLOSE", CODE_OF[kind], "e_kind"
    if kind in ("invoice", "collection", "group_company"):
        return "RFI", "RFI_PURPOSE_DOCUMENTS", "e_kind (no matching document)"
    if kind == "business_records":
        return "RFI", "RFI_BUSINESS_RECORDS", "e_kind (no matching document)"
    if any(a["rule_id"] == "TM22" for a in b.alerts):
        return "RFI", "RFI_COUNTERPARTY_DETAILS", "list unsettled"
    return "RFI", "RFI_SOURCE_OF_FUNDS", "nothing explains it"


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 10
    only = sys.argv[sys.argv.index("--ids") + 1].split(",") if "--ids" in sys.argv else None
    totals = {"bin": 0, "bin_code": 0, "holistic": 0, "holistic_code": 0, "n": 0, "bin_wrongful": 0}
    misses = []
    for inst in INSTITUTIONS:
        policy = open(os.path.join(ROOT, "data", "institutions", inst, "POLICY.md")).read()
        labels = {json.loads(line)["case_id"]: json.loads(line) for line in open(os.path.join(ROOT, "eval", "labels", f"{inst}.jsonl"))}
        hol_path = os.path.join(ROOT, "eval", "labels_model", f"{inst}.labelled.jsonl")
        holistic = {json.loads(line)["case_id"]: json.loads(line) for line in open(hol_path)} if os.path.exists(hol_path) else {}
        bs = {b.case["case_id"]: b for b in bundles(inst)}
        if only:
            ids = [c for c in only if c in labels]
        else:
            rnd = random.Random("bineval" + inst)
            close = sorted(c for c, lab in labels.items() if lab["verdict"] == "CLOSE")
            other = sorted(c for c, lab in labels.items() if lab["verdict"] != "CLOSE")
            ids = rnd.sample(close, min(n // 2, len(close))) + rnd.sample(other, min(n - n // 2, len(other)))
        for cid in ids:
            text = subprocess.run([sys.executable, os.path.join(ROOT, "eval", "view.py"), cid], capture_output=True, text=True).stdout
            got = ask(cid, inst, {"sop": policy, "case_file": text}, build_questions(policy, bs[cid].alerts))
            if not got:
                print(cid, "no answer", flush=True)
                continue
            v, code, why = decide(got["answers"], bs[cid])
            lab = labels[cid]
            totals["n"] += 1
            totals["bin"] += v == lab["verdict"]
            totals["bin_code"] += code == lab["reason_code"]
            totals["bin_wrongful"] += v == "CLOSE" and lab["verdict"] != "CLOSE"
            h = holistic.get(cid)
            totals["holistic"] += bool(h) and h["verdict"] == lab["verdict"]
            totals["holistic_code"] += bool(h) and h.get("reason_code") == lab["reason_code"]
            ok = "OK " if (v, code) == (lab["verdict"], lab["reason_code"]) else ("v  " if v == lab["verdict"] else "XX ")
            print(f"{ok}{cid}: bin {v} {code} [{why}] | label {lab['verdict']} {lab['reason_code']}", flush=True)
            if v != lab["verdict"] or code != lab["reason_code"]:
                yes_qs = [q for q in got["answers"] if q != "e_kind" and yes(got["answers"], q)]
                misses.append({"case_id": cid, "bin": [v, code, why], "label": [lab["verdict"], lab["reason_code"]],
                               "e_kind": choice(got["answers"], "e_kind"), "yes": yes_qs})
    t = totals
    print(f"\nBinEval table: verdict {t['bin']}/{t['n']}, code {t['bin_code']}/{t['n']}, wrongful closes {t['bin_wrongful']}")
    print(f"Holistic labeller on the same cases: verdict {t['holistic']}/{t['n']}, code {t['holistic_code']}/{t['n']}")
    os.makedirs(os.path.join(ROOT, "eval", "drafts"), exist_ok=True)
    json.dump({"version": BANK_VERSION, "totals": t, "misses": misses}, open(os.path.join(ROOT, "eval", "drafts", "bineval_report.json"), "w"), indent=1)
    for m in misses:
        print(" miss", m["case_id"], "bin", m["bin"], "label", m["label"], "e_kind", m["e_kind"], "yes:", m["yes"])


if __name__ == "__main__":
    main()
