# Payper Trail · Live case canvas

Run the canvas server from the repository root:

```sh
python3 andrei/live-canvas/serve.py
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). Select **Sample replay** to explore invented cases with each of
the three outcomes. The sample's reader answers are simulated. The live display uses only events emitted by the engine.

To watch the judges' run, keep the canvas server open and start the normal command in a second terminal with live
events enabled:

```sh
TM_LIVE=1 system/run /path/to/institutions/bank /tmp/bank.jsonl
```

Select the new run from the picker if it doesn't open automatically. Pick a case on the left and click a node to
inspect it. Intake shows each alert's measurements and policy trigger. Red flags and explainers show the functions
that ran and the signals they assigned. The reader node shows tier, model, probability when available, and any quote
or evidence returned. The rulebook shows the per-alert outcome and policy clauses. Validation shows the checks and
fingerprints, and the verdict node shows the decision, reason code, explanation, and cited evidence.

Each invocation writes a separate stream to the git-ignored `system/traces/live/` directory. The viewer reads the
stream locally and shows completed runs when reopened. The CLI outputs the same decision JSONL with or without
`TM_LIVE=1`. The viewer needs Python's standard library and a browser.
