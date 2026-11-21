# Bank: what decides each case shape (from 58 hand labels)

**Baseline (rules only + Lorenzo's first red flags):** 25% of escalate-all cost saved, **0 wrongful closes**,
3 of 29 closable cases closed. Every miss is a closable case with no explainer yet, or an RFI the fallback escalated.

**Main finding:** in the development set each shape has one right answer. Traps are their own shapes: the same story
with the deciding document missing (→ RFI) or with a contradiction (→ ESCALATE). So each check is: find the document,
then verify one or two numbers (amount to the penny, payee, date order, holder name).

Ordered by how much each check is worth (closable cases first). Codes in brackets.

## Clotilde — explainers (CLOSE) and their RFI twins
| # | Alerts | Close when (all must hold) | Code | Missing-document twin → RFI |
|---|---|---|---|---|
| 1 | TM01+TM05 | Chat says the cash is money withdrawn earlier; history has a cash **withdrawal of exactly that amount** (an earlier TM05 review usually closed it) | REFUND_OF_EARLIER_PAYMENT | Chat gives another story (e.g. sold a motorbike to a friend) with no receipt → RFI_SOURCE_OF_FUNDS |
| 2 | TM01+TM05 | Vehicle sale receipt: amount = cash deposit, dated on/before it, **seller = customer**, registration = the one on the customer's insurance schedule | DOCUMENTED_EVENT | |
| 3 | TM01 | Solicitor letter: amount = credit **to the penny**, payer is the firm's client account, reference names the estate in the letter | DOCUMENTED_EVENT | Same credit, no letter → RFI_SOURCE_OF_FUNDS |
| 4 | TM03 | Collection reports: every alerted cash deposit has a row with the same total; deposit is the day after emptying; procedure explains separate banking | BUSINESS_RECORDS_RECONCILE | |
| 5 | TM03 | Event cash reconciliation: "cash counted" values = the alerted deposits, banked 1–2 days after the event dates in the ticket report | BUSINESS_RECORDS_RECONCILE | |
| 6 | TM02+TM04 | Booking confirmation: every payer is in the traveller list, each pays the per-person price, the outgoing payment = total to the stated account/reference | COLLECTION_DOCUMENTED | Same pattern (N payers × price, then (N+1) × price to a travel company with a BOOKING ref), no confirmation → RFI_PURPOSE_DOCUMENTS |
| 7 | TM01+TM02 | Loan agreement principal = the LOAN ADVANCE credit from that lender; dealer invoice = the payment to the dealer (customer tops up £1–2.5k) | INVOICE_MATCHES | Same pattern, no agreement or invoice → RFI_PURPOSE_DOCUMENTS |
| 8 | TM06 | Hospital invoice amount = the SWIFT payment to that hospital, reference names the patient (chat: a parent, same surname) | INVOICE_MATCHES | |
| 9 | TM01+TM07, TM07 | Insurer letter: amount and CLAIM reference = the credit from that insurer | DOCUMENTED_EVENT | |
| 10 | TM01+TM06, TM06 | Venue email: refund = an earlier outgoing BOOKING payment to the same venue; an earlier review cleared the deposit | REFUND_OF_EARLIER_PAYMENT | |
| 11 | TM01+TM02, TM02 | Statements **in the customer's name** for both source and destination accounts; TM01 multiple **below** `own_account_rfi_multiple` (5×) | OWN_ACCOUNT | |
| 12 | TM01 | Statement in the customer's name for the source account, but TM01 multiple **≥ 5×** | — | → RFI_UPDATED_PROFILE |
| 13 | TM01+TM07 | Own-name statement + identity re-verification on file; multiple below 5× | OWN_ACCOUNT (or RETURNING_CUSTOMER) | Credit from an own-name overseas account but **no statement** → RFI (ask for the statement) |
| 14 | TM07 | Identity re-verified + own-name statement for the incoming money | RETURNING_CUSTOMER | |

The 5× test uses the TM01 alert's measured multiple (`measured.multiple`); the closable shape clusters at ≤ 4.5×, the RFI one at 6–8×.

## Lorenzo — red flags (ESCALATE) and TM22
| # | Alerts | Escalate when | Code |
|---|---|---|---|
| 15 | TM01+TM02+TM04 | Sending-bank fraud reports on incoming credits + chat about a "payments assistant" job forwarding money (to crypto) for a cut | ESC_MULE_ACTIVITY |
| 16 | TM01+TM06 | Several unrelated UK payers, then equal SWIFT payments to differently-surnamed people in a higher-risk country; only explanation is "helping family" in a chat | ESC_HIGH_RISK_CORRIDOR |
| 17 | TM01+TM02 | "CONSULTANCY" credits from a company the register shows **Dissolved**; chat calls it a loan from a friend; then a large payment out | ESC_UNEXPLAINED_FUNDS |
| 18 | TM01+TM03 | Many £9k–£9,999 cash deposits; staff note: customer asked whether staying under £10k avoids reporting / will use another branch | ESC_STRUCTURING |
| 19 | TM01+TM02+TM05 | Large cash with **contradictory sources** across two chats, sent abroad within hours | ESC_UNEXPLAINED_FUNDS |
| 20 | TM01+TM02 | "CONSULTING" credits from new payers with no contract (the only contract is an old, reviewed one); money out within a day to companies incorporated this year whose director is the customer's director | ESC_PASS_THROUGH |
| 21 | TM22 | Listed person matches the payee's officer on name and month/year of birth, and was **still a director or PSC on the payment date** — check the PSC "Ceased" date, not only the director's resignation | ESC_LISTED_PARTY |
| 22 | TM22 | Same building, **different unit**, and the officer's/PSC's name and birth year differ from the entry (watch shared surnames) | CLOSE LIST_MATCH_DIFFERENT_PARTY |
| 23 | TM22 | Name-only match, no documents, small payment for ordinary work (tiling, kitchen), nothing else concerning | RFI_COUNTERPARTY_DETAILS (the fallback already does this) |

## Policy ambiguities to agree on
- Re-deposited own cash has no exact code: we use REFUND_OF_EARLIER_PAYMENT (DOCUMENTED_EVENT is the alternative).
- "Prove you hold this overseas account" has no exact RFI code: we use RFI_SOURCE_OF_FUNDS.
- Shape 7's RFI twin needs two documents (agreement and invoice); still treated as RFI (nothing suspicious).
- Shape 8 relies on a chat for the family relationship; we close on the matching invoice (the hard signal).
- Dormant reactivation with no re-verification (shape 13 twin): treated as not suspicious → RFI, not ESCALATE.
