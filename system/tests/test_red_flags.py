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
        self.assertEqual(self.codes(bundle([alert], [reg], [txn])), [("red_flag", "ESC_THIRD_PARTY_FUNDING")])

    def test_payer_dissolved_after_the_payment_is_fine(self):
        reg = doc("REG-1", "company_register_extract",
                  "# Company register extract for Gone Trading Ltd\n**Company:** Gone Trading Ltd\n**Status:** Dissolved on 7 October 2027\n")
        txn = dict(TXN, counterparty_name="Gone Trading Ltd")
        alert = {"alert_id": "A1", "rule_id": "TM08", "transaction_ids": ["T1"], "measured": {}}
        self.assertEqual(self.codes(bundle([alert], [reg], [txn])), [])

    def test_ordinary_contact_note_raises_nothing(self):
        note = doc("NTE-2", "contact_note", "Customer called to set up a standing order. Guided them through the app.")
        alert = {"alert_id": "A1", "rule_id": "TM01", "transaction_ids": [], "measured": {}}
        self.assertEqual(red_flags(bundle([alert], [note])), ([], []))


if __name__ == "__main__":
    unittest.main()
