"""One command: does the reader help, and is it safe? Runs one institution three times and scores it.

  run0  rules only (no key)                      -> output/<inst>.run0.jsonl
  run1  rules + reader (key, fills the cache)     -> output/<inst>.run1.jsonl
  run2  rules + reader again (answers from cache) -> output/<inst>.run2.jsonl

Then: score run0 and run1 against eval/labels/<inst>.jsonl, check run1 == run2, and count reader calls and cost.
The .runN.jsonl files are git-ignored. Needs the dataset in data/institutions/ (or TM_DATA) and OPENROUTER_API_KEY.

  Windows:      py eval\\reader_check.py payments_fx
  Mac / Linux:  python3 eval/reader_check.py payments_fx
"""

import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("TM_DATA", os.path.join(ROOT, "data", "institutions"))
LOG = os.path.join(ROOT, "system", "traces", "reader_calls.jsonl")


def run(inst, out, with_key):
    env = dict(os.environ, PYTHONUTF8="1")
    if not with_key:
        env.pop("OPENROUTER_API_KEY", None)
    t0 = time.time()
    p = subprocess.run([sys.executable, os.path.join(ROOT, "system", "main.py"), os.path.join(DATA, inst), out],
                       env=env, capture_output=True, text=True, encoding="utf-8")
    print(f"  {os.path.basename(out)}: {time.time() - t0:.0f}s  {p.stdout.strip().splitlines()[-1] if p.stdout.strip() else ''}")
    if p.returncode != 0:
        print(p.stderr[-2000:])
        sys.exit("run failed: send this output to Claude")


def score(*args):
    p = subprocess.run([sys.executable, os.path.join(ROOT, "eval", "score.py"), *args],
                       env=dict(os.environ, PYTHONUTF8="1"), capture_output=True, text=True, encoding="utf-8")
    print(p.stdout.rstrip() or p.stderr[-1500:])


def main():
    inst = sys.argv[1] if len(sys.argv) > 1 else "payments_fx"
    if not os.path.exists(os.path.join(DATA, inst, "POLICY.md")):
        sys.exit(f"Dataset not found: {os.path.join(DATA, inst, 'POLICY.md')}\n"
                 f"Unzip the dataset so that folder exists (or set TM_DATA to the 'institutions' folder).")
    if not os.environ.get("OPENROUTER_API_KEY"):
        sys.exit("OPENROUTER_API_KEY is not set in this terminal. Set it first.")

    out = {i: os.path.join(ROOT, "output", f"{inst}.run{i}.jsonl") for i in range(3)}
    log_start = os.path.getsize(LOG) if os.path.exists(LOG) else 0

    print(f"Running {inst} three times (run1 is the slow one: it asks the models)...")
    run(inst, out[0], with_key=False)
    run(inst, out[1], with_key=True)
    run(inst, out[2], with_key=True)

    calls = []
    if os.path.exists(LOG):
        with open(LOG, encoding="utf-8") as f:
            f.seek(log_start)
            calls = [json.loads(line) for line in f if line.strip()]
    live = [c for c in calls if c.get("cached") is False]
    errors = [c for c in calls if "error" in c]
    cost = sum((c.get("usage") or {}).get("cost") or 0 for c in live)
    by_tier = {t: sum(1 for c in live if c.get("tier") == t) for t in (1, 2)}

    print("\n== WITHOUT reader (rules only)")
    score(inst, out[0])
    print("\n== WITH reader")
    score(inst, out[1])
    print("\n== Reproducibility (run1 vs run2)")
    score("--consistency", out[1], out[2])
    print(f"\n== Reader: {len(live)} model calls (tier 1: {by_tier[1]}, tier 2: {by_tier[2]}), "
          f"{len(calls) - len(live) - len(errors)} from cache, {len(errors)} errors, cost ${cost:.4f}")
    for e in errors[:5]:
        print("  error:", e.get("error"))
    print("\nSafe to merge only if WRONGFUL CLOSES is 0 in the WITH-reader score. Send this whole output to Claude.")


if __name__ == "__main__":
    main()
