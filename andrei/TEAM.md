# Team split

| | Owns | Also responsible for | Works against | Done when |
|---|---|---|---|---|
| **A — core: Andrei** | `types.py`, loader + document field parsing, decision engine, tier ladder, output checks, `system/run`, scorer (with 5-run consistency), `system/README.md` | Bank | Real data from the start | All 4,000 cases produce valid output (12:30), then scored against the hand labels |
| **B — explainers: Clotilde** | Every `CLOSE` code + the `RFI` fallbacks: invoice, own account and the 5× rule, documented event, business records, group company, refund, returning customer, earlier-review coverage, within profile | E-money | Fake `CaseBundle`s until A's loader lands (~12:15) | Each `CLOSE` code fires on the labelled closable cases, and only those |
| **C — red flags: Lorenzo** | Every `ESCALATE` code + internal list (TM22): fraud reports, structuring, mule/pass-through, undeclared higher-risk country, third-party funding, account misuse, early redemption, list match vs director dates and dates of birth | Investment | Same | No labelled `ESCALATE` case slips through |
| **D — reader + demo: Fedya** | `ask()`: OpenRouter client, prompts, JSON output, cache, cost/time logging (tier 1 `x-ai/grok-4.3`, tier 2 `x-ai/grok-4.7`); then the demo screen reading `trace.json` | Payments and FX | A stub `ask()` returning `unknown` until the key arrives | B and C use it for prose; demo shows verdict, rule path, documents, 5/5-runs tick |

"Also responsible for" = label that institution's cases, know its `POLICY.md` inside out, and check its score after every run.

## Milestones (code freeze 17:00)
| Time | Everyone | Andrei (A) | Clotilde (B) | Lorenzo (C) | Fedya (D) |
|---|---|---|---|---|---|
| 12:15–13:00 | Label ~40 cases each, by case shape, in your own institution | Case viewer + shape list first | E-money | Investment | Payments and FX |
| 13:00–14:30 | | Loader, engine, `run`, scorer | Explainers | Red flags + TM22 | Reader + cache |
| 14:30–15:30 | Tune on the labels: wrongful closes must be 0, then raise the close rate | | | | Real model in (no key by 13:30 → start the demo early; rules-only still scores) |
| 15:30–16:30 | Freeze tuning (bug fixes only) | Full runs ×5, README | | | Demo screen + video |
| 16:30–17:00 | Final `output/*.jsonl`, push, submit | | | | |

## House rules
- The model reads, code decides. Unknown never leads to `CLOSE`.
- Every signal carries a reason code, one sentence of this case's facts, and real evidence IDs.
- No development-case details (IDs, names, amounts, verdicts) in `system/`. Labels stay in `eval/` (git-ignored).
- Don't commit the dataset or any API key — the repo is public.
- Only `types.py` is shared; change it only by agreeing in the team chat.
- Pull before push; small commits; conventional messages (`feat:`, `fix:`, `docs:`).
