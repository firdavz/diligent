# BinEval results

Atomic SOP questions answered by pplx-decider (decisions endpoint), combined by the fixed table in `eval/bineval.py`.

| Run | Cases | Verdict | Code | Wrongful closes | Log |
|---|---|---|---|---|---|
| Iteration 1 | 40 tuning | 35/40 | 28/40 | 1 | `run_iteration1.log` |
| Iteration 2 | same 40 | 40/40 | 37/40 | 0 | `run_iteration2.log` |
| Iteration 2, validation | 40 untouched | 36/40 | 32/40 | 0 | `run_validation.log`, `report_validation.json` |

`sop-*/<institution>/<case>.json` are the cached answers per question-bank version (probabilities only, no case text):
copy them to `eval/drafts/bineval/` and `python3 eval/bineval.py` re-runs from cache instantly and identically.
Decisions D21, D25, D26 in `andrei/DECISIONS.md`.
