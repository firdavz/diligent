# Clotilde (B) — explainers: work plan

**Owns:** `system/tm/explainers.py` — every `CLOSE` code (except `LIST_MATCH_DIFFERENT_PARTY`, which is Lorenzo's) and the
`RFI` twins. **Also responsible for:** E-money (labels, its `POLICY.md`, its score after every run).
**Done when:** each `CLOSE` code fires on the labelled closable cases, and only those. **Wrongful closes stay at 0.**

Today `CHECKS = []`: every close in `output/` comes from Lorenzo's list-match check (bank 38, e-money 45, payments 22,
investment 0). Everything else falls back to RFI/ESCALATE, so explainers are where the score is.

## How an explainer fits in (contract recap)
- `explainers(b) -> (signals, questions)`. One function per check, `(b) -> (signals, questions)`, listed in `CHECKS`.
- `Signal(kind="explains", code=<CLOSE code>, strength="hard")` only when **structured data** proves it: amount to the
  penny, payee/payer, date order, holder name = customer. Emitted **per alert** (never `ALL_ALERTS` for an explanation:
  it would explain alerts it doesn't cover).
- `Signal(kind="partial", code=<RFI code>)` when the story is plausible but one document is missing. `facts` must say
  exactly what to ask for.
- `Question` when only prose (chat, contact note, letter) can settle it; a "yes" comes back **soft** and can't close alone.
- `facts` = one sentence with this case's names, amounts, dates and document IDs (reasons are 40% of the case score).
- Never: dev-case data in `system/`, document-type presence as the rule, hard-coded thresholds, reviews as an explanation
  on their own.

## Phase 0 — setup ✅
- Dataset stays where it was unzipped (no copy). Point the eval scripts at it with `TM_DATA`.
  On Windows `python3` doesn't exist and `system/run` is a sh script, so (PowerShell):
  `$env:TM_DATA = "<path to unzipped>\hackathon\institutions"`,
  `python system/main.py "$env:TM_DATA\emoney" output/emoney.jsonl`, `python eval/shapes.py emoney`,
  `python eval/view.py <case_id>`, `python eval/score.py emoney`. Set `$env:PYTHONIOENCODING = "utf-8"` if £ breaks.
- Baseline reproduced: E-money 1,000 cases in 1 s → 45 CLOSE (all list matches), 349 RFI, 606 ESCALATE.
- E-money POLICY read: TM03 = ≥4 cash top-ups £800–£999.99 in 10 days; TM05 = £1,000 individual / £5,000 business;
  own-account 5× rule and the own-name-account document rule are the same wording as the bank.

## E-money shapes → which check (hypotheses, confirm while labelling)
~14 of the 30 shapes (~530 cases) are explainer work; the rest are Lorenzo's or have no documents (fallback).

| Shape (rules + scenario docs) | Cases | Likely check | Note |
|---|---|---|---|
| TM02 + bank_statement | 46 | own_account | statement holder = customer? |
| TM01 + bank_statement | 42 | own_account | 5× split: `measured.multiple` |
| TM01+TM07 + bank_statement, reverification_record | 34 | returning_customer / own_account | |
| TM07 + bank_statement, reverification_record | 12 | returning_customer | |
| TM03 + takings_book | 46 | business_records | table: date, takings, "cash topped up" = each alerted top-up |
| TM05 + advert, sale_receipt | 46 | documented_event (sale) | seller = customer, amount/date vs top-up |
| TM01 + settlement_letter | 45 | documented_event | |
| TM01+TM07 + insurer_letter (and TM07 alone, 2) | 46 | documented_event | claim ref + amount |
| TM02 + deposit_return_letter, holding_deposit_receipt | 45 | documented_event or refund | amounts only in **prose**, payer = letter sender |
| TM02+TM04 + booking_confirmation | 45 | collection_documented | |
| TM06 + hospital_invoice, support_chat | 45 | invoice_matches | |
| TM06 / TM01+TM06 + venue_email | 45 | refund | refund = earlier outgoing booking payment |
| TM01+TM02 + support_chat | 41 | ? mixed | label 3–4: refund story vs red flag |
| No scenario docs (TM01, TM02, TM02+TM04, TM01+TM07, TM07) | ~167 | fallback / within_profile? | check if any are closable |
| TM22 (all), fraud report, staff note, device export, TM06 chats | rest | Lorenzo | |

**Seen in the data:** several documents carry the amount only in prose (a letter saying it is "returning £X to you today"), and
some in tables (takings book), so matching must read `util.amounts(doc.text)` and table rows, not only `doc.fields`.

## Phase 1 — label E-money ✅ done by Andrei
53 labels in `eval/labels/emoney.jsonl` and the per-shape work list in `andrei/emoney-findings.md` (it confirms the
shape map above and adds the exact "close when" conditions). Labels for all four institutions are now in the repo
(team decision, D9 update). Original checklist, kept for reference:
- [ ] `python eval/shapes.py emoney` → 30 shapes; label 1–2 per shape, 3–4 for big/mixed ones (`python eval/view.py <id>`).
- [ ] Write `eval/labels/emoney.jsonl` (`case_id, verdict, reason_code, key_evidence, note`). `note` = what decided it.
- [ ] Write `clotilde/emoney-findings.md` like `andrei/bank-findings.md`: per shape, "close when (all must hold)", code,
      missing-document twin → RFI, contradiction twin → ESCALATE (hand those to Lorenzo). No case IDs, names or amounts.

## Phase 2 — build the explainers (13:00–14:30), in order of value
Start with shared helpers (in `explainers.py`, not `util.py`, unless agreed):
- find an alert's transactions; match a document amount field / table row to a transaction **to the penny**;
- date order (document dated on/before the credit, or N days after for banking cash);
- party match via `util.same_name` (holder = customer, payer = firm in the letter, seller = customer);
- Markdown tables: `red_flags._tables` already does it — ask Lorenzo before moving it to `util.py`.

Then one check at a time, each with its RFI twin, scored after each one:

| # | Check → code | Close when (all hold) | RFI twin | Bank findings |
|---|---|---|---|---|
| 1 | `own_account` → `OWN_ACCOUNT` | statements **in the customer's name** for source and destination; TM01 `measured.multiple` < `policy["own_account_rfi_multiple"]` | multiple ≥ 5× → `RFI_UPDATED_PROFILE`; own-name account but no statement → `RFI_SOURCE_OF_FUNDS` | #11–13 |
| 2 | `documented_event` → `DOCUMENTED_EVENT` | a document's amount = the credit, dated on/before it, party matches (sale receipt seller = customer, solicitor client account + estate ref, insurer + claim ref) | same credit, no document → `RFI_SOURCE_OF_FUNDS` | #2, #3, #9 |
| 3 | `refund` → `REFUND_OF_EARLIER_PAYMENT` | the credit/cash = an earlier outgoing payment or cash withdrawal of exactly that amount (same counterparty for refunds) | chat tells another story with no document → `RFI_SOURCE_OF_FUNDS` | #1, #10 |
| 4 | `invoice_matches` → `INVOICE_MATCHES` | invoice/contract amount = the payment, payee = invoice issuer; loan principal = loan advance credit. **Payments and FX:** must cite `held_payment_id` or `decide` blocks the close | same pattern, no invoice → `RFI_PURPOSE_DOCUMENTS` | #7, #8 |
| 5 | `business_records` → `BUSINESS_RECORDS_RECONCILE` | every alerted cash deposit has a record row with the same total, banked 1–2 days after the event/emptying | records missing → `RFI_BUSINESS_RECORDS` | #4, #5 (TM03) |
| 6 | `collection_documented` → `COLLECTION_DOCUMENTED` | every payer is on the list, each pays the per-person price, outgoing = total to the stated account/ref | same pattern, no confirmation → `RFI_PURPOSE_DOCUMENTS` | #6 (TM02+TM04) |
| 7 | `returning_customer` → `RETURNING_CUSTOMER` | identity re-verified on file + own-name source for the incoming money (TM07) | no re-verification → RFI | #13–14 |
| 8 | `group_company` → `GROUP_COMPANY` | register shows the counterparty shares a parent/owner with the customer | — | labels needed (payments/investment) |
| 9 | `third_party_documented` → `THIRD_PARTY_DOCUMENTED` | gift letter / joint holder document names the payer and the amount (TM08) | no document → RFI (not ESCALATE — see Lorenzo's note on `FALLBACK["TM08"]`) | investment labels |
| 10 | `within_profile` → `WITHIN_PROFILE` | once the explained credits are removed, the rest is within the declared profile | — | labels needed |

**Earlier reviews:** never an explanation on their own; they only support a matching earlier transaction (e.g. the
withdrawal in #3 was cleared by a review).

## Phase 3 — tune (14:30–15:30), freeze at 15:30
- [ ] After every change: run all four institutions, `python eval/score.py <inst>`; **wrongful closes up anywhere → don't push**.
- [ ] Read misses in `system/traces/<inst>.jsonl` (each alert's path: `explained` / `partial` / `fallback`).
- [ ] `system/tests/test_explainers.py` with fake `CaseBundle`s (invented data only), like `test_red_flags.py`.
- [ ] Check reasons: names, amounts, doc IDs present; RFI says exactly what to ask.

## Open points to agree with the team
- **TM01 coverage (Andrei):** is a TM01 explained when the documented credit is the one that broke the profile, or only when
  the unexplained remainder is back within the multiple? Decide on the labels.
- **Prose check before closing (Andrei/Fedya):** who raises the "does the chat contradict this close?" `Question` —
  B per check, or the pipeline? Its `if_yes` would be a red flag (Lorenzo's code).
- **Codes with no exact fit** (bank findings): re-deposited own cash → `REFUND_OF_EARLIER_PAYMENT`; "prove you hold the
  overseas account" → `RFI_SOURCE_OF_FUNDS`. Confirm with labels or the organisers.
- **Reason-code choice by document type:** the match is on content; picking which CLOSE code to report may use the
  document's type. Flag to Andrei that this doesn't break D8.
