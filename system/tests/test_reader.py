"""Synthetic checks for tm/reader.py with a fake network (invented documents, no development-case data).

Run:  python3 system/tests/test_reader.py   (on Windows: py -I system/tests/test_reader.py)
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from tm import reader  # noqa: E402
from tm.load import parse_doc  # noqa: E402
from tm.pipeline import _answer_to_signal  # noqa: E402
from tm.types import CaseBundle, Question, Signal  # noqa: E402

CHAT = ("# Support chat\n\n**Customer:** Hi, the money I got this week is for my cousin's friends, "
        "I just pass it on to them.\n\n**Agent:** Thanks, noted.")
NOTE = "# Contact note\n\nCustomer confirmed the payment was for office furniture."


def doc(doc_id, dtype, text):
    return parse_doc({"doc_id": doc_id, "type": dtype, "title": dtype, "dated": "2026-09-01"}, text)


def bundle():
    docs = [doc("CHAT-1", "support_chat", CHAT), doc("NOTE-1", "contact_note", NOTE)]
    return CaseBundle(institution="test", case={"case_id": "C1", "customer_id": "U1", "alert_ids": ["A1"]},
                      alerts=[], customer={"name": "Pat Example"}, txns={}, docs={d.doc_id: d for d in docs},
                      reviews=[], list_entries={}, internal_list={}, policy={})


def question(doc_ids=("CHAT-1",)):
    sig = Signal(alert_id="A1", kind="red_flag", code="ESC_ACCOUNT_MISUSE", facts="x", evidence=["CHAT-1"])
    return Question(id="chat_shows_third_party_money", alert_id="A1",
                    text="Does the customer say the money belongs to other people?", doc_ids=list(doc_ids),
                    if_yes=sig)


def jev(p):
    return {"answers": {"answer": {"type": "noul", "noul": p}}, "usage": {"cost": 0.00002}}


def chat(obj):
    content = obj if isinstance(obj, str) else json.dumps(obj)
    return {"choices": [{"message": {"content": content}}], "usage": {"total_tokens": 100}}


class Reader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patches = [
            mock.patch.object(reader, "CACHE_DIR", os.path.join(self.tmp, "cache")),
            mock.patch.object(reader, "LOG_PATH", os.path.join(self.tmp, "calls.jsonl")),
            mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key", "TM_READER_CACHE": "1"}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_with(self, response, tier=1, q=None):
        with mock.patch.object(reader, "_post", return_value=response) as post:
            a = reader.ask(q or question(), bundle(), tier)
        return a, post

    # --- tier 1: Jev probability -> yes / no / unknown
    def test_jev_high_probability_is_yes(self):
        a, post = self.run_with(jev(0.97))
        self.assertEqual((a.value, a.tier, a.model, a.evidence), ("yes", 1, "typesafe/jev-1.13", ["CHAT-1"]))
        self.assertEqual(a.probability, 0.97)
        url, body = post.call_args[0]
        self.assertEqual(url, reader.DECISIONS_URL)
        self.assertEqual(body["questions"]["answer"]["type"], "noul")
        self.assertEqual([d["id"] for d in body["state"]["documents"]], ["CHAT-1"])  # only the question's docs

    def test_jev_low_probability_is_no(self):
        self.assertEqual(self.run_with(jev(0.03))[0].value, "no")

    def test_jev_middle_is_unknown(self):
        a = self.run_with(jev(0.6))[0]
        self.assertEqual((a.value, a.evidence), ("unknown", []))

    @mock.patch.dict(os.environ, {"TM_READER_CACHE": "0"})  # same question twice: no cache, or it returns the first
    def test_jev_rounding_is_stable(self):
        self.assertEqual(self.run_with(jev(0.8951))[0].value, "yes")  # rounds to 0.90
        self.assertEqual(self.run_with(jev(0.8949))[0].value, "unknown")

    def test_jev_unreadable_answer_is_unknown(self):
        for bad in ({}, {"answers": {}}, {"answers": {"answer": {"noul": "high"}}}, {"answers": {"answer": 1.7}}):
            self.assertEqual(self.run_with(bad)[0].value, "unknown", bad)

    # --- tier 2: chat model, the quote must really be in a document
    def test_chat_yes_with_real_quote(self):
        a, post = self.run_with(chat({"answer": "yes", "quote": "the money I got this week is for my cousin's friends",
                                      "evidence": ["CHAT-1"]}), tier=2)
        self.assertEqual((a.value, a.model, a.evidence), ("yes", "openai/gpt-4.1-mini", ["CHAT-1"]))
        url, body = post.call_args[0]
        self.assertEqual((url, body["temperature"], body["seed"]), (reader.CHAT_URL, 0, reader.SEED))

    def test_chat_yes_with_made_up_quote_is_unknown(self):
        a = self.run_with(chat({"answer": "yes", "quote": "I launder money for a gang", "evidence": ["CHAT-1"]}),
                          tier=2)[0]
        self.assertEqual((a.value, a.quote, a.evidence), ("unknown", "", []))

    def test_chat_no_without_quote_is_allowed(self):
        a = self.run_with(chat({"answer": "no", "quote": "", "evidence": []}), tier=2)[0]
        self.assertEqual((a.value, a.evidence), ("no", ["CHAT-1"]))

    def test_chat_evidence_outside_the_question_is_dropped(self):
        a = self.run_with(chat({"answer": "yes", "quote": "pass it on to them", "evidence": ["NOTE-1", "FAKE-9"]}),
                          tier=2)[0]
        self.assertEqual(a.evidence, ["CHAT-1"])

    def test_chat_broken_json_is_unknown(self):
        for bad in (chat("not json"), chat({"answer": "maybe"}), {"choices": []}, {}):
            self.assertEqual(self.run_with(bad, tier=2)[0].value, "unknown", bad)

    def test_chat_json_in_code_fence_is_read(self):
        fenced = '```json\n{"answer": "yes", "quote": "pass it on to them", "evidence": ["CHAT-1"]}\n```'
        self.assertEqual(self.run_with(chat(fenced), tier=2)[0].value, "yes")

    # --- safety
    def test_no_key_is_unknown_without_calling(self):
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            a, post = self.run_with(jev(0.99))
        self.assertEqual(a.value, "unknown")
        post.assert_not_called()

    def test_network_error_is_unknown(self):
        with mock.patch.object(reader, "_post", side_effect=RuntimeError("down")):
            self.assertEqual(reader.ask(question(), bundle(), 1).value, "unknown")

    def test_unknown_documents_are_unknown_without_calling(self):
        a, post = self.run_with(jev(0.99), q=question(doc_ids=("NOPE-1",)))
        self.assertEqual(a.value, "unknown")
        post.assert_not_called()

    def test_tier_beyond_max_is_unknown(self):
        self.assertEqual(self.run_with(jev(0.99), tier=3)[0].value, "unknown")

    # --- reproducibility: the second identical question comes from the cache
    def test_cache_reuses_the_answer(self):
        first, post1 = self.run_with(jev(0.97))
        second, post2 = self.run_with(jev(0.01))  # a different live answer would be ignored
        post2.assert_not_called()
        self.assertEqual((first.value, second.value, second.cached), ("yes", "yes", True))

    def test_cache_off_calls_again(self):
        with mock.patch.dict(os.environ, {"TM_READER_CACHE": "0"}):
            self.run_with(jev(0.97))
            _, post = self.run_with(jev(0.97))
        post.assert_called_once()

    # --- the pipeline turns a reader "yes" into a soft signal
    def test_yes_becomes_soft_signal(self):
        a = self.run_with(jev(0.97))[0]
        sig = _answer_to_signal(question(), a.value)
        self.assertEqual((sig.code, sig.strength), ("ESC_ACCOUNT_MISUSE", "soft"))
        self.assertIn("probability", vars(a))  # reaches the trace via vars(answer)


if __name__ == "__main__":
    unittest.main()
