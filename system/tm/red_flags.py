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
from .util import amounts, fmt_date, money, name_key, norm, parse_date, same_name

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
    r"(aggregat\w*|combined across|split\w*|break\w* (it )?up|keep\w* (each|individual|the|every) [\w ]{0,30}(below|under)|"
    r"(below|under) the [£\d,\. ]*(threshold|limit)|exempt\w* (them )?from)", re.I)
_LIMIT_CONTEXT = re.compile(r"(thresholds?|report\w*|verification|identity|limit|exempt|aggregat)", re.I)


def structuring_intent(b: CaseBundle) -> Checks:
    """The customer asked staff whether staying under a limit avoids reporting/ID checks -> structuring."""
    signals: list[Signal] = []
    cash_alerts = [a["alert_id"] for a in b.alerts if a.get("rule_id") in ("TM03", "TM05")]
    for doc in sorted(b.docs.values(), key=lambda d: d.doc_id):
        if doc.type in ("due_diligence_summary", "proof_of_address"):
            continue
        t = doc.text
        if _ASKS_ABOUT_LIMITS.search(t) and _LIMIT_CONTEXT.search(t) and re.search(r"(asked|inquir|enquir|wanted to know|wondered)", t, re.I):
            quote = re.search(r"[^.]*(aggregat|below|under|exempt)[^.]*\.", t, re.I)
            alert_ids = cash_alerts or [ALL_ALERTS]
            for alert_id in alert_ids:
                signals.append(Signal(
                    alert_id=alert_id, kind="red_flag", code="ESC_STRUCTURING",
                    facts=f"Staff note {doc.doc_id} records the customer asking whether keeping amounts under a limit avoids aggregation, reporting or ID checks; " +
                          "this shows the payments were split on purpose.",
                    evidence=[doc.doc_id] + [x for a in b.alerts if a["alert_id"] == alert_id for x in a.get("transaction_ids", [])[:2]],
                    source="red_flags.structuring_intent"))
            break
    return signals, []


# --------------------------------------------------------------------------- someone else's money (chat / email prose)

_ACTING_FOR_OTHERS = re.compile(
    r"(invest\w* (for|through|on behalf)|on behalf of|for (a few|some|other|several) (people|friends|relatives|clients)|"
    r"(send|sending|sent|pass|passing|forward\w*) (it|them|the money|the funds) (on|along)|"
    r"(cannot|can't|can not|unable to) open an account|through (mine|my account)|"
    r"(friends?|cousins?|relatives?|family|clients?) (sent|paid|gave) me money)", re.I)
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
        if doc.type not in ("support_chat", "customer_email", "customer_letter", "contact_note", "staff_note"):
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
            code = "ESC_MULE_ACTIVITY" if re.search(r"(send|sending|sent|pass|forward)\w* (it|them|the money|the funds) on|for (a few|some|other|several)|invest\w* for", said, re.I) \
                else "ESC_THIRD_PARTY_FUNDING"
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
        for a in b.alerts:
            for t in b.alert_txns(a):
                paid = _txn_date(t)
                if end and paid and paid > end and same_name(t.get("counterparty_name"), company):
                    inbound = t.get("direction") == "in"
                    signals.append(Signal(
                        alert_id=a["alert_id"], kind="red_flag",
                        code="ESC_THIRD_PARTY_FUNDING" if inbound else "ESC_UNEXPLAINED_FUNDS",
                        facts=(f"{company} {'paid' if inbound else 'was paid'} {money(t['amount_gbp'])} on {fmt_date(paid)}, but the "
                               f"register ({doc.doc_id}) shows it was dissolved on {fmt_date(end)}, so the payment cannot be genuine trade."),
                        evidence=[doc.doc_id, t["transaction_id"]], source="red_flags.dissolved_counterparty"))
                    break
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


CHECKS: list = [listed_party, fraud_report, structuring_intent, third_party_story, dissolved_counterparty]
# Next, once the labels show what separates the traps: mule/pass-through patterns in the transactions
# (receive-and-forward to linked parties), undeclared high-risk country with third parties,
# device/login anomalies (account misuse), early redemption with no documented reason.
