# Alert triage system — Track 1

`system/run <institution folder> <output file>` reads one institution's folder and writes one line per case:
`case_id`, `alert_ids`, `verdict` (CLOSE / RFI / ESCALATE), `reason_code`, `reason`, `evidence`. Python 3 standard
library only. Run from anywhere; paths are resolved from the arguments.

## How it decides: the SOP decides, the model only reads

Each institution's `POLICY.md` is read at run time: rule thresholds, higher-risk countries, the 5× own-account rule,
the £10,000 invoice rule, the internal-list clause. Nothing is hard-coded per institution.

For every case:

1. **Load** the case: alerts, the transactions they fired on, the customer, documents (parsed into fields), earlier
   reviews, internal-list entries.
2. **Red flags** (`tm/red_flags.py`): positive signs of crime from the evidence — a sending-bank fraud report, a note
   asking about staying under a threshold, a listed person still in control on the payment date (director *and* PSC
   dates), money forwarded to an exchange, pass-through to newly incorporated linked companies, invoices that don't
   support the payments, evasive routing, and more. Each raises an ESCALATE signal with its reason code.
3. **Explainers** (`tm/explainers.py`): documents that explain an alert, verified in code — amounts to the penny,
   payee, holder, dates: a sale receipt or solicitor's letter, business records that reconcile, an invoice/contract/
   payment file, own-account statements (with the 5× updated-profile rule), refunds, group companies, documented
   collections, returning customers. Each raises a CLOSE signal (or an RFI when one document is missing, saying what
   to ask for).
4. **Reader** (`tm/reader.py`): where only prose can settle a question (a support chat, an email), it asks a decision
   model a yes/no question about the named documents. Answers are *soft*: they can add a red flag or support a
   verified close, but **can never close a case on their own**. See `fedya/READER.md`.
5. **Rulebook** (`tm/decide.py`), per alert: red flag → ESCALATE; explained by hard evidence → CLOSE; one document
   missing → RFI; nothing found → the rule's default (RFI for profile, cash, dormancy, many-payer, third-party and
   early-redemption alerts; ESCALATE for money moved straight on and splits under a threshold). **Per case: the worst
   alert wins**, so a case closes only when every alert is explained. A held payment of £10,000+ to a third party
   (payments and FX) is never released without a matching invoice or contract.
6. **Check** (`tm/check.py`): the reason code belongs to the verdict, every evidence ID exists in the files, every alert
   is listed.

The reason is built from the deciding signals' facts — this case's names, amounts, dates and document IDs — and
`evidence` lists the IDs that decided it.

## Models

| Tier | Model | Endpoint | Used for |
|---|---|---|---|
| 1 | `typesafe/jev-1.13` (pinned `jev-1.13-20260917`) | OpenRouter `/api/alpha/decisions` | yes/no with a probability (≥ 0.90 yes, ≤ 0.10 no) |
| 2 | `openai/gpt-4.1-mini` | OpenRouter `/api/v1/chat/completions` | only when tier 1 is unsure; a "yes" must quote the document word for word |

Key from `OPENROUTER_API_KEY`. Without a key, or on any error, the answer is "unknown" and the rules still decide.

## Live judge demo

Start the [Payper Trail case canvas](../andrei/live-canvas/README.md), then set `TM_LIVE=1` on the normal run command. The canvas
shows each case's checks, reader answers, and verdict as they happen.

## Reproducibility

- Rules are deterministic; model calls use temperature 0, a fixed seed, inputs in a fixed order, and every answer is
  cached in `system/cache/reader/` keyed by a hash of the request, so repeat runs make no calls.
- Every run writes `system/traces/<institution>.manifest.json` with fingerprints of the code, the policy and the whole
  output file. **Measured: 5 runs × 4 institutions (4,000 cases) gave the same output fingerprint every time.**
- Every decision's trace (`system/traces/<institution>.jsonl`) records each alert's path through the rulebook, the
  signals with their facts and evidence, **the POLICY.md clauses it rests on (quoted)**, every model answer with its
  probability, and input/policy/decision fingerprints.

## Time and cost per 200 cases (measured, reader on)

- **Time:** rules alone ~1 s per 200 cases; with the reader and an empty cache, ~5 s per 200 cases (8 workers).
  Limit: 30 minutes.
- **Cost:** at most **~$0.005 per 200 cases** (bank, the busiest institution); e-money ~$0.0035, investment ~$0.002,
  payments and FX $0. With a filled cache, $0. Limit: about $4.
- Source: `fedya/READER.md` (1,000 cases per institution, 661 live calls, 0 errors).

## How well it does (development set)

The development set has no answers, so we built our own references: 326 team labels settled against each SOP clause,
514 confident labels from a second model family, and a blind Grok labelling of all 4,000 cases. Final run (reader on):
**0 wrongful closes** on the team labels, with 83/83 (bank), 78/78 (e-money), 85/85 (investment) and 80/80 (payments
and FX) verdicts right; the blind Grok labels agree on 3,996 / 4,000 verdicts. Verdict split: 500 / 250 / 250
(CLOSE / RFI / ESCALATE) in bank, e-money and investment, 499 / 251 / 250 in payments and FX. These are AI-made
references, not ground truth. Detail and history in `andrei/DECISIONS.md`.
