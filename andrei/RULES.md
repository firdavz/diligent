# The brief's rules, and where each is enforced

Source: the Track 1 brief (hosted page = `BRIEF.html`, unchanged since 11:40) and each institution's `POLICY.md`.
`system/tm/load.py` parses every threshold below from `POLICY.md` at run time (verified for all four institutions),
so nothing here is hard-coded per institution.

## Monitoring rules (what fired the alert)
| Rule | Bank | Payments and FX | E-money | Investment | No signal → fallback (`decide.FALLBACK`) |
|---|---|---|---|---|---|
| TM01 profile exceeded | 30-day inflow > 3× monthly income (individual) / 2× monthly turnover (business) | funding > 2× monthly share of declared annual volume | as bank | deposits > 3× / 2× | RFI_SOURCE_OF_FUNDS |
| TM02 rapid movement | ≥ 80% of ≥ £2,000 received over 10 days paid out within 48h (card excluded) | as bank, but money from anyone other than the client | as bank | ≥ 80% of ≥ £2,000 withdrawn within 10 days, < 20% invested | ESC_UNEXPLAINED_FUNDS |
| TM03 below threshold | ≥ 3 cash deposits £9,000–£9,999.99 in 10 days | ≥ 3 payments to one beneficiary £9,000–£9,999.99 in 10 days | ≥ 4 cash top-ups £800–£999.99 in 10 days | — | ESC_STRUCTURING |
| TM04 many-to-one | > 6 payers or payees in 30 days | > 25 beneficiaries in 30 days | > 6 | — | ESC_MULE_ACTIVITY |
| TM05 large cash | ≥ £10,000 individual / ≥ £25,000 business | — | ≥ £1,000 individual / ≥ £5,000 business | — | RFI_SOURCE_OF_FUNDS |
| TM06 higher-risk country | ≥ £5,000 in 30 days to/from an undeclared higher-risk country | beneficiary country | as bank | deposit source / withdrawal destination | ESC_HIGH_RISK_CORRIDOR |
| TM07 dormant reactivation | ≥ £5,000 after 180 days inactive | as bank | as bank | as bank | RFI_SOURCE_OF_FUNDS |
| TM08 third party | — | funding ≥ £1,000 not in the client's name | — | deposit/withdrawal ≥ £1,000 from/to someone else | ESC_THIRD_PARTY_FUNDING |
| TM10 early redemption | — | — | — | fund units sold back within 90 days | ESC_EARLY_REDEMPTION |
| TM22 internal list | payer or recipient | beneficiary or its officers | payer or recipient | who deposits | RFI_COUNTERPARTY_DETAILS |

The fallbacks are what an alert becomes when no explainer and no red flag fired — never CLOSE. They follow the brief's
own example (unexplained but not suspicious → RFI) and the policy on unsettled list matches. They are placeholders to tune
on labels.

## Verdict rules
| Rule (brief / POLICY.md) | Where enforced | Status |
|---|---|---|
| CLOSE only when the evidence explains **every** alert in the case | `decide`: worst alert wins | ✅ |
| Once there is suspicion, ESCALATE — never RFI (tipping off) | `decide`: any red flag beats any explanation | ✅ |
| RFI: nothing suspicious, **one** specific document or answer settles it; the reason says what to ask | `partial` signals carry the ask in `facts` | ✅ engine; each RFI check must word its ask |
| A wrongful CLOSE is the worst mistake | `decide`: CLOSE needs a **hard** explains signal on every alert; model answers alone can't close | ✅ |
| One case, one verdict; `alert_ids` lists every alert | `decide` + `check` | ✅ |
| Reason 2–4 sentences with this case's facts; evidence IDs exist in the files | `decide` builds it from signal facts; `check` drops unknown IDs | ✅ |

## Policy settings (the brief's "settings that most often decide a case")
| Setting | Where enforced | Status |
|---|---|---|
| **Own accounts** count only with a document on file showing the customer holds the other account | Explainer (Clotilde): own-account check | ❌ not yet — `bank-findings.md` #11–13 |
| Own-account activity ≥ **5×** declared income/volume → RFI_UPDATED_PROFILE; below → CLOSE OWN_ACCOUNT | Same check; threshold `policy["own_account_rfi_multiple"]`, measured on the TM01 alert's `measured.multiple` | ❌ not yet |
| **Internal list**: a match on one detail alone doesn't prove identity. Different party shown → CLOSE LIST_MATCH_DIFFERENT_PARTY; nothing settles it → RFI; listed party is or controls the counterparty → ESCALATE ESC_LISTED_PARTY | `red_flags.listed_party` (Lorenzo) both ways; fallback RFI | ✅ |
| **Earlier reviews** cover only what they describe, never new or larger activity | No check may treat a review as an explanation on its own; a review can only support a matching earlier transaction (e.g. a re-deposited withdrawal) | ✅ by design; reviewers of B's checks must hold to it |
| **Payments and FX**: a payment ≥ **£10,000** to anyone other than the client needs an invoice or contract on file before release | `decide._held_payment_needs_invoice`: no CLOSE without a hard INVOICE_MATCHES signal citing the held payment → RFI_PURPOSE_DOCUMENTS | ✅ (added 21 Nov) |
| **Context, not triggers**: round amounts, shared device / IP / contact details, a recipient added the same day, crypto or gambling counterparties never raise or decide a case alone | `red_flags` uses them only alongside a real red flag | ✅ (checked Lorenzo's checks) |
| Higher-risk countries **as of 1 October 2026** (17 listed) | `policy["high_risk_countries"]` | ✅ parsed |
| Currency: pounds; other currencies are also given in pounds | use `amount_gbp` everywhere | ✅ |
