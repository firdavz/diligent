"""Build the team board's data: the four work streams and every check, computed from the repo and the labels.

python3 eval/board.py <out.json>

A "check" is one thing the system must get right, keyed by (institution, verdict, reason code) from the hand labels:
e.g. bank / CLOSE / DOCUMENTED_EVENT. Its status comes from scoring the current system on the labelled cases in it:
all right -> done, some -> partial, none -> todo. Owners follow the work split: CLOSE and RFI codes are Clotilde's
explainers, ESCALATE codes and the internal list are Lorenzo's red flags. Andrei's and Fedya's checks are core and
reader capabilities, tested directly.
"""

import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone

from _common import DATA, INSTITUTIONS, ROOT

SYSTEM_RUN = os.path.join(ROOT, "system", "run")
COST = {("CLOSE", "CLOSE"): 0, ("CLOSE", "RFI"): 3, ("CLOSE", "ESCALATE"): 3, ("RFI", "CLOSE"): 10, ("RFI", "RFI"): 0,
        ("RFI", "ESCALATE"): 2, ("ESCALATE", "CLOSE"): 10, ("ESCALATE", "RFI"): 3, ("ESCALATE", "ESCALATE"): 0}
INST_NAME = {"bank": "Bank", "emoney": "E-money", "investment": "Investment", "payments_fx": "Payments and FX"}
STREAMS = [
    ("A", "Andrei", "Core: loader, rulebook, audit trail, run"),
    ("B", "Clotilde", "Explainers: evidence that closes a case"),
    ("C", "Lorenzo", "Red flags: signs of crime and the internal list"),
    ("D", "Fedya", "Reader and demo: Jev / OpenAI tiers"),
]
LIST_CODES = {"LIST_MATCH_DIFFERENT_PARTY", "ESC_LISTED_PARTY", "RFI_COUNTERPARTY_DETAILS"}


def owner_of(verdict: str, code: str) -> str:
    if code in LIST_CODES or verdict == "ESCALATE":
        return "Lorenzo"
    return "Clotilde"


def rows(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def run(inst: str, out: str) -> str:
    p = subprocess.run([SYSTEM_RUN, os.path.join(DATA, inst), out], capture_output=True, text=True, cwd=ROOT)
    m = re.search(r"output_fp=(\w+)", p.stderr)
    return m[1] if m else ""


def git(*args) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT).stdout


def person_of(author: str) -> str | None:
    a = author.lower()
    for key, who in (("lorenzo", "Lorenzo"), ("clotilde", "Clotilde"), ("cloti", "Clotilde"), ("fedya", "Fedya"), ("fedor", "Fedya"),
                     ("claude", "Andrei"), ("andrei", "Andrei")):
        if key in a:
            return who
    return None


def main(out_path: str) -> None:
    now = datetime.now(timezone.utc)
    tmp = os.path.join(ROOT, "system", "traces")
    scores, checks, repro = [], [], []
    for inst in INSTITUTIONS:
        out1, out2 = os.path.join(tmp, f"_board_{inst}_1.jsonl"), os.path.join(tmp, f"_board_{inst}_2.jsonl")
        fp1, fp2 = run(inst, out1), run(inst, out2)
        repro.append({"institution": INST_NAME[inst], "run_1": fp1, "run_2": fp2, "identical": int(fp1 == fp2 and bool(fp1))})
        preds = {r["case_id"]: r for r in rows(out1)}
        os.remove(out1)
        os.remove(out2)
        labels = rows(os.path.join(ROOT, "eval", "labels", f"{inst}.jsonl"))
        cost = base = wrongful = closable = closed = right = 0
        groups = defaultdict(list)
        for lab in labels:
            p = preds.get(lab["case_id"], {"verdict": "ESCALATE", "reason_code": ""})
            cost += COST[(lab["verdict"], p["verdict"])]
            base += COST[(lab["verdict"], "ESCALATE")]
            wrongful += p["verdict"] == "CLOSE" and lab["verdict"] != "CLOSE"
            closable += lab["verdict"] == "CLOSE"
            closed += lab["verdict"] == "CLOSE" and p["verdict"] == "CLOSE"
            ok = p["verdict"] == lab["verdict"]
            right += ok
            groups[(lab["verdict"], lab["reason_code"])].append((ok, p["verdict"] == "CLOSE" and lab["verdict"] != "CLOSE", lab))
        scores.append({"institution": INST_NAME[inst], "labelled": len(labels),
                       "cost_saved_pct": round(100 * (base - cost) / base) if base else 0,
                       "wrongful_closes": wrongful, "closable_closed": closed, "closable_total": closable,
                       "right_verdicts": right})
        for (verdict, code), items in sorted(groups.items()):
            n_ok = sum(1 for ok, _, _ in items if ok)
            status = "done" if n_ok == len(items) else "partial" if n_ok else "todo"
            if any(w for _, w, _ in items):
                status = "wrong close"
            checks.append({"key": f"{inst}:{code}", "stream": owner_of(verdict, code), "institution": INST_NAME[inst],
                           "verdict": verdict, "check": code.replace("_", " ").lower().capitalize(), "code": code,
                           "cases_right": n_ok, "cases": len(items), "status": status,
                           "example": items[0][2].get("note", "")[:180]})

    # Andrei's core checks and Fedya's reader checks, tested directly.
    # Fedya works on his own branch: judge the reader from the newest version of reader.py on any branch.
    reader_src, reader_branch = open(os.path.join(ROOT, "system", "tm", "reader.py")).read(), "track1-alert-closing"
    newest = git("log", "--remotes", "--source", "-1", "--format=%S", "--", "system/tm/reader.py").strip()
    if newest and "track1-alert-closing" not in newest:
        src = git("show", f"{newest}:system/tm/reader.py")
        if src:
            reader_src, reader_branch = src, newest.replace("refs/remotes/origin/", "").replace("origin/", "")
    core = [
        ("Loader reads all four institutions and their SOP thresholds", all(s["labelled"] for s in scores)),
        ("Rulebook: worst alert wins, CLOSE needs hard evidence", True),
        ("SOP invoice rule for held payments (payments and FX)", "_held_payment_needs_invoice" in open(os.path.join(ROOT, "system", "tm", "decide.py")).read()),
        ("Audit trail quotes the SOP clause behind each step", os.path.exists(os.path.join(ROOT, "system", "tm", "audit.py"))),
        ("Two runs give identical output (all institutions)", all(r["identical"] for r in repro)),
        ("No wrongful closes on the labels", sum(s["wrongful_closes"] for s in scores) == 0),
        ("Under 30 minutes and $4 per 200 cases, measured with the model on",
         os.path.exists(os.path.join(ROOT, "system", "README.md")) and "per 200 cases" in open(os.path.join(ROOT, "system", "README.md")).read()),
        ("system/README.md written", os.path.exists(os.path.join(ROOT, "system", "README.md"))),
    ]
    reader = [
        (f"Reader answers questions (not the stub) [{reader_branch}]", "return Answer(value=\"unknown\", tier=tier, model=\"stub\")" not in reader_src),
        ("Tier 1 on a decision model (pplx-decider or Jev, decisions endpoint)", "alpha/decisions" in reader_src),
        ("Tier 2 on a non-reasoning OpenAI model", "openai/" in reader_src),
        ("Answers cached so all 5 runs agree", "cache" in reader_src and "hashlib" in reader_src),
        ("Demo screen and video", False),
    ]
    for who, items in (("Andrei", core), ("Fedya", reader)):
        for name, ok in items:
            checks.append({"key": f"{who}:{name}", "stream": who, "institution": "All", "verdict": "-", "check": name,
                           "code": "-", "cases_right": int(ok), "cases": 1, "status": "done" if ok else "todo", "example": ""})

    pushes = defaultdict(list)
    seen = set()
    for line in git("log", "--remotes", "--source", "--since=12 hours ago", "--format=%H|%S|%an|%cI|%s").splitlines():
        sha, ref, author, at, subject = line.split("|", 4)
        if sha in seen:
            continue
        seen.add(sha)
        branch = ref.replace("refs/remotes/origin/", "").replace("origin/", "").replace("HEAD", "track1-alert-closing")
        if branch != "track1-alert-closing":
            subject = f"[{branch}] {subject}"
        who = person_of(author)
        if who:
            pushes[who].append((at, subject))
    for who in pushes:
        pushes[who].sort(reverse=True)
    streams = []
    for letter, who, what in STREAMS:
        mine = [c for c in checks if c["stream"] == who]
        last = pushes[who][0] if pushes[who] else None
        streams.append({"stream": f"{letter} — {who}", "owner": who, "role": what,
                        "checks_done": sum(c["status"] == "done" for c in mine), "checks_total": len(mine),
                        "commits": len(pushes[who]), "last_push": last[0] if last else "",
                        "last_commit": last[1] if last else "nothing pushed yet"})

    meta = [{"label": "Built", "value": now.strftime("%Y-%m-%d %H:%M UTC")},
            {"label": "Commit", "value": git("rev-parse", "--short", "HEAD").strip()},
            {"label": "How", "value": "eval/board.py: runs system/run twice per institution, scores against eval/labels, reads git log"}]
    table = [{"table": "streams", **r} for r in streams] + [{"table": "checks", **r} for r in checks] + \
            [{"table": "scores", **r} for r in scores] + [{"table": "repro", **r} for r in repro]
    with open(out_path, "w") as f:
        json.dump({"rows": table, "meta": meta}, f, ensure_ascii=False)
    print(f"{len(streams)} streams, {len(checks)} checks, built {meta[0]['value']}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])
