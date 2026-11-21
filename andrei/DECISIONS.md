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
- Labels, drafts and the case viewer live in `eval/`, which `system/` never reads. Labels and the dataset are git-ignored
  because this repo is public.

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

## Open questions
- [ ] How is Track 1 submitted (repo link? portal upload?) — confirm with organisers before 16:30.
- [x] Model access: Andrei's OpenRouter key ($50 limit) — see D14.
- [ ] Is a pre-filled model cache acceptable? (D6)
- [ ] Owners for A/B/C/D (see `TEAM.md`).
- [ ] Measure real tier-1/tier-2 cost and latency on 20 cases; set the tier-2 cap (D13).
