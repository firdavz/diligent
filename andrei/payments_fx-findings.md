# Payments and FX: what decides each case shape (from 55 hand labels)

**Baseline (rules only + Lorenzo's red flags + the £10k invoice guard):** 14% of escalate-all cost saved, **0 wrongful
closes**, 1 of 24 closable cases closed.

**Main finding:** every shape scanned in full; each has one right answer once split by its deciding check. An alert on an
outgoing payment **holds** it (the case's `held_payment_id`); CLOSE releases it.

Rules here: TM01 (funding > 2× the monthly share of declared annual volume), TM02 (only money from anyone other than the
client), TM03 (≥ 3 payments to one beneficiary £9,000–£9,999.99 in 10 days), TM04 (> 25 beneficiaries), TM06, TM07, TM08
(funding ≥ £1,000 not in the client's name), TM22 (beneficiary or its officers). **£10,000+ to anyone other than the client
needs an invoice or contract on file before release** (enforced in `decide`).

## Clotilde — explainers (CLOSE) and their RFI twins
| Size | Alerts | Close when (all must hold) | Code | Missing-document twin → RFI |
|---|---|---|---|---|
| 210 | TM01 | Statement holder = client; the statement's "IBAN ending X is held by client" = the OWN ACCOUNT TRANSFER out, to the penny; all inflows are FUNDING in the client's own name; TM01 multiple **< 5×** (closable: 2.6–4.4×, 178 cases) | OWN_ACCOUNT | Same but **≥ 5×** (6.1–8.5×, 32 cases) → RFI_UPDATED_PROFILE |
| 33 | TM01 | Customer purchase order from a third-party buyer names `PO n`; supplier invoice has the same PO, amount = payment, Pay to = account, Buyer = client | INVOICE_MATCHES | No documents: big own-name funding then a `PO n` payment → RFI_PURPOSE_DOCUMENTS (PO + invoice) |
| 34 | TM03 | Contract schedule: each stage amount = a payment to the penny, due date = booking date, ref `<PROJECT> STAGE n`, supplier = beneficiary | INVOICE_MATCHES | Same STAGE payments, no schedule → RFI_PURPOSE_DOCUMENTS |
| 34 | TM06 | Supply contract (dated before) + supplier invoice: amount = held payment, Pay to = account, supplier = payee; goods fit the declared business | INVOICE_MATCHES | — |
| 31+14 | TM06+TM08 (+TM02) | Credit `REFUND BOOKING n` from a higher-risk country; credit note = the credit; an earlier outgoing `BOOKING n` of the same amount to the same company (earlier review cleared it) | REFUND_OF_EARLIER_PAYMENT | — |
| 22 | TM02+TM08 | Freight forwarder: carrier invoice amount/payee/IBAN = held payment; each freight-invoice row = a `FREIGHT n` receipt (exporter, ref, amount); rows ≈ 1.1× the carrier invoice | INVOICE_MATCHES | No documents, held carrier payment ≥ £10k → RFI_PURPOSE_DOCUMENTS (the £10k guard decides it) |
| 18+3+1 | TM08 (+TM02/TM01) | `ADVANCE` from an invoice-finance company named in the factoring agreement; remittance "advance at 85%" = the credit = 0.85 × the financed total | THIRD_PARTY_DOCUMENTED | Advance with no agreement → RFI_SOURCE_OF_FUNDS |
| 22 | TM02+TM08 | Group structure: payer and client share the same 100% owner; director's email says the sister company covers this supplier payment; supplier invoice matches the held payment | GROUP_COMPANY | — |
| 19+3 | TM08 (+TM02) | `INTERCOMPANY FUNDING` from a holding company the group structure shows owns 100% of the client | GROUP_COMPANY | — |
| 22 | TM04 | Software studio: every `MONTHLY FEE` payee is in the payment file with the same amount and country, held payment included | INVOICE_MATCHES | No payment file → RFI_BUSINESS_RECORDS |
| 22 | TM07+TM08 | Insurer letter: CLAIM ref and amount = the credit from that insurer | DOCUMENTED_EVENT | — |
| 22 | TM07 | Re-verification dated before the payment; supplier invoice from the pre-pause supplier = the payment (amount, IBAN, PO) | RETURNING_CUSTOMER | No re-verification or invoice → RFI_PURPOSE_DOCUMENTS |

## Lorenzo — red flags (ESCALATE) and TM22
| Size | Alerts | Escalate when | Code |
|---|---|---|---|
| 42 | TM01 | `supplier_invoices` amounts ≠ the payments with those INV refs; invoices dated after the payments; goods unrelated to the business | ESC_INVOICE_MISMATCH |
| 42 | TM22 | Officer matched on name + month/year of birth; resigned as director before the payment but PSC "Ceased" **after** it | ESC_LISTED_PARTY |
| 22 | TM22 | Address-only match: a different Unit in the same building, director/PSC differ in name and birth year, receipt = held payment | CLOSE LIST_MATCH_DIFFERENT_PARTY |
| 32 | TM22 | Name-only match, small payment for ordinary work, no documents → RFI_COUNTERPARTY_DETAILS (fallback) | |
| 42 | TM03 | Staff note: director asked whether paying under £10k avoids the invoice requirement; one invoice total = the sum of the payments | ESC_STRUCTURING |
| 42 | TM06 | Higher-risk country; staff note: goods "come from" another country, evasive about routing; invoices for "consultancy and market access services" | ESC_HIGH_RISK_CORRIDOR (alt. ESC_INVOICE_MISMATCH) |
| 41 | TM02+TM08 | `CONSULTING` credits from new payers; only contract is an old reviewed one; out within hours as `SERVICES` to companies incorporated this year whose sole director/PSC is the client's director | ESC_PASS_THROUGH |
| 30+11 | TM04+TM08 (+TM02) | `COMMISSION POOL` from an unrelated promotions company (no agreement); within a day 92–95% goes out as ~30 `COMMISSION` payments abroad; payment file puts the payees at 3 shared UK addresses; business unrelated | ESC_MULE_ACTIVITY (judgement call; softer: RFI_COUNTERPARTY_DETAILS) |

## Differences from the other institutions
- The £10k rule decides only one shape (freight with no documents → RFI). Every closable held payment ≥ £10k already has its invoice or contract.
- Many cases have no held payment (TM01, TM07, factoring, group funding are about money in).
- Own account: the statement proves the overseas destination; the client's UK funding account is treated as theirs (declared channel; TM08 checks holder names).
- Earlier reviews are noise except the one supporting the original booking deposit in the credit-note shapes.

## Ambiguities
- Invoice-finance advance with no agreement: RFI_SOURCE_OF_FUNDS vs RFI_COUNTERPARTY_DETAILS.
- TM04 freelancers with no payment file: RFI_BUSINESS_RECORDS vs CLOSE WITHIN_PROFILE (chose RFI: dev comes as document / no-document twins).
- TM07 with no documents needs two items (re-verification + invoice); still RFI.
- Documented closes: INVOICE_MATCHES used for freight, payment files and the purchase-order shape.
