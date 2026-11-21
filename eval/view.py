"""Print one case on one screen, for labelling.  python3 eval/view.py <case_id> [--all-txns]"""

import json
import sys

from _common import bundles, institution_of

case_id = sys.argv[1]
show_all = "--all-txns" in sys.argv
b = next(x for x in bundles(institution_of(case_id)) if x.case["case_id"] == case_id)
c, cu = b.case, b.customer

print(f"=== {case_id}  [{b.institution}]  window {c['review_window']['from']} → {c['review_window']['to']}"
      + (f"  HELD {c['held_payment_id']}" if c.get("held_payment_id") else ""))
print(f"\n--- CUSTOMER {cu.get('customer_id')}: {cu.get('name')} ({cu.get('kind')}), risk {cu.get('risk_rating')}")
for k in ("date_of_birth", "occupation", "employer", "company_number", "business_activity", "address", "onboarded_on"):
    if cu.get(k):
        print(f"  {k}: {cu[k]}")
print("  declared: " + json.dumps(cu.get("declared", {})))

print("\n--- ALERTS")
alerted = set()
for a in b.alerts:
    print(f"  {a['alert_id']} {a['rule_id']} {a['rule_name']}\n    {a['message']}\n    measured: {json.dumps(a.get('measured'))}")
    alerted |= set(a.get("transaction_ids", []))

print("\n--- TRANSACTIONS" + ("" if show_all else " (alerted ones, plus the window; --all-txns for every one)"))
lo, hi = c["review_window"]["from"], c["review_window"]["to"] + "T99"
for t in sorted(b.txns.values(), key=lambda t: t["booked_at"]):
    if show_all or t["transaction_id"] in alerted or (lo <= t["booked_at"] <= hi and t["channel"] != "card"):
        mark = "*" if t["transaction_id"] in alerted else " "
        cur = "" if t.get("currency") == "GBP" else f" ({t.get('amount')} {t.get('currency')})"
        print(f" {mark}{t['transaction_id']} {t['booked_at'][:16]} {t['direction']:3} {t['channel']:14} "
              f"£{t['amount_gbp']:>11,.2f}{cur}  {t.get('counterparty_name')} [{t.get('counterparty_country')}] "
              f"ref={t.get('reference')!r}" + (f" acct={t['counterparty_account']}" if t.get("counterparty_account") else ""))

print("\n--- LIST ENTRIES")
for e in b.list_entries.values():
    print("  " + json.dumps(e))
print("\n--- PREVIOUS REVIEWS")
for r in b.reviews:
    print(f"  {r['review_id']} {r['reviewed_on']} {r['rule_id']} {r['verdict']}: {r['note']}")
print("\n--- DOCUMENTS")
for d in sorted(b.docs.values(), key=lambda d: d.dated or ""):
    print(f"\n[{d.doc_id}] {d.type} — {d.title} ({d.dated})")
    print("\n".join("    " + line for line in d.text.strip().splitlines()[1:] if line.strip()))
