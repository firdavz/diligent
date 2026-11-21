"""C (Lorenzo): signs of crime -> ESCALATE codes. A red flag on any alert escalates the whole case.

Return (signals, questions):
- Signal(kind="red_flag", code=<an ESC_ code>, strength="hard") when structured data shows it:
  e.g. a sending-bank fraud report naming the alert's payments, cash just under b.policy thresholds,
  a listed party still in control on the payment date, an undeclared country in b.policy["high_risk_countries"].
- Question(...) when only prose could show it (a chat story that contradicts the documents, someone else
  operating the account). D's reader answers; a "yes" becomes your if_yes signal (soft).

The internal list (TM22): b.list_entries has the entries this case's alerts matched; b.internal_list has them all.
Policy: listed party is/controls the counterparty -> ESC_LISTED_PARTY; evidence shows a different party ->
CLOSE LIST_MATCH_DIFFERENT_PARTY (an "explains" signal); unsettled and nothing else concerning -> RFI (decide's fallback).

Rules key on content, never on which document types exist. Thresholds from b.policy. No dev-case data here.
"""

from __future__ import annotations

from .types import CaseBundle, Question, Signal

Checks = tuple[list[Signal], list[Question]]


def red_flags(b: CaseBundle) -> Checks:
    signals: list[Signal] = []
    questions: list[Question] = []
    for check in CHECKS:
        s, q = check(b)
        signals += s
        questions += q
    return signals, questions


# Add one function per check, (b) -> (signals, questions), and list it here.
# Ideas: fraud_report, structuring, mule_pass_through, high_risk_corridor, third_party_funding,
# account_misuse, early_redemption, listed_party, invoice_mismatch.
CHECKS: list = []
