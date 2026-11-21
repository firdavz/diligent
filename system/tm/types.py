"""Shared contract. Owned by A (Andrei); change only by team agreement.

Flow: load -> red_flags (C) + explainers (B) -> open Questions -> reader tiers (D) -> decide (A).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Verdict = Literal["CLOSE", "RFI", "ESCALATE"]
SignalKind = Literal["red_flag", "explains", "partial"]
Strength = Literal["hard", "soft"]
AnswerValue = Literal["yes", "no", "unknown"]

ALL_ALERTS = "*"


@dataclass
class Doc:
    doc_id: str
    type: str
    title: str
    dated: str | None
    text: str  # full Markdown
    fields: dict[str, str]  # "**Key:** value" pairs, keys lower-cased
    body: str  # text that isn't a heading or a field line (prose: chats, notes, letters)


@dataclass
class CaseBundle:
    institution: str  # bank | emoney | investment | payments_fx
    case: dict  # the cases.jsonl row
    alerts: list[dict]  # alerts.jsonl rows in this case, in case order
    customer: dict
    txns: dict[str, dict]  # transaction_id -> row, every transaction of the customer
    docs: dict[str, Doc]  # doc_id -> Doc, every document on file for the customer
    reviews: list[dict]  # previous_reviews rows for the customer
    list_entries: dict[str, dict]  # internal-list entries referenced by this case's TM22 alerts
    internal_list: dict[str, dict]  # the whole internal list (for C's own matching)
    policy: dict  # see load.parse_policy

    @property
    def held_payment(self) -> dict | None:
        tid = self.case.get("held_payment_id")
        return self.txns.get(tid) if tid else None

    def alert_txns(self, alert: dict) -> list[dict]:
        return [self.txns[t] for t in alert.get("transaction_ids", []) if t in self.txns]

    def known_ids(self) -> set[str]:
        """Every ID this case may cite as evidence."""
        ids = set(self.txns) | set(self.docs) | set(self.list_entries)
        ids |= {r["review_id"] for r in self.reviews}
        return ids


@dataclass
class Signal:
    alert_id: str  # an alert_id in the case, or ALL_ALERTS
    kind: SignalKind
    code: str  # a reason code that belongs to the verdict this kind leads to
    facts: str  # ONE sentence with this case's own names, amounts, dates, document IDs
    evidence: list[str]  # IDs exactly as they appear in the files
    strength: Strength = "hard"  # "soft" = rests on a model answer
    source: str = ""  # which check produced it, for the trace (e.g. "explainers.invoice_match")


@dataclass
class Question:
    """Raised by B or C when structured data can't settle an alert; answered by D's reader."""

    id: str  # stable name of the check, e.g. "chat_explains_cash_source"
    alert_id: str
    text: str  # a yes/no question, filled in with this case's facts
    doc_ids: list[str]  # the documents the reader may use
    if_yes: Signal | None = None  # what a "yes" becomes (strength is forced to "soft")
    if_no: Signal | None = None  # what a "no" becomes


@dataclass
class Answer:
    value: AnswerValue
    quote: str = ""
    evidence: list[str] = field(default_factory=list)
    tier: int = 0
    model: str = ""


@dataclass
class Decision:
    case_id: str
    alert_ids: list[str]
    verdict: Verdict
    reason_code: str
    reason: str
    evidence: list[str]
    trace: dict = field(default_factory=dict)

    def output_row(self) -> dict:
        return {
            "case_id": self.case_id,
            "alert_ids": self.alert_ids,
            "verdict": self.verdict,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "evidence": self.evidence,
        }


CODES: dict[Verdict, tuple[str, ...]] = {
    "CLOSE": (
        "COLLECTION_DOCUMENTED", "BUSINESS_RECORDS_RECONCILE", "DOCUMENTED_EVENT", "INVOICE_MATCHES",
        "OWN_ACCOUNT", "GROUP_COMPANY", "THIRD_PARTY_DOCUMENTED", "REFUND_OF_EARLIER_PAYMENT",
        "RETURNING_CUSTOMER", "LIST_MATCH_DIFFERENT_PARTY", "WITHIN_PROFILE",
    ),
    "RFI": (
        "RFI_PURPOSE_DOCUMENTS", "RFI_BUSINESS_RECORDS", "RFI_SOURCE_OF_FUNDS",
        "RFI_COUNTERPARTY_DETAILS", "RFI_UPDATED_PROFILE",
    ),
    "ESCALATE": (
        "ESC_MULE_ACTIVITY", "ESC_STRUCTURING", "ESC_UNEXPLAINED_FUNDS", "ESC_PASS_THROUGH",
        "ESC_INVOICE_MISMATCH", "ESC_HIGH_RISK_CORRIDOR", "ESC_ACCOUNT_MISUSE",
        "ESC_THIRD_PARTY_FUNDING", "ESC_EARLY_REDEMPTION", "ESC_LISTED_PARTY",
    ),
}
VERDICT_OF_CODE = {c: v for v, codes in CODES.items() for c in codes}
KIND_VERDICT: dict[str, Verdict] = {"red_flag": "ESCALATE", "explains": "CLOSE", "partial": "RFI"}
