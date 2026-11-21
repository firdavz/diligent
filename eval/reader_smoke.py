"""Live check of the reader against OpenRouter (needs OPENROUTER_API_KEY). Invented documents, no dataset needed.

Asks two questions (one should be yes, one no) 5 times each on tier 1 (Jev) and tier 2 (gpt-4.1-mini), with the
cache OFF, and prints whether every run gave the same answer. Also prints the raw Jev reply once, so we can see
the decisions endpoint's real shape.

Run from the repo root:
  Windows:      py eval\\reader_smoke.py
  Mac / Linux:  python3 eval/reader_smoke.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "system"))
os.environ["TM_READER_CACHE"] = "0"  # test the models themselves, not the cache

from tm import reader  # noqa: E402
from tm.load import parse_doc  # noqa: E402
from tm.types import CaseBundle, Question  # noqa: E402

YES_CHAT = ("# Support chat\n\n**Customer:** The money that came in this week isn't mine, it belongs to some people "
            "I met online. I just send it on to them when they tell me.\n\n**Agent:** Thank you, noted.")
NO_CHAT = ("# Support chat\n\n**Customer:** The £4,200 is my salary from Harbour Café Ltd, I work there as a "
           "manager.\n\n**Agent:** Thanks, that matches your profile.")
QUESTION = ("Does the customer say, or does the document show, that the money received or sent belongs to other "
            "people, or that someone else controls or uses the account? Answer yes only if the text says so.")


def bundle():
    docs = [parse_doc({"doc_id": i, "type": "support_chat", "title": "Support chat", "dated": "2026-09-01"}, t)
            for i, t in (("CHAT-YES", YES_CHAT), ("CHAT-NO", NO_CHAT))]
    return CaseBundle(institution="smoke", case={"case_id": "S1", "customer_id": "U1", "alert_ids": ["A1"]},
                      alerts=[], customer={}, txns={}, docs={d.doc_id: d for d in docs}, reviews=[],
                      list_entries={}, internal_list={}, policy={})


def main():
    if not reader.enabled():
        print("OPENROUTER_API_KEY is not set. Set it first, then run again.")
        return 1
    b = bundle()

    # 1. Raw Jev reply once, to see the real response shape.
    orig_post = reader._post
    raw = {}

    def spy(url, payload):
        resp = orig_post(url, payload)
        raw.setdefault(url, resp)
        return resp

    reader._post = spy
    ok = True
    for tier in (1, 2):
        for doc_id, expected in (("CHAT-YES", "yes"), ("CHAT-NO", "no")):
            q = Question(id="smoke", alert_id="A1", text=QUESTION, doc_ids=[doc_id])
            runs = [reader.ask(q, b, tier) for _ in range(5)]
            values = [a.value for a in runs]
            probs = [getattr(a, "probability", None) for a in runs]
            same = len(set(values)) == 1  # the answer is what decides; probability and quote wording may wobble
            exact = len({(a.quote, getattr(a, "probability", None)) for a in runs}) == 1
            right = values[0] == expected
            ok &= same and right
            print(f"tier {tier} {reader.TIER_MODELS[tier]:22} {doc_id:9} -> {values}"
                  + (f" p={probs}" if tier == 1 else f" quote={runs[0].quote!r}")
                  + f"  same answer 5/5: {'YES' if same else 'NO'}"
                  + ("" if exact else " (wording/probability varied; the cache keeps real runs identical)")
                  + f"  expected {expected}: {'OK' if right else 'WRONG'}")
    reader._post = orig_post

    print("\nRaw replies (first call per endpoint):")
    for url, resp in raw.items():
        print(url)
        print(json.dumps(resp, indent=2)[:600])
    print("\nCall log:", reader.LOG_PATH)
    print("ALL GOOD" if ok else "SOMETHING TO CHECK: send this output to Claude")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
