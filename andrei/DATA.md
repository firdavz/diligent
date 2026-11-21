# The dataset, and tuning without labels

## Files (per institution folder; the unseen set has the same files)
`POLICY.md`, `cases.jsonl`, `alerts.jsonl`, `customers.jsonl`, `transactions.jsonl`, `evidence.jsonl` + `evidence/*.md`,
`previous_reviews.jsonl`, `internal_list.jsonl`. Links: case → `alert_ids` → alert `transaction_ids`;
case/alert → `customer_id` → customer, transactions, evidence, previous reviews; TM22 alert `measured.list_entry` → list.

## What we found
- 1,000 development cases per institution; ~4 documents per customer, ~400 bytes each — small enough to send whole.
- Every customer has a due-diligence summary; most have proof of address and a contact note. The **other** document
  types are scenario-specific (vehicle sale receipt, solicitor letter, gift letter, cash collection reports,
  sending-bank fraud report, payment file, …).
- Most documents are `**Field:** value` Markdown — parse them in code. Prose: support chats, contact notes, letters, emails.
- All 1,528 earlier reviews are `CLOSE`. That's context, not a base rate (and never covers new or larger activity).
- Traps are planted in the details, e.g. a list match on a company officer whose directorship ended the day before
  the payment, or a chat whose story doesn't match the documents.

## Case shapes
Grouping cases by (rules fired + scenario-specific document types):

| Institution | Cases | Shapes | Largest shape |
|---|---|---|---|
| Bank | 1,000 | 32 | TM01+TM05 with a support chat (75) |
| E-money | 1,000 | 30 | TM02 with a bank statement (46) |
| Investment | 1,000 | 34 | TM01+TM02+TM08 with a support chat (98) |
| Payments and FX | 1,000 | 31 | TM01 with a bank statement (210) |

~125 shapes cover all 4,000 cases.

## Labelling plan
1. `eval/` gets a case viewer (one case on one screen) and a shape list.
2. Each person labels their institution: 1–2 cases per shape, 3–4 for big or mixed shapes, ~40 in all.
   For mixed shapes, write down what separates the closable case from the trap — that's the rule.
3. Optionally a larger Grok model drafts verdicts; humans confirm or fix.
4. Take disagreements to the Track 1 organisers or the judges in the room.

Label format, in `eval/labels/<institution>.jsonl` (git-ignored):
```json
{"case_id": "...", "verdict": "CLOSE|RFI|ESCALATE", "reason_code": "...", "key_evidence": ["..."], "note": "what decided it"}
```

## Checks that need no labels
- A sending-bank fraud report on file → must `ESCALATE`.
- No `CLOSE` resting only on model answers.
- Every cited ID exists in the case's files; reason code belongs to the verdict.
- Five runs give identical output.
- Rules vs model disagreements get a human look.
