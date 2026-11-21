# BinEval results

Atomic SOP questions answered by pplx-decider (decisions endpoint), combined by the fixed table in `eval/bineval.py`.

| Run | Cases | Verdict | Code | Wrongful closes | Log |
|---|---|---|---|---|---|
| Iteration 1 | 40 tuning | 35/40 | 28/40 | 1 | `run_iteration1.log` |
| Iteration 2 | same 40 | 40/40 | 37/40 | 0 | `run_iteration2.log` |
| Iteration 2, validation | 40 untouched | 36/40 | 32/40 | 0 | `run_validation.log`, `report_validation.json` |
| Iteration 2, the rest | 146 untouched | 131/146 | 112/146 | 0 | `run_rest146.log`, `report_rest146.json` |
| Iteration 2, newest agent labels | 100 untouched | 92/100 | 80/100 | 0 | `run_agent100.log`, `report_agent100.json` |

`sop-*/<institution>/<case>.json` are the cached answers per question-bank version (probabilities only, no case text):
copy them to `eval/drafts/bineval/` and `python3 eval/bineval.py` re-runs from cache instantly and identically.
Decisions D21, D25, D26 in `andrei/DECISIONS.md`.

## Blind threshold comparison

The candidate lowers the yes threshold for `r_contradict` and `r_corridor` to 0.60, with the remaining questions at 0.70.
The two tables share one set of model answers. The hybrid emits a review flag when the candidate disagrees with an
unresolved rules decision and preserves all rules verdicts. Its report counts how many requests for review surfaced
a rules error.

1. Save a case list outside the known label files and answer caches. The sampler draws 40 Payments and FX cases
   and 20 per other institution, using the case IDs from the saved rules output as its inventory.
   `python3 eval/bineval_compare.py sample > /tmp/bineval-holdout.ids`
2. Save predictions before opening the reference labels. Set `TM_DATA` to the participant institutions directory
   and configure `OPENROUTER_API_KEY`.
   `python3 eval/bineval_compare.py predict --ids /tmp/bineval-holdout.ids --out /tmp/bineval-predictions.jsonl`
3. Have an independent labeller use the same case IDs and the original case files and policies. Keep the predictions
   out of its input. The reference JSONL needs a `case_id` and `verdict` for each case. Pass one file or disjoint files
   for a single labeller. To compare different labellers, score them separately.
   `python3 eval/bineval_compare.py score --predictions /tmp/bineval-predictions.jsonl --reference /tmp/blind-labels.jsonl`

If Grok has already labelled cases, select its cases outside the committed team labels and all known BinEval answer
caches with `python3 eval/bineval_compare.py unseen --reference eval/drafts/llm/*.grok-bot.jsonl > /tmp/grok-holdout.ids`.
Use that list with `predict` and then pass the Grok files to `score`. Only IDs pass from case selection to prediction.
