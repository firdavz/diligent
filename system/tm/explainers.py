"""B (Clotilde): evidence that EXPLAINS an alert -> CLOSE codes, or a gap -> RFI codes.

Return (signals, questions):
- Signal(kind="explains", code=<a CLOSE code>, strength="hard") when structured data proves the explanation:
  amounts / payees / dates in doc.fields match the alert's transactions.
- Signal(kind="partial", code=<an RFI code>) when it's plausible but one document is missing.
  Its facts must say exactly what to ask for.
- Question(...) when only prose (chat, contact note, letter) could settle it. D's reader answers it; a "yes"
  becomes your if_yes signal with strength forced to "soft" (which alone can't CLOSE a case).

Rules key on content, never on which document types exist. Thresholds from b.policy. No dev-case data here.

Explanations are emitted per alert (never ALL_ALERTS): an explanation covers only the alert whose transactions it
matched, and decide() closes a case only when every alert is explained and no red flag fired.
"""

from __future__ import annotations

import re
from datetime import date

from .types import CaseBundle, Doc, Question, Signal
from .util import amounts, money, norm, parse_date, same_name

Checks = tuple[list[Signal], list[Question]]


def explainers(b: CaseBundle) -> Checks:
    signals: list[Signal] = []
    questions: list[Question] = []
    for check in CHECKS:
        s, q = check(b)
        signals += s
        questions += q
    return signals, questions


# --------------------------------------------------------------------------- helpers

def _same_amount(a: float | None, b: float | None) -> bool:
    """Equal to the penny."""
    return a is not None and b is not None and abs(a - b) < 0.005


def _tables(doc: Doc) -> list[list[dict[str, str]]]:
    """Every Markdown table in a document as a list of {lower-case header: cell} rows.
    (Same parsing as red_flags._tables; kept separate so B and C don't edit each other's modules.)"""
    tables: list[list[dict[str, str]]] = []
    header: list[str] | None = None
    rows: list[dict[str, str]] = []
    for line in doc.text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            if rows:
                tables.append(rows)
            header, rows = None, []
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        if header is None:
            header = [c.lower() for c in cells]
        else:
            rows.append(dict(zip(header, cells)))
    if rows:
        tables.append(rows)
    return tables


def _txn_date(t: dict) -> date | None:
    return parse_date(t.get("booked_at"))


def _is_cash_in(t: dict) -> bool:
    return t.get("direction") == "in" and "cash" in (t.get("channel") or "")


def _mentioned(needle: str, haystack: str) -> bool:
    n = norm(needle)
    return len(n) >= 5 and n in norm(haystack)


# --------------------------------------------------------------------------- BUSINESS_RECORDS_RECONCILE

# Cash counted or emptied on one day is paid in that day or shortly after (next morning, the days after an event).
RECORDS_BANKED_WITHIN_DAYS = 2
_INCOME_COLUMNS = ("takings", "sales")


def _row_fits(row: dict[str, str], t: dict) -> int | None:
    """Days between the row's date and the cash deposit if the row records this deposit, else None.

    The row must hold the deposit's amount to the penny and a date on the deposit day or up to
    RECORDS_BANKED_WITHIN_DAYS before it. If the row also states the day's takings or sales, the deposit
    can't exceed them.
    """
    if not any(_same_amount(x, t["amount_gbp"]) for v in row.values() for x in amounts(v)):
        return None
    for k, v in row.items():
        if any(w in k for w in _INCOME_COLUMNS):
            income = amounts(v)
            if income and not _same_amount(income[0], t["amount_gbp"]) and income[0] < t["amount_gbp"]:
                return None
    td = _txn_date(t)
    if not td:
        return None
    offsets = [(td - d).days for d in (parse_date(v) for v in row.values()) if d]
    fits = [o for o in offsets if 0 <= o <= RECORDS_BANKED_WITHIN_DAYS]
    return min(fits) if fits else None


def _reconcile(rows: list[dict[str, str]], txns: list[dict]) -> list[dict[str, str]] | None:
    """Give every deposit its own row (closest date first). None if any deposit has no row."""
    used: set[int] = set()
    matched: list[dict[str, str]] = []
    for t in sorted(txns, key=lambda t: (t.get("booked_at", ""), t["transaction_id"])):
        options = sorted((off, i) for i, r in enumerate(rows) if i not in used
                         for off in [_row_fits(r, t)] if off is not None)
        if not options:
            return None
        used.add(options[0][1])
        matched.append(rows[options[0][1]])
    return matched


def _row_labels(rows: list[dict[str, str]]) -> set[str]:
    """Words in the matched rows that name a site, point or market (cells with no amount and no date)."""
    return {v for r in rows for v in r.values()
            if v and not amounts(v) and not parse_date(v) and not re.search(r"\d", v)}


def _supporting_docs(b: CaseBundle, record: Doc, rows: list[dict[str, str]]) -> list[str]:
    """Other documents that describe the same sites or event (cash procedure, ticket report). Evidence only."""
    subject = re.search(r"\b(?:for|from|,)\s+(.+)$", record.title or "")
    subject_name = subject[1].strip() if subject else ""
    if same_name(subject_name, b.customer.get("name")):
        subject_name = ""  # the customer's own name would pull in every document
    labels = _row_labels(rows)
    out = []
    for d in sorted(b.docs.values(), key=lambda d: d.doc_id):
        if d.doc_id == record.doc_id:
            continue
        text = f"{d.title}\n{d.text}"
        if (subject_name and _mentioned(subject_name, text)) or any(_mentioned(lab, text) for lab in labels):
            out.append(d.doc_id)
    return out


def business_records(b: CaseBundle) -> Checks:
    """TM03: the customer's own business records (collection reports, cash reconciliation, takings book) have a row
    for every alerted cash deposit, with the same amount, counted or emptied on the day or shortly before."""
    signals: list[Signal] = []
    for a in b.alerts:
        if a.get("rule_id") != "TM03":
            continue
        txns = [t for t in b.alert_txns(a) if _is_cash_in(t)]
        if not txns or len(txns) != len(a.get("transaction_ids", [])):
            continue  # every alerted transaction must be a cash deposit we can reconcile
        for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
            matched = next((m for rows in _tables(doc) for m in [_reconcile(rows, txns)] if m), None)
            if not matched:
                continue
            total = sum(t["amount_gbp"] for t in txns)
            name = doc.title or doc.type.replace("_", " ")
            facts = (f"{doc.doc_id} ({name}) has its own row for each of the {len(txns)} alerted cash deposits "
                     f"({money(total)} in all), with the same amount to the penny, counted on the day of the deposit "
                     f"or up to {RECORDS_BANKED_WITHIN_DAYS} days before it.")
            evidence = [doc.doc_id] + _supporting_docs(b, doc, matched) + sorted(t["transaction_id"] for t in txns)
            signals.append(Signal(
                alert_id=a["alert_id"], kind="explains", code="BUSINESS_RECORDS_RECONCILE", facts=facts,
                evidence=evidence, strength="hard", source="explainers.business_records",
            ))
            break
    return signals, []


# Add one function per check, (b) -> (signals, questions), and list it here.
# Next: own_account (5x rule via b.policy["own_account_rfi_multiple"]), documented_event, refund, invoice_matches,
# collection_documented, returning_customer, group_company, third_party_documented, within_profile.
# list_match_different_party is Lorenzo's (red_flags.listed_party).
CHECKS: list = [business_records]
