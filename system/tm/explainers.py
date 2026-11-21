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
                      "sir or madam", "colleague", "applicant", "investor", "valued customer", "valued client",
                      "account holder", "member"}
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


_ROLE_WORDS = {"sir", "madam", "beneficiary", "tenant", "customer", "client", "policyholder", "colleague", "applicant",
               "investor", "member", "employee", "holder", "valued", "former", "friend", "team", "partner", "supplier",
               "student", "patient", "account", "all", "whom", "concern", "parent", "guardian", "owner", "director"}


def _looks_like_a_name(greeting: str) -> bool:
    """'Robin Other' is a person; 'Investor', 'valued client', 'Former Employee' are roles. A name has at least two
    capitalised words and no role word."""
    words = re.findall(r"[A-Za-z][\w'-]*", greeting)
    return (len(words) >= 2 and all(w[0].isupper() for w in words)
            and not ({w.lower() for w in words} & _ROLE_WORDS) and norm(greeting) not in _GENERIC_ADDRESSEE)


def _addressed_elsewhere(b: CaseBundle, doc: Doc) -> bool:
    """The document names someone other than the customer as its addressee or client."""
    customer = b.customer.get("name")
    named = [doc.fields.get(k) for k in ("client", "policyholder", "beneficiary") if doc.fields.get(k)]
    named += [m for m in _GREETING.findall(doc.text) if _looks_like_a_name(m)]
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


def _amount_key(doc: Doc, t: dict) -> tuple:
    return (doc.doc_id, round(t["amount_gbp"], 2))


def _match_each_once(txns: list[dict], finder) -> dict:
    """Run finder(t, used) over the transactions in booking order, so one document's amount backs one transaction:
    a receipt for £X can't explain two deposits of £X. finder returns (result, key) or None."""
    used: set = set()
    found = {}
    for t in sorted(txns, key=lambda t: (t.get("booked_at", ""), t["transaction_id"])):
        hit = finder(t, used)
        if hit:
            result, key = hit
            used.add(key)
            found[t["transaction_id"]] = result
    return found


def _event_doc_for(b: CaseBundle, t: dict, used: set = frozenset()) -> Doc | None:
    """A document about a one-off event that accounts for transaction t (see documented_event), not already used for
    another transaction of the same amount."""
    customer = b.customer.get("name")
    td = _txn_date(t)
    if not td:
        return None
    cash = _is_cash_in(t)
    payer = _party(t.get("counterparty_name"))
    if not cash and (not payer or same_name(payer, customer)):
        return None  # own-name money is own_account's business
    for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
        if not _is_event_doc(doc) or _amount_key(doc, t) in used:
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
        found = _match_each_once(txns, lambda t, used: (lambda d: (d, _amount_key(d, t)) if d else None)(
            _event_doc_for(b, t, used)))
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


def _twin(b: CaseBundle, t: dict, taken: set = frozenset()) -> tuple[dict, dict] | None:
    """(return, original): t and the closest transaction going the other way for the same amount with the same party,
    not already paired with another one (one payment is returned once). t may be the return of an earlier payment, or
    the original of a later return."""
    best = None
    for e in b.txns.values():
        if (e["transaction_id"] == t["transaction_id"] or e["transaction_id"] in taken
                or e.get("direction") == t.get("direction")
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


def _refund_doc(b: CaseBundle, t: dict, e: dict, used: set = frozenset()) -> Doc | None:
    """A document written between the two payments that confirms the return: it states the amount and names the
    reference number, the account or the (non-customer) party, and isn't addressed to someone else (nor already used
    to confirm another return of the same amount)."""
    ed, td = _txn_date(e), _txn_date(t)
    refs = set(re.findall(r"\d{3,}", f"{t.get('reference') or ''} {e.get('reference') or ''}"))
    accts = [a for a in (t.get("counterparty_account"), e.get("counterparty_account")) if len(_digits(a)) >= 6]
    party = _party(t.get("counterparty_name") or e.get("counterparty_name"))
    if same_name(party, b.customer.get("name")):
        party = ""
    for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
        dd = _doc_date(doc)
        if not dd or not ed or not td or not ed <= dd <= td or _amount_key(doc, t) in used:
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
        used_docs: set = set()
        pairs = []
        for x in sorted(txns, key=lambda t: (t.get("booked_at", ""), t["transaction_id"])):
            if x["transaction_id"] in explained:
                continue
            pair = _twin(b, x, set(explained))
            if not pair:
                continue
            t, e = pair  # t returns e
            doc = _refund_doc(b, t, e, used_docs)
            review = _covering_review(b, e, t)
            if not doc or (_is_cash_in(t) and not (review and re.search(r"withdr", review.get("note", ""), re.I))):
                continue
            used_docs.add(_amount_key(doc, t))
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
    """What can match one transaction: each table row (with its own date if it has one), then the text outside the
    tables. The last unit leaves the table rows out, so a row's amount is never counted a second time through it."""
    out = []
    for rows in _tables(doc):
        for r in rows:
            text = " | ".join(r.values())
            out.append((text, next((d for d in (parse_date(v) for v in r.values()) if d), None)))
    out.append(("\n".join(line for line in doc.text.splitlines() if not line.strip().startswith("|")), None))
    return out


def _unit_key(doc: Doc, i: int, n_units: int, t: dict) -> tuple:
    """What a match uses up: a table row once; outside the tables, one transaction per amount the document states."""
    return (doc.doc_id, i) if i < n_units - 1 else (doc.doc_id, "text", round(t["amount_gbp"], 2))


def _invoice_unit_for(b: CaseBundle, t: dict, used: set[tuple]) -> tuple[Doc, tuple] | None:
    """A document (or one of its table rows) that matches t on amount, party, reference number and date, and that no
    other transaction of the alert has used. Returns the document and the key of what it used up."""
    td = _txn_date(t)
    party = _party(t.get("counterparty_name"))
    if not td or not party or same_name(party, b.customer.get("name")):
        return None
    refs = re.findall(r"\d{3,}", t.get("reference") or "")
    for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
        if not _is_invoice_doc(doc) or _invoice_contradicts(b, doc, t):
            continue
        header = f"{doc.title}\n" + "\n".join(doc.fields.values())
        units = _units(doc)
        for i, (text, row_date) in enumerate(units):
            key = _unit_key(doc, i, len(units), t)
            if key in used or not any(_same_amount(x, t["amount_gbp"]) for x in amounts(text)):
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
                return doc, key
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
        used: set[tuple] = set()  # each table row, and each amount stated outside the tables, backs one transaction
        found: dict[str, Doc] = {}
        for t in sorted(txns, key=lambda t: (t.get("booked_at", ""), t["transaction_id"])):
            hit = _invoice_unit_for(b, t, used)
            if hit:
                doc, key = hit
                used.add(key)
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


def _gift_doc_for(b: CaseBundle, t: dict, payer: str, used: set = frozenset()) -> Doc | None:
    """A gift letter from the payer to the customer for this amount, written shortly before the money arrived (and not
    already used for another gift of the same amount)."""
    td = _txn_date(t)
    for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
        if not _kind(doc, "gift") or _amount_key(doc, t) in used:
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


def _advance_docs_for(b: CaseBundle, t: dict, payer: str, used: set = frozenset()) -> list[Doc] | None:
    """An invoice-finance advance: an agreement with the payer, and the payer's remittance advice to the customer stating
    this amount (each advice backs one advance); if the advice gives the financed total and the agreement the advance
    rate, total x rate = the credit."""
    td = _txn_date(t)
    agreements = [d for d in b.docs.values() if _kind(d, "factoring", "finance")
                  and _mentioned(payer, f"{d.title}\n{d.text}") and (_doc_date(d) or date.max) <= td]
    for adv in sorted(b.docs.values(), key=lambda d: d.doc_id):
        dd = _doc_date(adv)
        if (not _kind(adv, "remittance") or _amount_key(adv, t) in used
                or not dd or not 0 <= (td - dd).days <= REMITTANCE_MAX_DAYS_BEFORE
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
        def finder(t: dict, used: set):
            payer = _party(t.get("counterparty_name"))
            if t.get("direction") != "in" or not payer or same_name(payer, customer):
                return None
            gift = _gift_doc_for(b, t, payer, used)
            docs = [gift] if gift else _advance_docs_for(b, t, payer, used)
            return (docs, _amount_key(docs[-1], t)) if docs else None  # the letter / the advice is used up

        found: dict[str, list[Doc]] = _match_each_once(txns, finder)
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


# --------------------------------------------------------------------------- COLLECTION_DOCUMENTED

_PER_PERSON = re.compile(r"£\s?([\d,]+(?:\.\d+)?)\s*per\s+(?:person|head|traveller|participant)", re.I)
_LISTED = re.compile(r"^\s*\d{1,3}[.)]\s+(.+?)\s*$", re.M)
_COMPANY_WORDS = {"ltd", "limited", "plc", "llp", "llc", "inc", "co", "company", "srl", "sas", "gmbh", "bv"}
COLLECTION_MIN_PAYERS = 3


def _is_company(name: str | None) -> bool:
    return bool(set(norm(name).split()) & _COMPANY_WORDS)


def _collection_terms(doc: Doc) -> dict | None:
    """From a booking confirmation: price per person, total, the people listed, and the payment account/reference."""
    m = _PER_PERSON.search(doc.text)
    names = _LISTED.findall(doc.text)
    if not m or not names:
        return None
    price = float(m[1].replace(",", ""))
    total = next((x for x in amounts(doc.text) if not _same_amount(x, price) and x > price), None)
    if total is None or not _same_amount(price * len(names), total):
        return None  # the listed travellers at the stated price must make the stated total
    pay = doc.fields.get("payment") or doc.text
    ref = doc.fields.get("booking reference") or ""
    return {"price": price, "total": total, "names": names, "pay": pay, "ref": ref}


def _pays_as_instructed(t: dict, doc: Doc, terms: dict) -> bool:
    """The stated total, to the company named in the confirmation, to its stated account, with its reference."""
    return (t.get("direction") == "out" and _same_amount(t["amount_gbp"], terms["total"])
            and _mentioned(_party(t.get("counterparty_name")), f"{doc.title}\n{terms['pay']}")
            and (not t.get("counterparty_account") or t["counterparty_account"] in terms["pay"]
                 or _same_account(t["counterparty_account"], terms["pay"]))
            and (not terms["ref"] or terms["ref"] in (t.get("reference") or "")))


def _collection_for(b: CaseBundle, txns: list[dict]) -> tuple[Doc, dict[str, Doc]] | None:
    """A booking confirmation that lists the customer and the payers, at the per-person price, and whose total was paid
    as instructed (looked for among all the customer's transactions: a TM04 alert holds only the money in). A listed
    traveller paying another amount contradicts it. Returns the document and the alert transactions it explains."""
    customer = b.customer.get("name")
    for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
        if not _kind(doc, "booking"):
            continue
        terms = _collection_terms(doc)
        if not terms or not any(same_name(n, customer) for n in terms["names"]):
            continue
        paid = [t for t in b.txns.values() if _pays_as_instructed(t, doc, terms)]
        if not paid:
            continue  # the money didn't go where the confirmation says
        explained: dict[str, Doc] = {t["transaction_id"]: doc for t in paid if t["transaction_id"] in
                                     {x["transaction_id"] for x in txns}}
        contradicted = False
        for t in txns:
            payer = t.get("counterparty_name")
            if t.get("direction") != "in" or not any(same_name(n, payer) for n in terms["names"]) \
                    or same_name(payer, customer):
                continue
            if _same_amount(t["amount_gbp"], terms["price"]):
                explained[t["transaction_id"]] = doc
            else:
                contradicted = True  # a listed traveller paid something other than the stated price
        if explained and not contradicted:
            return doc, explained
    return None


def _collection_pattern(b: CaseBundle, txns: list[dict]) -> tuple[list[dict], dict, int] | None:
    """Without a confirmation: at least COLLECTION_MIN_PAYERS different people each pay the same amount, then one
    payment of that amount times the number of payers (or one more, the customer's own share) goes to a company with a
    numbered reference. Returns (payers' transactions, the payment out, shares)."""
    customer = b.customer.get("name")
    by_amount: dict[float, list[dict]] = {}
    for t in txns:
        if t.get("direction") == "in" and t.get("counterparty_name") and not same_name(t["counterparty_name"], customer) \
                and not _is_company(t["counterparty_name"]):
            by_amount.setdefault(round(t["amount_gbp"], 2), []).append(t)
    for price, ins in sorted(by_amount.items(), key=lambda kv: -len(kv[1])):
        people = {name_key(t["counterparty_name"]) for t in ins}
        if len(people) < COLLECTION_MIN_PAYERS:
            continue
        last_in = max(t.get("booked_at", "") for t in ins)
        for out in b.txns.values():
            if (out.get("direction") != "out" or not _is_company(out.get("counterparty_name"))
                    or not re.search(r"\d{3,}", out.get("reference") or "") or out.get("booked_at", "") < last_in):
                continue
            for shares in (len(ins) + 1, len(ins)):
                if _same_amount(out["amount_gbp"], price * shares):
                    return ins, out, shares
    return None


def collection_documented(b: CaseBundle) -> Checks:
    """A documented collection made on behalf of named people: a booking confirmation lists the customer and every
    payer, each paid the per-person price, and the total went to the stated account with the booking reference.
    The same pattern with no confirmation on file is not suspicious but needs that one document: RFI."""
    signals: list[Signal] = []
    for a in b.alerts:
        if a.get("rule_id") not in ("TM02", "TM04"):
            continue
        txns = b.alert_txns(a)
        hit = _collection_for(b, txns)
        if hit:
            doc, explained = hit
            if _own_covers(b, a, txns, explained):
                ins = [t for t in txns if t["transaction_id"] in explained and t.get("direction") == "in"]
                terms = _collection_terms(doc)
                outs = [t for t in sorted(b.txns.values(), key=lambda t: t["transaction_id"])
                        if _pays_as_instructed(t, doc, terms)][:1]
                facts = (f"{doc.doc_id} ({doc.title}) lists {len(terms['names'])} travellers including "
                         f"{b.customer.get('name')} at {money(terms['price'])} each; the {len(ins)} payers in the alert "
                         f"are all on it and each paid {money(terms['price'])}"
                         + (f", and the {money(outs[0]['amount_gbp'])} paid to {_party(outs[0].get('counterparty_name'))}"
                            f" on {fmt_date(_txn_date(outs[0]))} ({outs[0]['transaction_id']}) is the stated total"
                            if outs else "") + ".")
                signals.append(Signal(
                    alert_id=a["alert_id"], kind="explains", code="COLLECTION_DOCUMENTED", facts=facts,
                    evidence=list(dict.fromkeys([doc.doc_id] + [t["transaction_id"] for t in outs + ins])),
                    strength="hard", source="explainers.collection_documented",
                ))
                continue
        # The RFI twin only when no booking confirmation is on file at all: a confirmation the payments don't follow
        # is not a missing document, and is left to the fallback.
        pattern = None if any(_kind(d, "booking") for d in b.docs.values()) else _collection_pattern(b, txns)
        if pattern:
            ins, out, shares = pattern
            price = ins[0]["amount_gbp"]
            signals.append(Signal(
                alert_id=a["alert_id"], kind="partial", code="RFI_PURPOSE_DOCUMENTS",
                facts=(f"{len(ins)} people each paid {money(price)} and {money(out['amount_gbp'])} ({shares} shares) went "
                       f"to {_party(out.get('counterparty_name'))} on {fmt_date(_txn_date(out))} with reference "
                       f"{out.get('reference')} ({out['transaction_id']}), which looks like a group collection, but no "
                       f"booking confirmation is on file; ask the customer for the booking confirmation listing the "
                       f"travellers and the price per person."),
                evidence=list(dict.fromkeys([out["transaction_id"]] + [t["transaction_id"] for t in ins][:5])),
                strength="hard", source="explainers.collection_documented",
            ))
    return signals, []


# --------------------------------------------------------------------------- GROUP_COMPANY

GROUP_CONTROL_SHARE = 75.0  # the register's own control threshold ("owns 75% or more of shares")


def _group_chart(b: CaseBundle) -> tuple[Doc, dict[str, tuple[str, float]]] | None:
    """A group structure table on file: company -> (owner, share %). Read from any table with company/owner/share
    columns (the content, not the document's type)."""
    for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
        owners: dict[str, tuple[str, float]] = {}
        for rows in _tables(doc):
            for r in rows:
                company = next((v for k, v in r.items() if k == "company"), "")
                owner = next((v for k, v in r.items() if k.startswith("owne")), "")
                share = next((v for k, v in r.items() if "share" in k or k == "%"), "")
                pct = re.search(r"(\d{1,3}(?:\.\d+)?)\s?%", share)
                if company and owner and pct:
                    owners[name_key(company)] = (owner, float(pct[1]))
        if owners:
            return doc, owners
    return None


def _chain(owners: dict[str, tuple[str, float]], company: str) -> list[str]:
    """company, its controlling owner, that owner's controlling owner... (links below the control share stop it)."""
    out, seen = [company], set()
    while name_key(out[-1]) in owners and name_key(out[-1]) not in seen and len(out) < 6:
        seen.add(name_key(out[-1]))
        owner, pct = owners[name_key(out[-1])]
        if pct < GROUP_CONTROL_SHARE:
            break
        out.append(owner)
    return out


def _register_controllers(b: CaseBundle) -> list[str]:
    """People the customer's company register names as having significant control."""
    out = []
    for doc in b.docs.values():
        for rows in _tables(doc):
            for r in rows:
                person = next((v for k, v in r.items() if "significant control" in k), "")
                if person and same_name(doc.fields.get("company"), b.customer.get("name")):
                    out.append(person)
    return out


def _same_group(b: CaseBundle, owners: dict[str, tuple[str, float]], payer: str) -> str | None:
    """How the payer and the customer are in one group (None if they aren't): one controls the other, or both have
    the same ultimate controller. The customer's register controllers must appear in its chain, or it contradicts."""
    customer = b.customer.get("name", "")
    mine, theirs = _chain(owners, customer), _chain(owners, payer)
    if len(mine) == 1 and len(theirs) == 1:
        return None  # neither is in the chart with a controlling owner
    controllers = _register_controllers(b)
    if controllers and not any(same_name(c, x) for c in controllers for x in mine[1:]):
        return None  # the register names a controller the chart doesn't show
    if any(same_name(payer, x) for x in mine[1:]):
        return f"{payer} controls {customer}"
    if any(same_name(customer, x) for x in theirs[1:]):
        return f"{customer} controls {payer}"
    if len(mine) > 1 and len(theirs) > 1 and same_name(mine[-1], theirs[-1]):
        return f"{payer} and {customer} are both controlled by {mine[-1]}"
    return None


def group_company(b: CaseBundle) -> Checks:
    """Money from a verified company in the same group: a group structure on file shows the payer controls the
    customer, is controlled by it, or shares its ultimate owner (each link at or above the control share), consistent
    with the company register. Payments out that the same alert holds are matched to their invoices; a held payment so
    matched is also reported as INVOICE_MATCHES, which the payments-and-FX invoice rule needs."""
    signals: list[Signal] = []
    chart = _group_chart(b)
    if not chart:
        return signals, []
    chart_doc, owners = chart
    customer = b.customer.get("name")
    for a in b.alerts:
        if a.get("rule_id") not in ("TM01", "TM02", "TM08"):
            continue
        txns = b.alert_txns(a)
        group_in: dict[str, Doc] = {}
        why = ""
        for t in txns:
            payer = _party(t.get("counterparty_name"))
            if t.get("direction") == "in" and payer and not same_name(payer, customer):
                how = _same_group(b, owners, payer)
                if how:
                    group_in[t["transaction_id"]] = chart_doc
                    why = why or how
        if not group_in:
            continue
        invoiced = _match_each_once([t for t in txns if t.get("direction") == "out"],
                                    lambda t, used: _invoice_unit_for(b, t, used))
        explained = {**group_in, **invoiced}
        if not _own_covers(b, a, txns, explained):
            continue
        ins = [t for t in txns if t["transaction_id"] in group_in]
        support = [d.doc_id for d in sorted(b.docs.values(), key=lambda d: d.doc_id)
                   if d.doc_id != chart_doc.doc_id and not _is_invoice_doc(d)
                   and any(_mentioned(_party(t.get("counterparty_name")), d.text) for t in ins)]
        facts = (f"{chart_doc.doc_id} ({chart_doc.title}) shows {why}, so "
                 + " and ".join(f"the {money(t['amount_gbp'])} received from {_party(t.get('counterparty_name'))} on "
                                f"{fmt_date(_txn_date(t))} ({t['transaction_id']})" for t in ins)
                 + " came from a company in the customer's own group.")
        signals.append(Signal(
            alert_id=a["alert_id"], kind="explains", code="GROUP_COMPANY", facts=facts,
            evidence=list(dict.fromkeys([chart_doc.doc_id] + support + sorted(group_in))), strength="hard",
            source="explainers.group_company",
        ))
        held = b.case.get("held_payment_id")
        if held in invoiced:
            t = b.txns[held]
            doc = invoiced[held]
            signals.append(Signal(
                alert_id=a["alert_id"], kind="explains", code="INVOICE_MATCHES",
                facts=(f"{doc.doc_id} ({doc.title}) matches the held payment of {money(t['amount_gbp'])} to "
                       f"{_party(t.get('counterparty_name'))} ({held}) on amount, payee and reference."),
                evidence=[doc.doc_id, held], strength="hard", source="explainers.group_company",
            ))
    return signals, []


# --------------------------------------------------------------------------- RFI twins: one document missing

FUNDED_PURCHASE_MAX_DAYS = 2
FUNDED_PURCHASE_MAX_RATIO = 1.5  # the customer tops up from their own money; a pass-through keeps a cut instead


def _own_round_trip(b: CaseBundle, txns: list[dict]):
    """Money in from an account in the customer's own name and back out to that same account, same amount, with no
    document showing the customer holds it."""
    customer = b.customer.get("name")
    for t in txns:
        if t.get("direction") != "in" or not same_name(t.get("counterparty_name"), customer) \
                or len(_digits(t.get("counterparty_account"))) < 6:
            continue
        back = [e for e in b.txns.values() if e.get("direction") == "out" and _same_amount(e["amount_gbp"], t["amount_gbp"])
                and _same_account(e.get("counterparty_account"), t.get("counterparty_account"))
                and e.get("booked_at", "") > t.get("booked_at", "")]
        if back:
            e = back[0]
            return ([t, e], "RFI_SOURCE_OF_FUNDS",
                    f"{money(t['amount_gbp'])} came in from account {t['counterparty_account']} in "
                    f"{customer}'s name on {fmt_date(_txn_date(t))} ({t['transaction_id']}) and went back to it on "
                    f"{fmt_date(_txn_date(e))} ({e['transaction_id']}), but nothing on file shows the customer holds "
                    f"that account; ask for a statement of account {t['counterparty_account']} in the customer's name "
                    f"(or the cancellation confirmation).")
    return None


def _funded_purchase(b: CaseBundle, txns: list[dict]):
    """Money in from one company, then within days a slightly larger payment to another company (the customer adds
    their own money): a purchase funded by a loan, a returned deposit and the like, with neither document on file."""
    customer = b.customer.get("name")
    for t in txns:
        payer = _party(t.get("counterparty_name"))
        if t.get("direction") != "in" or not _is_company(payer) or same_name(payer, customer):
            continue
        for e in sorted(b.txns.values(), key=lambda e: e.get("booked_at", "")):
            payee = _party(e.get("counterparty_name"))
            gap = ((_txn_date(e) or date.min) - (_txn_date(t) or date.max)).days
            if (e.get("direction") == "out" and _is_company(payee) and not same_name(payee, payer)
                    and 0 <= gap <= FUNDED_PURCHASE_MAX_DAYS and e.get("booked_at", "") > t.get("booked_at", "")
                    and t["amount_gbp"] < e["amount_gbp"] <= t["amount_gbp"] * FUNDED_PURCHASE_MAX_RATIO):
                return ([t, e], "RFI_PURPOSE_DOCUMENTS",
                        f"{money(t['amount_gbp'])} from {payer} ('{t.get('reference')}', {t['transaction_id']}) was "
                        f"followed on {fmt_date(_txn_date(e))} by {money(e['amount_gbp'])} to {payee} "
                        f"('{e.get('reference')}', {e['transaction_id']}), which looks like a purchase the customer "
                        f"topped up, but nothing on file documents either side; ask for the agreement or letter behind "
                        f"the money from {payer} and the invoice or receipt for the payment to {payee}.")
    return None


def _invoiced_receipts(b: CaseBundle, txns: list[dict]):
    """A business receiving money from several companies, each payment carrying a numbered reference (customers
    paying its invoices), with no invoices on file."""
    if b.customer.get("kind") != "business":
        return None
    ins = [t for t in txns if t.get("direction") == "in" and _is_company(t.get("counterparty_name"))
           and not same_name(t.get("counterparty_name"), b.customer.get("name"))
           and re.search(r"\d{3,}", t.get("reference") or "")]
    if len({name_key(_party(t["counterparty_name"])) for t in ins}) < 2:
        return None
    refs = ", ".join(f"{t.get('reference')} from {_party(t['counterparty_name'])}" for t in ins[:4])
    return (ins, "RFI_PURPOSE_DOCUMENTS",
            f"{len(ins)} payments from different companies, each with its own reference ({refs}), fit the customer's "
            f"business, but no invoices are on file; ask for the invoices behind these receipts"
            + (" and for the invoice behind the held payment." if b.case.get("held_payment_id") else "."))


def _staged_payments(b: CaseBundle, txns: list[dict]):
    """Payments to one beneficiary whose references run 1, 2, 3... after a common prefix: stage payments under a
    contract, with no payment schedule on file."""
    outs = [t for t in txns if t.get("direction") == "out"]
    if len(outs) < 2 or len({name_key(_party(t.get("counterparty_name"))) for t in outs}) != 1:
        return None
    parsed = [re.match(r"^(.*?)(\d{1,2})\s*$", (t.get("reference") or "").strip()) for t in outs]
    if not all(parsed) or len({p[1].strip().lower() for p in parsed}) != 1 or not parsed[0][1].strip():
        return None
    if sorted(int(p[2]) for p in parsed) != list(range(1, len(outs) + 1)):
        return None
    payee = _party(outs[0].get("counterparty_name"))
    return (outs, "RFI_PURPOSE_DOCUMENTS",
            f"{len(outs)} payments to {payee} referenced '{parsed[0][1].strip()} 1' to '{len(outs)}' "
            f"({money(sum(t['amount_gbp'] for t in outs))} in all) look like stage payments under a contract, but no "
            f"payment schedule is on file; ask for the contract and its payment schedule.")


_TWINS = (_own_round_trip, _funded_purchase, _invoiced_receipts, _staged_payments)


def missing_document(b: CaseBundle) -> Checks:
    """The RFI twins: a recognisable, unsuspicious pattern whose one deciding document is missing. Each fires only when
    its transactions would account for the alert (without them it wouldn't have fired). A partial signal never closes;
    a red flag still wins, and so does an explanation from another check."""
    signals: list[Signal] = []
    for a in b.alerts:
        txns = b.alert_txns(a)
        for twin in _TWINS:
            hit = twin(b, txns)
            if not hit:
                continue
            covered, code, facts = hit
            if a.get("rule_id") != "TM03" and not _own_covers(b, a, txns, {t["transaction_id"]: None for t in covered}):
                continue
            if a.get("rule_id") == "TM03" and {t["transaction_id"] for t in covered} != set(a.get("transaction_ids", [])):
                continue
            signals.append(Signal(
                alert_id=a["alert_id"], kind="partial", code=code, facts=facts,
                evidence=list(dict.fromkeys(t["transaction_id"] for t in covered))[:8], strength="hard",
                source=f"explainers.missing_document.{twin.__name__.lstrip('_')}",
            ))
            break
    return signals, []


# --------------------------------------------------------------------------- TM10: early redemption with a documented reason

REDEMPTION_LINK_DAYS = 7  # own top-up shortly before the purchase, proceeds out shortly after the sale
_JOB_ENDED = re.compile(r"redundan|terminat|end of your employment|last working day", re.I)


def _own_leg(b: CaseBundle, t: dict, direction: str, before: bool) -> dict | None:
    """The customer's own-name transfer that funded a purchase (before) or received the proceeds (after)."""
    td = _txn_date(t)
    for e in sorted(b.txns.values(), key=lambda e: e.get("booked_at", "")):
        ed = _txn_date(e)
        if (e.get("direction") != direction or not same_name(e.get("counterparty_name"), b.customer.get("name"))
                or not ed or not td):
            continue
        gap = (td - ed).days if before else (ed - td).days
        enough = e["amount_gbp"] >= t["amount_gbp"] - 0.005 if before else _same_amount(e["amount_gbp"], t["amount_gbp"])
        if 0 <= gap <= REDEMPTION_LINK_DAYS and enough:
            return e
    return None


def early_redemption_explained(b: CaseBundle) -> Checks:
    """TM10: fund units bought with the customer's own money and sold back early, the proceeds withdrawn to the
    customer's own name, with the reason documented before the sale: a letter from the declared employer ending the
    job and the customer's own request to sell."""
    signals: list[Signal] = []
    employer = b.customer.get("employer") or ""
    for a in b.alerts:
        if a.get("rule_id") != "TM10" or not employer:
            continue
        txns = b.alert_txns(a)
        buys = [t for t in txns if t.get("direction") == "out"]
        sells = [t for t in txns if t.get("direction") == "in"]
        if not buys or not sells:
            continue
        funded = [_own_leg(b, t, "in", before=True) for t in buys]
        paid_out = [_own_leg(b, t, "out", before=False) for t in sells]
        if not all(funded) or not all(paid_out):
            continue  # someone else's money in, or the proceeds to someone else: not this story
        sold_on = min(_txn_date(t) for t in sells)
        prior = [d for d in sorted(b.docs.values(), key=lambda d: d.doc_id)
                 if _doc_date(d) and _doc_date(d) <= sold_on]
        letter = next((d for d in prior if _mentioned(employer, f"{d.title}\n{d.text}") and _JOB_ENDED.search(d.text)), None)
        request = next((d for d in prior if d is not letter and re.search(r"\bsell\b", d.text, re.I)), None)
        if not letter or not request:
            continue
        facts = (f"{letter.doc_id} ({letter.title}, dated {fmt_date(_doc_date(letter))}) ends the customer's job at the "
                 f"declared employer {employer} and {request.doc_id} (dated {fmt_date(_doc_date(request))}) asks to sell, "
                 f"both before the units were sold on {fmt_date(sold_on)}; the units were bought with the customer's own "
                 f"{money(funded[0]['amount_gbp'])} ({funded[0]['transaction_id']}) and the "
                 f"{money(paid_out[0]['amount_gbp'])} proceeds went back to the customer ({paid_out[0]['transaction_id']}).")
        signals.append(Signal(
            alert_id=a["alert_id"], kind="explains", code="DOCUMENTED_EVENT", facts=facts,
            evidence=list(dict.fromkeys([letter.doc_id, request.doc_id] + [t["transaction_id"] for t in buys + sells])),
            strength="hard", source="explainers.early_redemption_explained",
        ))
    return signals, []


# --------------------------------------------------------------------------- funding through the declared own-account channel

FUNDING_ONWARD_DAYS = 2
FUNDING_ONWARD_MIN_SHARE = 0.9  # most of the funding goes straight on (the firm's fees and FX margin take the rest)


def _declared_own_funding(b: CaseBundle, t: dict) -> bool:
    """Money in from an account in the client's own name, when the client declared that as how it funds the account
    ('Bank transfer from own account'). The policy itself treats only funding from someone else's account as a trigger
    (TM08), so this is the expected channel, not an own-account claim that needs a statement."""
    channels = (b.customer.get("declared") or {}).get("expected_channels") or []
    return (t.get("direction") == "in" and same_name(t.get("counterparty_name"), b.customer.get("name"))
            and any("own account" in (c or "").lower() for c in channels))


def _statement_for_ending(b: CaseBundle, t: dict) -> Doc | None:
    """A statement in the client's name that says the account 'ending NNNN' (the transaction's) is held by the client
    and records the same amount."""
    last4 = _digits(t.get("counterparty_account"))[-4:]
    if len(last4) < 4:
        return None
    for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
        if (any(same_name(h, b.customer.get("name")) for h in _holders(doc)) and re.search(rf"ending\s+{last4}\b", doc.text)
                and any(_same_amount(x, t["amount_gbp"]) for x in amounts(doc.text))):
            return doc
    return None


def _onward(b: CaseBundle, t: dict, test) -> tuple[dict, Doc] | None:
    """The payment out within days that carries most of funding t on, and the document test(e) finds for it."""
    td = _txn_date(t)
    for e in sorted(b.txns.values(), key=lambda e: e.get("booked_at", "")):
        ed = _txn_date(e)
        if (e.get("direction") != "out" or not ed or not td or not 0 <= (ed - td).days <= FUNDING_ONWARD_DAYS
                or e.get("booked_at", "") <= t.get("booked_at", "")
                or not FUNDING_ONWARD_MIN_SHARE * t["amount_gbp"] <= e["amount_gbp"] <= t["amount_gbp"]):
            continue
        doc = test(e)
        if doc:
            return e, doc
    return None


def _order_backed(b: CaseBundle, e: dict) -> Doc | None:
    """The supplier invoice for e, when a purchase order from a buyer to the client carries the same order number."""
    hit = _invoice_unit_for(b, e, set())
    if not hit:
        return None
    nums = re.findall(r"\d{3,}", e.get("reference") or "")
    order = next((d for d in b.docs.values() if _kind(d, "order") and nums and all(n in d.text for n in nums)
                  and _mentioned(b.customer.get("name", ""), d.text)), None)
    return hit[0] if order else None


def declared_funding(b: CaseBundle) -> Checks:
    """Payments and FX: the client funds its account from its own bank account, as declared. A funding that goes
    straight on (≥ 90% within 2 days) is explained by where it went:
    - to an account a statement shows the client holds → OWN_ACCOUNT (TM01 at ≥ own_account_rfi_multiple → RFI);
    - to a supplier whose invoice matches, for a buyer's purchase order with the same number → INVOICE_MATCHES.
    TM07: re-verified identity, declared funding, and the payment out matched to its invoice → RETURNING_CUSTOMER."""
    signals: list[Signal] = []
    rfi_multiple = b.policy.get("own_account_rfi_multiple")
    for a in b.alerts:
        rule = a.get("rule_id")
        if rule not in ("TM01", "TM07"):
            continue
        txns = b.alert_txns(a)
        fundings = [t for t in txns if _declared_own_funding(b, t)]
        if not fundings:
            continue
        m = a.get("measured", {})
        if rule == "TM01":
            for kind_, test, code in (("own", lambda e: _statement_for_ending(b, e) or _statement_for(b, e), "OWN_ACCOUNT"),
                                      ("order", lambda e: _order_backed(b, e), "INVOICE_MATCHES")):
                hits = {t["transaction_id"]: (t, *on) for t in fundings for on in [_onward(b, t, test)] if on}
                if not hits or not _own_covers(b, a, txns, {k: v[2] for k, v in hits.items()}):
                    continue
                t, e, doc = next(iter(hits.values()))
                where = (f"an account {doc.doc_id} shows {b.customer.get('name')} holds" if kind_ == "own"
                         else f"{_party(e.get('counterparty_name'))}, whose invoice {doc.doc_id} matches it, for the "
                              f"buyer's purchase order with the same number")
                facts = (f"The {money(t['amount_gbp'])} funding from {b.customer.get('name')}'s own account on "
                         f"{fmt_date(_txn_date(t))} ({t['transaction_id']}), the declared funding channel, went on the "
                         f"next days as {money(e['amount_gbp'])} ({e['transaction_id']}, '{e.get('reference')}') to {where}")
                evidence = [doc.doc_id] + ([d.doc_id for d in b.docs.values() if kind_ == "order" and _kind(d, "order")])
                evidence += [t["transaction_id"], e["transaction_id"]]
                multiple = m.get("multiple")
                if code == "OWN_ACCOUNT" and rfi_multiple and multiple is not None and multiple >= rfi_multiple:
                    signals.append(Signal(
                        alert_id=a["alert_id"], kind="partial", code="RFI_UPDATED_PROFILE",
                        facts=(f"{facts}, but the funding is {multiple:g} times the declared volume, at or above the "
                               f"{rfi_multiple} times at which the policy asks for an update; ask the client for an "
                               f"updated expected annual volume and what it is based on."),
                        evidence=list(dict.fromkeys(evidence)), strength="hard", source="explainers.declared_funding"))
                else:
                    signals.append(Signal(
                        alert_id=a["alert_id"], kind="explains", code=code, facts=facts + ".",
                        evidence=list(dict.fromkeys(evidence)), strength="hard", source="explainers.declared_funding"))
                break
        else:  # TM07
            dates = [d for d in (_txn_date(t) for t in txns) if d]
            if not dates or not m.get("dormant_days") or not m.get("limit_gbp"):
                continue
            rv = _reverification(b, min(dates), int(m["dormant_days"]))
            paid = _match_each_once([t for t in txns if t.get("direction") == "out"],
                                    lambda t, used: _invoice_unit_for(b, t, used))
            explained = {**{t["transaction_id"]: None for t in fundings}, **paid}
            if not rv or not paid or not _own_covers(b, a, txns, explained):
                continue
            rv_doc, rv_date = rv
            outs = [t for t in txns if t["transaction_id"] in paid]
            facts = (f"Identity was re-verified on {fmt_date(rv_date)} ({rv_doc.doc_id}) before the account moved again "
                     f"after {m['dormant_days']} days; it was funded from the client's own account (the declared channel) "
                     f"and " + " and ".join(f"the {money(t['amount_gbp'])} to {_party(t.get('counterparty_name'))} "
                                            f"({t['transaction_id']}) matches invoice {paid[t['transaction_id']].doc_id}"
                                            for t in outs) + ".")
            signals.append(Signal(
                alert_id=a["alert_id"], kind="explains", code="RETURNING_CUSTOMER", facts=facts,
                evidence=list(dict.fromkeys([rv_doc.doc_id] + [paid[t["transaction_id"]].doc_id for t in outs]
                                            + [t["transaction_id"] for t in fundings + outs])),
                strength="hard", source="explainers.declared_funding"))
            held = b.case.get("held_payment_id")
            if held in paid:
                signals.append(Signal(
                    alert_id=a["alert_id"], kind="explains", code="INVOICE_MATCHES",
                    facts=f"{paid[held].doc_id} matches the held payment {held} on amount, payee and reference.",
                    evidence=[paid[held].doc_id, held], strength="hard", source="explainers.declared_funding"))
    return signals, []


# Add one function per check, (b) -> (signals, questions), and list it here.
# Funding from the client's own account counts as the client's money only where the client declared that channel
# (payments and FX): elsewhere an own-name account still needs a statement (POLICY own-account clause).
# list_match_different_party is Lorenzo's (red_flags.listed_party).
CHECKS: list = [business_records, own_account, returning_customer, documented_event, refund, invoice_matches,
                third_party_documented, collection_documented, group_company, missing_document,
                early_redemption_explained, declared_funding]
