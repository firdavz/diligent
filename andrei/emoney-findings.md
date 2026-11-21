# E-money: what decides each case shape (from 53 hand labels)

**Baseline (rules only + Lorenzo's red flags):** 24% of escalate-all cost saved, **0 wrongful closes**, 2 of 25 closable
cases closed. As at the bank, the gap is explainers.

**Main finding:** all 1,000 cases scanned on their deciding numbers: **every shape has exactly one right answer.** Traps
are their own shapes: the same story with the document missing (→ RFI) or with a contradiction (→ ESCALATE).

Thresholds differ from the bank (TM03: ≥ 4 cash top-ups £800–£999.99 in 10 days; TM05: £1,000 individual / £5,000
business). **Take thresholds from POLICY.md, not alert text:** TM03/TM04 messages say "the limit is 3" where the policy
means "more than 3".

## Clotilde — explainers (CLOSE) and their RFI twins
| Size | Alerts | Close when (all must hold) | Code | Missing-document twin → RFI |
|---|---|---|---|---|
| 46 | TM02 | Two statements in the customer's name; their account numbers equal the `counterparty_account` of the in and the out transfer; same amount (no TM01, so no 5× test) | OWN_ACCOUNT | — |
| 46 | TM03 | Takings book (market trader) has one row per alerted cash top-up with the same date and amount; top-up ≤ that day's takings | BUSINESS_RECORDS_RECONCILE | (escalate twin: structuring below) |
| 46 | TM05 | Sale receipt amount = cash top-up; seller = customer; dated the day before; advert placed by the customer | DOCUMENTED_EVENT | — |
| 45 | TM01 | Settlement letter amount = credit to the penny; payer = the letter's issuer; letter dated before | DOCUMENTED_EVENT | Same credit, no letter → RFI_SOURCE_OF_FUNDS |
| 45 | TM06 | Hospital invoice amount = SWIFT payment to the penny; payee = invoice "Pay to"; reference names the patient | INVOICE_MATCHES | — |
| 45 | TM02+TM04 | Booking confirmation: every payer a listed traveller, each pays the per-person price, outgoing = total to the stated account/reference | COLLECTION_DOCUMENTED | N payers × price then (N+1) × price to a travel company with a BOOKING ref, no confirmation → RFI_PURPOSE_DOCUMENTS |
| 45 | TM02 | Deposit-return letter amount = credit from the letting agent; holding-deposit receipt amount = payment out to the new agent; return + small own top-up = holding deposit | DOCUMENTED_EVENT | Same pattern, no letters → RFI_PURPOSE_DOCUMENTS (ask for both) |
| 44+2 | TM01+TM07, TM07 | Insurer letter amount and CLAIM reference = credit from that insurer | DOCUMENTED_EVENT | — |
| 42 | TM01 | Own-name statement matches the credit but TM01 multiple **≥ 5×** (6.0–8.4) | — | → RFI_UPDATED_PROFILE |
| 34 | TM01+TM07 | Own-name statement + re-verification dated the day before the credit; multiple **< 5×** (3.0–4.5) | OWN_ACCOUNT | Own-name "SAVINGS" credit, no statement or re-verification → RFI_SOURCE_OF_FUNDS |
| 12 | TM07 | Re-verification the day before + own-name statement | RETURNING_CUSTOMER | No documents → RFI_SOURCE_OF_FUNDS |
| 26+19 | TM06, TM01+TM06 | Venue email confirms a full refund of BOOKING n; credit = an earlier outgoing payment with the same BOOKING ref to the same venue | REFUND_OF_EARLIER_PAYMENT | — |

The 5× split is clean: closable tops out at 4.5×, the RFI shape starts at 6.0×.

## Lorenzo — red flags (ESCALATE) and TM22
| Size | Alerts | Escalate when | Code |
|---|---|---|---|
| 42 | TM01+TM02+TM04 | Two sending-bank APP-scam reports on credits; chat about a "payments assistant" job forwarding money to crypto for a cut; device used from two countries | ESC_MULE_ACTIVITY |
| 33+9 | TM01+TM02, TM02 | 4 unrelated payers, each ~97% forwarded to a crypto exchange within 1–3 hours; device export: the login device is shared by several customer IDs, logins from abroad. **New vs bank:** no chat, no fraud report — the device plus the forwarding pattern decide it | ESC_MULE_ACTIVITY (alt. ESC_ACCOUNT_MISUSE) |
| 42 | TM22 | Officer matched on name + month/year of birth; resigned as director the day **before** the payment but PSC "Ceased" **after** it → still in control. The matching invoice doesn't cure it | ESC_LISTED_PARTY |
| 45 | TM22 | Same building, **different unit**; officer/PSC name and birth year differ; receipt matches | CLOSE LIST_MATCH_DIFFERENT_PARTY |
| — | TM22 | Name-only match, no documents → RFI_COUNTERPARTY_DETAILS (the fallback) | |
| 41 | TM01+TM02+TM03 | 5–7 cash top-ups £800–£999.99 over 2 days at several outlets; staff note: asked whether staying under £1,000 avoids ID checks; then sent to crypto | ESC_STRUCTURING |
| 41 | TM01+TM02 | Equal "CONSULTANCY" credits from a company the register shows **Dissolved**; chat calls it a loan from a friend; then paid out | ESC_UNEXPLAINED_FUNDS |
| 36+3+3 | TM01+TM06 (±TM04/TM02) | 3 unrelated UK payers, then equal SWIFT payments to differently-surnamed people in a higher-risk country; only explanation is "help my family" | ESC_HIGH_RISK_CORRIDOR |

## Ambiguities
- Deposit return → holding deposit: no exact code (DOCUMENTED_EVENT chosen; REFUND / INVOICE_MATCHES possible). The small
  own-name top-up that completes it is treated as an ordinary top-up, not an own-account claim needing a statement.
- Shared device is "context only" in the policy, but here it comes with third-party money passed on within hours → escalate.
- Settlement letters always come from a payer other than the declared employer: a generator convention across the whole
  shape, not a trap.
- "Prove you hold this account" has no exact RFI code: RFI_SOURCE_OF_FUNDS, as at the bank.
