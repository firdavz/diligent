"""D (Fedya): answers Questions about prose documents via OpenRouter. Never picks a verdict.

Contract: ask(question, bundle, tier) -> Answer(value="yes"|"no"|"unknown", quote, evidence, tier, model).

How it answers (see andrei/DECISIONS.md D17, D18):
- Tier 1: typesafe/jev-1.13 on OpenRouter's decisions endpoint. One yes/no ("noul") question in, a probability
  that the answer is "yes" out. Rounded to 2 dp, then: >= 0.90 -> yes, <= 0.10 -> no, otherwise unknown
  (unknown climbs to tier 2). Jev gives no quote; the probability is kept on the answer for the trace.
- Tier 2: openai/gpt-4.1-mini on chat completions, JSON out: {"answer", "quote", "evidence"}. A "yes" must come
  with a quote copied word for word from one of the documents, checked in code; no valid quote -> unknown.

Safety: no key, no documents, an HTTP error, a timeout or an answer we can't read -> "unknown". Unknown never
leads to CLOSE (decide.py). We never retry with different wording, only the identical request.

Reproducibility: temperature 0, fixed seed, inputs in a fixed order, and every answer cached on disk in
system/cache/reader/, keyed by a hash of (prompt version, endpoint, request body). Set TM_READER_CACHE=0 to turn
the cache off (for the 5-run reproducibility test of the models themselves).

Only the question and the documents in question.doc_ids are sent, nothing else from the case.
Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

from .types import Answer, CaseBundle, Question

TIER_MODELS = {1: "typesafe/jev-1.13", 2: "openai/gpt-4.1-mini"}
MAX_TIER = 2

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

YES_AT = 0.90  # tier-1 probability at or above this -> "yes"
NO_AT = 0.10  # at or below this -> "no"; in between -> "unknown"
SEED = 7
TIMEOUT_S = 20  # per attempt; keeps a stuck call from eating the 30-minute run limit
ATTEMPTS = 2  # one retry of the identical request on 429 / 5xx / network error (FEDYA_BRIEF: one retry at most)
MAX_DOC_CHARS = 12000  # per document, cut deterministically
PROMPT_VERSION = "reader-v1"  # change it whenever a prompt changes, so old cached answers are not reused

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # system/
CACHE_DIR = os.path.join(HERE, "cache", "reader")
LOG_PATH = os.path.join(HERE, "traces", "reader_calls.jsonl")
_log_lock = threading.Lock()

RULES = (
    "You read bank compliance documents and answer one yes/no question about them. "
    "Use only the documents given. Do not guess and do not use outside knowledge. "
    "Answer yes only if the documents clearly say so. Answer no if they clearly do not, or say the opposite. "
    "Answer unknown if the documents are not enough to tell."
)


def enabled() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY"))


def ask(q: Question, b: CaseBundle, tier: int) -> Answer:
    model = TIER_MODELS.get(tier, "")
    docs = _docs(q, b)
    if not model or not docs or not enabled():
        return Answer(value="unknown", tier=tier, model=model or "none")
    try:
        if tier == 1:
            return _ask_decisions(q, docs, model)
        return _ask_chat(q, docs, model, tier)
    except Exception as e:  # any failure is "unknown", never a guess
        _log({"question": q.id, "tier": tier, "model": model, "error": repr(e)[:300]})
        return Answer(value="unknown", tier=tier, model=model)


# --------------------------------------------------------------------------- documents

def _docs(q: Question, b: CaseBundle) -> list[dict]:
    """The question's documents, in the question's order, without duplicates or unknown IDs."""
    out, seen = [], set()
    for doc_id in q.doc_ids:
        d = b.docs.get(doc_id)
        if d is None or doc_id in seen:
            continue
        seen.add(doc_id)
        out.append({"id": d.doc_id, "type": d.type, "title": d.title, "dated": d.dated,
                    "text": (d.text or "")[:MAX_DOC_CHARS]})
    return out


def _docs_block(docs: list[dict]) -> str:
    parts = []
    for d in docs:
        head = f"[{d['id']}] {d['title']} ({d['type']}" + (f", dated {d['dated']})" if d["dated"] else ")")
        parts.append(f"{head}\n{d['text']}")
    return "\n\n---\n\n".join(parts)


def _norm(s: str) -> str:
    """For quote checks: lower case, straight quotes, one space."""
    s = (s or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[*_`>#]", " ", s)  # Markdown marks
    return " ".join(s.lower().split())


# --------------------------------------------------------------------------- tier 1: Jev (decisions endpoint)

def _ask_decisions(q: Question, docs: list[dict], model: str) -> Answer:
    payload = {
        "model": model,
        "questions": {
            "answer": {
                "type": "noul",
                "instructions": f"{RULES}\n\nQuestion: {q.text}",
                "criteria": {
                    "true": "The documents clearly say this is so.",
                    "false": "The documents do not say this, or they say the opposite.",
                },
            }
        },
        "state": {"documents": docs},
    }
    resp, cached = _call(DECISIONS_URL, payload, q, 1)
    p = _probability(resp)
    if p is None:
        return Answer(value="unknown", tier=1, model=model)
    p = round(p, 2)
    value = "yes" if p >= YES_AT else "no" if p <= NO_AT else "unknown"
    a = Answer(value=value, quote="", evidence=[d["id"] for d in docs] if value != "unknown" else [], tier=1,
               model=model)
    a.probability = p  # extra field: pipeline copies vars(answer) into the trace; types.py stays unchanged
    a.cached = cached
    return a


def _probability(resp: dict) -> float | None:
    """Probability of 'yes' from a decisions response: {"answers": {"answer": {"type": "noul", "noul": 0.97}}}."""
    ans = (resp or {}).get("answers", {}).get("answer")
    if isinstance(ans, (int, float)) and not isinstance(ans, bool):
        val = ans
    elif isinstance(ans, dict):
        val = next((ans[k] for k in ("noul", "probability", "value", "p") if k in ans), None)
    else:
        return None
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return None
    return float(val) if 0.0 <= val <= 1.0 else None


# --------------------------------------------------------------------------- tier 2: chat model with a quote

def _ask_chat(q: Question, docs: list[dict], model: str, tier: int) -> Answer:
    system = (
        f"{RULES}\n\nReply with one JSON object and nothing else:\n"
        '{"answer": "yes" | "no" | "unknown", '
        '"quote": "the exact sentence from a document that decides it, copied word for word, or \\"\\"", '
        '"evidence": ["IDs of the documents you relied on, as written in square brackets"]}\n'
        "A yes needs a quote."
    )
    user = f"Question: {q.text}\n\nDocuments:\n\n{_docs_block(docs)}"
    payload = {
        "model": model,
        "temperature": 0,
        "seed": SEED,
        "max_tokens": 400,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    resp, cached = _call(CHAT_URL, payload, q, tier)
    try:
        content = resp["choices"][0]["message"]["content"]
        out = json.loads(_strip_fence(content))
    except (KeyError, IndexError, TypeError, ValueError):
        return Answer(value="unknown", tier=tier, model=model)

    value = str(out.get("answer", "")).strip().lower()
    if value not in ("yes", "no", "unknown"):
        return Answer(value="unknown", tier=tier, model=model)
    quote = str(out.get("quote") or "").strip()
    ids = [d["id"] for d in docs]
    quoted_in = [d["id"] for d in docs if quote and _norm(quote) in _norm(d["text"])]
    if quote and not quoted_in:
        quote = ""  # the model made it up or changed it: drop it
    if value == "yes" and not quote:
        value = "unknown"  # a yes we can't point to in the documents is not a yes
    claimed = [e for e in (out.get("evidence") or []) if isinstance(e, str) and e in ids]
    evidence = list(dict.fromkeys(quoted_in + claimed)) or (ids if value != "unknown" else [])
    a = Answer(value=value, quote=quote, evidence=evidence if value != "unknown" else [], tier=tier, model=model)
    a.cached = cached
    return a


def _strip_fence(s: str) -> str:
    s = (s or "").strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", s, re.S)
    return m.group(1) if m else s


# --------------------------------------------------------------------------- HTTP, cache, log

def _cache_key(url: str, payload: dict) -> str:
    raw = json.dumps({"v": PROMPT_VERSION, "url": url, "body": payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_on() -> bool:
    return os.environ.get("TM_READER_CACHE", "1") != "0"


def _call(url: str, payload: dict, q: Question, tier: int) -> tuple[dict, bool]:
    key = _cache_key(url, payload)
    path = os.path.join(CACHE_DIR, key[:2], key + ".json")
    if _cache_on() and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            resp = json.load(f)
        _log({"question": q.id, "tier": tier, "model": payload["model"], "cached": True})
        return resp, True

    t0 = time.time()
    resp = _post(url, payload)
    _log({"question": q.id, "tier": tier, "model": payload["model"], "cached": False,
          "seconds": round(time.time() - t0, 2), "usage": resp.get("usage")})
    if _cache_on():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(resp, f, ensure_ascii=False)
        os.replace(tmp, path)  # atomic: a parallel worker never reads half a file
    return resp, False


def _post(url: str, payload: dict) -> dict:
    """POST JSON to OpenRouter. Retries the identical request on 429, 5xx and network errors."""
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY', '')}",
        "Content-Type": "application/json",
        "X-Title": "diligent-track1-reader",
    }
    last = None
    for attempt in range(ATTEMPTS):
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code != 429 and e.code < 500:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"OpenRouter failed after {ATTEMPTS} attempts: {last!r}")


def _log(row: dict) -> None:
    try:
        with _log_lock:
            os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass  # logging must never break a run
