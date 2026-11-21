# Investment: what decides each case shape (from 60 hand labels)

**Baseline (rules only + Lorenzo's red flags):** 8% of escalate-all cost saved, **0 wrongful closes**, **0 of 28** closable
cases closed — the weakest institution so far, and the biggest win once explainers land.

**Main finding:** every case of every shape scanned. Each shape has one right answer, **except TM22 + gift letter**, where
the **date of birth decides it**: the gift letter's DOB = the list entry's → ESCALATE; different → CLOSE
(about 50/41 across the two shapes). No amount, name, account or date-order trap elsewhere. 1p differences in some
completion statements are rounding, not traps.

Rules here: TM01, TM02 (≥ 80% of ≥ £2,000 withdrawn within 10 days, < 20% invested), TM06, TM07, TM08 (third-party
deposit/withdrawal ≥ £1,000), TM10 (units sold back within 90 days), TM22. No TM03/TM04/TM05.

## Clotilde — explainers (CLOSE) and their RFI twins
| Alerts / documents | Close when (all must hold) | Code | Missing-document twin → RFI |
|---|---|---|---|
| TM01+TM08, completion statement | Statement's client = customer; "paid to client's investment account" = the SALE PROCEEDS credit to the penny; payer = the statement's conveyancer client account; price − mortgage − fees = paid (±1p); dated on/before the credit | DOCUMENTED_EVENT | Same credit (20–55×), no statement → RFI_SOURCE_OF_FUNDS (ask for the completion statement) |
| TM01+TM08 / TM08, gift letter (parent → child) | Giver = payer, recipient = customer, amount = credit, letter dated before | THIRD_PARTY_DOCUMENTED — closes at **any** TM01 multiple (5× is for own accounts only) | — |
| TM08 / TM01+TM08, joint-account statement | Payer is "X & Y Surname" with the customer's initial and surname; statement holders include the customer; account number = payer's; amount/date match; TM01 < 5× | OWN_ACCOUNT | Same joint-name "ISA TOP UP", no statement → RFI_SOURCE_OF_FUNDS |
| TM01, own-name statement | Holder = customer but TM01 6–8.5× | — | → RFI_UPDATED_PROFILE |
| TM06, statement + customer letter | Withdrawal to the customer's own-name account in a higher-risk country: statement holder = customer, "account ending" matches, a relocation letter predates it | OWN_ACCOUNT | — |
| TM01+TM06 / TM06, statement + employment contract | SWIFT "SAVINGS" credit from an own-name overseas account (statement in the customer's name, account matches); employment contract for work there; TM01 < 5× | OWN_ACCOUNT | — |
| TM01+TM07, statement + re-verification | Re-verification before the credit + own-name statement for the source; TM01 < 5× | OWN_ACCOUNT | No documents → RFI_SOURCE_OF_FUNDS |
| TM07, statement + re-verification | As above | RETURNING_CUSTOMER | No documents → RFI_SOURCE_OF_FUNDS |
| TM07+TM08 / TM01+TM07+TM08, insurer letter | Letter from the paying insurer: claim ref = transaction reference, amount = credit, addressed to the customer, dated before; closes even ≥ 5× (not own-account money) | DOCUMENTED_EVENT | — |
| TM01+TM02 / TM02, cancellation confirmation | ISA subscription and a "CANCELLATION REFUND" of the same amount to the same own-name account; confirmation gives amount, date and account | REFUND_OF_EARLIER_PAYMENT | No confirmation → RFI_SOURCE_OF_FUNDS |
| TM02 / TM01+TM02, statement + email | Email says the transfer was a mistake (amount and account match); own-name statement shows out and back; TM01 < 5× | OWN_ACCOUNT | — |
| TM10, redundancy letter + email | Redundancy letter from the declared employer and an email asking to sell, both before the redemption; units bought with the customer's own top-up; proceeds to the customer's own name | DOCUMENTED_EVENT | No documents → RFI_PURPOSE_DOCUMENTS (ask why the units were sold) — **override the TM10 fallback**, which escalates |

## Lorenzo — red flags (ESCALATE) and TM22
| Alerts | Escalate when | Code |
|---|---|---|
| TM01+TM02+TM08, chat | Equal "CONSULTANCY" credits from a company the register shows **Dissolved**; chat calls it a loan from a friend; then a large withdrawal to an unrelated person | ESC_UNEXPLAINED_FUNDS |
| TM01+TM02+TM08 / TM02+TM08, chat | Three unrelated "INVEST" payers, then a withdrawal to a crypto exchange; chat: friends sent money to invest, "sending it on" | ESC_MULE_ACTIVITY |
| TM01+TM06+TM08, chat | SWIFT "INVESTMENT" credits from differently-surnamed people in a higher-risk country; chat: cousins investing through the customer's account | ESC_THIRD_PARTY_FUNDING (alt. ESC_HIGH_RISK_CORRIDOR) |
| TM08+TM10 / TM01+TM08+TM10, chat | Repeating cycle: third party pays "INVEST", units bought, sold back ~16 days later, paid to another third party; chat: "I invest for a few people" | ESC_EARLY_REDEMPTION |
| TM22 + gift letter | **Gift letter DOB = list entry DOB** (an exited customer) | ESC_LISTED_PARTY |
| TM22 + gift letter | List match on name only, letter DOB **≠** list DOB; amount and payer match the letter | CLOSE LIST_MATCH_DIFFERENT_PARTY |
| TM22, no letter | Name-only match on a "GIFT" → RFI_COUNTERPARTY_DETAILS (ask relationship, DOB, a gift letter) — the fallback | |

## Differences from bank / e-money
- A **joint-account** statement counts as the customer's own account.
- A gift letter both settles a list match (through the DOB) and explains a third-party payer.
- Cooling-off cancellations are new; TM10 has a closable redundancy story (trap: third parties fund purchases and receive proceeds).
- Earlier reviews here are all noise; none decides a case.
- The ≥ 5× rule only bites in one shape (all ≥ 6×); every other own-account shape is ≤ 4.5×.

## Ambiguities
- Proving an account is the customer's (joint account, cancellation, dormant top-up): no exact RFI code — RFI_SOURCE_OF_FUNDS.
- A cancellation refund visible in the firm's own transactions but with no document: labelled RFI (policy needs a document).
- A TM10 sale with no reason: RFI, not the ESCALATE fallback (the customer's own money in and out).
- Gift letters from a "relative" with a different surname: accepted as a documented relationship.
- A TM22 close that also explains TM08/TM01: main code LIST_MATCH_DIFFERENT_PARTY.
