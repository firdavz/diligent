"""B (Clotilde): evidence that EXPLAINS an alert -> CLOSE codes, or a gap -> RFI codes.

Return (signals, questions):
- Signal(kind="explains", code=<a CLOSE code>, strength="hard") when structured data proves the explanation:
  amounts / payees / dates in doc.fields match the alert's transactions.
- Signal(kind="partial", code=<an RFI code>) when it's plausible but one document is missing.
  Its facts must say exactly what to ask for.
- Question(...) when only prose (chat, contact note, letter) could settle it. D's reader answers it; a "yes"
  becomes your if_yes signal with strength forced to "soft" (which alone can't CLOSE a case).

Rules key on content, never on which document types exist. Thresholds from b.policy. No dev-case data here.
"""

from __future__ import annotations

from .types import CaseBundle, Question, Signal

Checks = tuple[list[Signal], list[Question]]


def explainers(b: CaseBundle) -> Checks:
    signals: list[Signal] = []
    questions: list[Question] = []
    for check in CHECKS:
        s, q = check(b)
        signals += s
        questions += q
    return signals, questions


# Add one function per check, (b) -> (signals, questions), and list it here.
# Ideas: invoice_matches, own_account (5x rule via b.policy["own_account_rfi_multiple"]), documented_event,
# business_records, group_company, refund, returning_customer, third_party_documented, within_profile,
# list_match_different_party (with Lorenzo), earlier_review_covers.
CHECKS: list = []
