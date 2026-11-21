"""A self-contained BLIND folder for Grok Bot (or any agent) to label cases, and the collector that reads its answers back.

python3 eval/grok_task.py make [--per-shape 2]   -> eval/drafts/grok_task/  (git-ignored)
    README.md          the instructions (SOP-first method, answer format, valid reason codes)
    policy/<inst>.md   each institution's POLICY.md
    cases/<inst>/<case_id>.txt   one case rendered as plain text; ONLY cases that have no team label yet
    out/<inst>/        where the agent writes one <case_id>.json per case
python3 eval/grok_task.py collect  -> eval/drafts/llm/<inst>.grok-bot.jsonl, then: python3 eval/metrics.py <inst> --llm grok-bot

Point the agent at eval/drafts/grok_task/ ONLY: nothing in it shows the team labels or what the system answered.
"""

import json
import os
import shutil
import sys
import types

from _common import DATA, INSTITUTIONS, ROOT, bundles
import llm_label as L
from tm.types import CODES

TASK = os.path.join(ROOT, "eval", "drafts", "grok_task")


def readme() -> str:
    method = L.SYSTEM.split("--- SOP ---")[0].replace("Answer with ONE JSON object and nothing else:", "ANSWER FORMAT: write ONE JSON object per case:")
    codes = "\n".join(f"  {v}: {', '.join(c)}" for v, c in CODES.items())
    return f"""# Task: label transaction-monitoring cases

You are labelling cases for an evaluation. Work ONLY inside this folder. Do not open any file outside it and do not look for
answers elsewhere: the point is an independent opinion.

For each institution (bank, emoney, investment, payments_fx):
1. Read `policy/<institution>.md` completely. It is the SOP and the source of truth.
2. For every file in `cases/<institution>/`, read the case and decide.
3. Write your answer to `out/<institution>/<case_id>.json` (same file name as the case, `.json`). One file per case, valid JSON, nothing else in it.
Do every case. When unsure, still choose, with confidence "low". Never invent IDs: `key_evidence` may only contain IDs that appear in the case file.

{method}
Valid reason codes (the code MUST belong to the verdict):
{codes}

The case file lists the alerts, the transactions behind them, the matched internal-list entries, earlier reviews and every document on file.
"""


def make(per_shape: int) -> None:
    shutil.rmtree(TASK, ignore_errors=True)
    os.makedirs(os.path.join(TASK, "policy"))
    n = 0
    for inst in INSTITUTIONS:
        shutil.copy(os.path.join(DATA, inst, "POLICY.md"), os.path.join(TASK, "policy", f"{inst}.md"))
        os.makedirs(os.path.join(TASK, "cases", inst))
        os.makedirs(os.path.join(TASK, "out", inst))
        bs = {b.case["case_id"]: b for b in bundles(inst)}
        ids = L.pick(types.SimpleNamespace(inst=inst, ids=f"shapes:{per_shape}"), bs)
        for cid in ids:
            with open(os.path.join(TASK, "cases", inst, cid + ".txt"), "w", encoding="utf-8") as f:
                f.write(L.render(bs[cid]))
        n += len(ids)
        print(inst, len(ids), "cases")
    with open(os.path.join(TASK, "README.md"), "w", encoding="utf-8") as f:
        f.write(readme())
    print(f"{n} cases in {TASK}")


def collect() -> None:
    for inst in INSTITUTIONS:
        d = os.path.join(TASK, "out", inst)
        rows, bad = [], []
        for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            try:
                j = json.load(open(os.path.join(d, name), encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                bad.append(name)
                continue
            ok = j.get("verdict") in CODES and j.get("reason_code") in CODES.get(j.get("verdict"), ())
            if not ok:
                bad.append(name)
                continue
            rows.append({"case_id": name[:-5], **{k: j.get(k) for k in ("verdict", "reason_code", "sop_basis", "key_evidence", "confidence", "rationale")}, "valid": True})
        out = os.path.join(ROOT, "eval", "drafts", "llm", f"{inst}.grok-bot.jsonl")
        with open(out, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"{inst}: {len(rows)} labels collected, unusable files: {len(bad)} {bad[:3]}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("make", "collect"):
        sys.exit(__doc__)
    if sys.argv[1] == "make":
        make(int(sys.argv[sys.argv.index("--per-shape") + 1]) if "--per-shape" in sys.argv else 2)
    else:
        collect()
