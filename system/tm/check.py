"""Last line of defence before a row is written. Owned by A."""

from __future__ import annotations

from .types import CODES, CaseBundle, Decision


def check(d: Decision, b: CaseBundle) -> list[str]:
    """Fix what can be fixed in place; return a list of problems for the run log."""
    problems = []
    if d.reason_code not in CODES[d.verdict]:
        problems.append(f"{d.case_id}: code {d.reason_code} does not belong to {d.verdict}")
        d.reason_code = CODES[d.verdict][0]
    known = b.known_ids()
    bad = [e for e in d.evidence if e not in known]
    if bad:
        problems.append(f"{d.case_id}: dropped unknown evidence IDs {bad}")
        d.evidence = [e for e in d.evidence if e in known]
    if sorted(d.alert_ids) != sorted(b.case["alert_ids"]):
        problems.append(f"{d.case_id}: alert_ids mismatch")
        d.alert_ids = list(b.case["alert_ids"])
    if not d.reason.strip():
        problems.append(f"{d.case_id}: empty reason")
    return problems
