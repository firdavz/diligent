"""Audit trail: fingerprints for reproducibility, and the SOP clause behind every step. Owned by A.

Every decision records
  input_fp     hash of everything the case's decision may depend on (case, alerts, customer, transactions, documents,
               earlier reviews, list entries) — same input_fp + same code_fp + same policy_fp must give the same decision_fp
  decision_fp  hash of the output row (verdict, code, reason, evidence)
  sop          per alert: the rule that fired (from POLICY.md) and the SOP clauses the verdict rests on, quoted verbatim
"""

from __future__ import annotations

import hashlib
import json
import os
import re

from .types import CaseBundle, Decision

_HERE = os.path.dirname(os.path.abspath(__file__))


def fp(obj) -> str:
    raw = obj if isinstance(obj, (bytes, str)) else json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode() if isinstance(raw, str) else raw).hexdigest()[:16]


def code_fp() -> str:
    """Hash of the system's own source, so a decision can be tied to the exact code that made it."""
    h = hashlib.sha256()
    root = os.path.dirname(_HERE)
    for dirpath, _, files in sorted(os.walk(root)):
        if "cache" in dirpath or "traces" in dirpath or "__pycache__" in dirpath or "tests" in dirpath:
            continue
        for name in sorted(files):
            if name.endswith(".py") or name == "run":
                p = os.path.join(dirpath, name)
                h.update(os.path.relpath(p, root).encode())
                h.update(open(p, "rb").read())
    return h.hexdigest()[:16]


def input_fp(b: CaseBundle) -> str:
    return fp({
        "case": b.case, "alerts": b.alerts, "customer": b.customer,
        "txns": [b.txns[k] for k in sorted(b.txns)],
        "docs": {k: b.docs[k].text for k in sorted(b.docs)},
        "reviews": b.reviews, "list": b.list_entries,
    })


# ---------------------------------------------------------------- SOP clauses, quoted from the institution's POLICY.md

def _policy_lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", ln.strip("- ").strip()) for ln in text.splitlines() if ln.strip().startswith("- ")]


def _verdict_def(lines: list[str], verdict: str) -> str | None:
    return next((ln for ln in lines if ln.startswith(f"**{verdict}**")), None)


def _setting(lines: list[str], *words: str) -> str | None:
    return next((ln for ln in lines if all(w.lower() in ln.lower() for w in words)), None)


_SETTING_FOR_CODE = {
    "OWN_ACCOUNT": ("own name elsewhere counts as their own account",),
    "RFI_UPDATED_PROFILE": ("own accounts explain activity",),
    "LIST_MATCH_DIFFERENT_PARTY": ("internal list",),
    "ESC_LISTED_PARTY": ("internal list",),
    "RFI_COUNTERPARTY_DETAILS": ("internal list",),
    "ESC_HIGH_RISK_CORRIDOR": ("higher-risk countries",),
}


def sop_basis(b: CaseBundle, rule_id: str, path: str, codes: list[str], verdict: str) -> list[str]:
    lines = _policy_lines(b.policy.get("text", ""))
    out: list[str] = []
    rule = b.policy.get("rules", {}).get(rule_id)
    if rule:
        out.append(f"{rule_id} {rule['name']}: fires when {rule['fires_when']}")
    vd = _verdict_def(lines, verdict)
    if vd:
        out.append(vd)
    if verdict == "ESCALATE" and path == "red_flag":
        out.append("Once there is suspicion, escalate. Do not send the customer an RFI at that point.")
    if path == "held_payment_invoice":
        s = _setting(lines, "invoice or contract on file")
        if s:
            out.append(s)
    for c in codes:
        words = _SETTING_FOR_CODE.get(c)
        s = _setting(lines, *words) if words else None
        if s and s not in out:
            out.append(s)
    return out


def annotate(b: CaseBundle, d: Decision) -> None:
    """Add the audit block to a decision's trace."""
    alerts = []
    for a in d.trace.get("alerts", []):
        alerts.append({**a, "sop": sop_basis(b, a["rule_id"], a["path"], a.get("codes", []), a["verdict"])})
    d.trace["alerts"] = alerts
    d.trace["audit"] = {
        "input_fp": input_fp(b),
        "policy_fp": fp(b.policy.get("text", "")),
        "decision_fp": fp(d.output_row()),
    }
