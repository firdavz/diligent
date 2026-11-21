# Lorenzo (C) — red flags: what `system/tm/red_flags.py` does, and what the others need to know

A red flag here is **positive evidence of suspicion**. "Nothing explains it" is not a red flag — `decide.FALLBACK` covers that,
and B's explainers can still close it. Checks (all hard unless noted; run `python3 system/tests/test_red_flags.py`):

| Check | Fires when | Signal |
|---|---|---|
| `listed_party` (TM22, **owned entirely by C**) | a document gives a birth date / month-year for the matched party and it equals the list entry's | `red_flag ESC_LISTED_PARTY` |
| | the documents give a *different* birth date | `explains LIST_MATCH_DIFFERENT_PARTY` |
| | register shows the listed person left every role **before** the payment (a resigned director who still holds significant control on the payment date is still a red flag) | `explains LIST_MATCH_DIFFERENT_PARTY` |
| | list match on an address: same building but a different unit → different occupier; same unit → linked | `explains` / `red_flag` |
| | name-only match and no identity evidence | nothing → decide's fallback (RFI) |
| `fraud_report` | a document of type `*fraud_report*` (or text about a scam) is on file | `red_flag ESC_MULE_ACTIVITY` on the whole case |
| `structuring_intent` | staff note records the customer asking whether staying under a limit avoids aggregation / reporting / ID checks | `red_flag ESC_STRUCTURING` |
| `third_party_story` | the customer says the money is other people's, or says "a friend" while the payer is a company | `red_flag ESC_MULE_ACTIVITY` / `ESC_THIRD_PARTY_FUNDING`; unreadable chats become a `Question` for D |
| `dissolved_counterparty` | the register shows the counterparty company was dissolved before the payment date | `red_flag ESC_UNEXPLAINED_FUNDS` (whole case) |
| `evasive_routing` | TM06 + a note says the client could not / would not justify the routing to the higher-risk country | `red_flag ESC_HIGH_RISK_CORRIDOR` |
| `invoice_mismatch` | an invoice row cited by an outgoing payment has another amount, is dated after the payment, or bills consultancy to a goods business | `red_flag ESC_INVOICE_MISMATCH` (whole case) |
| `linked_new_company` | money goes out (TM02/TM04/TM08 case) to companies incorporated in the last year whose officer/controller also runs the client | `red_flag ESC_PASS_THROUGH` |
| `shared_payee_addresses` | a payment file with ≥ 10 payees at ≤ a third as many addresses | `red_flag ESC_MULE_ACTIVITY` |
| `corridor_to_individuals` | TM06: ≥ 2 unrelated payers in, then payments to ≥ 2 differently-surnamed people in the higher-risk country | `red_flag ESC_HIGH_RISK_CORRIDOR` (whole case) |
| `forwarded_to_exchange` | TM02: ≥ 2 unrelated payers, ≥ 80% on to an exchange within a day | `red_flag ESC_MULE_ACTIVITY` (whole case) |

Order in `CHECKS` matters: the first red flag's code becomes the case's reason code, so the most specific checks run first.
On the 226 team labels (21 Nov, 15:00): no labelled ESCALATE missed, no red flag on a labelled CLOSE/RFI case, and the escalation
reason code matches the label in every bank, e-money and investment case.

## For Clotilde (B)
- **Don't build the list-match CLOSE** — `listed_party` already emits `LIST_MATCH_DIFFERENT_PARTY`. The *other* alerts in the same
  case (TM08 gift, TM01 profile) are still yours: the case only closes when every alert is explained.
- A red flag always beats an explanation in `decide`, so your signals can stay simple.

## For Andrei (A) — observations from labelling Investment (drafts, not confirmed)
- Of 43 hand-labelled Investment cases, **no ESCALATE label slips** and **0 wrongful closes**; the only misses are RFI/CLOSE cases
  that nobody has explained yet (B's work). My red flags never touched a case labelled CLOSE or RFI.
- `decide.FALLBACK["TM08"]` = `ESC_THIRD_PARTY_FUNDING` is too harsh for a plain gift / joint-account style payer with **no document and no
  other concern** (labelled RFI: ask for the gift letter or proof the customer holds the account). Same for a name-only TM22 match.
  Suggest `RFI_COUNTERPARTY_DETAILS` for TM08 when no red flag fired. Unsure — worth checking against the other institutions' labels.
- `FALLBACK["TM10"]` / `["TM02"]` with no documents at all: I labelled ESCALATE (unsure; could be RFI). Costs are 3 vs 2 either way.
- Per-alert fallback + "worst alert wins" means a case with five explained alerts and one unexplained TM08 still escalates; fine, but it
  is why Investment currently closes 0 cases until B lands.

## Next (C)
Mule / pass-through patterns in the transactions themselves (receive-and-forward to linked parties), undeclared higher-risk country
with third parties, device/login anomalies (account misuse). Waiting on labels to see what separates the traps.
