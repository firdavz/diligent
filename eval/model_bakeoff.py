"""Compare decision models on one SOP question against our labels.   python3 eval/model_bakeoff.py [n_per_institution]

Question (BinEval-style, one atomic yes/no): "Does the evidence on file explain all the activity the alerts raised, so
the case can close under the SOP?" True when the label is CLOSE. Each model sees the case file and the SOP's verdict
definitions, never our label. Each case is asked twice to check reproducibility.

Models: Jev 1.13 and pplx-decider (OpenRouter decisions endpoint, probability of "true"), and an OpenAI chat model asked
for a JSON probability. A probability >= 0.9 counts as "close". Results print per model and save to
eval/drafts/bakeoff.json. Needs OPENROUTER_API_KEY. Costs well under $0.10 for 40 cases.
"""

import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request

from _common import INSTITUTIONS, ROOT

KEY = os.environ["OPENROUTER_API_KEY"]
DEC = "https://openrouter.ai/api/alpha/decisions"
CHAT = "https://openrouter.ai/api/v1/chat/completions"
MODELS = [("typesafe/jev-1.13", "decisions"), ("perplexity/pplx-decider-v1.3:free", "decisions"), ("openai/gpt-4.1-mini", "chat")]
INSTRUCTION = ("Under this institution's SOP, does the evidence on file explain ALL the activity the alerts raised, so the "
               "case can be CLOSED? Close only when the evidence explains every alert and nothing suggests crime.")
CRITERIA = {"true": "CLOSE: the evidence on file (documents, the customer's own records, verified facts) explains all the "
                    "activity every alert raised and it fits what the institution knows about the customer.",
            "false": "Not closable: something is unexplained (RFI: one document or answer would settle it) or there are "
                     "signs of crime (ESCALATE)."}


def post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    for wait in (3, 10, 0):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except Exception as e:  # rate limits on the free model, timeouts
            if not wait:
                return {"error": repr(e)[:200]}
            time.sleep(wait)


def ask(model, kind, case_text, policy):
    if kind == "decisions":
        j = post(DEC, {"model": model, "questions": {"close": {"type": "noul", "instructions": INSTRUCTION, "criteria": CRITERIA}},
                       "state": {"sop": policy, "case_file": case_text}})
        try:
            return round(float(j["answers"]["close"]["noul"]), 2), float(j.get("usage", {}).get("cost") or 0)
        except Exception:
            return None, 0.0
    j = post(CHAT, {"model": model, "temperature": 0, "seed": 7, "max_tokens": 50, "usage": {"include": True},
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "system", "content": "You apply a bank's SOP. Answer only with JSON {\"p_close\": <probability 0-1>}.\n\nSOP:\n" + policy},
                                 {"role": "user", "content": f"{INSTRUCTION}\nTRUE means: {CRITERIA['true']}\nFALSE means: {CRITERIA['false']}\n\nCase file:\n{case_text}"}]})
    try:
        m = re.search(r"[01](?:\.\d+)?", json.loads(j["choices"][0]["message"]["content"]).__str__())
        return round(float(m[0]), 2), float(j.get("usage", {}).get("cost") or 0)
    except Exception:
        return None, 0.0


def main(n):
    rows = []
    for inst in INSTITUTIONS:
        policy = open(os.path.join(ROOT, "data", "institutions", inst, "POLICY.md")).read()
        labels = [json.loads(line) for line in open(os.path.join(ROOT, "eval", "labels", f"{inst}.jsonl"))]
        rnd = random.Random(inst)
        close = [lab for lab in labels if lab["verdict"] == "CLOSE"]
        other = [lab for lab in labels if lab["verdict"] != "CLOSE"]
        for lab in rnd.sample(close, min(n // 2, len(close))) + rnd.sample(other, min(n - n // 2, len(other))):
            text = subprocess.run([sys.executable, os.path.join(ROOT, "eval", "view.py"), lab["case_id"]], capture_output=True, text=True).stdout
            row = {"case_id": lab["case_id"], "truth": lab["verdict"] == "CLOSE"}
            for model, kind in MODELS:
                p1, c1 = ask(model, kind, text, policy)
                p2, c2 = ask(model, kind, text, policy)
                row[model] = {"p": p1, "p_again": p2, "cost": c1 + c2}
            rows.append(row)
            print(row["case_id"], row["truth"], {m: (row[m]["p"], row[m]["p_again"]) for m, _ in MODELS}, flush=True)
    print()
    for model, _ in MODELS:
        got = [r for r in rows if r[model]["p"] is not None]
        right = sum((r[model]["p"] >= 0.9) == r["truth"] for r in got)
        wrongful = sum(r[model]["p"] >= 0.9 and not r["truth"] for r in got)
        closed = sum(r[model]["p"] >= 0.9 and r["truth"] for r in got)
        same = sum(r[model]["p"] == r[model]["p_again"] for r in got)
        cost = sum(r[model]["cost"] for r in rows)
        print(f"{model:40} answered {len(got)}/{len(rows)}  right {right}/{len(got)}  wrongful closes {wrongful}  "
              f"closable closed {closed}/{sum(r['truth'] for r in got)}  identical twice {same}/{len(got)}  cost ${cost:.4f}")
    os.makedirs(os.path.join(ROOT, "eval", "drafts"), exist_ok=True)
    json.dump(rows, open(os.path.join(ROOT, "eval", "drafts", "bakeoff.json"), "w"), indent=1)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 10)
