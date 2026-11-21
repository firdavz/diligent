# Payper Trail — transaction-monitoring alert triage (Fin Crime Hackathon, Track 1)

Reads a transaction-monitoring case (alerts, transactions, customer, documents, earlier reviews, internal list) and
closes it the way a careful analyst would: **CLOSE**, **RFI** (saying exactly what to ask for) or **ESCALATE**, with a
reason code, a reason built from the case's own facts, and the evidence IDs it rests on.

**The SOP decides, the model only reads.** Each institution's `POLICY.md` is parsed at run time; deterministic rules
make every verdict; a decision model only answers narrow yes/no questions about prose documents and can never close a
case on its own.

## Run it

```
system/run <institution folder> <output file>        # e.g. system/run data/institutions/bank output/bank.jsonl
```
Python 3 standard library only. Optional `OPENROUTER_API_KEY` turns on the reader (`typesafe/jev-1.13`, then
`openai/gpt-4.1-mini`); without it the rules still decide everything.

## What to look at

| | |
|---|---|
| [`system/README.md`](system/README.md) | How it decides, models, reproducibility, time and cost per 200 cases |
| [`output/`](output/) | Our answers on the 4,000 development cases, produced by `system/run` from this commit |
| [`system/tm/`](system/tm/) | `red_flags.py` (signs of crime → ESCALATE), `explainers.py` (verified explanations → CLOSE / RFI), `reader.py` (decision model), `decide.py` (one rulebook, worst alert wins) |
| [`system/traces/`](system/traces/) | Per-case audit trail written by each run: rule path, signals, quoted SOP clauses, model answers, fingerprints |
| [`eval/`](eval/) | Scorer, case viewer, labels, blind-labeller and metrics tools (never read by `system/`) |
| `andrei/`, `clotilde/`, `fedya/`, `lorenzo/` | Each team member's design notes and decisions (`andrei/DECISIONS.md` is the log) |

## Results on the development set (final run, reader on)

| | CLOSE / RFI / ESCALATE | Team labels right | Wrongful closes |
|---|---|---|---|
| Bank | 500 / 250 / 250 | 83 / 83 | 0 |
| E-money | 500 / 250 / 250 | 78 / 78 | 0 |
| Investment | 500 / 250 / 250 | 85 / 85 | 0 |
| Payments and FX | 499 / 251 / 250 | 80 / 80 | 0 |

- **Independent check:** a blind Grok labeller (no access to our labels or outputs) labelled all 4,000 cases (251 answers revised after a second look, marked `revised` in `eval/labels_model/`); the
  system agrees on 3,996 / 4,000 verdicts (99.9%); only one case we close is one it would escalate.
- **Reproducibility:** 5 runs with an empty model cache gave the same verdict and reason code on 4,000 / 4,000 cases.
- **Speed:** a few seconds per 1,000 cases, well under 30 minutes per 200.

The development set has no answer key: these are reference labels we built (team labels settled against the SOP,
plus blind model labels), not ground truth.

## Team
Andrei (core, rulebook, scorer), Clotilde (explainers), Lorenzo (red flags, internal list), Fedya (reader, demo).
