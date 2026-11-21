"""Synthetic checks for tm/red_flags.py (invented names and amounts, no development-case data).

Run:  python3 system/tests/test_red_flags.py   (on this Windows machine: py -I system/tests/test_red_flags.py)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from tm.load import parse_doc  # noqa: E402
from tm.red_flags import red_flags  # noqa: E402
from tm.types import CaseBundle  # noqa: E402


def doc(doc_id, dtype, text):
    return parse_doc({"doc_id": doc_id, "type": dtype, "title": dtype, "dated": None}, text)


def bundle(alerts, docs, txns=(), entries=(), customer=None):
    return CaseBundle(
        institution="test", case={"case_id": "C1", "customer_id": "U1", "alert_ids": [a["alert_id"] for a in alerts]},
        alerts=alerts, customer=customer or {"name": "Pat Example"},
        txns={t["transaction_id"]: t for t in txns}, docs={d.doc_id: d for d in docs}, reviews=[],
        list_entries={e["entry_id"]: e for e in entries}, internal_list={e["entry_id"]: e for e in entries}, policy={})


def tm22(matched_on="name", party="Sam Sample"):
    return {"alert_id": "A1", "rule_id": "TM22", "transaction_ids": ["T1"],
            "measured": {"list_entry": "L1", "matched_on": matched_on, "matched_party": party}}


TXN = {"transaction_id": "T1", "booked_at": "2026-08-13T10:00:00Z", "direction": "in", "amount_gbp": 5000.0,
       "counterparty_name": "Sam Sample"}
ENTRY = {"entry_id": "L1", "kind": "individual", "name": "Sam Sample", "date_of_birth": "1959-02-17",
         "address": "Unit 4B, Mill Works, Testtown", "reason": "Exited customer."}


class RedFlags(unittest.TestCase):
    def codes(self, b):
        return [(s.kind, s.code) for s in red_flags(b)[0]]

    def test_gift_letter_birth_date_matches_listed_person(self):
        letter = doc("GFT-1", "gift_letter", "I, Sam Sample, born 17 February 1959, give a gift of £5,000.00.")
        self.assertEqual(self.codes(bundle([tm22()], [letter], [TXN], [ENTRY])), [("red_flag", "ESC_LISTED_PARTY")])

    def test_gift_letter_dob_written_as_dob(self):
        letter = doc("GFT-1", "gift_letter", "I, Sam Sample (DOB: 17 February 1959), give a gift of £5,000.00.")
        self.assertEqual(self.codes(bundle([tm22()], [letter], [TXN], [ENTRY])), [("red_flag", "ESC_LISTED_PARTY")])

    def test_gift_letter_birth_date_differs(self):
        letter = doc("GFT-1", "gift_letter", "I, Sam Sample, born 3 May 1980, give a gift of £5,000.00.")
        self.assertEqual(self.codes(bundle([tm22()], [letter], [TXN], [ENTRY])), [("explains", "LIST_MATCH_DIFFERENT_PARTY")])

    def test_name_only_match_is_left_to_the_fallback(self):
        self.assertEqual(self.codes(bundle([tm22()], [], [TXN], [ENTRY])), [])

    def test_resigned_director_who_still_holds_control_is_a_red_flag(self):
        alert = tm22("company officer name and month and year of birth", "Sam Sample")
        officers = doc("REG-1", "company_register_extract",
                       "| Officer | Role | Born | Appointed | Resigned |\n|---|---|---|---|---|\n"
                       "| Sam Sample | Director | February 1959 | 1 May 2020 | 12 August 2026 |\n")
        psc = doc("PSC-1", "significant_control_register",
                  "| Person | Born | Control | Notified | Ceased |\n|---|---|---|---|---|\n"
                  "| Sam Sample | February 1959 | Owns 60% | 1 May 2020 | 20 August 2026 |\n")
        self.assertEqual(self.codes(bundle([alert], [officers, psc], [TXN], [ENTRY])), [("red_flag", "ESC_LISTED_PARTY")])

    def test_address_in_a_different_unit_is_a_different_party(self):
        alert = tm22("registered address in Mill Works, Testtown", "Other Studio Ltd")
        receipt = doc("RCT-1", "receipt", "Receipt from Other Studio Ltd\nClasses are held at Unit 4A, Mill Works.\n")
        self.assertEqual(self.codes(bundle([alert], [receipt], [TXN], [ENTRY])), [("explains", "LIST_MATCH_DIFFERENT_PARTY")])

    def test_fraud_report_escalates_the_case(self):
        report = doc("RPT-1", "sending_bank_fraud_report",
                     "# Fraud report from Example Bank\n**Subject:** Authorised push payment scam\n"
                     "Our customer Alex Victim sent £5,000.00 on 13 August 2026 to your customer's account.\n")
        alert = {"alert_id": "A1", "rule_id": "TM01", "transaction_ids": ["T1"], "measured": {}}
        sigs = red_flags(bundle([alert], [report], [TXN]))[0]
        self.assertEqual([(s.alert_id, s.code) for s in sigs], [("*", "ESC_MULE_ACTIVITY")])
        self.assertIn("RPT-1", sigs[0].evidence)

    def test_customer_asking_whether_splitting_avoids_reporting(self):
        note = doc("NTE-1", "staff_note", "Customer asked whether deposits made across branches are aggregated and "
                   "whether keeping each amount below the £10,000 threshold avoids reporting.")
        alert = {"alert_id": "A1", "rule_id": "TM05", "transaction_ids": [], "measured": {}}
        self.assertEqual(self.codes(bundle([alert], [note])), [("red_flag", "ESC_STRUCTURING")])

    def test_chat_about_investing_for_other_people(self):
        chat = doc("CHT-1", "support_chat",
                   "**Agent:** Who sent the deposits?\n\n**Customer:** Some friends sent me money to invest for them, so I am sending it on.\n")
        alert = {"alert_id": "A1", "rule_id": "TM08", "transaction_ids": ["T1"], "measured": {}}
        self.assertEqual(self.codes(bundle([alert], [chat], [TXN])), [("red_flag", "ESC_MULE_ACTIVITY")])

    def test_payer_dissolved_before_the_payment(self):
        reg = doc("REG-1", "company_register_extract",
                  "# Company register extract for Gone Trading Ltd\n**Company:** Gone Trading Ltd\n**Status:** Dissolved on 7 October 2025\n")
        txn = dict(TXN, counterparty_name="Gone Trading Ltd")
        alert = {"alert_id": "A1", "rule_id": "TM08", "transaction_ids": ["T1"], "measured": {}}
        self.assertEqual(self.codes(bundle([alert], [reg], [txn])), [("red_flag", "ESC_UNEXPLAINED_FUNDS")])

    def test_payer_dissolved_after_the_payment_is_fine(self):
        reg = doc("REG-1", "company_register_extract",
                  "# Company register extract for Gone Trading Ltd\n**Company:** Gone Trading Ltd\n**Status:** Dissolved on 7 October 2027\n")
        txn = dict(TXN, counterparty_name="Gone Trading Ltd")
        alert = {"alert_id": "A1", "rule_id": "TM08", "transaction_ids": ["T1"], "measured": {}}
        self.assertEqual(self.codes(bundle([alert], [reg], [txn])), [])

    def test_invoice_dated_after_the_payment_with_another_amount(self):
        inv = doc("INV-1", "supplier_invoices", "| Invoice | Dated | Goods | Amount |\n|---|---|---|---|\n"
                  "| INV 111 | 20 August 2026 | widgets | £6,000.00 |\n")
        pay = dict(TXN, direction="out", reference="INV 111", counterparty_name="Widget Co")
        alert = {"alert_id": "A1", "rule_id": "TM01", "transaction_ids": [], "measured": {}}
        self.assertEqual(self.codes(bundle([alert], [inv], [pay])), [("red_flag", "ESC_INVOICE_MISMATCH")])

    def test_matching_invoice_raises_nothing(self):
        inv = doc("INV-1", "supplier_invoices", "| Invoice | Goods | Amount |\n|---|---|---|\n| INV 111 | widgets | £5,000.00 |\n")
        pay = dict(TXN, direction="out", reference="INV 111", counterparty_name="Widget Co")
        alert = {"alert_id": "A1", "rule_id": "TM01", "transaction_ids": [], "measured": {}}
        self.assertEqual(self.codes(bundle([alert], [inv], [pay])), [])

    def test_client_cannot_justify_the_higher_risk_routing(self):
        note = doc("NTE-1", "staff_note", "The director said the goods come from Turkey but was unable to explain why the money goes to Lebanon.")
        alert = {"alert_id": "A1", "rule_id": "TM06", "transaction_ids": [], "measured": {"countries": "Lebanon"}}
        self.assertEqual(self.codes(bundle([alert], [note])), [("red_flag", "ESC_HIGH_RISK_CORRIDOR")])

    def test_many_payees_at_three_addresses(self):
        rows = "".join(f"| Payee {i} | Italy | {i % 3 + 1} Shared Road | £500.00 |\n" for i in range(12))
        pf = doc("PAY-1", "payment_file", "| Payee | Country | Address | Amount |\n|---|---|---|---|\n" + rows)
        alert = {"alert_id": "A1", "rule_id": "TM04", "transaction_ids": [], "measured": {}}
        self.assertEqual(self.codes(bundle([alert], [pf])), [("red_flag", "ESC_MULE_ACTIVITY")])

    def test_money_out_to_a_new_company_run_by_the_clients_director(self):
        own = doc("INC-1", "company_register_extract", "**Company:** Client Ltd\n| Officer | Role |\n|---|---|\n| Pat Boss | Director |\n")
        new = doc("REG-1", "company_register_extract",
                  "**Company:** Fresh Holdings Ltd\n**Incorporated:** 1 May 2026\n| Officer | Role |\n|---|---|\n| Pat Boss | Director |\n")
        out = dict(TXN, transaction_id="T2", direction="out", counterparty_name="Fresh Holdings Ltd")
        alert = {"alert_id": "A1", "rule_id": "TM02", "transaction_ids": ["T1", "T2"], "measured": {}}
        b = bundle([alert], [own, new], [TXN, out], customer={"name": "Client Ltd", "kind": "business"})
        b.case["review_window"] = {"from": "2026-08-01", "to": "2026-08-31"}
        self.assertEqual(self.codes(b), [("red_flag", "ESC_PASS_THROUGH")])

    def test_unrelated_payers_forwarded_to_an_exchange_within_a_day(self):
        ins = [dict(TXN, transaction_id=f"T{i}", counterparty_name=n, amount_gbp=1000.0) for i, n in ((1, "Ann One"), (2, "Bob Two"))]
        out = dict(TXN, transaction_id="T3", direction="out", counterparty_name="Quick Crypto Exchange", amount_gbp=1950.0,
                   booked_at="2026-08-13T12:00:00Z")
        alert = {"alert_id": "A1", "rule_id": "TM02", "transaction_ids": ["T1", "T2", "T3"], "measured": {}}
        self.assertEqual(self.codes(bundle([alert], [], ins + [out])), [("red_flag", "ESC_MULE_ACTIVITY")])

    def test_two_chats_about_the_cash_raise_a_question_for_the_reader(self):
        c1 = doc("CHT-1", "support_chat", "**Agent:** Where is the cash from?\n\n**Customer:** I sold my car.\n")
        c2 = doc("CHT-2", "support_chat", "**Agent:** Where is the cash from?\n\n**Customer:** My uncle gave it to me.\n")
        alert = {"alert_id": "A1", "rule_id": "TM05", "transaction_ids": [], "measured": {}}
        signals, questions = red_flags(bundle([alert], [c1, c2]))
        self.assertEqual(signals, [])
        self.assertEqual([(q.id, q.if_yes.code) for q in questions], [("stories_contradict_source", "ESC_UNEXPLAINED_FUNDS")])

    def test_ordinary_contact_note_raises_nothing(self):
        note = doc("NTE-2", "contact_note", "Customer called to set up a standing order. Guided them through the app.")
        alert = {"alert_id": "A1", "rule_id": "TM01", "transaction_ids": [], "measured": {}}
        self.assertEqual(red_flags(bundle([alert], [note])), ([], []))


if __name__ == "__main__":
    unittest.main()
