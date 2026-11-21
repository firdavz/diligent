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

Design note: a red flag here means POSITIVE evidence of suspicion. "Nothing explains it" is not a red flag:
decide.FALLBACK covers that, and B's explainers can still close it. TM22 is owned entirely by this module
(both directions: listed party confirmed -> ESC_LISTED_PARTY, different party shown -> LIST_MATCH_DIFFERENT_PARTY).
"""

from __future__ import annotations

import re
from datetime import date

from .types import ALL_ALERTS, CaseBundle, Doc, Question, Signal
from .util import amounts, fmt_date, money, name_key, norm, parse_date, parse_dt, same_name

Checks = tuple[list[Signal], list[Question]]

_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december"]


# --------------------------------------------------------------------------- helpers

def _month_year(text: str | None) -> tuple[int, int] | None:
    """'August 1978' -> (1978, 8). A full date also works. None if unreadable."""
    m = re.search(r"([A-Za-z]+)\s+(\d{4})", text or "")
    if m and m[1].lower() in _MONTHS:
        return int(m[2]), _MONTHS.index(m[1].lower()) + 1
    d = parse_date(text)
    return (d.year, d.month) if d else None


def _tables(doc: Doc) -> list[list[dict[str, str]]]:
    """Every Markdown table in a document as a list of {lower-case header: cell} rows."""
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


def _alert_ids_for_txn(b: CaseBundle, txn_id: str) -> list[str]:
    ids = [a["alert_id"] for a in b.alerts if txn_id in a.get("transaction_ids", [])]
    return ids or [ALL_ALERTS]


def _txn_date(t: dict) -> date | None:
    return parse_date(t.get("booked_at"))


def _doc_mentions(doc: Doc, name: str) -> bool:
    key = name_key(name)
    return bool(key) and key in name_key(doc.text) or norm(name) in norm(doc.text)


# --------------------------------------------------------------------------- TM22: internal list

def _identity_records(b: CaseBundle, name: str) -> list[dict]:
    """What the documents on file say about a named person: birth date / month, start and end of a role.

    Each record: {"doc": doc_id, "born_full": date|None, "born_my": (y, m)|None, "start": date|None, "end": date|None}
    """
    out: list[dict] = []
    for doc in b.docs.values():
        # Register tables: Officer / Person columns with Born, Appointed / Notified, Resigned / Ceased.
        for rows in _tables(doc):
            for row in rows:
                who = next((v for k, v in row.items() if k in ("officer", "person", "name", "director")), "")
                if not who or not same_name(who, name):
                    continue
                end = next((parse_date(v) for k, v in row.items()
                            if any(w in k for w in ("ceased", "resign", "left", "terminat", "end")) and v), None)
                start = next((parse_date(v) for k, v in row.items()
                              if any(w in k for w in ("appointed", "notified", "start")) and v), None)
                born = row.get("born") or row.get("date of birth") or ""
                out.append({"doc": doc.doc_id, "born_full": parse_date(born) if re.search(r"\d{1,2}\s", born) or "-" in born else None,
                            "born_my": _month_year(born), "start": start, "end": end})
        # Prose or letter: "I, Riley Selholt, born 17 February 1959, ..."  or a "**Date of birth:**" field.
        if not _doc_mentions(doc, name) or doc.type == "due_diligence_summary":
            continue
        for m in re.finditer(r"born\s+(?:on\s+)?(\d{1,2}\s+[A-Za-z]+\s+\d{4})", doc.text):
            near = doc.text[max(0, m.start() - 120): m.start()]
            if _doc_mentions(Doc("", "", "", None, near, {}, near), name):
                d = parse_date(m[1])
                out.append({"doc": doc.doc_id, "born_full": d, "born_my": (d.year, d.month) if d else None,
                            "start": None, "end": None})
        dob = doc.fields.get("date of birth")
        subject = doc.fields.get("customer") or doc.fields.get("name") or doc.fields.get("payer") or ""
        if dob and same_name(subject, name):
            d = parse_date(dob)
            out.append({"doc": doc.doc_id, "born_full": d, "born_my": (d.year, d.month) if d else None,
                        "start": None, "end": None})
    return out


_UNIT = re.compile(r"\b(Unit|Suite|Flat|Floor|Office|Room)\s+(\w+)\s*,?\s*([A-Z][\w' ]+?)(?=[,.\n]|$)", re.M)


def _unit_of(text: str) -> tuple[str, str] | None:
    """'Unit 4B, Stanfield Works, Aldwick' -> ('4b', 'stanfield works')."""
    m = _UNIT.search(text or "")
    return (m[2].lower(), norm(m[3])) if m else None


def _address_signal(b: CaseBundle, a: dict, entry: dict, party: str, ev_base: list[str], pay: date | None) -> Signal | None:
    """List match on an address: same building but a different unit shows a different occupier; same unit is linked."""
    listed = _unit_of(entry["address"])
    if not listed:
        return None
    for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
        if doc.type == "due_diligence_summary" or not _doc_mentions(doc, party):
            continue
        theirs = _unit_of(doc.text) or _unit_of(doc.fields.get("registered office", ""))
        if not theirs or theirs[1] != listed[1]:
            continue
        if theirs[0] != listed[0]:
            return Signal(
                alert_id=a["alert_id"], kind="explains", code="LIST_MATCH_DIFFERENT_PARTY",
                facts=(f"{party} matched list entry {entry['entry_id']} only on the building: {doc.doc_id} puts them in unit "
                       f"{theirs[0].upper()} of {theirs[1].title()}, while the listed person was in unit {listed[0].upper()}, "
                       f"so they are a different occupier."),
                evidence=[doc.doc_id] + ev_base, source="red_flags.listed_party.address")
        return Signal(
            alert_id=a["alert_id"], kind="red_flag", code="ESC_LISTED_PARTY",
            facts=(f"{party} operates from unit {theirs[0].upper()} of {theirs[1].title()} ({doc.doc_id}), the same unit as "
                   f"the listed person in {entry['entry_id']}, so it is linked to them."),
            evidence=[doc.doc_id] + ev_base, source="red_flags.listed_party.address")
    return None


def listed_party(b: CaseBundle) -> Checks:
    signals: list[Signal] = []
    for a in b.alerts:
        if a.get("rule_id") != "TM22":
            continue
        m = a.get("measured", {})
        entry = b.list_entries.get(m.get("list_entry")) or b.internal_list.get(m.get("list_entry"))
        if not entry:
            continue
        party = m.get("matched_party") or entry.get("name", "")
        txns = b.alert_txns(a)
        pay_dates = [d for d in (_txn_date(t) for t in txns) if d]
        pay = max(pay_dates) if pay_dates else None
        listed_dob = parse_date(entry.get("date_of_birth"))
        recs = _identity_records(b, party) + ([] if same_name(party, entry.get("name")) else _identity_records(b, entry.get("name", "")))
        recs = [r for r in recs if r["born_full"] or r["born_my"]]
        ev_base = [m.get("list_entry")] if m.get("list_entry") else []
        if str(m.get("matched_on", "")).startswith("registered address") and entry.get("address"):
            sig = _address_signal(b, a, entry, party, ev_base, pay)
            if sig:
                signals.append(sig)
            continue
        if not recs or not listed_dob:
            continue  # nothing settles it: decide's fallback (RFI for the list match unless something else is concerning)

        def agrees(r: dict) -> bool:
            if r["born_full"]:
                return r["born_full"] == listed_dob
            return r["born_my"] == (listed_dob.year, listed_dob.month)

        same = [r for r in recs if agrees(r)]
        if not same:
            r = recs[0]
            born = fmt_date(r["born_full"]) if r["born_full"] else f"{_MONTHS[r['born_my'][1] - 1].title()} {r['born_my'][0]}"
            signals.append(Signal(
                alert_id=a["alert_id"], kind="explains", code="LIST_MATCH_DIFFERENT_PARTY",
                facts=(f"{party} matched list entry {entry['entry_id']} on {m.get('matched_on', 'name')} only: "
                       f"{r['doc']} gives their birth as {born}, but the listed person was born {fmt_date(listed_dob)}, "
                       f"so they are a different person."),
                evidence=[r["doc"]] + ev_base, source="red_flags.listed_party"))
            continue
        # The listed person is still in the role if ANY record says so (e.g. resigned as director but still holds
        # significant control on the payment date). Only when every record has ended before the payment is it safe.
        active = [r for r in same if not (r["end"] and pay and r["end"] < pay)]
        if not active:
            r = same[0]
            signals.append(Signal(
                alert_id=a["alert_id"], kind="explains", code="LIST_MATCH_DIFFERENT_PARTY",
                facts=(f"{party}, who matches list entry {entry['entry_id']}, left every role on {fmt_date(r['end'])} at the latest, "
                       f"before the payment on {fmt_date(pay)} ({r['doc']}), so the listed person did not control the counterparty then."),
                evidence=[r["doc"]] + ev_base, source="red_flags.listed_party.ceased"))
            continue
        r = active[0]
        why = ("their date of birth matches" if r["born_full"] else "their birth month and year match")
        signals.append(Signal(
            alert_id=a["alert_id"], kind="red_flag", code="ESC_LISTED_PARTY",
            facts=(f"{party} is the listed person in {entry['entry_id']} ({entry.get('reason', '').rstrip('.')}): {why} "
                   f"({r['doc']}), and {'they control the counterparty' if r['start'] else 'they are the counterparty'} "
                   f"on the payment date{' ' + fmt_date(pay) if pay else ''}."),
            evidence=[r["doc"]] + ev_base + [t["transaction_id"] for t in txns[:2]], source="red_flags.listed_party"))
    return signals, []


# --------------------------------------------------------------------------- fraud reports

def fraud_report(b: CaseBundle) -> Checks:
    """A report from another bank saying money it sent to this account was a scam -> proceeds of fraud."""
    signals: list[Signal] = []
    for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
        if "fraud" not in doc.type and not re.search(r"\b(scam|freeze (any )?remaining funds)\b", doc.text, re.I):
            continue
        if "fraud" not in doc.type and "scam" not in norm(doc.text):
            continue
        paid = amounts(doc.text)
        match = [t for t in b.txns.values() if t.get("direction") == "in" and any(abs(t["amount_gbp"] - x) < 0.005 for x in paid)]
        sender = re.search(r"[Ff]raud report from ([^\n]+)", doc.text)
        victim = re.search(r"Our customer ([A-Z][\w'\- ]+?) sent", doc.text)
        what = re.search(r"Subject:\*\*\s*(.+)", doc.text)
        facts = (f"{sender[1].strip() if sender else 'Another bank'}'s fraud report {doc.doc_id} says "
                 f"{victim[1] if victim else 'its customer'} sent {money(paid[0]) if paid else 'money'} to this account "
                 f"in a scam ({what[1].strip().lower() if what else 'payment fraud'}), so the account received fraud proceeds.")
        # A fraud report on file suspects the account itself, so it escalates the whole case.
        signals.append(Signal(alert_id=ALL_ALERTS, kind="red_flag", code="ESC_MULE_ACTIVITY", facts=facts,
                              evidence=[doc.doc_id] + [t["transaction_id"] for t in match[:2]],
                              source="red_flags.fraud_report"))
    return signals, []


# --------------------------------------------------------------------------- structuring intent

_ASKS_ABOUT_LIMITS = re.compile(
    r"(aggregat\w*|combined across|split\w*|break\w*( them| it| payments)? (up|down)|instal+ments? of less than|"
    r"keep\w* (each|individual|the|every) [\w ]{0,30}(below|under)|(below|under|less than|beneath) (the )?[£\d,\. ]*(threshold|limit)|"
    r"(under|below|less than) £\s?[\d,]+|exempt\w*)", re.I)
_LIMIT_CONTEXT = re.compile(r"(thresholds?|report\w*|verification|identity|limit|exempt|aggregat)", re.I)


def structuring_intent(b: CaseBundle) -> Checks:
    """The customer asked staff whether staying under a limit avoids reporting/ID checks -> structuring."""
    signals: list[Signal] = []
    cash_alerts = [a["alert_id"] for a in b.alerts if a.get("rule_id") in ("TM03", "TM05")]
    for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
        if doc.type in ("due_diligence_summary", "proof_of_address"):
            continue
        t = doc.text
        if _ASKS_ABOUT_LIMITS.search(t) and _LIMIT_CONTEXT.search(t) and re.search(r"(ask(ed|ing)|inquir|enquir|question(ed|ing)|wanted to know|wondered)", t, re.I):
            quote = re.search(r"[^.]*(aggregat|below|under|exempt)[^.]*\.", t, re.I)
            said = f" (\"{' '.join(quote[0].split())[:180]}\")" if quote else ""
            # Intent to split shows on the whole case, so the case-level code is structuring whichever alert comes first.
            signals.append(Signal(
                alert_id=ALL_ALERTS, kind="red_flag", code="ESC_STRUCTURING",
                facts=f"{doc.doc_id} records the customer asking whether keeping amounts under a limit avoids aggregation, reporting, "
                      f"invoice or ID checks{said}; the payments were split on purpose.",
                evidence=[doc.doc_id] + [x for a in b.alerts if a["alert_id"] in cash_alerts for x in a.get("transaction_ids", [])[:3]],
                source="red_flags.structuring_intent"))
            break
    return signals, []


# --------------------------------------------------------------------------- someone else's money (chat / email prose)

_ACTING_FOR_OTHERS = re.compile(
    r"(invest\w* (for|through|on behalf)|on behalf of|for (a few|some|other|several) (people|friends|relatives|clients)|"
    r"(send|sending|sent|pass|passing|forward\w*) (it|them|the money|the funds) (on|along)|"
    r"(cannot|can't|can not|unable to) open an account|through (mine|my account)|"
    r"(friends?|cousins?|relatives?|family|clients?) (sent|paid|gave) me money|payments? assistant|"
    r"keep (a|my) (cut|share|percentage|commission)|for a (cut|fee|commission)|forward\w* (the )?(money|payments|funds))", re.I)
_PERSON_WORDS = re.compile(r"\b(friend|cousin|relative|family|brother|sister|uncle|aunt|colleague|neighbour)\b", re.I)
_COMPANY = re.compile(r"\b(ltd|limited|plc|llp|holdings|ventures|trading|group|inc|gmbh)\b", re.I)


def _customer_words(doc: Doc) -> str:
    lines = [ln.split(":**", 1)[1].strip() for ln in doc.text.splitlines() if ln.lower().startswith("**customer:**")]
    return " ".join(lines) if lines else doc.body


def third_party_story(b: CaseBundle) -> Checks:
    """What the customer says in a chat or email, read against the payments themselves."""
    signals: list[Signal] = []
    questions: list[Question] = []
    for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
        if doc.type not in ("support_chat", "customer_email", "customer_letter"):  # the customer's own words only
            continue
        said = _customer_words(doc)
        if not said:
            continue
        flows = [a for a in b.alerts if a.get("rule_id") in ("TM02", "TM04", "TM08", "TM06")]
        txn_ids = [t for a in flows for t in a.get("transaction_ids", [])]
        payers = {b.txns[t]["counterparty_name"] for t in txn_ids if t in b.txns and b.txns[t].get("counterparty_name")}
        own = b.customer.get("name")
        others = {p for p in payers if not same_name(p, own)}
        if _ACTING_FOR_OTHERS.search(said):
            code = "ESC_MULE_ACTIVITY" if re.search(r"(send|sending|sent|pass|forward)\w* (it|them|the money|the funds) on|for (a few|some|other|several)|invest\w* for|assistant|cut|forward", said, re.I) \
                else "ESC_THIRD_PARTY_FUNDING"
            if any(x.get("rule_id") == "TM10" for x in b.alerts):  # buy-and-sell-back cycles for other people
                code = "ESC_EARLY_REDEMPTION"
            for a in flows or b.alerts:
                signals.append(Signal(
                    alert_id=a["alert_id"], kind="red_flag", code=code,
                    facts=(f"In {doc.doc_id} the customer says the money belongs to other people (\"{said.strip()[:140]}\"), "
                           f"so the account is being used to receive and pass on third-party funds."),
                    evidence=[doc.doc_id] + [t for t in a.get("transaction_ids", []) if t in b.txns][:2],
                    source="red_flags.third_party_story"))
            continue
        # A story of "a friend / family" that doesn't fit payers that are companies.
        if _PERSON_WORDS.search(said) and others and all(_COMPANY.search(p) for p in others):
            names = ", ".join(sorted(others)[:2])
            for a in [x for x in flows if x.get("rule_id") == "TM08"] or flows or b.alerts:
                signals.append(Signal(
                    alert_id=a["alert_id"], kind="red_flag", code="ESC_THIRD_PARTY_FUNDING",
                    facts=(f"In {doc.doc_id} the customer says the money came from a friend or family member, but the payer is "
                           f"{names}, a company, so the story does not match the payments."),
                    evidence=[doc.doc_id] + [t for t in a.get("transaction_ids", []) if t in b.txns][:2],
                    source="red_flags.third_party_story"))
            continue
        # Prose we cannot read with a pattern: let the reader tell us whether it shows other people's money.
        if flows and doc.type in ("support_chat", "customer_email"):
            a = flows[0]
            questions.append(Question(
                id="chat_shows_third_party_money", alert_id=a["alert_id"],
                text=("Does the customer say, or does the document show, that the money received or sent belongs to other people, "
                      "or that someone else controls or uses the account? Answer yes only if the text says so."),
                doc_ids=[doc.doc_id],
                if_yes=Signal(alert_id=a["alert_id"], kind="red_flag", code="ESC_ACCOUNT_MISUSE",
                              facts=f"{doc.doc_id} shows the account being used for other people's money or by someone else.",
                              evidence=[doc.doc_id], strength="soft", source="red_flags.chat_shows_third_party_money")))
    return signals, questions


# --------------------------------------------------------------------------- dissolved counterparties

def dissolved_counterparty(b: CaseBundle) -> Checks:
    """Money moving with a company the register says had already been dissolved on the payment date."""
    signals: list[Signal] = []
    for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
        status = doc.fields.get("status", "")
        gone = re.match(r"dissolved on (.+)", status, re.I)
        company = doc.fields.get("company") or re.sub(r"^.*? for ", "", doc.title or "")
        if not gone or not company:
            continue
        end = parse_date(gone[1])
        hits = [t for a in b.alerts for t in b.alert_txns(a)
                if end and _txn_date(t) and _txn_date(t) > end and same_name(t.get("counterparty_name"), company)]
        hits = list({t["transaction_id"]: t for t in hits}.values())
        if hits:
            t, inbound = hits[0], hits[0].get("direction") == "in"
            signals.append(Signal(
                alert_id=ALL_ALERTS, kind="red_flag", code="ESC_UNEXPLAINED_FUNDS",
                facts=(f"{company} {'paid' if inbound else 'was paid'} {money(sum(x['amount_gbp'] for x in hits))} from {fmt_date(_txn_date(t))}, "
                       f"but the register ({doc.doc_id}) shows it was dissolved on {fmt_date(end)}, so the money has no credible explanation."),
                evidence=[doc.doc_id] + [x["transaction_id"] for x in hits[:3]], source="red_flags.dissolved_counterparty"))
    return signals, []


# --------------------------------------------------------------------------- higher-risk routing nobody can explain

_EVASIVE = re.compile(r"(unable or unwilling|unwilling|refused|declined|would not|could not|couldn't|was unable|were unable|evasive)"
                      r"\s+(to\s+)?(provide|give|explain|justify|say|clarify|answer)", re.I)


def _sentence(text: str, m: re.Match) -> str:
    start = max(text.rfind(".", 0, m.start()) + 1, text.rfind("\n", 0, m.start()) + 1)
    end = text.find(".", m.end())
    return " ".join(text[start: end + 1 if end != -1 else len(text)].split())


def evasive_routing(b: CaseBundle) -> Checks:
    """TM06: a staff or contact note says the client could not or would not explain why money goes to the higher-risk country."""
    risky = [a for a in b.alerts if a.get("rule_id") == "TM06"]
    if not risky:
        return [], []
    for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
        if doc.type in ("due_diligence_summary", "proof_of_address"):
            continue
        m = _EVASIVE.search(doc.text)
        if not m:
            continue
        quote = _sentence(doc.text, m)[:200]
        return [Signal(
            alert_id=a["alert_id"], kind="red_flag", code="ESC_HIGH_RISK_CORRIDOR",
            facts=(f"{doc.doc_id} records that the client could not justify the routing to {a.get('measured', {}).get('countries', 'the higher-risk country')} "
                   f"(\"{quote}\"), so these higher-risk payments are unexplained."),
            evidence=[doc.doc_id] + [t for t in a.get("transaction_ids", []) if t in b.txns][:2],
            source="red_flags.evasive_routing") for a in risky], []
    return [], []


# --------------------------------------------------------------------------- invoices that don't support the payments

_SERVICES = re.compile(r"\b(consultanc\w*|consulting|advisory|market access|management fees?)\b", re.I)
_GOODS_BUSINESS = re.compile(r"\b(imports?|importing|supplies|supplier|manufactur\w*|wholesal\w*|exports?|trading)\b", re.I)


def _client_business(b: CaseBundle) -> str:
    for doc in b.docs.values():
        if same_name(doc.fields.get("company"), b.customer.get("name")) and doc.fields.get("nature of business"):
            return doc.fields["nature of business"]
    return b.customer.get("business_activity") or ""


def invoice_mismatch(b: CaseBundle) -> Checks:
    """Invoice rows cited by outgoing payments: different amount, dated after the payment, or billing services to a goods business."""
    business = _client_business(b)
    problems: list[tuple[str, str, dict]] = []
    for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
        for rows in _tables(doc):
            for r in rows:
                inv = next((v for k, v in r.items() if k.startswith("invoice")), "")
                amt = amounts(r.get("amount", ""))
                if not inv or not amt:
                    continue
                for t in sorted(b.txns.values(), key=lambda t: t["booked_at"]):
                    if t.get("direction") != "out" or not re.search(rf"(?<![\w]){re.escape(inv)}(?![\w])", t.get("reference") or ""):
                        continue
                    why = []
                    if abs(t["amount_gbp"] - amt[0]) >= 0.005:
                        why.append(f"{inv} is for {money(amt[0])} but {money(t['amount_gbp'])} was paid")
                    dated, paid = parse_date(r.get("dated")), _txn_date(t)
                    if dated and paid and dated > paid:
                        why.append(f"{inv} is dated {fmt_date(dated)}, after the payment on {fmt_date(paid)}")
                    goods = r.get("goods") or r.get("description") or ""
                    if _SERVICES.search(goods) and _GOODS_BUSINESS.search(business):
                        why.append(f"{inv} bills '{goods}', not the goods a business that {business[0].lower() + business[1:]} buys")
                    if why:
                        problems.append((doc.doc_id, "; ".join(why), t))
    if not problems:
        return [], []
    docs = sorted({p[0] for p in problems})
    return [Signal(
        alert_id=ALL_ALERTS, kind="red_flag", code="ESC_INVOICE_MISMATCH",
        facts=f"The invoices on file do not support the payments: {'; '.join(p[1] for p in problems[:2])} ({', '.join(docs)}).",
        evidence=docs + [p[2]["transaction_id"] for p in problems[:3]], source="red_flags.invoice_mismatch")], []


# --------------------------------------------------------------------------- pass-through to linked new companies

def _company_people(b: CaseBundle) -> dict[str, tuple[str, set[str], date | None]]:
    """company name -> (doc_id, officers and controllers, incorporated) from every register extract on file."""
    out: dict[str, tuple[str, set[str], date | None]] = {}
    for doc in b.docs.values():
        company = doc.fields.get("company")
        if not company:
            continue
        people = {v for rows in _tables(doc) for r in rows for k, v in r.items()
                  if v and k in ("officer", "person", "person with significant control", "director", "name")}
        out[company] = (doc.doc_id, people, parse_date(doc.fields.get("incorporated")))
    return out


def linked_new_company(b: CaseBundle) -> Checks:
    """Money from third parties leaves for companies set up in the last year by the people who run the client."""
    reg = _company_people(b)
    own = next((v for k, v in reg.items() if same_name(k, b.customer.get("name"))), None)
    ctrl = set(own[1]) if own else set()
    if b.customer.get("kind") == "individual":
        ctrl.add(b.customer.get("name", ""))
    if not ctrl:
        return [], []
    flows = [a for a in b.alerts if a.get("rule_id") in ("TM02", "TM08", "TM04")]
    if not flows:
        return [], []
    w0, w1 = parse_date(b.case.get("review_window", {}).get("from")), parse_date(b.case.get("review_window", {}).get("to"))
    hits = []
    for company, (doc_id, people, inc) in sorted(reg.items()):
        shared = sorted(p for p in people if any(same_name(p, c) for c in ctrl))
        if not shared or same_name(company, b.customer.get("name")):
            continue
        for t in sorted(b.txns.values(), key=lambda t: t["booked_at"]):
            d = _txn_date(t)
            if t.get("direction") == "out" and same_name(t.get("counterparty_name"), company) and d and w0 and w1 and w0 <= d <= w1 \
                    and inc and (d - inc).days <= 365:
                hits.append((company, doc_id, shared[0], inc, t))
    if not hits:
        return [], []
    paid = sum(h[4]["amount_gbp"] for h in hits)
    names = sorted({h[0] for h in hits})
    h = hits[0]
    facts = (f"Money that came in from third parties went out to {', '.join(names[:3])} ({money(paid)} in total), companies "
             f"incorporated in the last year whose director or controller {h[2]} also runs the client (e.g. {h[1]}, incorporated "
             f"{fmt_date(h[3])}), so the funds pass through to linked parties.")
    return [Signal(alert_id=a["alert_id"], kind="red_flag", code="ESC_PASS_THROUGH", facts=facts,
                   evidence=sorted({x[1] for x in hits}) + [x[4]["transaction_id"] for x in hits[:3]],
                   source="red_flags.linked_new_company") for a in flows], []


# --------------------------------------------------------------------------- payees that share a handful of addresses

def shared_payee_addresses(b: CaseBundle) -> Checks:
    """A payment file where many payees sit at a few shared addresses: a network of collection accounts, not real payees."""
    for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
        for rows in _tables(doc):
            if len(rows) < 10 or "address" not in rows[0]:
                continue
            addrs: dict[str, int] = {}
            for r in rows:
                addrs[norm(r.get("address"))] = addrs.get(norm(r.get("address")), 0) + 1
            if len(addrs) > len(rows) / 3:
                continue
            top = max(addrs.items(), key=lambda kv: kv[1])
            first = next(r["address"] for r in rows if norm(r.get("address")) == top[0])
            targets = [a for a in b.alerts if a.get("rule_id") in ("TM04", "TM08", "TM02")] or b.alerts
            return [Signal(
                alert_id=a["alert_id"], kind="red_flag", code="ESC_MULE_ACTIVITY",
                facts=(f"Payment file {doc.doc_id} lists {len(rows)} payees at only {len(addrs)} addresses ({top[1]} of them at {first}), "
                       f"so the money is being spread through a network of linked recipients rather than paid to genuine separate payees."),
                evidence=[doc.doc_id] + [t for t in a.get("transaction_ids", []) if t in b.txns][:2],
                source="red_flags.shared_payee_addresses") for a in targets], []
    return [], []


# --------------------------------------------------------------------------- unrelated payers, then straight on

_EXCHANGE = re.compile(r"\b(exchange|crypto\w*|coin\w*|bitcoin|btc)\b", re.I)


def forwarded_to_exchange(b: CaseBundle) -> Checks:
    """TM02: several unrelated payers, and most of it goes to a crypto exchange within a day."""
    own = b.customer.get("name")
    signals: list[Signal] = []
    for a in b.alerts:
        if a.get("rule_id") != "TM02":
            continue
        txs = sorted(b.alert_txns(a), key=lambda t: t["booked_at"])
        ins = [t for t in txs if t.get("direction") == "in" and not same_name(t.get("counterparty_name"), own)]
        outs = [t for t in txs if t.get("direction") == "out" and _EXCHANGE.search(t.get("counterparty_name") or "")]
        payers = {name_key(t.get("counterparty_name")) for t in ins}
        if len(payers) < 2 or not outs or sum(t["amount_gbp"] for t in outs) < 0.8 * sum(t["amount_gbp"] for t in ins):
            continue
        fast = [o for o in outs if any(0 <= (parse_dt(o["booked_at"]) - parse_dt(i["booked_at"])).total_seconds() <= 86400 for i in ins)]
        if not fast:
            continue
        signals.append(Signal(  # case-level: the forwarding pattern is the story of the whole case
            alert_id=ALL_ALERTS, kind="red_flag", code="ESC_MULE_ACTIVITY",
            facts=(f"{len(payers)} unrelated payers sent {money(sum(t['amount_gbp'] for t in ins))} and "
                   f"{money(sum(t['amount_gbp'] for t in outs))} went on to {outs[0]['counterparty_name']} within a day, "
                   f"the pattern of an account receiving and passing on other people's money."),
            evidence=[t["transaction_id"] for t in ins[:2]] + [outs[0]["transaction_id"]],
            source="red_flags.forwarded_to_exchange"))
    return signals, []


# --------------------------------------------------------------------------- higher-risk country, many unrelated people

def corridor_to_individuals(b: CaseBundle) -> Checks:
    """TM06: unrelated payers in, then payments to several differently-surnamed people in the higher-risk country."""
    own = b.customer.get("name") or ""
    surname = norm(own).split()[-1] if own else ""
    w0, w1 = parse_date(b.case.get("review_window", {}).get("from")), parse_date(b.case.get("review_window", {}).get("to"))
    payers = {name_key(t.get("counterparty_name")) for t in b.txns.values()
              if t.get("direction") == "in" and not same_name(t.get("counterparty_name"), own) and w0 and w1
              and _txn_date(t) and w0 <= _txn_date(t) <= w1 and not _COMPANY.search(t.get("counterparty_name") or "")}
    signals: list[Signal] = []
    for a in b.alerts:
        if a.get("rule_id") != "TM06":
            continue
        outs = [t for t in b.alert_txns(a) if t.get("direction") == "out" and not _COMPANY.search(t.get("counterparty_name") or "")
                and norm(t.get("counterparty_name")).split()[-1:] != [surname]]
        people = sorted({t["counterparty_name"] for t in outs})
        if len(people) < 2 or len(payers) < 2:
            continue
        signals.append(Signal(  # the pattern (payers in, people abroad out) explains every alert in the case
            alert_id=ALL_ALERTS, kind="red_flag", code="ESC_HIGH_RISK_CORRIDOR",
            facts=(f"{len(payers)} unrelated people paid the account, then {money(sum(t['amount_gbp'] for t in outs))} went to "
                   f"{len(people)} people with other surnames in {a.get('measured', {}).get('countries', 'a higher-risk country')} "
                   f"({', '.join(people[:3])}), which nothing on file explains."),
            evidence=[t["transaction_id"] for t in outs[:3]], source="red_flags.corridor_to_individuals"))
    return signals, []


# --------------------------------------------------------------------------- orchestration

def red_flags(b: CaseBundle) -> Checks:
    signals: list[Signal] = []
    questions: list[Question] = []
    for check in CHECKS:
        s, q = check(b)
        signals += s
        questions += q
    return signals, questions


# Order matters: when several checks fire, the first signal's code becomes the case's reason code, so the most specific go first.
CHECKS: list = [listed_party, fraud_report, structuring_intent, evasive_routing, invoice_mismatch, linked_new_company,
                shared_payee_addresses, dissolved_counterparty, corridor_to_individuals, forwarded_to_exchange, third_party_story]
# Next, once the labels show what separates the traps: mule/pass-through patterns in the transactions
# (receive-and-forward to linked parties), undeclared high-risk country with third parties,
# device/login anomalies (account misuse), early redemption with no documented reason.
