# Brief for Fedya: the Jev reader

You own `system/tm/reader.py`. It is still the stub that answers "unknown", so the system runs on rules alone. This brief
is what you need to build it; the implementation is yours. Ask Andrei or Lorenzo if anything here is unclear.

## The job, in one line
Answer typed questions about a case's documents with **Jev 1.13** on OpenRouter's decisions endpoint, deterministically,
and hand back an `Answer` per question. **Never pick a verdict**: the rulebook (`system/tm/decide.py`) does that.

## Already decided (don't re-litigate, see `andrei/DECISIONS.md`)
- **D18:** decision models are allowed (organisers confirmed). Tier 1 = `typesafe/jev-1.13`.
- **D17:** tier 2 = a non-reasoning OpenAI model on chat completions (`openai/gpt-4.1-mini` or the pinned
  `openai/gpt-4o-mini-2024-07-18`), only for what Jev leaves unknown.
- **D19:** the SOP decides. Question criteria quote the institution's `POLICY.md`, never our own wording of it.
- Standard library only (`urllib.request`, `json`, `hashlib`, `concurrent.futures`). No `pip install` in `system/`.

## The endpoint (tested 21 Nov, works with the team key)
`POST https://openrouter.ai/api/alpha/decisions`, header `Authorization: Bearer $OPENROUTER_API_KEY`.

```json
{"model": "typesafe/jev-1.13",
 "questions": {"<question id>": {"type": "noul",
                                 "instructions": "<the question>",
                                 "criteria": {"true": "<what a yes means>", "false": "<what a no means>"}}},
 "state": {"<any keys you like>": "<the documents' text>"}}
```
Response: `{"model": "typesafe/jev-1.13-20260917", "answers": {"<question id>": {"type": "noul", "noul": 0.98}}, "usage": {"cost": ...}}`.
`noul` is the probability of true. Other types: `choice` (criteria is an object of option → meaning), `score` (criteria is
an ordered list), `box`. Docs: https://openrouter.ai/docs/client-sdks/python/sdks/decisions/README.md (alpha: the shape
may change, so handle unexpected responses as "unknown").

Measured: the same question 5× gave **0.98 every time** for a yes-case and **0.02** for a no-case; ~$0.00002 per call;
~0.2 s. Several questions can go in one request.

## What to build
1. **`ask(question, bundle, tier)`**: build the request from `question.text`, criteria, and only the documents in
   `question.doc_ids` (their `text`), call Jev at tier 1, the OpenAI model at tier 2.
2. **Thresholds:** round the probability to 2 dp, then ≥ 0.90 → `"yes"`, ≤ 0.10 → `"no"`, anything between → `"unknown"`
   (the pipeline then climbs to tier 2). Keep the probability in the `Answer` so the audit trail can show it.
3. **Cache:** every answer on disk in `system/cache/`, keyed by a hash of (model, full request body). A cached answer is
   returned without a call. This is what makes all 5 judge runs identical.
4. **Failures are "unknown":** no key, timeout, HTTP error, unparsable body, rate limit. Never raise into the pipeline.
   One retry at most, with a short timeout, or a stuck call blows the 30-minute budget.
5. **`TIER_MODELS`:** update to the D17/D18 choice.

The pipeline already calls you: `system/tm/pipeline.py` walks the tiers and turns your yes/no into the question's
`if_yes` / `if_no` signal (marked "soft", so a model answer alone can never close a case). You don't need to touch it.

## Typed questions (the part Andrei and you agreed on)
Lorenzo already emits `Question`s from `red_flags.py` (look at the one around line 333 for the shape). Clotilde's
explainers will add more. The idea to build towards with them:
- A **`choice`** question: "Which explanation does the evidence on file give for this alert?" whose options are the
  SOP's own CLOSE codes, each option's criteria copied from the code table in `POLICY.md`, plus "none".
- A **`choice`** over the ESCALATE codes for signs of crime, plus "none".
- **`noul`** questions for prose: "Does the chat contradict the documents?", "Does the customer ask about avoiding a
  limit?"

Jev names the story; code then verifies it against the hard evidence (amounts, payees, dates) before anything closes.
If `Question` needs a `type`/`options` field for `choice`, propose the change to `types.py` in the team chat first
(it's the shared contract).

## How to check your work
```bash
export OPENROUTER_API_KEY=...            # the team key, from Discord; never commit it
system/run data/institutions/bank output/bank.jsonl && python3 eval/score.py bank
```
- **Wrongful closes must stay 0** on all four institutions.
- Run twice and compare the `output_fp=` printed at the end: they must match (cache works).
- `python3 eval/audit.py <case_id>` should list your answers under "MODEL ANSWERS" with tier, model and probability.
- The Track 1 Build Board shows your four reader checks turning green as each lands (it reads `reader.py`).

## Done when
- [ ] Reader answers questions (not the stub) — tier 1 on Jev 1.13
- [ ] Tier 2 on a non-reasoning OpenAI model
- [ ] Answers cached; two runs give the same output fingerprint
- [ ] No wrongful closes; time and cost per 200 cases logged for the README
- [ ] Then the demo screen and video (from 15:30)

Commit and push as you go (root `CLAUDE.md`): small commits on `track1-alert-closing`.
