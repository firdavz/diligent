# Constraints and scoring (from the Track 1 brief and README)

## Hard constraints
- Entry point: `system/run <institution folder> <output file>`, run from inside `system/` with full paths.
- Reads only the given institution folder; writes only the output file and files inside `system/`.
- Python 3 / Node standard library, or shell. Nothing that needs installing.
- Models only via OpenRouter chat completions, key in `OPENROUTER_API_KEY`. Judges use their own key.
- 200 cases in under 30 minutes and under ~US$4.
- One JSON line per case: `case_id`, `alert_ids` (all of them), `verdict`, `reason_code` (must belong to the verdict),
  `reason` (2–4 sentences, this case's facts; for an RFI, exactly what to ask), `evidence` (IDs as in the files).
  A missing case counts as an escalation.
- Deliver `system/run`, `system/README.md` (how it decides, which model, time and cost per 200 cases),
  and `output/{bank,emoney,investment,payments_fx}.jsonl` produced by the system.

## Score (out of 100)
| Part | Weight | What counts |
|---|---|---|
| Unseen cases (800, 200 per institution) | 60% | Verdicts 60%, reasons 40% |
| Development cases | 20% | Verdicts 60%, reasons 40% |
| Reproducibility (5 runs) | 20% | Same verdict and reason code every run; scaled by the unseen score |

Reasons are scored, for correct verdicts only, on: deciding documents in `evidence`, the right grounds, and naming this
case's own documents, people and amounts (generic wording scores little).

## Cost per case (lower is better; escalate-everything scores 0)
| Right verdict ↓ / you sent → | CLOSE | RFI | ESCALATE |
|---|---|---|---|
| CLOSE | 0 | 3 | 3 |
| RFI | 10 | 0 | 2 |
| ESCALATE | 10 | 3 | 0 |

## What follows
- `CLOSE` pays off only at ≥ ~77% confidence the case is closable (3p > 10(1 − p)).
- Between `RFI` and `ESCALATE` when unsure: `ESCALATE` (2 vs 3), and policy says escalate once there's suspicion.
- There is no target close rate. The brief says most alerts turn out to be explained; the organisers said the cases are
  partly real (anonymised) and partly generated from real patterns.
- Organisers in person: "a wrong decision is worse than no decision"; reproducibility and explainability matter as
  much as accuracy; judges favour solutions specific to financial crime; bring something visual to the demo.
