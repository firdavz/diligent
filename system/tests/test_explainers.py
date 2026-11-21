"""Synthetic checks for tm/explainers.py (invented names and amounts, no development-case data).

Run:  python3 system/tests/test_explainers.py   (on Windows: python system/tests/test_explainers.py)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from tm.explainers import business_records, explainers  # noqa: E402
from tm.load import parse_doc  # noqa: E402
from tm.types import CaseBundle  # noqa: E402


def doc(doc_id, dtype, text, title=None):
    return parse_doc({"doc_id": doc_id, "type": dtype, "title": title or dtype, "dated": None}, text)


def bundle(alerts, docs, txns=(), customer=None):
    return CaseBundle(
        institution="test", case={"case_id": "C1", "customer_id": "U1", "alert_ids": [a["alert_id"] for a in alerts]},
        alerts=alerts, customer=customer or {"name": "Pat Example"},
        txns={t["transaction_id"]: t for t in txns}, docs={d.doc_id: d for d in docs}, reviews=[],
        list_entries={}, internal_list={}, policy={})


def cash(tid, day, amount, channel="cash_topup"):
    return {"transaction_id": tid, "booked_at": f"2026-03-{day:02d}T17:00:00Z", "direction": "in",
            "channel": channel, "amount_gbp": amount, "counterparty_name": None}


def tm03(txns):
    return {"alert_id": "A1", "rule_id": "TM03", "transaction_ids": [t["transaction_id"] for t in txns]}


TOPUPS = [cash("T1", 3, 910.0), cash("T2", 4, 875.5), cash("T3", 7, 940.0), cash("T4", 8, 860.0)]


def takings(rows):
    lines = ["| Date | Market | Takings | Cash topped up |", "|---|---|---|---|"]
    lines += [f"| {d} March 2026 | Testford market | £{t:,.2f} | £{c:,.2f} |" for d, t, c in rows]
    return doc("TAK-1", "takings_book", "\n".join(lines), title="Daily takings book")


GOOD_ROWS = [(3, 1200.0, 910.0), (4, 1010.0, 875.5), (7, 1100.0, 940.0), (8, 990.0, 860.0)]


class BusinessRecords(unittest.TestCase):
    def codes(self, b):
        return [(s.kind, s.code, s.alert_id) for s in business_records(b)[0]]

    def test_every_top_up_has_a_row_with_same_day_and_amount(self):
        b = bundle([tm03(TOPUPS)], [takings(GOOD_ROWS)], TOPUPS)
        self.assertEqual(self.codes(b), [("explains", "BUSINESS_RECORDS_RECONCILE", "A1")])
        s = business_records(b)[0][0]
        self.assertEqual(s.strength, "hard")
        self.assertEqual(s.evidence, ["TAK-1", "T1", "T2", "T3", "T4"])
        self.assertIn("£3,585.50", s.facts)

    def test_one_top_up_without_a_row_explains_nothing(self):
        b = bundle([tm03(TOPUPS)], [takings(GOOD_ROWS[:3])], TOPUPS)
        self.assertEqual(self.codes(b), [])

    def test_amount_one_penny_off_explains_nothing(self):
        rows = GOOD_ROWS[:3] + [(8, 990.0, 860.01)]
        self.assertEqual(self.codes(bundle([tm03(TOPUPS)], [takings(rows)], TOPUPS)), [])

    def test_row_dated_after_the_deposit_explains_nothing(self):
        rows = GOOD_ROWS[:3] + [(9, 990.0, 860.0)]
        self.assertEqual(self.codes(bundle([tm03(TOPUPS)], [takings(rows)], TOPUPS)), [])

    def test_row_dated_too_long_before_explains_nothing(self):
        rows = GOOD_ROWS[:3] + [(4, 990.0, 860.0)]  # 4 days before the deposit on the 8th
        self.assertEqual(self.codes(bundle([tm03(TOPUPS)], [takings(rows)], TOPUPS)), [])

    def test_top_up_larger_than_the_days_takings_explains_nothing(self):
        rows = GOOD_ROWS[:3] + [(8, 700.0, 860.0)]
        self.assertEqual(self.codes(bundle([tm03(TOPUPS)], [takings(rows)], TOPUPS)), [])

    def test_two_equal_deposits_need_two_rows(self):
        txns = [cash("T1", 3, 900.0), cash("T2", 3, 900.0)]
        one_row = takings([(3, 2000.0, 900.0)])
        self.assertEqual(self.codes(bundle([tm03(txns)], [one_row], txns)), [])
        two_rows = takings([(3, 1000.0, 900.0), (3, 1000.0, 900.0)])
        self.assertEqual(len(self.codes(bundle([tm03(txns)], [two_rows], txns))), 1)

    def test_collection_emptied_the_day_before_and_procedure_cited(self):
        txns = [cash("T1", 9, 9420.0, "cash_deposit"), cash("T2", 10, 9615.0, "cash_deposit")]
        report = doc("COL-1", "cash_collection_reports",
                     "| Site | Emptied | Total |\n|---|---|---|\n"
                     "| Elmgate car park | 8 March 2026 | £9,420.00 |\n"
                     "| Fernway car park | 9 March 2026 | £9,615.00 |\n",
                     title="Machine collection reports from Testco Parking Ltd")
        procedure = doc("PRC-1", "cash_handling_procedure",
                        "Elmgate car park is emptied on Sundays and paid in the next morning.",
                        title="Cash handling procedure, Testco Parking Ltd")
        kyc = doc("KYC-1", "due_diligence_summary", "**Customer:** Testco Parking Ltd")
        b = bundle([tm03(txns)], [report, procedure, kyc], txns, customer={"name": "Testco Parking Ltd"})
        s = business_records(b)[0]
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0].evidence, ["COL-1", "PRC-1", "T1", "T2"])  # not the KYC summary

    def test_only_tm03_alerts(self):
        alert = {**tm03(TOPUPS), "rule_id": "TM05"}
        self.assertEqual(self.codes(bundle([alert], [takings(GOOD_ROWS)], TOPUPS)), [])

    def test_non_cash_transactions_are_not_reconciled(self):
        txns = [{**t, "channel": "faster_payment"} for t in TOPUPS]
        self.assertEqual(self.codes(bundle([tm03(txns)], [takings(GOOD_ROWS)], txns)), [])

    def test_explainers_entry_point_runs(self):
        s, q = explainers(bundle([tm03(TOPUPS)], [takings(GOOD_ROWS)], TOPUPS))
        self.assertEqual([x.code for x in s], ["BUSINESS_RECORDS_RECONCILE"])
        self.assertEqual(q, [])


if __name__ == "__main__":
    unittest.main()
