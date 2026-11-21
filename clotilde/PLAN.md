# Clotilde (B) — explainers: work plan

**Owns:** `system/tm/explainers.py` — every `CLOSE` code (except `LIST_MATCH_DIFFERENT_PARTY`, which is Lorenzo's) and the
`RFI` twins. **Also responsible for:** E-money (labels, its `POLICY.md`, its score after every run).
**Done when:** each `CLOSE` code fires on the labelled closable cases, and only those. **Wrongful closes stay at 0.**

At the start `CHECKS = []`: every close in `output/` came from Lorenzo's list-match check (bank 38, e-money 45,
payments 22, investment 0). Everything else fell back to RFI/ESCALATE, so explainers are where the score is.

## Status (updated after each check)

`CHECKS = [business_records, own_account, returning_customer, documented_event, refund]` on `track1-alert-closing`
(PR #1 merged; the `clotilde` branch is retired).

| Check → code | Rules | Close when (all hold) | Commit |
|---|---|---|---|
| `business_records` → `BUSINESS_RECORDS_RECONCILE` | TM03 | every alerted cash deposit has its own row in one record table, same amount to the penny, dated on the deposit day or ≤ 2 days before; a stated day's takings ≥ the top-up | ✅ merged |
| `own_account` → `OWN_ACCOUNT` / `RFI_UPDATED_PROFILE` | TM01, TM02, TM06, TM08 | a statement names the customer as holder (joint holders count), has the transaction's counterparty account (or its "ending" digits) and the same amount; without that money the alert wouldn't fire; TM01 ≥ `own_account_rfi_multiple` → RFI | ✅ merged |
| `returning_customer` → `RETURNING_CUSTOMER` | TM07 | "re-verified on <date>" inside the dormant period and on/before the reactivation + the money came from a statement-proven own account; the rest moved < the alert's limit | ✅ pushed |
| `documented_event` → `DOCUMENTED_EVENT` | TM01, TM02, TM05, TM06, TM07, TM08 | an event letter / receipt / completion statement states the amount to the penny, names the payer, is dated 0–30 days before, carries the reference number, isn't addressed to someone else; cash: the customer is the seller (and owned the vehicle) | ✅ pushed |
| `refund` → `REFUND_OF_EARLIER_PAYMENT` | TM01, TM02, TM05, TM06, TM07, TM08 | a transaction going the other way for the same amount with the same party (cash: withdrawal then deposit), before or after; a document written between the two states the amount and names the reference, account or party; cash also needs an earlier review written in between that covers the withdrawal | this commit |

**TM02 coverage follows the policy wording:** where TM02 counts only money "from anyone other than the client"
(payments and FX), explaining the third-party money is enough; elsewhere both what's left coming in and going out must
stay under the floor (so own money in, then out to an undocumented party, stays unexplained).

Results on the team labels (rules only, after each step; **wrongful closes 0 throughout**):

| | Start | + business_records | + own_account | + returning_customer | + documented_event | + refund |
|---|---|---|---|---|---|---|
| Bank (closable closed /29) | 3 | 7 | 9 | 11 | 18 | **23** |
| E-money (/25) | 2 | 4 | 6 | 9 | 18 | **21** |
| Investment (/28) | 0 | 0 | 10 | 13 | 17 | **20** |
| Payments and FX (/24) | 1 | 1 | 1 | 1 | 2 | **5** |

Every shape a check touches closes 100% of its cases; every remaining closable miss belongs to a check not yet built.

### Tests — `system/tests/test_explainers.py` (invented data only; 51 tests)
| Check | What the tests pin down |
|---|---|
| `business_records` (11) | all rows match → close; one row missing, one penny off, row dated after or > 2 days before, top-up above the day's takings, two equal deposits with one row → nothing; collection reports emptied the day before cite the cash procedure but not the KYC summary; only TM03; only cash deposits |
| `own_account` (11) | TM02 in + out both own → close; destination undocumented, holder someone else, account number differs, amount differs, third-party money left over → nothing; TM01 < 5× close, = 5× RFI_UPDATED_PROFILE, still over profile without the own money → nothing; "account ending" + joint holders; TM07 not handled here |
| `returning_customer` (6) | re-verified the day before + own statement → close (evidence order, "the day before" in the reason); re-verified after the reactivation or before the dormancy, no statement, no re-verification, large payment out left unexplained → nothing |
| `documented_event` (14) | insurer letter (amount + payer + claim) → close, also TM01 at 8× (5× is own-account only); claim number missing, addressed to someone else, dated after or > 30 days before, other company, amount differs → nothing; invoice / gift letter / venue email / credit note ignored (their own checks); own-name credit ignored; six seller phrasings read as the customer; someone else selling → nothing; vehicle receipt needs the customer's ownership document (registration must match); house move: deposit return + holding deposit both documented → close, one missing → nothing |
| `refund` (9) | venue refund of an earlier deposit → close (evidence: email, covering review, both legs); no document, document written before the original payment, no earlier payment of that amount, earlier payment to someone else, document naming neither booking nor party → nothing; cancelled subscription returned to the same account closes TM01 and TM02, without confirmation nothing; cash paid back in needs the review that covered the withdrawal (none, or written before the withdrawal → nothing); TM02 third-party-money wording closes, all-money wording with a big payment out doesn't |

### Next, in order of value
1. ~~`refund`~~ ✅
2. `invoice_matches` → `INVOICE_MATCHES`: outgoing payment = invoice/contract amount, payee, reference (hospital, dealer +
   loan, supplier invoices, held payments in payments and FX, TM07 pre-pause supplier).
3. `third_party_documented` → `THIRD_PARTY_DOCUMENTED`: gift letter (giver = payer, recipient = customer), invoice-finance
   advance (= advance rate × financed total).
4. `collection_documented`, `group_company`, TM10 redundancy (`DOCUMENTED_EVENT`), payments and FX own account (needs a
   team decision: undocumented UK funding account).
5. Robustness test: reword dev documents (field names, titles, one-penny rounding) and see which checks still hold —
   the unseen set may be worded differently.

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
- [x] `system/tests/test_explainers.py` with fake `CaseBundle`s (invented data only), like `test_red_flags.py` — see Status.
- [ ] Check reasons: names, amounts, doc IDs present; RFI says exactly what to ask.

## Open points to agree with the team
- ~~**TM01 coverage**~~ decided: a TM01 is explained only when, without the explained credits, the rest of the money
  received is within the profile multiple (same idea for TM02/TM05/TM06/TM07/TM08 with their own thresholds).
- **Prose check before closing (Andrei/Fedya):** who raises the "does the chat contradict this close?" `Question` —
  B per check, or the pipeline? Its `if_yes` would be a red flag (Lorenzo's code).
- **Codes with no exact fit** (bank findings): re-deposited own cash → `REFUND_OF_EARLIER_PAYMENT`; "prove you hold the
  overseas account" → `RFI_SOURCE_OF_FUNDS`. Confirm with labels or the organisers.
- **Document type only narrows a check:** `documented_event` reads only letters, receipts and completion statements
  (not gift letters), so invoices, refunds and gifts get their own code and checks. The verdict still rests on content
  (amount, payer, date, reference); the type filter can only remove closes, never add one. Flag to Andrei re D8.
- **Payments and FX own account:** the statement proves the outgoing own-account transfer, but the UK funding account
  has no statement; policy says an own-name account counts only with a document. Ask Andrei before closing those.
