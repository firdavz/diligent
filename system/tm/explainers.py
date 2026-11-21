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
from .util import amounts, fmt_date, money, name_key, norm, parse_date, same_name

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
    """Would the alert still have fired without the explained transactions (`own`: transaction_id -> the document
    that explains it)? Used for own-account money and for documented events alike."""
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
        fires_when = b.policy.get("rules", {}).get("TM02", {}).get("fires_when", "").lower()
        if "other than the client" in fires_when:
            # The rule counts only money from third parties: once that is explained, it cannot fire, whatever the
            # client pays out of its own funds.
            third = [t for t in rest if t.get("direction") == "in"
                     and not same_name(t.get("counterparty_name"), b.customer.get("name"))]
            return sum(t["amount_gbp"] for t in third) < floor
        # The rule counts all money received: both what is left coming in and what is left going out (card spending
        # excluded) must be small, so own money in and out to an undocumented party is not explained.
        rest_in = sum(t["amount_gbp"] for t in rest if t.get("direction") == "in")
        rest_out = sum(t["amount_gbp"] for t in rest if t.get("direction") == "out" and t.get("channel") != "card")
        return rest_in < floor and rest_out < floor
    if rule in ("TM06", "TM07", "TM08"):
        limit = m.get("limit_gbp")
        return bool(limit) and sum(t["amount_gbp"] for t in rest) < limit
    if rule == "TM05":  # every alerted cash deposit is explained
        return not [t for t in rest if _is_cash_in(t)]
    if rule == "TM03":  # payments just under a threshold (the structuring rule): every one must be explained
        return not rest
    if rule == "TM04":  # many parties: the distinct parties left unexplained are within the limit
        limit = m.get("limit")
        parties = {name_key(_party(t.get("counterparty_name"))) for t in rest if t.get("counterparty_name")}
        return limit is not None and len(parties) <= limit
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
    named = [a if a.lower().startswith(("account", "iban")) else f"account {a}" for a in accts]
    return (f"Statement{s} {' and '.join(docs)} show{'' if s else 's'} that {' and '.join(named)} "
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


# --------------------------------------------------------------------------- RETURNING_CUSTOMER (TM07)

_REVERIFIED = re.compile(r"re-?verified\s+on\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})", re.I)


def _reverification(b: CaseBundle, start: date, dormant_days: int) -> tuple[Doc, date] | None:
    """A record that the customer's identity was re-verified while the account was dormant, on or before the day it
    moved again. The date is read from the record's own words ('re-verified on 18 August 2026')."""
    for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
        m = _REVERIFIED.search(doc.text)
        d = parse_date(m[1]) if m else None
        if d and 0 <= (start - d).days <= dormant_days:
            return doc, d
    return None


def returning_customer(b: CaseBundle) -> Checks:
    """TM07: a verified customer resumed using a dormant account. Identity re-verified during the dormancy, on or
    before the reactivation, and the money that woke the account came from an account a statement shows the customer
    holds; what is left unexplained moved less than the alert's limit."""
    signals: list[Signal] = []
    for a in b.alerts:
        if a.get("rule_id") != "TM07":
            continue
        m = a.get("measured", {})
        txns = b.alert_txns(a)
        dates = [d for d in (_txn_date(t) for t in txns) if d]
        limit, dormant = m.get("limit_gbp"), m.get("dormant_days")
        if not dates or not limit or not dormant:
            continue
        start = min(dates)
        rv = _reverification(b, start, int(dormant))
        if not rv:
            continue
        own = {t["transaction_id"]: doc for t in txns if t.get("direction") == "in"
               for doc in [_statement_for(b, t)] if doc}
        if not own or sum(t["amount_gbp"] for t in _not_own(txns, own)) >= limit:
            continue
        rv_doc, rv_date = rv
        gap = (start - rv_date).days
        when = "the same day as" if gap == 0 else "the day before" if gap == 1 else f"{gap} days before"
        own_facts = _own_facts(b, txns, own)
        facts = (f"Identity was re-verified on {fmt_date(rv_date)} ({rv_doc.doc_id}), {when} the account moved again "
                 f"after {dormant} days dormant, and {own_facts[0].lower()}{own_facts[1:]}.")
        signals.append(Signal(
            alert_id=a["alert_id"], kind="explains", code="RETURNING_CUSTOMER", facts=facts,
            evidence=list(dict.fromkeys([rv_doc.doc_id] + [d.doc_id for d in own.values()] + sorted(own))),
            strength="hard", source="explainers.returning_customer",
        ))
    return signals, []


# --------------------------------------------------------------------------- DOCUMENTED_EVENT

# A letter or receipt about a one-off event is written shortly before (or on the day of) the money moving.
EVENT_DOC_MAX_DAYS_BEFORE = 30
# Which documents this check reads. This only narrows the check (it can never add a close): invoices, contracts,
# credit notes, remittances, emails and gift letters belong to invoice_matches / refund / third_party_documented,
# which report their own codes and verify their own conditions.
_EVENT_DOC_KINDS = ("letter", "receipt", "completion")
_NOT_EVENT_DOC_KINDS = ("gift",)


def _is_event_doc(doc: Doc) -> bool:
    kind = (doc.type or "").lower()
    return any(k in kind for k in _EVENT_DOC_KINDS) and not any(k in kind for k in _NOT_EVENT_DOC_KINDS)
_GREETING = re.compile(r"^Dear\s+(.+?),?\s*$", re.M)
_GENERIC_ADDRESSEE = {"sir", "madam", "sir madam", "beneficiary", "tenant", "customer", "client", "policyholder",
                      "sir or madam", "colleague", "applicant"}
_REGISTRATION = re.compile(r"\b([A-Z]{2}\d{2}\s?[A-Z]{3})\b")
_NAME = r"([A-Z][\w'-]+(?:\s+[A-Z][\w'-]+)+)"
_SELLER_PATTERNS = (  # ways a receipt names its seller, most explicit first
    re.compile(r"^\s*\**Seller:?\**:?\s*([^,\n]+)", re.M | re.I),
    re.compile(r"\bI,\s*([^,]+),\s*(?:[a-z]+\s+){0,4}(?:sold|sale)\b", re.I),  # "I, X, have today sold" / "hereby confirm the sale"
    re.compile(r"\bsale of\b[^.]*?\bfrom\s+" + _NAME + r"\s+to\s+"),
    re.compile(_NAME + r"\s+has\s+sold\b"),
    re.compile(r"\bsold by\s+" + _NAME),
)


def _doc_date(doc: Doc) -> date | None:
    return parse_date(doc.dated) or parse_date(doc.fields.get("dated"))


def _party(name: str | None) -> str:
    """'Wenbrook Solicitors LLP client account' -> 'Wenbrook Solicitors LLP'."""
    return re.sub(r"\s+client account\s*$", "", name or "", flags=re.I).strip()


def _addressed_elsewhere(b: CaseBundle, doc: Doc) -> bool:
    """The document names someone other than the customer as its addressee or client."""
    customer = b.customer.get("name")
    named = [doc.fields.get(k) for k in ("client", "policyholder", "beneficiary") if doc.fields.get(k)]
    named += [m for m in _GREETING.findall(doc.text) if norm(m) not in _GENERIC_ADDRESSEE]
    return any(not same_name(n.split(",")[0], customer) for n in named)


def _reference_missing(t: dict, doc: Doc) -> bool:
    """The transaction reference carries a number (CLAIM 44642, PO 123) that the document doesn't mention."""
    return any(n not in doc.text for n in re.findall(r"\d{3,}", t.get("reference") or ""))


def _seller(doc: Doc) -> str:
    seller = (doc.fields.get("seller") or "").split(",")[0].strip()
    for pattern in _SELLER_PATTERNS:
        if seller:
            break
        m = pattern.search(doc.text)
        seller = m[1].strip() if m else ""
    return seller


def _vehicle_owned(b: CaseBundle, doc: Doc) -> bool | None:
    """If the receipt is for a registered vehicle: does another document show the customer held that registration?
    None when the receipt names no registration."""
    regs = {r.replace(" ", "") for r in _REGISTRATION.findall(doc.text)}
    if not regs:
        return None
    customer = b.customer.get("name")
    for d in b.docs.values():
        if d.doc_id == doc.doc_id or not {r.replace(" ", "") for r in _REGISTRATION.findall(d.text)} & regs:
            continue
        holder = d.fields.get("policyholder") or d.fields.get("registered keeper") or d.fields.get("owner") or ""
        if same_name(holder, customer):
            return True
    return False


def _event_doc_for(b: CaseBundle, t: dict) -> Doc | None:
    """A document about a one-off event that accounts for transaction t (see documented_event)."""
    customer = b.customer.get("name")
    td = _txn_date(t)
    if not td:
        return None
    cash = _is_cash_in(t)
    payer = _party(t.get("counterparty_name"))
    if not cash and (not payer or same_name(payer, customer)):
        return None  # own-name money is own_account's business
    for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
        if not _is_event_doc(doc):
            continue
        dd = _doc_date(doc)
        if not dd or not 0 <= (td - dd).days <= EVENT_DOC_MAX_DAYS_BEFORE:
            continue
        if not any(_same_amount(x, t["amount_gbp"]) for x in amounts(doc.text)):
            continue
        if cash:
            if not same_name(_seller(doc), customer) or _vehicle_owned(b, doc) is False:
                continue
        else:
            if not _mentioned(payer, f"{doc.title}\n{doc.text}"):
                continue
            if _reference_missing(t, doc) or _addressed_elsewhere(b, doc):
                continue
        return doc
    return None


def _event_supporting(b: CaseBundle, docs: list[Doc]) -> list[str]:
    """Documents backing a sale receipt: the insurance schedule for the same registration, the customer's advert."""
    ids = {d.doc_id for d in docs}
    customer = norm(b.customer.get("name"))
    out = []
    for d in sorted(b.docs.values(), key=lambda d: d.doc_id):
        if d.doc_id in ids:
            continue
        regs = {r.replace(" ", "") for r in _REGISTRATION.findall(d.text)}
        same_reg = any(regs & {r.replace(" ", "") for r in _REGISTRATION.findall(x.text)} for x in docs)
        advert = bool(customer) and f"seller {customer}" in norm(d.text)
        if same_reg or advert:
            out.append(d.doc_id)
    return out


def documented_event(b: CaseBundle) -> Checks:
    """A one-off event documented on file explains the money: a letter from the payer (solicitor, insurer, former
    employer, letting agent, conveyancer) stating the same amount, dated shortly before, not addressed to anyone else
    and carrying the transaction's reference number; or, for cash, a sale receipt for the same amount where the
    customer is the seller (and, for a vehicle, owned it). The alert is explained when, without that money, it would
    not have fired. Unlike own-account money, the 5x profile rule doesn't apply."""
    signals: list[Signal] = []
    for a in b.alerts:
        if a.get("rule_id") not in ("TM01", "TM02", "TM05", "TM06", "TM07", "TM08"):
            continue
        txns = b.alert_txns(a)
        found = {t["transaction_id"]: doc for t in txns for doc in [_event_doc_for(b, t)] if doc}
        if not found or not _own_covers(b, a, txns, found):
            continue
        parts = []
        for t in txns:
            doc = found.get(t["transaction_id"])
            if not doc:
                continue
            dd, td = _doc_date(doc), _txn_date(t)
            if _is_cash_in(t):
                parts.append(f"{doc.doc_id} ({doc.title}, dated {fmt_date(dd)}) shows {b.customer.get('name')} as the "
                             f"seller paid {money(t['amount_gbp'])} in cash, the amount deposited on {fmt_date(td)} "
                             f"({t['transaction_id']})")
                continue
            what = (f"received from {_party(t.get('counterparty_name'))}" if t.get("direction") == "in"
                    else f"paid to {_party(t.get('counterparty_name'))}")
            parts.append(f"{doc.doc_id} ({doc.title}, dated {fmt_date(dd)}) records the {money(t['amount_gbp'])} "
                         f"{what} on {fmt_date(td)} ({t['transaction_id']})")
        docs = list({d.doc_id: d for d in found.values()}.values())
        signals.append(Signal(
            alert_id=a["alert_id"], kind="explains", code="DOCUMENTED_EVENT",
            facts="; ".join(parts) + ", to the penny.",
            evidence=list(dict.fromkeys([d.doc_id for d in docs] + _event_supporting(b, docs) + sorted(found))),
            strength="hard", source="explainers.documented_event",
        ))
    return signals, []


# --------------------------------------------------------------------------- REFUND_OF_EARLIER_PAYMENT

def _same_party(t: dict, e: dict) -> bool:
    if _is_cash_in(t) or _is_cash_in(e):  # cash comes back as cash: withdrawal then deposit
        return "cash" in (t.get("channel") or "") and "cash" in (e.get("channel") or "")
    return (same_name(_party(t.get("counterparty_name")), _party(e.get("counterparty_name")))
            or _same_account(t.get("counterparty_account"), e.get("counterparty_account")))


def _twin(b: CaseBundle, t: dict) -> tuple[dict, dict] | None:
    """(return, original): t and the closest transaction going the other way for the same amount with the same party.
    t may be the return of an earlier payment, or the original of a later return."""
    best = None
    for e in b.txns.values():
        if (e["transaction_id"] == t["transaction_id"] or e.get("direction") == t.get("direction")
                or not _same_amount(e["amount_gbp"], t["amount_gbp"]) or not _same_party(t, e)):
            continue
        pair = (t, e) if e.get("booked_at", "") < t.get("booked_at", "") else (e, t)
        gap = abs((_txn_date(pair[0]) or date.min) - (_txn_date(pair[1]) or date.min)).days
        if best is None or gap < best[0]:
            best = (gap, pair)
    return best[1] if best else None


def _covering_review(b: CaseBundle, e: dict, t: dict) -> dict | None:
    """An earlier review written between the original payment and its return (it can describe only the original)."""
    ed, td = _txn_date(e), _txn_date(t)
    for r in b.reviews:
        rd = parse_date(r.get("reviewed_on"))
        if rd and ed and td and ed <= rd <= td:
            return r
    return None


def _refund_doc(b: CaseBundle, t: dict, e: dict) -> Doc | None:
    """A document written between the two payments that confirms the return: it states the amount and names the
    reference number, the account or the (non-customer) party, and isn't addressed to someone else."""
    ed, td = _txn_date(e), _txn_date(t)
    refs = set(re.findall(r"\d{3,}", f"{t.get('reference') or ''} {e.get('reference') or ''}"))
    accts = [a for a in (t.get("counterparty_account"), e.get("counterparty_account")) if len(_digits(a)) >= 6]
    party = _party(t.get("counterparty_name") or e.get("counterparty_name"))
    if same_name(party, b.customer.get("name")):
        party = ""
    for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
        dd = _doc_date(doc)
        if not dd or not ed or not td or not ed <= dd <= td:
            continue
        if not any(_same_amount(x, t["amount_gbp"]) for x in amounts(doc.text)) or _addressed_elsewhere(b, doc):
            continue
        text = f"{doc.title}\n{doc.text}"
        if (any(r in text for r in refs) or any(a in text for a in accts)
                or (party and _mentioned(party, text)) or (_is_cash_in(t) and re.search(r"withdr[ae]w", text, re.I))):
            return doc
    return None


def _describe(t: dict, verb_in: str, verb_out: str) -> str:
    party = _party(t.get("counterparty_name"))
    if "cash" in (t.get("channel") or ""):
        what = "cash deposited" if t.get("direction") == "in" else "cash withdrawn"
    else:
        what = f"{verb_in} {party}" if t.get("direction") == "in" else f"{verb_out} {party}"
    d = _txn_date(t)
    return f"the {money(t['amount_gbp'])} {what} on {fmt_date(d) if d else '?'} ({t['transaction_id']})"


def refund(b: CaseBundle) -> Checks:
    """Money that is the return of an earlier payment: a transaction going the other way for the same amount with the
    same party (cash: withdrawal then deposit), confirmed by a document written between the two (venue email, credit
    note, cancellation confirmation, chat). Cash needs an earlier review written in between that covers the withdrawal.
    Both legs count as explained; the alert is explained when, without them, it would not have fired."""
    signals: list[Signal] = []
    for a in b.alerts:
        if a.get("rule_id") not in ("TM01", "TM02", "TM05", "TM06", "TM07", "TM08"):
            continue
        txns = b.alert_txns(a)
        explained: dict[str, Doc] = {}
        pairs = []
        for x in txns:
            if x["transaction_id"] in explained:
                continue
            pair = _twin(b, x)
            if not pair:
                continue
            t, e = pair  # t returns e
            doc = _refund_doc(b, t, e)
            review = _covering_review(b, e, t)
            if not doc or (_is_cash_in(t) and not (review and re.search(r"withdr", review.get("note", ""), re.I))):
                continue
            explained[t["transaction_id"]] = doc
            explained[e["transaction_id"]] = doc
            pairs.append((t, e, doc, review))
        if not pairs or not _own_covers(b, a, txns, explained):
            continue
        parts, evidence = [], []
        for t, e, doc, review in pairs:
            dd = _doc_date(doc)
            parts.append(f"{doc.doc_id} ({doc.title}, dated {fmt_date(dd)}) confirms that "
                         f"{_describe(t, 'received from', 'paid back to')} returns "
                         f"{_describe(e, 'received from', 'paid to')}"
                         + (f", which earlier review {review['review_id']} covered" if review else ""))
            evidence += [doc.doc_id] + ([review["review_id"]] if review else []) + [t["transaction_id"], e["transaction_id"]]
        signals.append(Signal(
            alert_id=a["alert_id"], kind="explains", code="REFUND_OF_EARLIER_PAYMENT",
            facts="; ".join(parts) + ", for the same amount.",
            evidence=list(dict.fromkeys(evidence)), strength="hard", source="explainers.refund",
        ))
    return signals, []


# --------------------------------------------------------------------------- INVOICE_MATCHES

# An invoice or contract is paid on or after its date; a business's own sales invoices may be issued a few days after
# the money for them arrives, so receipts get a short grace when the row carries the transaction's reference number.
INVOICE_MAX_DAYS_BEFORE = 90
INVOICE_RECEIPT_GRACE_DAYS = 7
_INVOICE_DOC_KINDS = ("invoice", "contract", "schedule", "agreement", "order", "payment_file")
_NOT_INVOICE_DOC_KINDS = ("factoring", "employment")


def _is_invoice_doc(doc: Doc) -> bool:
    kind = (doc.type or "").lower()
    return any(k in kind for k in _INVOICE_DOC_KINDS) and not any(k in kind for k in _NOT_INVOICE_DOC_KINDS)


def _invoice_contradicts(b: CaseBundle, doc: Doc, t: dict) -> bool:
    """The document names a different buyer/borrower than the customer, or a different account to pay."""
    customer = b.customer.get("name")
    for k in ("buyer", "customer", "borrower", "bill to"):
        v = doc.fields.get(k)
        if v and not same_name(v.split(",")[0], customer):
            return True
    pay_to = doc.fields.get("pay to") or ""
    if len(_digits(pay_to)) >= 4 and t.get("counterparty_account") and not _same_account(pay_to, t["counterparty_account"]):
        return True
    return False


def _units(doc: Doc) -> list[tuple[str, date | None]]:
    """What can match one transaction: each table row (with its own date if it has one), then the whole document."""
    out = []
    for rows in _tables(doc):
        for r in rows:
            text = " | ".join(r.values())
            out.append((text, next((d for d in (parse_date(v) for v in r.values()) if d), None)))
    out.append((doc.text, None))
    return out


def _invoice_unit_for(b: CaseBundle, t: dict, used: set[tuple[str, int]]) -> tuple[Doc, int] | None:
    """A document (or one of its table rows) that matches t on amount, party, reference number and date."""
    td = _txn_date(t)
    party = _party(t.get("counterparty_name"))
    if not td or not party or same_name(party, b.customer.get("name")):
        return None
    refs = re.findall(r"\d{3,}", t.get("reference") or "")
    for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
        if not _is_invoice_doc(doc) or _invoice_contradicts(b, doc, t):
            continue
        header = f"{doc.title}\n" + "\n".join(doc.fields.values())
        for i, (text, row_date) in enumerate(_units(doc)):
            if (doc.doc_id, i) in used or not any(_same_amount(x, t["amount_gbp"]) for x in amounts(text)):
                continue
            if not (_mentioned(party, text) or _mentioned(party, header)):
                continue
            if any(r not in text and r not in doc.text and r not in header for r in refs):
                continue
            ud = row_date or _doc_date(doc)
            if not ud:
                continue
            gap = (td - ud).days
            grace = INVOICE_RECEIPT_GRACE_DAYS if t.get("direction") == "in" and refs and all(r in text for r in refs) else 0
            if -grace <= gap <= INVOICE_MAX_DAYS_BEFORE:
                return doc, i
    return None


def invoice_matches(b: CaseBundle) -> Checks:
    """Payments matched to the invoices, contracts and schedules behind them: an invoice / contract / schedule row /
    payment-file row with the same amount, naming the counterparty, carrying the transaction's reference number,
    dated on or before the payment, and not naming another buyer or account. Also the money in that such a document
    accounts for (a loan agreement's principal, the business's own freight invoices). The alert is explained when,
    without the matched transactions, it would not have fired."""
    signals: list[Signal] = []
    for a in b.alerts:
        if a.get("rule_id") not in ("TM01", "TM02", "TM03", "TM04", "TM06", "TM08"):
            continue
        txns = b.alert_txns(a)
        used: set[tuple[str, int]] = set()
        found: dict[str, Doc] = {}
        for t in sorted(txns, key=lambda t: (t.get("booked_at", ""), t["transaction_id"])):
            hit = _invoice_unit_for(b, t, used)
            if hit:
                doc, i = hit
                if i < len(_units(doc)) - 1:  # a table row is used once; a whole document may back several rows
                    used.add((doc.doc_id, i))
                found[t["transaction_id"]] = doc
        if not found or not _own_covers(b, a, txns, found):
            continue
        matched = [t for t in txns if t["transaction_id"] in found]
        docs = list({found[t["transaction_id"]].doc_id: found[t["transaction_id"]] for t in matched}.values())
        if len(matched) <= 3:
            facts = "; ".join(
                f"{found[t['transaction_id']].doc_id} ({found[t['transaction_id']].title}) matches the "
                f"{money(t['amount_gbp'])} {'paid to' if t.get('direction') == 'out' else 'received from'} "
                f"{_party(t.get('counterparty_name'))} on {fmt_date(_txn_date(t))} ({t['transaction_id']})"
                for t in matched) + " on amount, party and reference."
        else:
            parties = {name_key(_party(t.get("counterparty_name"))) for t in matched}
            facts = (f"{' and '.join(d.doc_id + ' (' + d.title + ')' for d in docs)} "
                     f"list{'s' if len(docs) == 1 else ''} each of the {len(matched)} alerted payments to "
                     f"{len(parties)} {'party' if len(parties) == 1 else 'parties'} with the same amount "
                     f"({money(sum(t['amount_gbp'] for t in matched))} in all).")
        held = b.case.get("held_payment_id")
        ids = sorted(found)
        shown = ([held] if held in found else []) + [i for i in ids if i != held][:8]
        signals.append(Signal(
            alert_id=a["alert_id"], kind="explains", code="INVOICE_MATCHES", facts=facts,
            evidence=list(dict.fromkeys([d.doc_id for d in docs] + shown)), strength="hard",
            source="explainers.invoice_matches",
        ))
    return signals, []


# --------------------------------------------------------------------------- THIRD_PARTY_DOCUMENTED

REMITTANCE_MAX_DAYS_BEFORE = 7
_GIVER = re.compile(r"\bI,\s*([^,]+),")


def _kind(doc: Doc, *words: str) -> bool:
    return any(w in (doc.type or "").lower() for w in words)


def _gift_doc_for(b: CaseBundle, t: dict, payer: str) -> Doc | None:
    """A gift letter from the payer to the customer for this amount, written shortly before the money arrived."""
    td = _txn_date(t)
    for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
        if not _kind(doc, "gift"):
            continue
        dd = _doc_date(doc)
        if not dd or not td or not 0 <= (td - dd).days <= EVENT_DOC_MAX_DAYS_BEFORE:
            continue
        m = _GIVER.search(doc.text)
        giver = m[1].strip() if m else re.sub(r"^.*\bfrom\s+", "", doc.title or "", flags=re.I)
        if not same_name(giver, payer) or not _mentioned(b.customer.get("name", ""), doc.text):
            continue
        if any(_same_amount(x, t["amount_gbp"]) for x in amounts(doc.text)) and not _addressed_elsewhere(b, doc):
            return doc
    return None


def _advance_docs_for(b: CaseBundle, t: dict, payer: str) -> list[Doc] | None:
    """An invoice-finance advance: an agreement with the payer, and the payer's remittance advice to the customer stating
    this amount; if the advice gives the financed total and the agreement the advance rate, total x rate = the credit."""
    td = _txn_date(t)
    agreements = [d for d in b.docs.values() if _kind(d, "factoring", "finance")
                  and _mentioned(payer, f"{d.title}\n{d.text}") and (_doc_date(d) or date.max) <= td]
    for adv in sorted(b.docs.values(), key=lambda d: d.doc_id):
        dd = _doc_date(adv)
        if (not _kind(adv, "remittance") or not dd or not 0 <= (td - dd).days <= REMITTANCE_MAX_DAYS_BEFORE
                or not _mentioned(payer, f"{adv.title}\n{adv.text}") or _addressed_elsewhere(b, adv)):
            continue
        figures = amounts(adv.text)
        if not any(_same_amount(x, t["amount_gbp"]) for x in figures):
            continue
        for agr in sorted(agreements, key=lambda d: d.doc_id):
            rates = [float(r) for r in re.findall(r"(\d{1,3}(?:\.\d+)?)\s?%", f"{agr.text}\n{adv.text}")]
            totals = [x for x in figures if x > t["amount_gbp"]]
            if rates and totals and not any(abs(x * r / 100 - t["amount_gbp"]) <= 0.01 for x in totals for r in rates):
                continue  # the advice's own arithmetic doesn't give this credit
            return [agr, adv]
    return None


def third_party_documented(b: CaseBundle) -> Checks:
    """A documented relationship explains money from a third party: a gift letter from the payer to the customer for
    the amount, or an invoice-finance advance backed by the agreement and the remittance advice. Red flags about the
    payer (a listed party, a fraud report) still win in decide()."""
    signals: list[Signal] = []
    customer = b.customer.get("name")
    for a in b.alerts:
        if a.get("rule_id") not in ("TM01", "TM02", "TM08"):
            continue
        txns = b.alert_txns(a)
        found: dict[str, list[Doc]] = {}
        for t in txns:
            payer = _party(t.get("counterparty_name"))
            if t.get("direction") != "in" or not payer or same_name(payer, customer):
                continue
            gift = _gift_doc_for(b, t, payer)
            docs = [gift] if gift else _advance_docs_for(b, t, payer)
            if docs:
                found[t["transaction_id"]] = docs
        if not found or not _own_covers(b, a, txns, {k: v[0] for k, v in found.items()}):
            continue
        parts = []
        for t in txns:
            docs = found.get(t["transaction_id"])
            if not docs:
                continue
            payer = _party(t.get("counterparty_name"))
            what = (f"a gift from {payer} to {customer}" if _kind(docs[0], "gift")
                    else f"an invoice-finance advance from {payer} under its agreement")
            parts.append(f"{' and '.join(d.doc_id for d in docs)} document{'s' if len(docs) == 1 else ''} the "
                         f"{money(t['amount_gbp'])} received on {fmt_date(_txn_date(t))} ({t['transaction_id']}) as {what}")
        evidence = [d.doc_id for v in found.values() for d in v] + sorted(found)
        signals.append(Signal(
            alert_id=a["alert_id"], kind="explains", code="THIRD_PARTY_DOCUMENTED",
            facts="; ".join(parts) + ", for the same amount.",
            evidence=list(dict.fromkeys(evidence)), strength="hard", source="explainers.third_party_documented",
        ))
    return signals, []


# Add one function per check, (b) -> (signals, questions), and list it here.
# Next: collection_documented, group_company (also the payments and FX TM07 supplier invoice), collection_documented, group_company,
# third_party_documented, own account on payments and FX (outgoing own-account transfer; needs a team decision).
# list_match_different_party is Lorenzo's (red_flags.listed_party).
CHECKS: list = [business_records, own_account, returning_customer, documented_event, refund, invoice_matches,
                third_party_documented]
