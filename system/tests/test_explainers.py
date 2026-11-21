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

    def test_explainers_entry_point_runs_business_records(self):
        s, q = explainers(bundle([tm03(TOPUPS)], [takings(GOOD_ROWS)], TOPUPS))
        self.assertEqual([x.code for x in s], ["BUSINESS_RECORDS_RECONCILE"])
        self.assertEqual(q, [])


POLICY = {"own_account_rfi_multiple": 5, "rules": {"TM02": {"amounts": [2000.0]}}}


def xfer(tid, day, direction, amount, account, name="Pat Example", channel="faster_payment"):
    return {"transaction_id": tid, "booked_at": f"2026-05-{day:02d}T10:00:00Z", "direction": direction,
            "channel": channel, "amount_gbp": amount, "counterparty_name": name, "counterparty_account": account}


def statement(doc_id, holder, account, text):
    return doc(doc_id, "bank_statement",
               f"**Account holder:** {holder}\n**Bank:** Testbank\n**Account:** {account}\n\n{text}")


def own_bundle(alerts, docs, txns, customer=None):
    b = bundle(alerts, docs, txns, customer)
    b.policy = POLICY
    return b


def tm01(txns, received, baseline, multiple, limit=3):
    return {"alert_id": "A1", "rule_id": "TM01", "transaction_ids": [t["transaction_id"] for t in txns],
            "measured": {"received_gbp": received, "baseline_gbp": baseline, "multiple": multiple,
                         "limit_multiple": limit}}


class OwnAccount(unittest.TestCase):
    def codes(self, b):
        from tm.explainers import own_account
        return [(s.kind, s.code) for s in own_account(b)[0]]

    IN = xfer("T1", 7, "in", 4200.0, "11-22-33 44556677")
    OUT = xfer("T2", 8, "out", 4200.0, "99-88-77 66554433")
    SMALL = xfer("T3", 6, "in", 150.0, None)
    SRC = statement("STM-1", "Pat Example", "11-22-33 44556677", "7 May 2026: transfer of £4,200.00 out.")
    DST = statement("STM-2", "Pat Example", "99-88-77 66554433", "8 May 2026: £4,200.00 received.")

    def tm02(self, txns):
        return {"alert_id": "A1", "rule_id": "TM02", "transaction_ids": [t["transaction_id"] for t in txns],
                "measured": {}}

    def test_tm02_in_and_out_both_own_accounts_closes(self):
        txns = [self.SMALL, self.IN, self.OUT]
        b = own_bundle([self.tm02(txns)], [self.SRC, self.DST], txns)
        self.assertEqual(self.codes(b), [("explains", "OWN_ACCOUNT")])

    def test_tm02_destination_not_documented_explains_nothing(self):
        txns = [self.SMALL, self.IN, self.OUT]
        self.assertEqual(self.codes(own_bundle([self.tm02(txns)], [self.SRC], txns)), [])

    def test_statement_in_someone_elses_name_explains_nothing(self):
        txns = [self.IN, self.OUT]
        other = statement("STM-2", "Robin Other", "99-88-77 66554433", "8 May 2026: £4,200.00 received.")
        self.assertEqual(self.codes(own_bundle([self.tm02(txns)], [self.SRC, other], txns)), [])

    def test_statement_for_a_different_account_number_explains_nothing(self):
        txns = [self.IN, self.OUT]
        wrong = statement("STM-2", "Pat Example", "99-88-77 66554400", "8 May 2026: £4,200.00 received.")
        self.assertEqual(self.codes(own_bundle([self.tm02(txns)], [self.SRC, wrong], txns)), [])

    def test_statement_amount_differs_explains_nothing(self):
        txns = [self.IN, self.OUT]
        wrong = statement("STM-2", "Pat Example", "99-88-77 66554433", "8 May 2026: £4,100.00 received.")
        self.assertEqual(self.codes(own_bundle([self.tm02(txns)], [self.SRC, wrong], txns)), [])

    def test_tm02_large_third_party_money_left_over_explains_nothing(self):
        other = xfer("T4", 7, "in", 2500.0, "12-12-12 12121212", name="Robin Other")
        txns = [self.IN, self.OUT, other]
        self.assertEqual(self.codes(own_bundle([self.tm02(txns)], [self.SRC, self.DST], txns)), [])

    def test_tm01_below_five_times_closes(self):
        txns = [self.SMALL, self.IN]
        b = own_bundle([tm01(txns, 4350.0, 1400.0, 3.11)], [self.SRC], txns)
        self.assertEqual(self.codes(b), [("explains", "OWN_ACCOUNT")])

    def test_tm01_at_or_above_five_times_asks_for_updated_profile(self):
        txns = [self.SMALL, self.IN]
        b = own_bundle([tm01(txns, 4350.0, 870.0, 5.0)], [self.SRC], txns)
        self.assertEqual(self.codes(b), [("partial", "RFI_UPDATED_PROFILE")])

    def test_tm01_still_over_profile_without_the_own_money_explains_nothing(self):
        salary = xfer("T5", 1, "in", 5000.0, "55-55-55 55555555", name="Employer Ltd")
        txns = [salary, self.IN]
        b = own_bundle([tm01(txns, 9200.0, 1400.0, 4.0)], [self.SRC], txns)  # 5,000 left > 3 x 1,400
        self.assertEqual(self.codes(b), [])

    def test_account_ending_matches_and_joint_holders_count(self):
        t = xfer("T1", 7, "in", 4200.0, "account ending 6677", name="P & R Example")
        joint = doc("STM-1", "bank_statement",
                    "**Account holders:** Pat Example and Robin Example\n**Account:** 11-22-33 44556677\n\n"
                    "7 May 2026: transfer of £4,200.00.")
        alert = {"alert_id": "A1", "rule_id": "TM08", "transaction_ids": ["T1"], "measured": {"limit_gbp": 1000}}
        from tm.explainers import own_account
        s = own_account(own_bundle([alert], [joint], [t]))[0]
        self.assertEqual([(x.kind, x.code) for x in s], [("explains", "OWN_ACCOUNT")])
        self.assertIn("jointly held by Pat Example and Robin Example", s[0].facts)

    def test_other_rules_are_not_explained_by_own_account(self):
        txns = [self.IN]
        alert = {"alert_id": "A1", "rule_id": "TM07", "transaction_ids": ["T1"], "measured": {}}
        self.assertEqual(self.codes(own_bundle([alert], [self.SRC], txns)), [])


class ReturningCustomer(unittest.TestCase):
    CREDIT = xfer("T1", 12, "in", 7300.0, "account ending 4321")
    SPEND = xfer("T2", 13, "out", 85.0, None, name="Shop", channel="card")
    STMT = statement("STM-1", "Pat Example", "account ending 4321", "12 May 2026: transfer of £7,300.00.")

    def rvf(self, day):
        return doc("RVF-1", "reverification_record",
                   f"Identity re-verified on {day} May 2026 with a live selfie on the registered device.")

    def tm07(self, txns, dormant=240):
        return {"alert_id": "A1", "rule_id": "TM07", "transaction_ids": [t["transaction_id"] for t in txns],
                "measured": {"dormant_days": dormant, "limit_gbp": 5000}}

    def codes(self, b):
        from tm.explainers import returning_customer
        return [(s.kind, s.code) for s in returning_customer(b)[0]]

    def test_reverified_the_day_before_and_own_statement_closes(self):
        txns = [self.CREDIT, self.SPEND]
        from tm.explainers import returning_customer
        s = returning_customer(own_bundle([self.tm07(txns)], [self.rvf(11), self.STMT], txns))[0]
        self.assertEqual([(x.kind, x.code) for x in s], [("explains", "RETURNING_CUSTOMER")])
        self.assertEqual(s[0].evidence, ["RVF-1", "STM-1", "T1"])
        self.assertIn("the day before", s[0].facts)

    def test_reverified_after_the_account_moved_explains_nothing(self):
        txns = [self.CREDIT, self.SPEND]
        self.assertEqual(self.codes(own_bundle([self.tm07(txns)], [self.rvf(14), self.STMT], txns)), [])

    def test_reverified_before_the_dormancy_explains_nothing(self):
        txns = [self.CREDIT, self.SPEND]
        self.assertEqual(self.codes(own_bundle([self.tm07(txns, dormant=5)], [self.rvf(1), self.STMT], txns)), [])

    def test_no_statement_for_the_money_explains_nothing(self):
        txns = [self.CREDIT, self.SPEND]
        self.assertEqual(self.codes(own_bundle([self.tm07(txns)], [self.rvf(11)], txns)), [])

    def test_no_reverification_explains_nothing(self):
        txns = [self.CREDIT, self.SPEND]
        self.assertEqual(self.codes(own_bundle([self.tm07(txns)], [self.STMT], txns)), [])

    def test_large_payment_out_left_unexplained_explains_nothing(self):
        out = xfer("T3", 13, "out", 6000.0, "IBAN ending 9999", name="Supplier Co")
        txns = [self.CREDIT, out]
        self.assertEqual(self.codes(own_bundle([self.tm07(txns)], [self.rvf(11), self.STMT], txns)), [])


if __name__ == "__main__":
    unittest.main()
