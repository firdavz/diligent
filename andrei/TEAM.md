# Team split

| | Owns | Works against | Done when |
|---|---|---|---|
| **A — core** _(name?)_ | `types.py`, loader + document field parsing, decision engine, output checks, `system/run`, scorer (with 5-run consistency), `system/README.md` | Real data from the start | All 4,000 cases produce valid output (12:30), then scored against the hand labels |
| **B — explainers** _(name?)_ | Every `CLOSE` code + the `RFI` fallbacks: invoice, own account and the 5× rule, documented event, business records, group company, refund, returning customer, earlier-review coverage, within profile | Fake `CaseBundle`s until A's loader lands (~12:15) | Each `CLOSE` code fires on the labelled closable cases, and only those |
| **C — red flags** _(name?)_ | Every `ESCALATE` code + internal list (TM22): fraud reports, structuring, mule/pass-through, undeclared higher-risk country, third-party funding, account misuse, early redemption, list match vs director dates and dates of birth | Same | No labelled `ESCALATE` case slips through |
| **D — reader + demo** _(name?)_ | `ask()`: OpenRouter client, prompts, JSON output, cache, cost/time logging; then the demo screen reading `trace.json` | A stub `ask()` returning `unknown` until the key arrives | B and C use it for prose; demo shows verdict, rule path, documents, 5/5-runs tick |

## Milestones (code freeze 17:00)
| Time | Everyone | A | B | C | D |
|---|---|---|---|---|---|
| 11:50–12:40 | Label ~40 cases each, by case shape (one institution each) | Case viewer + shape list first | | | |
| 12:40–14:00 | | Loader, engine, `run`, scorer | Explainers | Red flags + TM22 | Reader + cache |
| 14:00–15:30 | Tune on the labels: wrongful closes must be 0, then raise the close rate | | | | Real model in |
| 15:30–16:30 | Freeze tuning (bug fixes only) | Full runs ×5, README | | | Demo screen + video |
| 16:30–17:00 | Final `output/*.jsonl`, push, submit | | | | |

## House rules
- The model reads, code decides. Unknown never leads to `CLOSE`.
- Every signal carries a reason code, one sentence of this case's facts, and real evidence IDs.
- No development-case details (IDs, names, amounts, verdicts) in `system/`. Labels stay in `eval/` (git-ignored).
- Don't commit the dataset or any API key — the repo is public.
- Only `types.py` is shared; change it only by agreeing in the team chat.
- Pull before push; small commits; conventional messages (`feat:`, `fix:`, `docs:`).
