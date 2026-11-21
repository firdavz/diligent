# Testing loop

Put the dataset at `data/` (git-ignored): `ln -s <path to unzipped>/hackathon data`.
Labels go in `eval/labels/<institution>.jsonl` (git-ignored — the repo is public). `system/` never reads `eval/`.

## 1. Label (once, ~45 min, one institution each)
```bash
python3 eval/shapes.py bank            # case shapes, biggest first, with case IDs to label
python3 eval/view.py BK-CS100585       # one case on one screen (--all-txns for every transaction)
```
One line per case in `eval/labels/bank.jsonl`:
```json
{"case_id": "BK-CS100585", "verdict": "CLOSE", "reason_code": "DOCUMENTED_EVENT", "key_evidence": ["SAL-750"], "note": "receipt matches the cash deposit"}
```
`note` = what decided it. For big shapes, label 3–4 cases and note what separates the closable one from the trap.

## 2. Change → run → score (every change, ~5 s)
```bash
system/run data/institutions/bank output/bank.jsonl
python3 eval/score.py bank
```
The score prints the verdict score (share of escalate-everything cost saved), **wrongful closes (must stay 0)**,
closable cases closed, right codes, key evidence cited, and every miss with your note.

## 3. Read the misses
`system/traces/<institution>.jsonl` has, per case: each alert's verdict and path (`red_flag` / `explained` /
`partial` / `fallback`), every signal with its source, and every model answer.

## 4. Before pushing
```bash
for i in bank emoney investment payments_fx; do system/run data/institutions/$i output/$i.jsonl; done
for i in bank emoney investment payments_fx; do python3 eval/score.py $i; done
```
Wrongful closes went up anywhere → don't push.

## 5. Reproducibility (A, before freeze)
```bash
for n in 1 2 3 4 5; do system/run data/institutions/bank output/bank.run$n.jsonl; done
python3 eval/score.py --consistency output/bank.run*.jsonl
```
