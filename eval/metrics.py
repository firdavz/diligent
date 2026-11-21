"""Metrics to see whether we are improving, against several imperfect answer keys.

python3 eval/metrics.py <institution> [--llm anthropic_claude-sonnet-5.5] [--out output/<inst>.jsonl] [--log] [--show N]
python3 eval/metrics.py --history [institution]

Answer keys (none is ground truth; the organisers hold that):
  team       eval/labels/<inst>.jsonl                      hand labels by the team
  llm        eval/drafts/llm/<inst>.<model>.jsonl          blind second opinion from a strong model (eval/llm_label.py)
  consensus  cases where team and llm give the same verdict, the key we trust most
Reported per key, for the system's output: verdict agreement, cost per case with the brief's cost table and the share of the
escalate-everything cost saved, WRONGFUL CLOSES (must be 0), closable cases closed, per-verdict recall.
Also: team vs llm confusion, and the list of cases where they differ: those deserve a human look.
--log appends one line per key to eval/history.csv (tracked), so progress over commits is visible with --history.
"""

import csv
import datetime
import json
import os
import subprocess
import sys

from _common import ROOT
from score import COST

VERDICTS = ("CLOSE", "RFI", "ESCALATE")
HISTORY = os.path.join(ROOT, "eval", "history.csv")


def rows(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return {r["case_id"]: r for r in (json.loads(line) for line in f if line.strip()) if r.get("verdict")}


def confusion(truth, pred, ids):
    m = {(t, p): 0 for t in VERDICTS for p in VERDICTS}
    for i in ids:
        m[(truth[i]["verdict"], pred.get(i, {"verdict": "ESCALATE"})["verdict"])] += 1  # a missing case counts as ESCALATE
    return m


def show_confusion(m, a="key", b="system"):
    print(f"      {a}↓ / {b}→  " + "  ".join(f"{v:>8}" for v in VERDICTS))
    for t in VERDICTS:
        print(f"      {t:>14}    " + "  ".join(f"{m[(t, p)]:>8}" for p in VERDICTS))


def stats(m):
    n = sum(m.values())
    cost = sum(COST[k] * v for k, v in m.items())
    base = sum(COST[(t, "ESCALATE")] * m[(t, p)] for t in VERDICTS for p in VERDICTS)
    closable = sum(m[("CLOSE", p)] for p in VERDICTS)
    return {"n": n, "agree": sum(m[(v, v)] for v in VERDICTS) / n if n else 0, "cost_per_case": cost / n if n else 0,
            "saved": (base - cost) / base if base else 0, "wrongful": m[("RFI", "CLOSE")] + m[("ESCALATE", "CLOSE")],
            "closable_closed": m[("CLOSE", "CLOSE")], "closable": closable}


def commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def history(inst):
    if not os.path.exists(HISTORY):
        return print("no history yet: run with --log")
    for r in csv.DictReader(open(HISTORY, encoding="utf-8")):
        if inst in (None, r["institution"]):
            print(f"{r['when']}  {r['commit']:>8}  {r['institution']:<11} {r['key']:<9} n={r['n']:<3} agree={float(r['agree']):.0%} "
                  f"cost/case={float(r['cost_per_case']):.2f} saved={float(r['saved']):.0%} wrongful={r['wrongful']} "
                  f"closed={r['closable_closed']}/{r['closable']}")


def main(argv):
    if argv[0] == "--history":
        return history(argv[1] if len(argv) > 1 else None)
    inst = argv[0]
    opt = {argv[i]: argv[i + 1] for i in range(1, len(argv) - 1) if argv[i].startswith("--") and not argv[i + 1].startswith("--")}
    model = opt.get("--llm", "anthropic_claude-sonnet-5.5")
    team = rows(os.path.join(ROOT, "eval", "labels", f"{inst}.jsonl"))
    llm = rows(os.path.join(ROOT, "eval", "drafts", "llm", f"{inst}.{model}.jsonl"))
    system = rows(opt.get("--out", os.path.join(ROOT, "output", f"{inst}.jsonl")))
    both = sorted(set(team) & set(llm))
    consensus = {i: team[i] for i in both if team[i]["verdict"] == llm[i]["verdict"]}
    keys = {"team": team, "llm": llm, "consensus": consensus}

    if both:
        print(f"== team vs llm ({model}) on {len(both)} cases: they agree on {len(consensus)} "
              f"({len(consensus) / len(both):.0%}); cost of their disagreement per case {stats(confusion(team, llm, both))['cost_per_case']:.2f}")
        show_confusion(confusion(team, llm, both), "team", "llm")
    print("== system output vs each key")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    out = []
    for name, key in keys.items():
        ids = sorted(key)
        if not ids:
            continue
        m = confusion(key, system, ids)
        s = stats(m)
        print(f"  {name:<9} n={s['n']:<3} verdict agreement {s['agree']:.0%}   cost/case {s['cost_per_case']:.2f}   "
              f"saved {s['saved']:.0%} of escalate-all   WRONGFUL CLOSES {s['wrongful']}   closable closed {s['closable_closed']}/{s['closable']}")
        if name == "consensus":
            show_confusion(m)
        out.append([now, commit(), inst, name, s["n"], f"{s['agree']:.4f}", f"{s['cost_per_case']:.4f}", f"{s['saved']:.4f}",
                    s["wrongful"], s["closable_closed"], s["closable"]])
    diff = [i for i in both if team[i]["verdict"] != llm[i]["verdict"]]
    if diff:
        print(f"== {len(diff)} cases where team and llm differ (human look, then fix the label or the system):")
        for i in diff[: int(opt.get("--show", 30))]:
            print(f"  {i}: team {team[i]['verdict']} {team[i].get('reason_code')} | llm {llm[i]['verdict']} {llm[i].get('reason_code')} "
                  f"({llm[i].get('confidence')}) | system {system.get(i, {}).get('verdict')}")
            print(f"      team: {str(team[i].get('note'))[:230]}")
            print(f"      llm : {str(llm[i].get('rationale'))[:230]}")
    if "--log" in argv:
        new = not os.path.exists(HISTORY)
        with open(HISTORY, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["when", "commit", "institution", "key", "n", "agree", "cost_per_case", "saved", "wrongful",
                            "closable_closed", "closable"])
            w.writerows(out)
        print("logged to eval/history.csv")


if __name__ == "__main__":
    main(sys.argv[1:])
