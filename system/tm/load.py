"""Load an institution folder into CaseBundles. Reads only that folder."""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict

from .types import CaseBundle, Doc
from .util import amounts

_FIELD = re.compile(r"^\*\*(.+?):\*\*\s*(.*)$")


def _jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def parse_doc(meta: dict, text: str) -> Doc:
    fields: dict[str, str] = {}
    body: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = _FIELD.match(s)
        if m:
            fields[m[1].strip().lower()] = m[2].strip()
        else:
            body.append(s)
    return Doc(
        doc_id=meta["doc_id"], type=meta.get("type", ""), title=meta.get("title", ""),
        dated=meta.get("dated"), text=text, fields=fields, body="\n".join(body),
    )


def parse_policy(text: str) -> dict:
    """Pull the numbers every module needs out of POLICY.md, so nothing is hard-coded per institution.

    rules[rule_id] = {"name", "fires_when", "amounts": [£ values in the rule], "multiples": [N for 'N times']}
    """
    rules: dict[str, dict] = {}
    for m in re.finditer(r"^\|\s*(TM\d+)\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|\s*$", text, re.M):
        fires = m[3]
        rules[m[1]] = {
            "name": m[2],
            "fires_when": fires,
            "amounts": amounts(fires),
            "multiples": [int(x) for x in re.findall(r"(\d+) times", fires)],
        }
    hr = re.search(r"Higher-risk countries[^:]*:\s*(.+?)\.\s*$", text, re.M)
    countries = {c.strip() for c in hr[1].split(",")} if hr else set()
    cash = re.search(r"Cash reporting threshold:\s*(£[\d,\.]+)", text)
    own = re.search(r"own accounts explain activity at (\d+) times", text)
    invoice = re.search(r"Payments of (£[\d,\.]+) or more to anyone other than the client need an invoice", text)
    return {
        "rules": rules,
        "high_risk_countries": countries,
        "cash_reporting_threshold": amounts(cash[1])[0] if cash else None,
        "own_account_rfi_multiple": int(own[1]) if own else None,
        "third_party_invoice_threshold": amounts(invoice[1])[0] if invoice else None,
        "text": text,
    }


def load_institution(folder: str) -> list[CaseBundle]:
    folder = os.path.abspath(folder)
    inst = os.path.basename(folder.rstrip("/"))
    j = lambda name: _jsonl(os.path.join(folder, name))  # noqa: E731

    with open(os.path.join(folder, "POLICY.md"), encoding="utf-8") as f:
        policy = parse_policy(f.read())

    customers = {c["customer_id"]: c for c in j("customers.jsonl")}
    alerts = {a["alert_id"]: a for a in j("alerts.jsonl")}
    internal_list = {e["entry_id"]: e for e in j("internal_list.jsonl")}

    txns: dict[str, dict[str, dict]] = defaultdict(dict)
    for t in j("transactions.jsonl"):
        txns[t["customer_id"]][t["transaction_id"]] = t

    docs: dict[str, dict[str, Doc]] = defaultdict(dict)
    for meta in j("evidence.jsonl"):
        path = os.path.join(folder, meta.get("file") or f"evidence/{meta['doc_id']}.md")
        text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
        docs[meta["customer_id"]][meta["doc_id"]] = parse_doc(meta, text)

    reviews: dict[str, list[dict]] = defaultdict(list)
    for r in j("previous_reviews.jsonl"):
        reviews[r["customer_id"]].append(r)

    bundles = []
    for case in j("cases.jsonl"):
        cid = case["customer_id"]
        case_alerts = [alerts[a] for a in case["alert_ids"] if a in alerts]
        refs = {a.get("measured", {}).get("list_entry") for a in case_alerts}
        bundles.append(CaseBundle(
            institution=inst,
            case=case,
            alerts=case_alerts,
            customer=customers.get(cid, {}),
            txns=txns.get(cid, {}),
            docs=docs.get(cid, {}),
            reviews=sorted(reviews.get(cid, []), key=lambda r: r.get("reviewed_on", "")),
            list_entries={e: internal_list[e] for e in sorted(r for r in refs if r) if e in internal_list},
            internal_list=internal_list,
            policy=policy,
        ))
    return bundles
