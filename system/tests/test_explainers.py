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


def dated_doc(doc_id, dtype, text, dated, title=None):
    return parse_doc({"doc_id": doc_id, "type": dtype, "title": title or dtype, "dated": dated}, text)


class DocumentedEvent(unittest.TestCase):
    PAYOUT = {"transaction_id": "T1", "booked_at": "2026-06-14T10:00:00Z", "direction": "in",
              "channel": "faster_payment", "amount_gbp": 16250.40, "counterparty_name": "Testshire Life Assurance plc",
              "counterparty_account": "10-20-30 40506070", "reference": "CLAIM 55123"}

    def letter(self, text=None, dated="2026-06-12", dtype="insurer_letter",
               title="Claim settlement letter from Testshire Life Assurance plc"):
        text = text or ("Dear Pat Example,\nWe have accepted your claim, reference CLAIM 55123.\n"
                        "A settlement payment of £16,250.40 will be sent to you by bank transfer.")
        return dated_doc("INS-1", dtype, text, dated, title)

    def tm07(self, txns):
        return {"alert_id": "A1", "rule_id": "TM07", "transaction_ids": [t["transaction_id"] for t in txns],
                "measured": {"dormant_days": 300, "limit_gbp": 5000}}

    def codes(self, b):
        from tm.explainers import documented_event
        return [(s.kind, s.code) for s in documented_event(b)[0]]

    def test_insurer_letter_matching_amount_payer_and_claim_closes(self):
        b = own_bundle([self.tm07([self.PAYOUT])], [self.letter()], [self.PAYOUT])
        self.assertEqual(self.codes(b), [("explains", "DOCUMENTED_EVENT")])

    def test_explains_tm01_whatever_the_multiple(self):
        alert = tm01([self.PAYOUT], 16250.40, 2000.0, 8.13)  # 8x: the 5x rule is for own accounts only
        self.assertEqual(self.codes(own_bundle([alert], [self.letter()], [self.PAYOUT])),
                         [("explains", "DOCUMENTED_EVENT")])

    def test_claim_reference_not_in_the_letter_explains_nothing(self):
        text = "Dear Pat Example,\nWe have accepted claim CLAIM 99999.\nWe will pay £16,250.40."
        self.assertEqual(self.codes(own_bundle([self.tm07([self.PAYOUT])], [self.letter(text)], [self.PAYOUT])), [])

    def test_letter_addressed_to_someone_else_explains_nothing(self):
        text = "Dear Robin Other,\nWe have accepted your claim, CLAIM 55123.\nWe will pay £16,250.40."
        self.assertEqual(self.codes(own_bundle([self.tm07([self.PAYOUT])], [self.letter(text)], [self.PAYOUT])), [])

    def test_letter_dated_after_the_credit_explains_nothing(self):
        b = own_bundle([self.tm07([self.PAYOUT])], [self.letter(dated="2026-06-15")], [self.PAYOUT])
        self.assertEqual(self.codes(b), [])

    def test_letter_dated_too_long_before_explains_nothing(self):
        b = own_bundle([self.tm07([self.PAYOUT])], [self.letter(dated="2026-04-01")], [self.PAYOUT])
        self.assertEqual(self.codes(b), [])

    def test_letter_from_another_company_explains_nothing(self):
        b = own_bundle([self.tm07([self.PAYOUT])], [self.letter(title="Claim letter from Other Mutual plc")],
                       [self.PAYOUT])
        self.assertEqual(self.codes(b), [])

    def test_amount_differs_explains_nothing(self):
        text = "Dear Pat Example,\nWe have accepted your claim, CLAIM 55123.\nWe will pay £16,250.00."
        self.assertEqual(self.codes(own_bundle([self.tm07([self.PAYOUT])], [self.letter(text)], [self.PAYOUT])), [])

    def test_invoices_and_gift_letters_are_left_to_their_own_checks(self):
        for dtype in ("supplier_invoice", "gift_letter", "venue_email", "credit_note"):
            b = own_bundle([self.tm07([self.PAYOUT])], [self.letter(dtype=dtype)], [self.PAYOUT])
            self.assertEqual(self.codes(b), [], dtype)

    def test_own_name_credit_is_left_to_own_account(self):
        own = {**self.PAYOUT, "counterparty_name": "Pat Example"}
        text = "Dear Pat Example,\nTransfer of £16,250.40, CLAIM 55123, to Pat Example."
        b = own_bundle([self.tm07([own])], [self.letter(text, title="Letter from Pat Example")], [own])
        self.assertEqual(self.codes(b), [])

    # ---- cash: sale receipts
    CASH = {"transaction_id": "T1", "booked_at": "2026-06-09T12:00:00Z", "direction": "in", "channel": "cash_topup",
            "amount_gbp": 1340.0, "counterparty_name": None, "counterparty_account": None, "reference": "CASH TOP UP"}
    TM05 = {"alert_id": "A1", "rule_id": "TM05", "transaction_ids": ["T1"], "measured": {"limit_gbp": 1000}}

    def receipt(self, body, dtype="sale_receipt"):
        return dated_doc("SAL-1", dtype, body, "2026-06-08", "Sale receipt")

    def test_seller_phrasings_all_read_as_the_customer(self):
        bodies = [
            "**Seller:** Pat Example\n**Buyer:** Sam Buyer\nReceived £1,340.00 in cash.",
            "Seller: Pat Example\nBuyer: Sam Buyer\nTotal Amount Paid: £1,340.00\nPayment Method: Cash",
            "I, Pat Example, confirm the sale of one bike to Sam Buyer for £1,340.00 in cash.",
            "I, Pat Example, have today sold one bike to Sam Buyer for £1,340.00, paid in cash.",
            "This document confirms the sale of one bike from Pat Example to Sam Buyer for £1,340.00 in cash.",
            "This confirms that Pat Example has sold one bike to Sam Buyer for £1,340.00 in cash.",
        ]
        for body in bodies:
            b = own_bundle([self.TM05], [self.receipt(body)], [self.CASH])
            self.assertEqual(self.codes(b), [("explains", "DOCUMENTED_EVENT")], body)

    def test_someone_else_selling_explains_nothing(self):
        body = "I, Sam Buyer, confirm the sale of one bike to Pat Example for £1,340.00 in cash."
        self.assertEqual(self.codes(own_bundle([self.TM05], [self.receipt(body)], [self.CASH])), [])

    def test_vehicle_receipt_needs_the_customers_ownership_document(self):
        cash = {**self.CASH, "amount_gbp": 12500.0, "channel": "cash_deposit"}
        body = "**Seller:** Pat Example\nReceived £12,500.00 in cash for a 2020 hatchback, registration AB20 CDE."
        rec = self.receipt(body, "vehicle_sale_receipt")
        self.assertEqual(self.codes(own_bundle([self.TM05], [rec], [cash])), [])  # no ownership document
        mine = doc("INS-1", "insurance_schedule", "**Policyholder:** Pat Example\n**Vehicle:** registration AB20 CDE")
        from tm.explainers import documented_event
        s = documented_event(own_bundle([self.TM05], [rec, mine], [cash]))[0]
        self.assertEqual([x.code for x in s], ["DOCUMENTED_EVENT"])
        self.assertIn("INS-1", s[0].evidence)
        theirs = doc("INS-1", "insurance_schedule", "**Policyholder:** Pat Example\n**Vehicle:** registration ZZ99 ZZZ")
        self.assertEqual(self.codes(own_bundle([self.TM05], [rec, theirs], [cash])), [])

    # ---- house move: deposit returned, holding deposit paid
    def test_deposit_return_and_holding_deposit_both_documented_closes_tm02(self):
        back = {"transaction_id": "T1", "booked_at": "2026-06-10T10:00:00Z", "direction": "in",
                "channel": "faster_payment", "amount_gbp": 1900.0, "counterparty_name": "Oldtown Lettings Ltd",
                "counterparty_account": "11-11-11 11111111", "reference": "DEPOSIT RETURN"}
        top = xfer("T2", 10, "in", 600.0, "22-22-22 22222222")
        out = {"transaction_id": "T3", "booked_at": "2026-06-11T10:00:00Z", "direction": "out",
               "channel": "faster_payment", "amount_gbp": 2500.0, "counterparty_name": "Newtown Homes Ltd",
               "counterparty_account": "33-33-33 33333333", "reference": "HOLDING DEPOSIT"}
        docs = [dated_doc("LET-1", "deposit_return_letter", "Dear Tenant,\nWe are returning £1,900.00 to you today.",
                          "2026-06-09", "Deposit return from Oldtown Lettings Ltd"),
                dated_doc("LET-2", "holding_deposit_receipt", "Dear Tenant,\nThank you for your holding deposit of £2,500.00.",
                          "2026-06-11", "Holding deposit receipt from Newtown Homes Ltd")]
        alert = {"alert_id": "A1", "rule_id": "TM02", "transaction_ids": ["T1", "T2", "T3"], "measured": {}}
        self.assertEqual(self.codes(own_bundle([alert], docs, [back, top, out])), [("explains", "DOCUMENTED_EVENT")])
        self.assertEqual(self.codes(own_bundle([alert], docs[:1], [back, top, out])), [])  # holding deposit undocumented


def txn(tid, when, direction, amount, name=None, account=None, ref="", channel="faster_payment", country="United Kingdom"):
    return {"transaction_id": tid, "booked_at": f"2026-{when}T10:00:00Z", "direction": direction, "channel": channel,
            "amount_gbp": amount, "counterparty_name": name, "counterparty_account": account, "reference": ref,
            "counterparty_country": country}


class Refund(unittest.TestCase):
    PAID = txn("T0", "05-10", "out", 7400.55, "Testvale Hotel and Gardens", "account ending 1234", "BOOKING 48151")
    BACK = txn("T1", "07-20", "in", 7400.55, "Testvale Hotel and Gardens", "12-34-56 78901234", "REFUND BOOKING 48151")
    TM06 = {"alert_id": "A1", "rule_id": "TM06", "transaction_ids": ["T1"], "measured": {"limit_gbp": 5000}}

    def email(self, text=None, dated="2026-07-18"):
        text = text or "Dear Client,\nWe have refunded your deposit of £7,400.55 for BOOKING 48151."
        return dated_doc("EML-1", "venue_email", text, dated, "Email from Testvale Hotel and Gardens")

    def run_refund(self, alerts, docs, txns, reviews=(), policy=None):
        from tm.explainers import refund
        b = own_bundle(alerts, docs, txns)
        b.reviews = list(reviews)
        if policy:
            b.policy = policy
        return refund(b)[0]

    def test_venue_refund_of_an_earlier_deposit_closes(self):
        review = {"review_id": "R1", "reviewed_on": "2026-05-12", "rule_id": "TM06", "note": "Closed. Venue deposit."}
        s = self.run_refund([self.TM06], [self.email()], [self.PAID, self.BACK], [review])
        self.assertEqual([(x.kind, x.code) for x in s], [("explains", "REFUND_OF_EARLIER_PAYMENT")])
        self.assertEqual(s[0].evidence, ["EML-1", "R1", "T1", "T0"])

    def test_no_document_explains_nothing(self):
        self.assertEqual(self.run_refund([self.TM06], [], [self.PAID, self.BACK]), [])

    def test_document_written_before_the_original_payment_explains_nothing(self):
        self.assertEqual(self.run_refund([self.TM06], [self.email(dated="2026-05-01")], [self.PAID, self.BACK]), [])

    def test_no_earlier_payment_of_that_amount_explains_nothing(self):
        paid = {**self.PAID, "amount_gbp": 7000.00}
        self.assertEqual(self.run_refund([self.TM06], [self.email()], [paid, self.BACK]), [])

    def test_earlier_payment_to_someone_else_explains_nothing(self):
        paid = {**self.PAID, "counterparty_name": "Other Venue Ltd", "counterparty_account": "account ending 9999"}
        self.assertEqual(self.run_refund([self.TM06], [self.email()], [paid, self.BACK]), [])

    def test_document_not_naming_the_booking_or_party_explains_nothing(self):
        doc_ = dated_doc("EML-1", "customer_email", "We refunded £7,400.55.", "2026-07-18", "Email")
        self.assertEqual(self.run_refund([self.TM06], [doc_], [self.PAID, self.BACK]), [])

    def test_cancelled_subscription_returned_to_the_same_account_closes_both_alerts(self):
        sub = txn("T1", "09-13", "in", 27500.0, "Pat Example", "71-01-34 10009843", "ISA SUBSCRIPTION")
        ret = txn("T2", "09-19", "out", 27500.0, "Pat Example", "71-01-34 10009843", "CANCELLATION REFUND")
        conf = dated_doc("CAN-1", "cancellation_confirmation",
                         "Dear Customer,\nWe have returned your subscription of £27,500.00 to 71-01-34 10009843.",
                         "2026-09-18", "Cancellation confirmation")
        alerts = [tm01([sub], 28700.0, 6400.0, 4.48),
                  {"alert_id": "A2", "rule_id": "TM02", "transaction_ids": ["T1", "T2"], "measured": {}}]
        s = self.run_refund(alerts, [conf], [sub, ret])
        self.assertEqual(sorted(x.alert_id for x in s), ["A1", "A2"])
        self.assertEqual(self.run_refund(alerts, [], [sub, ret]), [])  # no confirmation: not explained

    def test_cash_paid_back_in_needs_the_review_that_covered_the_withdrawal(self):
        out = txn("T0", "07-17", "out", 14000.0, channel="cash_withdrawal")
        back = txn("T1", "10-06", "in", 14000.0, channel="cash_deposit")
        chat = dated_doc("CHT-1", "support_chat", "**Customer:** It is the £14,000.00 I withdrew in July.",
                         "2026-10-06", "Chat with the customer")
        alert = {"alert_id": "A1", "rule_id": "TM05", "transaction_ids": ["T1"], "measured": {"limit_gbp": 10000}}
        covers = {"review_id": "R1", "reviewed_on": "2026-07-19", "rule_id": "TM05",
                  "note": "Closed. Cash withdrawal to buy a car privately."}
        self.assertEqual(len(self.run_refund([alert], [chat], [out, back], [covers])), 1)
        self.assertEqual(self.run_refund([alert], [chat], [out, back]), [])  # no review
        too_early = {**covers, "reviewed_on": "2026-06-01"}  # written before the withdrawal: can't describe it
        self.assertEqual(self.run_refund([alert], [chat], [out, back], [too_early]), [])

    def test_tm02_third_party_money_rule_follows_the_policy_wording(self):
        own_payment = txn("T2", "07-21", "out", 116000.0, "Regular Supplier Co", "IBAN ending 4321", "PO 12 BALANCE")
        alert = {"alert_id": "A1", "rule_id": "TM02", "transaction_ids": ["T1", "T2"], "measured": {}}
        third_party_only = {**POLICY, "rules": {"TM02": {"amounts": [2000.0], "fires_when":
                            "at least 80% of the money received from anyone other than the client is paid out"}}}
        self.assertEqual(len(self.run_refund([alert], [self.email()], [self.PAID, self.BACK, own_payment],
                                             policy=third_party_only)), 1)
        all_money = {**POLICY, "rules": {"TM02": {"amounts": [2000.0], "fires_when":
                     "at least 80% of the money received is paid out within 48 hours"}}}
        self.assertEqual(self.run_refund([alert], [self.email()], [self.PAID, self.BACK, own_payment],
                                         policy=all_money), [])


class InvoiceMatches(unittest.TestCase):
    PAY = txn("T1", "10-05", "out", 10250.47, "Testcastle Medical Center", "account ending 1986", "PATIENT ROBIN EXAMPLE",
              channel="swift", country="Lebanon")
    TM06 = {"alert_id": "A1", "rule_id": "TM06", "transaction_ids": ["T1"], "measured": {"limit_gbp": 5000}}

    def invoice(self, extra="", dated="2026-10-03", amount="£10,250.47", title="Invoice from Testcastle Medical Center",
                dtype="hospital_invoice"):
        return dated_doc("INV-1", dtype, f"**Patient:** Robin Example\n**Amount due:** {amount}\n"
                                          f"**Pay to:** Testcastle Medical Center\n{extra}", dated, title)

    def run_inv(self, alerts, docs, txns, held=None):
        from tm.explainers import invoice_matches
        b = own_bundle(alerts, docs, txns)
        if held:
            b.case["held_payment_id"] = held
        return invoice_matches(b)[0]

    def codes(self, alerts, docs, txns):
        return [(s.kind, s.code) for s in self.run_inv(alerts, docs, txns)]

    def test_hospital_invoice_matching_amount_and_payee_closes(self):
        self.assertEqual(self.codes([self.TM06], [self.invoice()], [self.PAY]), [("explains", "INVOICE_MATCHES")])

    def test_invoice_dated_after_the_payment_explains_nothing(self):
        self.assertEqual(self.codes([self.TM06], [self.invoice(dated="2026-10-07")], [self.PAY]), [])

    def test_invoice_amount_differs_explains_nothing(self):
        self.assertEqual(self.codes([self.TM06], [self.invoice(amount="£10,520.47")], [self.PAY]), [])

    def test_invoice_from_another_payee_explains_nothing(self):
        other = dated_doc("INV-1", "hospital_invoice", "**Amount due:** £10,250.47\n**Pay to:** Other Clinic",
                          "2026-10-03", "Invoice from Other Clinic")
        self.assertEqual(self.codes([self.TM06], [other], [self.PAY]), [])

    def test_reference_number_not_on_the_invoice_explains_nothing(self):
        pay = {**self.PAY, "reference": "INV 50123"}
        self.assertEqual(self.codes([self.TM06], [self.invoice("**Invoice:** INV 50999")], [pay]), [])

    def test_other_buyer_or_other_account_explains_nothing(self):
        self.assertEqual(self.codes([self.TM06], [self.invoice("**Buyer:** Someone Else Ltd")], [self.PAY]), [])
        pay = {**self.PAY, "counterparty_account": "account ending 7777"}
        acct = dated_doc("INV-1", "supplier_invoice", "**Amount:** £10,250.47\n**Pay to:** account ending 1986",
                         "2026-10-03", "Invoice from Testcastle Medical Center")
        self.assertEqual(self.codes([self.TM06], [acct], [pay]), [])

    def test_factoring_and_employment_documents_are_not_invoices(self):
        for dtype in ("factoring_agreement", "employment_contract", "insurer_letter"):
            self.assertEqual(self.codes([self.TM06], [self.invoice(dtype=dtype)], [self.PAY]), [], dtype)

    def test_financed_car_needs_both_the_loan_agreement_and_the_dealer_invoice(self):
        loan = txn("T1", "09-19", "in", 23000.0, "Testfin Finance Ltd", "52-28-61 17163589", "LOAN ADVANCE")
        car = txn("T2", "09-20", "out", 24900.0, "Testtown Motors Ltd", "77-65-33 86174645", "INV 72911")
        agreement = dated_doc("LOA-1", "loan_agreement", "**Borrower:** Pat Example\n**Lender:** Testfin Finance Ltd\n"
                              "**Principal Amount:** £23,000.00", "2026-09-16", "Loan agreement with Testfin Finance Ltd")
        dealer = dated_doc("INV-2", "dealer_invoice", "**Customer:** Pat Example\n**Price:** £24,900.00",
                           "2026-09-19", "Invoice INV 72911 from Testtown Motors Ltd")
        alert = {"alert_id": "A1", "rule_id": "TM02", "transaction_ids": ["T1", "T2"], "measured": {}}
        self.assertEqual(self.codes([alert], [agreement, dealer], [loan, car]), [("explains", "INVOICE_MATCHES")])
        self.assertEqual(self.codes([alert], [dealer], [loan, car]), [])  # the loan advance stays unexplained

    def test_stage_payments_each_on_their_schedule_row(self):
        stages = [txn(f"T{i}", f"10-{6 + 3 * i:02d}", "out", amt, "Testmore Arredamenti Srl", "IBAN ending 9186",
                      f"PROJECT STAGE {i}", channel="swift", country="Italy")
                  for i, amt in enumerate([9269.70, 9101.27, 9431.90, 9188.78], start=1)]
        rows = "\n".join(f"| {i} | Work | {6 + 3 * i} October 2026 | £{t['amount_gbp']:,.2f} |" for i, t in enumerate(stages, 1))
        schedule = dated_doc("CON-1", "contract_schedule", "**Supplier:** Testmore Arredamenti Srl\n\n"
                             "| Stage | Work | Due | Amount |\n|---|---|---|---|\n" + rows, "2026-09-01",
                             "Payment schedule, contract with Testmore Arredamenti Srl")
        alert = {"alert_id": "A1", "rule_id": "TM03", "transaction_ids": [t["transaction_id"] for t in stages],
                 "measured": {"limit_count": 2}}
        s = self.run_inv([alert], [schedule], stages, held="T4")
        self.assertEqual([x.code for x in s], ["INVOICE_MATCHES"])
        self.assertEqual(s[0].evidence[:2], ["CON-1", "T4"])  # the held payment is cited first
        short = dated_doc("CON-1", "contract_schedule", schedule.text.rsplit("\n", 1)[0], "2026-09-01", schedule.title)
        self.assertEqual(self.run_inv([alert], [short], stages), [])  # one stage without a row: TM03 not explained

    def test_payment_file_covers_the_contractors_and_leaves_few_other_parties(self):
        fees = [txn(f"T{i}", "09-20", "out", 900.0 + i, f"Contractor Name{chr(65 + i)}", f"IBAN ending {1000 + i}",
                    "MONTHLY FEE", channel="swift") for i in range(6)]
        supplier = txn("T9", "09-15", "out", 90000.0, "Big Supplier Co", "IBAN ending 3180", "INV 84609", channel="swift")
        rows = "\n".join(f"| {t['counterparty_name']} | Poland | C-{i} | £{t['amount_gbp']:,.2f} |" for i, t in enumerate(fees))
        pfile = dated_doc("PAY-1", "payment_file", "| Contractor | Country | Contract | Amount |\n|---|---|---|---|\n" + rows,
                          "2026-09-19", "Contractor payment file")
        alert = {"alert_id": "A1", "rule_id": "TM04", "transaction_ids": [t["transaction_id"] for t in fees + [supplier]],
                 "measured": {"distinct_counterparties": 7, "limit": 3}}
        self.assertEqual(self.codes([alert], [pfile], fees + [supplier]), [("explains", "INVOICE_MATCHES")])
        few = dated_doc("PAY-1", "payment_file", "| Contractor | Country | Contract | Amount |\n|---|---|---|---|\n"
                        + "\n".join(rows.splitlines()[:2]), "2026-09-19", "Contractor payment file")
        self.assertEqual(self.codes([alert], [few], fees + [supplier]), [])  # 5 parties left > limit 3

    def test_own_freight_invoices_may_be_issued_after_the_receipt_when_the_reference_matches(self):
        rec = txn("T1", "10-11", "in", 12216.28, "Testcote Exports Ltd", "35-30-06 29236070", "FREIGHT 10102")
        inv = dated_doc("INV-3", "freight_invoices", "| Invoice | Exporter | Amount |\n|---|---|---|\n"
                        "| FREIGHT 10102 | Testcote Exports Ltd | £12,216.28 |", "2026-10-13",
                        "Freight invoices issued by Pat Example")
        alert = {"alert_id": "A1", "rule_id": "TM08", "transaction_ids": ["T1"], "measured": {"limit_gbp": 1000}}
        self.assertEqual(self.codes([alert], [inv], [rec]), [("explains", "INVOICE_MATCHES")])
        late = dated_doc("INV-3", "freight_invoices", inv.text, "2026-10-25", inv.title)
        self.assertEqual(self.codes([alert], [late], [rec]), [])  # beyond the grace


if __name__ == "__main__":
    unittest.main()
