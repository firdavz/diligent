# Andrei — decisions and context

Newest last. Each entry: the decision, why, and what would make us revisit it.
Teammates: keep your own notes in a folder named after you, like this one.

## D1 — Track 1 (transaction monitoring), not Track 2 (sanctions screening)
- **Why:** team preference; the brief, data and scoring are fully known; four institutions split naturally across four people.
- **Trade-off accepted:** Track 1 ships with no answers, so we must build our own answer key (D7). Track 2 had 50 practice labels and a more algorithmic policy.

## D2 — The model reads, code decides
- Deterministic rules produce every verdict and reason code. The model only answers narrow questions about
  prose documents (support chats, contact notes, letters, emails): `yes` / `no` / `unknown`, with cited IDs.
- **Why:** 20% of the score is reproducibility across five runs, and the organisers said a bank would rather take
  a model that's 90% accurate but 99.9% reproducible and explainable than the reverse. Rules are reproducible
  and explainable by construction; a model choosing verdicts is neither.
- **Revisit if:** rules can't cover a case shape and the model's verdicts prove stable across runs.

## D3 — Split by what a module decides (red flags vs explainers), not by institution
- Per alert, an analyst asks two questions: *is there a red flag?* and *does the evidence explain the activity?*
  Red flags → `ESCALATE`; fully explained and no red flag → `CLOSE`; otherwise → `RFI` saying what to ask for.
- One module produces red-flag signals, another produces explainer signals, a small engine combines them.
- **Why:** the two modules share nothing but the contract, so two people build them in parallel; the safety rules
  live in one place (the engine); the same code serves all four institutions because thresholds come from policy.

## D4 — Thresholds come from each institution's `POLICY.md` at runtime
- Limits differ (TM03 is just under £10,000 at the bank, under £1,000 at the e-money firm; TM01 is 3× for
  individuals vs 2× for businesses; the payments and FX firm needs an invoice for ≥ £10,000 to a third party).
- Parse them, or keep one table per institution keyed by the folder name — never hard-code one institution's number
  in shared code.

## D5 — Safety rules (non-negotiable, enforced in the decision engine)
1. An `unknown` answer is never treated as `yes`. Unknown never leads to `CLOSE`.
2. `CLOSE` only when **every** alert in the case is explained and **no** red flag fires.
3. A `CLOSE` may not rest only on model answers ("soft" signals): at least one "hard" signal from structured data
   (amount/payee/date match, register record, document field) must support it.
4. The worst alert decides the case: any `ESCALATE` → `ESCALATE`; else any `RFI` → `RFI`; else `CLOSE`.
5. Once there's suspicion, `ESCALATE`, never `RFI` (tipping-off). When torn between the two, `ESCALATE`
   (cheaper on the cost table too: 2 vs 3).
- **Why:** a wrongful close costs 10 vs 3 for an unnecessary escalation; break-even confidence for `CLOSE` is ~77%.
  The organisers said it in person: "a wrong decision is worse than no decision".

## D6 — Model: Grok via OpenRouter, temperature 0, fixed seed, on-disk cache
- The rules allow models **only** through OpenRouter (`OPENROUTER_API_KEY`); judges test with their own key,
  so we must use a Grok model **listed on OpenRouter** (`x-ai/grok-…`). Pick the cheapest one that reads documents well.
- Cache answers in `system/cache/`, keyed by a hash of (model, prompt). Writing inside `system/` is allowed.
- **Open:** whether the Grok credits from Discord work through OpenRouter (bring-your-own-key) — ask on Discord.
- **Open:** whether a pre-filled cache looks odd to the judges, who rerun on the development cases to check our
  outputs came from the system — ask before relying on it.

## D7 — Tuning without labels: label by case shape
- Grouping cases by (rules fired + unusual document types on file) gives ~30 shapes per institution, ~125 in all,
  covering all 4,000 cases. Label 1–2 cases per shape (3–4 for big or mixed shapes), and note what separates
  the closable variant from the trap. That difference is the rule to write.
- A larger Grok model may draft labels for humans to confirm (faster). Drafts and labels live in `eval/` only.
- Check disputed cases with the Track 1 organisers or the judges in the room — they hold the true labels.

## D8 — Rules key on content, never on case shape
- "Has a vehicle sale receipt" is not a rule. "The receipt's amount and date match the cash deposit and the customer
  is the seller" is. The unseen set is partly real and may be worded differently; trap variants likely share
  document types with the closable ones.

## D9 — Nothing from development cases goes into `system/`
- No case IDs, customer names, amounts, document IDs or verdicts in code or prompts (a competition rule).
- Labels, drafts and the case viewer live in `eval/`, which `system/` never reads. The dataset is git-ignored.
  **Update (team decision):** the 226 hand labels are pushed to `eval/labels/` so everyone can score, accepting that the
  answer key is public.

## D10 — Standard library only
- Python 3 stdlib (`json`, `urllib.request`, `concurrent.futures`, `hashlib`, `re`, `dataclasses`). No `pip install`.
  The demo screen may use anything — it isn't part of the scored system.

## D11 — Demo shows reproducibility and the evidence trail
- Judges want something visual. Per case: verdict, the rule path that led to it, every cited document (clickable to
  its text), and a "same in all 5 runs" tick. Headline numbers: wrongful closes, share of closable cases closed,
  cost per case, 5-run agreement.

## D12 — Keep the escalating system: tiers escalate the *reader*, not the decision
- Our first idea was three layers (cheap model → fast model → big model) each able to decide. Kept the ladder, changed
  what climbs it: tier 0 rules → tier 1 fast Grok → tier 2 big Grok. Each tier only answers the open yes/no questions;
  one rulebook decides at every tier. A case stops at the first tier that settles it. See `ARCHITECTURE.md`.
- Escalation triggers: an alert neither explained nor red-flagged by hard data; any would-be `CLOSE` that rests on a
  model answer; `unknown` or unquoted answers; model contradicting hard data; `RFI` vs `ESCALATE` hinging on a chat.
- Hard red flags end at tier 0 (no model spend). Tier 2 is capped per run by a deterministic risk ranking.
- **Why:** keeps reproducibility and the evidence trail (rule → signal → quote → ID) while spending the expensive model
  only where a wrong answer costs 10.

## D13 — Models (from OpenRouter's model list, 21 Nov)
- Tier 1: `x-ai/grok-4.3` — cheapest Grok listed ($1.25 in / $2.50 out per M tokens, 1M context; supports `seed`,
  `temperature`, `structured_outputs`). ~3k tokens in, ~200 out ≈ $0.004 per call.
- Tier 2: `x-ai/grok-4.7` ($2 / $6 per M), low reasoning effort, capped at ~25% of cases.
  Rough total for 200 cases: ~$2–3 — under the $4 limit, but D must measure it.
- **Not Jev.** `typesafe/jev-1.13` returns 404 on OpenRouter and isn't in the public model list; the listed
  `typesafe/jev-router` picks a different model and reasoning effort per request with variable pricing, which breaks
  run-to-run reproducibility and makes the cost unpredictable. Judges run with their own key, so an unlisted model may
  simply fail. Revisit only if a fixed, publicly listed Jev version appears and beats Grok on our labels.

## D14 — OpenRouter key live (shared with the team privately)
- Andrei's key works: $50 credit limit on the key, so a runaway loop can't overspend. Shared by private message only;
  never in the repo (`.env` is git-ignored). Rotate it after the event.
- Test: `x-ai/grok-4.3`, temperature 0, seed 7, `response_format: json_object` -> valid JSON, $0.0006 per tiny call.
- **Grok 4.3 reasons by default** (163 hidden reasoning tokens for a trivial reply). For tier 1, cap or disable
  reasoning (`reasoning: {"effort": "low"}` or `{"enabled": false}` — Fedya to test which the model accepts): cheaper and
  less run-to-run variation. Ask for `usage: {"include": true}` to log real cost per call.

## D15 — Audit trail and reproducibility are first-class outputs
- Judges care most about reproducibility and explainability, and about **following each institution's SOP**, not a
  generic view of risk. So every decision now carries, in `system/traces/<institution>.jsonl`:
  - per alert: its path through the rulebook (red flag / explained / partial / fallback / SOP invoice rule), the deciding
    signals with their facts and evidence, and **the SOP clauses it rests on, quoted verbatim from that institution's
    POLICY.md** (the rule that fired, the verdict definition, and any policy setting used: own accounts, internal list,
    invoice rule, higher-risk countries);
  - fingerprints: `input_fp` (everything the case may depend on), `policy_fp` (POLICY.md), `code_fp` (the system's own
    source), `decision_fp` (the output row). Same input + policy + code ⇒ same decision_fp.
- `system/traces/<institution>.manifest.json` per run: code/policy fingerprints, models, `output_fp` of the whole file,
  verdict and path counts. Two runs are identical iff their `output_fp` match.
- `python3 eval/audit.py <case_id>` prints one case's trail for the demo.
- Verified: two back-to-back bank runs give the same `output_fp`.

## D16 — Jev: real, but not on the endpoint the rules allow (superseded by D18: organisers allow it)
- `typesafe/jev-1.13` exists on OpenRouter but is a **decisions model**: it answers only on `/api/alpha/decisions`, not
  `/api/v1/chat/completions` ("cannot be used with the chat/completions endpoint"). The rules allow models **only**
  through the chat-completions endpoint. `typesafe/jev-router` is on chat completions but routes each request to a
  different model with variable price, which breaks reproducibility.
- So Jev stays out of `system/` unless the organisers confirm the decisions endpoint is allowed. Andrei is sending a paper
  on it; revisit then.

## D17 — Reader models: OpenAI without reasoning beats Grok on reproducibility (recommendation for Fedya)
- Any OpenAI model via OpenRouter chat completions is allowed by the rules (unlike Jev, D16).
- Test (21 Nov): one real yes/no question about a support chat, 5 identical calls per model, temperature 0, seed 7,
  JSON output:

  | Model | Identical outputs | Answer | Cost/call | Time |
  |---|---|---|---|---|
  | `openai/gpt-4o-mini-2024-07-18` (date-pinned) | 5/5 | yes | $0.00005 | 0.9s |
  | `openai/gpt-4.1-mini` | 5/5 | yes | $0.00013 | 0.8s |
  | `openai/gpt-4.1-nano` | 5/5 | yes | $0.00003 | 0.7s |
  | `x-ai/grok-4.3` (reasoning low) | 2 distinct of 5 | yes | $0.00112 | 3.8s |

- Grok reasons before answering, so its output text varies run to run; non-reasoning OpenAI models were byte-identical,
  10–35× cheaper, 4× faster.
- **Recommendation:** tier 1 `openai/gpt-4.1-mini` or the pinned `openai/gpt-4o-mini-2024-07-18` (a pinned snapshot can't
  change before the judges' runs); tier 2 a larger non-reasoning OpenAI model (e.g. `openai/gpt-4.1`). Grok for the sponsor
  story outside the scored path, or tier 2 only if a 5-run test shows it stable. The answer cache keeps repeat runs
  identical whatever the model. `system/tm/reader.py` `TIER_MODELS` is Fedya's to change. Supersedes the model choice in D13.

## D18 — Organisers: any OpenRouter endpoint is allowed → decision models are in. Recommend Jev 1.13 for the reader
- The organisers said to ignore the chat-completions-only wording: anything through OpenRouter (same `OPENROUTER_API_KEY`)
  is allowed. This reverses D16.
- **Decisions endpoint** `POST https://openrouter.ai/api/alpha/decisions` (alpha; shape may change):
  `{"model": ..., "questions": {<id>: {"type": "noul"|"choice"|"score"|"box", "instructions": ..., "criteria": {...}}},
  "state": <string | object | array>}` → `{"answers": {<id>: {"type": "noul", "noul": <probability of true>}}, "usage": {...}}`.
  Typed questions in, one typed answer with its probability out. That is exactly our reader's job (B and C ask yes/no
  questions; the rulebook decides), and the probability gives the audit trail a confidence per answer.
  Docs: https://openrouter.ai/docs/client-sdks/python/sdks/decisions/README.md
- Test (21 Nov), 5 identical calls per model on two support chats (one should be yes, one no):

  | Model | Pinned snapshot | "yes" chat | "no" chat | Identical? | Cost/call | Time |
  |---|---|---|---|---|---|---|
  | `typesafe/jev-1.13` | `jev-1.13-20260917` | 0.98 ×5 | 0.02 ×5 | **5/5 byte-identical** | ~$0.00002 | 0.2s |
  | `perplexity/pplx-decider-v1.3:free` | `-20261112` | 0.99906–0.99917 | 0.00056–0.00066 | values drift in the 4th decimal (same verdict after a threshold) | $0 (free tier, rate-limited) | 0.4s |
  | `perplexity/pplx-decider-v1.3` (paid) | — | — | — | 404 "No endpoints found" — only `:free` exists | — | — |

- **Recommendation for Fedya:** tier 1 = `typesafe/jev-1.13` on the decisions endpoint. Byte-identical across runs,
  pinned snapshot, cheapest and fastest of everything tested, and returns a probability. Threshold it in code
  (e.g. ≥ 0.9 → yes, ≤ 0.1 → no, else unknown → climbs to tier 2), and record the probability in the trace.
  Tier 2 = `openai/gpt-4.1-mini` or the pinned `gpt-4o-mini-2024-07-18` on chat completions (D17), for questions Jev
  leaves unknown. pplx-decider `:free` as a fallback only: free-tier rate limits are a risk when the judges run 800 cases ×5.
- Cache every answer as before; round probabilities (e.g. to 2 dp) before thresholding so float drift can't flip anything.

## D19 — The SOP is the source of truth
- Each institution's `POLICY.md` decides. Labels, the blind model's opinions, our own judgement and the code all yield
  to it. When a case looks doubtful, find the clause first; ask the organisers only where two clauses genuinely pull apart.
- Applied (21 Nov): 44 of the 50 doubtful labels are settled by a clause, now `confidence: high` with the clause quoted in
  `sop_basis`:
  - the own-account clause (no document showing the customer holds the account → RFI);
  - the internal-list clause (nothing settles it and nothing else concerning → RFI);
  - "no suspicion yet" → RFI, not ESCALATE;
  - "signs of crime" → ESCALATE;
  - the reason-code table.
- The last 6 are settled by reasoning through the clauses too (`sop_basis` on each):
  - group trip with no booking → RFI (CLOSE needs the activity to fit what the institution knows, and a *documented*
    collection);
  - freelancer studio with no payment file → RFI_BUSINESS_RECORDS (payees in undeclared countries, so it doesn't fit the
    profile);
  - re-deposited cash → CLOSE REFUND_OF_EARLIER_PAYMENT (the bank's own history shows the identical withdrawal, the chat
    explains its return; ~80% confident, so worth a confirmation from Ahmad but not a blocker).
- No new SOPs at test time: the unseen cases come "under the same policies" with the same files, and the system reads
  each folder's POLICY.md at run time anyway.
- Rules and code follow the same order: SOP clause → code. The audit trail quotes the clause (D15).

## D20 — OpenRouter credit is the constraint, not the key limit
- The team key has a $50 cap, but the account behind it holds **$5**; $4.06 is spent (21 Nov 13:40), almost all on the
  blind second-opinion labelling. Running 7 labelling jobs at once also hit 429 rate limits. 266 of 411 blind labels came
  back unusable (402 Payment Required, 429 Too Many Requests).
- Usable blind labels: ~145. They confirmed 67 of 69 team labels and found 3 shape conflicts (all settled by the SOP or
  logged as rule gaps on the review desk) and one open question: does the own-account clause apply to a payments and FX
  client's own funding account (PX-CS123336)?
- **Keep the remaining credit for the reader** (Jev costs ~$0.00002 a call). More blind labelling needs a top-up first, and
  then one job at a time with ≤ 4 workers.

## D21 — BinEval: "ask, don't judge" is our design, with a published method behind it
- Paper: Cho et al., *Ask, Don't Judge: Binary Questions for Interpretable LLM Evaluation and Self-Improvement*
  (BinEval), https://arxiv.org/abs/2606.27226. It breaks a judgement into atomic yes/no questions, has a model answer
  each independently, and combines the answers with fixed rules. That beats holistic model judges on accuracy, avoids
  their inflated scores, and gives question-level feedback to improve the questions.
- Mapping to our system:

  | BinEval | Ours | Criterion |
  |---|---|---|
  | Criteria → atomic binary questions | Each institution's **SOP** → yes/no questions per alert ("Does a document show the customer holds this account?", "Was the listed person still a PSC on the payment date?") | Explainability |
  | A model answers each question independently | **Jev 1.13** typed questions (`noul`/`choice`) with a probability, cached; code answers what is arithmetic (amount to the penny, dates, thresholds) | Reproducibility |
  | Fixed aggregation into a score | The **rulebook** (`decide.py`): red flag → ESCALATE; hard evidence on every alert → CLOSE; else RFI. The model never picks a verdict | Determinism |
  | Question-level feedback improves prompts | Labels show **which question** gets a case wrong; fix that question, keep the trail of why | Creativity, self-improvement |

- **Auditability:** each decision's trail lists every question, its answer (and Jev's probability), the document read and
  the SOP clause, replayable from the fingerprints. Viewer: the Decision Audit Trail artifact (`andrei/audit-viewer/`,
  built by `python3 eval/audit_page.py <out.html> <runs_dir>`).
- **Pitch line:** "We don't ask an AI to judge a case. We turn each institution's SOP into yes/no questions, answer them
  with a pinned decision model, and let a fixed rulebook decide: reproducible and audit-ready down to the clause."
- **Verified 21 Nov:** 5 runs × 4 institutions (4,000 cases) → the same output fingerprint every time.

## D22 — Model bake-off on labelled cases: pplx-decider wins on accuracy, Jev on byte-identical output
- `eval/model_bakeoff.py`: one SOP yes/no question per case ("does the evidence on file explain all the activity the
  alerts raised, so the case can close?"), 40 labelled cases (10 per institution, half closable), each asked twice.
  The model sees the case file and the institution's POLICY.md, never our label. Total cost ~$0.07.

  | Model | Best threshold | Right | Wrongful closes | Closable closed | Verdict flips between runs | Cost (80 calls) |
  |---|---|---|---|---|---|---|
  | `perplexity/pplx-decider-v1.3:free` | ≥ 0.7 | **40/40** | **0** | **20/20** | 0 (probabilities drift in the 3rd decimal) | $0 |
  | `typesafe/jev-1.13` | ≥ 0.5 | 33/40 | 0 | 13/20 | 0 (identical to 2 dp on 17/40) | $0.014 |
  | `openai/gpt-4.1-mini` (chat) | ≥ 0.9 | 32/40 | **7** | 19/20 | 2 dp identical 38/40 | $0.055 |

- Jev is cautious: it never says ≥ 0.9 on this holistic question, but separates the classes (closable 0.5–0.89, not
  closable ≈ 0.09). OpenAI says "yes" too easily, the expensive mistake. pplx-decider is accurate and stable after a
  threshold.
- `perplexity/pplx-decider-v1.1-27b` returns "No endpoints found" on OpenRouter, paid and free.
- **Recommendation for Fedya:** a question the model answers goes to pplx-decider v1.3, with Jev as the fallback when the
  free tier is rate-limited or down; round to 2 dp, cache, threshold in code (≥ 0.7 yes, ≤ 0.3 no, else unknown).
  Caveats: 40 cases only; one holistic question, where the design is atomic questions (BinEval, D21), so re-test on those;
  the `:free` tier may be rate-limited when the judges run 800 cases × 5. Keep cache plus fallback so a refusal can
  never stop a run. Data: `eval/drafts/bakeoff.json`.

## D23 — Bake-off on all 226 labelled cases: pplx-decider confirmed
- Same SOP close question as D22, every labelled case, each asked twice (Jev ~$0.08, pplx free):

  | Model | Threshold | Right | Wrongful closes | Closable closed | Verdict flips between runs |
  |---|---|---|---|---|---|
  | `pplx-decider-v1.3:free` | ≥ 0.9 | 210/226 | **0** | 90/106 | 0 |
  | `pplx-decider-v1.3:free` | ≥ 0.7 | **222/226** | 1 | **103/106** | 0 |
  | `jev-1.13` | ≥ 0.5 | 189/226 | 3 | 72/106 | 4 |
  | `jev-1.13` | ≥ 0.9 | 122/226 | 0 | 2/106 | 2 |

- pplx-decider at ≥ 0.7 is perfect on bank (58/58), e-money (53/53) and investment (60/60). All 4 misses are payments and
  FX (3 closable cases scored 0.57–0.67, 1 wrongful close at 0.72 on PX-CS123153), which is where our own open question
  sits (D20).
- Jev at ≥ 0.9 almost never says yes (2 of 106 closable). As a tier-1 yes/no reader with a 0.90 cut-off it will mostly
  return "unknown". **Fedya's reader (merged) uses Jev at tier 1: recommend switching tier 1 to pplx-decider v1.3 with
  Jev as fallback**, or lowering Jev's yes cut-off only after a test on atomic questions.
- First calibration of the full pplx labeller (verdict then code, SOP-worded choice questions, `eval/pplx_label.py`):
  bank verdict agrees 56/58, code 49/58, would-be wrongful closes 0. Others running.

## D24 — pplx-decider as a full labeller: 95% verdict agreement; trust it only at ≥ 0.7
- `eval/pplx_label.py` (verdict, then reason code, as choice questions worded from POLICY.md and the code table) on all
  226 human-labelled cases:

  | Institution | Verdict agrees | Code agrees | Would-be wrongful closes |
  |---|---|---|---|
  | Bank | 56/58 | 49/58 | 0 |
  | E-money | 53/53 | 44/53 | 0 |
  | Investment | 55/60 | 42/60 | 1 (IV-CS791635, p 0.52) |
  | Payments and FX | 51/55 | 42/55 | 1 (PX-CS123153, p 0.59) |
  | **All** | **215/226 (95%)** | **177/226 (78%)** | 2, both below 0.7 |

- Rule for model labels: use a model label as a silver label only when its verdict probability is ≥ 0.7; below that it
  goes to the review desk. Silver labels live in `eval/labels_model/` and are scored separately from the human labels.
- New cases: 2 per case shape running now (~250), then 3 more per shape (~375). Free tier, cached.

## Open questions
- [ ] How is Track 1 submitted (repo link? portal upload?) — confirm with organisers before 16:30.
- [x] Model access: Andrei's OpenRouter key ($50 limit) — see D14.
- [ ] Is a pre-filled model cache acceptable? (D6)
- [x] OpenRouter's `/api/alpha/decisions` endpoint is allowed — organisers confirmed (D18).
- [ ] Owners for A/B/C/D (see `TEAM.md`).
- [ ] Ask Ahmad: does the own-account clause cover a payments and FX client's own funding account? (PX-CS123336; decides ~210 cases)
- [ ] Measure real tier-1/tier-2 cost and latency on 20 cases; set the tier-2 cap (D13).
