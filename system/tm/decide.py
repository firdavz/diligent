"""The rulebook: signals -> one verdict per case. Owned by A.

Per alert:   red flag -> ESCALATE;  hard explanation -> CLOSE;  partial / soft-only -> RFI;  nothing -> fallback.
Per case:    the worst alert wins (ESCALATE > RFI > CLOSE).
Safety:      a CLOSE needs a HARD explains signal on every alert. Model answers alone never close.
"""

from __future__ import annotations

import re

from .types import ALL_ALERTS, CODES, KIND_VERDICT, CaseBundle, Decision, Signal
from .util import amounts, money, same_name

SEVERITY = {"CLOSE": 0, "RFI": 1, "ESCALATE": 2}
CLOSE_NEEDS_HARD = True

# What an alert becomes when neither B nor C produced a signal for it. Placeholders, tuned on the labels:
# the brief's own example sends unexplained-but-not-suspicious profile breaches to RFI, and the policies say
# an unsettled list match with nothing else concerning is an RFI. Unexplained movement patterns escalate
# (ESCALATE also costs less than RFI when the two are confused: 2 vs 3).
FALLBACK: dict[str, tuple[str, str]] = {
    "TM01": ("RFI_SOURCE_OF_FUNDS", "Ask the customer for proof of where the money received in the window came from."),
    "TM02": ("ESC_UNEXPLAINED_FUNDS", "Nothing on file explains the money that came in and was moved straight out again."),
    "TM03": ("ESC_STRUCTURING", "Nothing on file explains the repeated amounts just under the threshold."),
    "TM04": ("ESC_MULE_ACTIVITY", "Nothing on file explains why so many different parties paid or were paid by the account."),
    "TM05": ("RFI_SOURCE_OF_FUNDS", "Ask the customer for proof of where the cash came from."),
    "TM06": ("ESC_HIGH_RISK_CORRIDOR", "Nothing on file explains the payments involving an undeclared higher-risk country."),
    "TM07": ("RFI_SOURCE_OF_FUNDS", "Ask the customer where the money moving on the reactivated account came from."),
    "TM08": ("ESC_THIRD_PARTY_FUNDING", "Nothing on file explains the third party funding or receiving money from the account."),
    "TM10": ("ESC_EARLY_REDEMPTION", "Nothing on file explains why fund units were bought and quickly sold back."),
    "TM22": ("RFI_COUNTERPARTY_DETAILS", "Nothing on file settles whether the counterparty is the listed party; ask the customer who the counterparty is and what the payment was for."),
}
_DEFAULT_FALLBACK = ("ESC_UNEXPLAINED_FUNDS", "Nothing on file explains the activity the alert raised.")


def _signals_for(alert_id: str, signals: list[Signal]) -> list[Signal]:
    return [s for s in signals if s.alert_id in (alert_id, ALL_ALERTS)]


def _first_sentence(text: str) -> str:
    m = re.match(r"(.+?\.)(\s|$)", text or "")
    return m[1] if m else (text or "")


def decide_alert(alert: dict, signals: list[Signal], b: CaseBundle) -> tuple[str, list[Signal], str]:
    """Return (verdict, deciding signals, path) for one alert."""
    mine = _signals_for(alert["alert_id"], signals)
    red = [s for s in mine if s.kind == "red_flag"]
    if red:
        red.sort(key=lambda s: s.strength != "hard")
        return "ESCALATE", red, "red_flag"
    hard = [s for s in mine if s.kind == "explains" and s.strength == "hard"]
    soft = [s for s in mine if s.kind == "explains" and s.strength == "soft"]
    if hard or (soft and not CLOSE_NEEDS_HARD):
        return "CLOSE", hard + soft, "explained"
    partial = [s for s in mine if s.kind == "partial"]
    if partial:
        return "RFI", partial, "partial"
    if soft:
        s = soft[0]
        return "RFI", [Signal(
            alert_id=alert["alert_id"], kind="partial", code="RFI_PURPOSE_DOCUMENTS",
            facts=f"{s.facts} Ask the customer for a document that confirms this.",
            evidence=s.evidence, strength="soft", source="decide.soft_only",
        )], "soft_only"
    code, text = FALLBACK.get(alert["rule_id"], _DEFAULT_FALLBACK)
    verdict = next(v for v, codes in CODES.items() if code in codes)
    fb = Signal(
        alert_id=alert["alert_id"], kind="partial" if verdict == "RFI" else "red_flag", code=code,
        facts=f"{_first_sentence(alert.get('message', ''))} {text}".strip(),
        evidence=list(alert.get("transaction_ids", []))[:6] + ([alert["measured"]["list_entry"]] if alert.get("measured", {}).get("list_entry") else []),
        strength="hard", source="decide.fallback",
    )
    return verdict, [fb], "fallback"


def _held_payment_needs_invoice(b: CaseBundle, signals: list[Signal]) -> Signal | None:
    """Policy (payments and FX): a held payment at or above the invoice threshold to anyone other than the client
    is released only with an invoice or contract on file. Without a hard INVOICE_MATCHES signal citing it, no CLOSE."""
    limit = b.policy.get("third_party_invoice_threshold")
    held = b.held_payment
    if not limit or not held or held.get("amount_gbp", 0) < limit:
        return None
    if same_name(held.get("counterparty_name"), b.customer.get("name")):
        return None  # transfers to the client's own accounts don't need one
    if any(s.kind == "explains" and s.strength == "hard" and s.code == "INVOICE_MATCHES"
           and held["transaction_id"] in s.evidence for s in signals):
        return None
    return Signal(
        alert_id=ALL_ALERTS, kind="partial", code="RFI_PURPOSE_DOCUMENTS",
        facts=(f"The held payment {held['transaction_id']} of {money(held['amount_gbp'])} to "
               f"{held.get('counterparty_name')} is at or above the {money(limit)} threshold, and no invoice or contract "
               f"on file matches it; ask the client for the invoice or contract before it is released."),
        evidence=[held["transaction_id"]], strength="hard", source="decide.held_payment_invoice",
    )


def decide(b: CaseBundle, signals: list[Signal], answers: list[dict] | None = None) -> Decision:
    per_alert = []
    for a in b.alerts:
        verdict, deciding, path = decide_alert(a, signals, b)
        per_alert.append({"alert_id": a["alert_id"], "rule_id": a["rule_id"], "verdict": verdict,
                          "path": path, "deciding": deciding})

    worst = max((p["verdict"] for p in per_alert), key=SEVERITY.__getitem__, default="ESCALATE")
    if worst == "CLOSE":
        guard = _held_payment_needs_invoice(b, signals)
        if guard:
            per_alert.append({"alert_id": ALL_ALERTS, "rule_id": "POLICY", "verdict": "RFI",
                              "path": "held_payment_invoice", "deciding": [guard]})
            worst = "RFI"
    deciding: list[Signal] = []
    for p in per_alert:
        if p["verdict"] == worst:
            deciding.extend(p["deciding"])
    # A signal's own kind must lead to the case verdict; otherwise its code wouldn't belong to it.
    lead = [s for s in deciding if KIND_VERDICT[s.kind] == worst and s.code in CODES[worst]]
    code = lead[0].code if lead else CODES[worst][0]

    known = b.known_ids()
    evidence: list[str] = []
    for s in deciding:
        for e in s.evidence:
            if e in known and e not in evidence:
                evidence.append(e)
    if not evidence:  # cite at least what the alerts fired on
        for a in b.alerts:
            for t in a.get("transaction_ids", [])[:3]:
                if t in known and t not in evidence:
                    evidence.append(t)

    sentences: list[str] = []
    for s in deciding:
        f = s.facts.strip()
        if f and f not in sentences:
            sentences.append(f)
    if len(sentences) < 2 and b.alerts:
        msg = _first_sentence(b.alerts[0].get("message", ""))
        if msg and all(msg not in s for s in sentences):
            sentences.insert(0, msg)
    reason = " ".join(sentences[:4])

    return Decision(
        case_id=b.case["case_id"],
        alert_ids=list(b.case["alert_ids"]),
        verdict=worst,  # type: ignore[arg-type]
        reason_code=code,
        reason=reason,
        evidence=evidence,
        trace={
            "alerts": [{**{k: v for k, v in p.items() if k != "deciding"},
                        "deciding": [s.source or s.code for s in p["deciding"]],
                        "codes": [s.code for s in p["deciding"]],
                        "facts": [s.facts for s in p["deciding"]],
                        "evidence": [e for s in p["deciding"] for e in s.evidence]} for p in per_alert],
            "signals": [vars(s) for s in signals],
            "answers": answers or [],
        },
    )


__all__ = ["decide", "decide_alert", "FALLBACK", "amounts", "money"]
