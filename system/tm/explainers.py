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
from .util import amounts, fmt_date, money, norm, parse_date, same_name

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


# --------------------------------------------------------------------------- OWN_ACCOUNT (and the 5x rule)

def _digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def _same_account(a: str | None, b: str | None) -> bool:
    """'10-82-50 13513685' == '10825013513685'; 'account ending 2089' matches any number ending 2089."""
    da, db = _digits(a), _digits(b)
    if len(da) < 4 or len(db) < 4:
        return False
    if da == db:
        return True
    if "ending" in (a or "").lower() or "ending" in (b or "").lower():
        short, long_ = sorted((da, db), key=len)
        return long_.endswith(short)
    return False


def _holders(doc: Doc) -> list[str]:
    """Names in the statement's 'Account holder(s)' field ('Sam Example and Robin Example' -> both)."""
    raw = doc.fields.get("account holder") or doc.fields.get("account holders") or ""
    return [p.strip() for p in re.split(r",|\band\b|&", raw) if p.strip()]


def _statement_for(b: CaseBundle, t: dict) -> Doc | None:
    """A document showing the customer holds the account at the other end of t: the customer is a named holder,
    its account number is the transaction's counterparty account, and it records the same amount to the penny."""
    customer = b.customer.get("name")
    for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
        if not any(same_name(h, customer) for h in _holders(doc)):
            continue
        if not _same_account(doc.fields.get("account"), t.get("counterparty_account")):
            continue
        if any(_same_amount(x, t["amount_gbp"]) for x in amounts(doc.text)):
            return doc
    return None


def _not_own(txns: list[dict], own: dict[str, Doc]) -> list[dict]:
    return [t for t in txns if t["transaction_id"] not in own]


def _own_covers(b: CaseBundle, a: dict, txns: list[dict], own: dict[str, Doc]) -> bool:
    """Would the alert still have fired without the money moved between the customer's own accounts?"""
    m = a.get("measured", {})
    rest = _not_own(txns, own)
    rule = a.get("rule_id")
    if rule == "TM01":
        received, baseline, limit = m.get("received_gbp"), m.get("baseline_gbp"), m.get("limit_multiple")
        if received is None or not baseline or not limit:
            return False
        own_in = sum(t["amount_gbp"] for t in txns if t["transaction_id"] in own and t.get("direction") == "in")
        return received - own_in <= limit * baseline + 0.005
    if rule == "TM02":
        floor = (b.policy.get("rules", {}).get("TM02", {}).get("amounts") or [None])[0]
        if not floor:
            return False
        rest_in = sum(t["amount_gbp"] for t in rest if t.get("direction") == "in")
        rest_out = sum(t["amount_gbp"] for t in rest if t.get("direction") == "out" and t.get("channel") != "card")
        return rest_in < floor and rest_out < floor
    if rule in ("TM06", "TM08"):
        limit = m.get("limit_gbp")
        return bool(limit) and sum(t["amount_gbp"] for t in rest) < limit
    return False


def _own_facts(b: CaseBundle, txns: list[dict], own: dict[str, Doc]) -> str:
    docs = list(dict.fromkeys(own[t["transaction_id"]].doc_id for t in txns if t["transaction_id"] in own))
    accts = list(dict.fromkeys(b.docs[d].fields.get("account", "") for d in docs))
    moves = []
    for t in txns:
        if t["transaction_id"] in own:
            d = _txn_date(t)
            verb = "received" if t.get("direction") == "in" else "paid out"
            moves.append(f"the {money(t['amount_gbp'])} {verb}{' on ' + fmt_date(d) if d else ''} ({t['transaction_id']})")
    s = "s" if len(docs) > 1 else ""
    joint = len(docs) == 1 and len(_holders(b.docs[docs[0]])) > 1
    held_by = (f"jointly held by {' and '.join(_holders(b.docs[docs[0]]))}" if joint
               else f"held by {b.customer.get('name')}")
    return (f"Statement{s} {' and '.join(docs)} show{'' if s else 's'} that account{s} {' and '.join(accts)} "
            f"{'are' if s else 'is'} {held_by}, so {' and '.join(moves)} moved between the "
            f"customer's own accounts")


def _own_supporting(b: CaseBundle, own: dict[str, Doc]) -> list[str]:
    """Other documents naming the same bank or account (a relocation letter, an email about the transfer).
    Evidence only: they never decide the verdict."""
    stmts = {d.doc_id: d for d in own.values()}
    out = []
    for d in sorted(b.docs.values(), key=lambda d: d.doc_id):
        if d.doc_id in stmts:
            continue
        for s in stmts.values():
            bank, acct = s.fields.get("bank", ""), s.fields.get("account", "")
            if _mentioned(bank, d.text) or (len(_digits(acct)) >= 8 and acct in d.text):
                out.append(d.doc_id)
                break
    return out


def own_account(b: CaseBundle) -> Checks:
    """Money moved between accounts a document shows the customer holds. Policy: such transfers explain activity
    below `own_account_rfi_multiple` times the declared income or volume (CLOSE OWN_ACCOUNT); at or above it, ask for
    an updated expected income or volume (RFI_UPDATED_PROFILE). The multiple is the TM01 alert's measured one."""
    signals: list[Signal] = []
    rfi_multiple = b.policy.get("own_account_rfi_multiple")
    basis = "turnover" if b.customer.get("kind") == "business" else "income"
    for a in b.alerts:
        if a.get("rule_id") not in ("TM01", "TM02", "TM06", "TM08"):
            continue
        txns = b.alert_txns(a)
        own = {t["transaction_id"]: doc for t in txns for doc in [_statement_for(b, t)] if doc}
        if not own or not _own_covers(b, a, txns, own):
            continue
        facts = _own_facts(b, txns, own)
        evidence = list(dict.fromkeys([d.doc_id for d in own.values()] + _own_supporting(b, own) + sorted(own)))
        multiple = a.get("measured", {}).get("multiple")
        if a["rule_id"] == "TM01" and rfi_multiple and multiple is not None and multiple >= rfi_multiple:
            signals.append(Signal(
                alert_id=a["alert_id"], kind="partial", code="RFI_UPDATED_PROFILE",
                facts=(f"{facts}, but the money received is {multiple:g} times the declared monthly {basis}, at or above "
                       f"the {rfi_multiple} times at which the policy asks for an update; ask the customer for an "
                       f"updated expected monthly {basis} and what it is based on."),
                evidence=evidence, strength="hard", source="explainers.own_account",
            ))
            continue
        tail = (f"; the money received is {multiple:g} times the declared monthly {basis}, below the {rfi_multiple} "
                f"times at which the policy asks for an update." if a["rule_id"] == "TM01" and multiple is not None
                and rfi_multiple else ".")
        signals.append(Signal(
            alert_id=a["alert_id"], kind="explains", code="OWN_ACCOUNT", facts=facts + tail,
            evidence=evidence, strength="hard", source="explainers.own_account",
        ))
    return signals, []


# Add one function per check, (b) -> (signals, questions), and list it here.
# Next: returning_customer (TM07), own account on payments and FX (outgoing own-account transfer), documented_event,
# refund, invoice_matches, collection_documented, group_company, third_party_documented, within_profile.
# list_match_different_party is Lorenzo's (red_flags.listed_party).
CHECKS: list = [business_records, own_account]
