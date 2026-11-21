"""Where a blind model and the system disagree, ranked by how bad it would be if the model were right.

python3 eval/disagreements.py <institution> [--llm grok-bot] [--out output/<inst>.jsonl] [--top 15]

severity = cost from the brief's table if the model is right (10: the system CLOSES a case the model would RFI/ESCALATE;
3: the system escalates or RFIs something closable, or RFIs an escalation; 2: ESCALATE where the model says RFI),
weighted by the model's confidence. Each line shows the model's reason for REJECTING the system's verdict (why_not), so a
human can tell quickly whether the disagreement is serious. Full report: eval/drafts/disagreements_<inst>.md (git-ignored).
"""

import json
import os
import sys
from collections import Counter

from _common import ROOT
from metrics import rows
from score import COST

CLASS = {10: "GRAVE", 3: "MEDIA", 2: "LIEVE"}


def main(argv):
    inst = argv[0]
    opt = {argv[i]: argv[i + 1] for i in range(1, len(argv) - 1) if argv[i].startswith("--")}
    tag = opt.get("--llm", "grok-bot")
    llm = rows(os.path.join(ROOT, "eval", "drafts", "llm", f"{inst}.{tag}.jsonl"))
    system = rows(opt.get("--out", os.path.join(ROOT, "output", f"{inst}.jsonl")))
    team = rows(os.path.join(ROOT, "eval", "labels", f"{inst}.jsonl"))
    both = sorted(set(llm) & set(system))
    if not both:
        return print(f"no overlap between {tag} labels and the system output for {inst}")
    out = []
    for cid in both:
        m, s = llm[cid], system[cid]
        if m["verdict"] == s["verdict"]:
            continue
        cost = COST[(m["verdict"], s["verdict"])]
        c = m.get("confidence")
        conf = {"high": 85.0, "medium": 65.0, "low": 45.0}.get(str(c).lower()) or (float(c) if isinstance(c, (int, float)) else 50.0)
        why = (m.get("why_not") or {}).get(s["verdict"], "") if isinstance(m.get("why_not"), dict) else ""
        out.append({"case_id": cid, "cost": cost, "class": CLASS[cost], "severity": round(cost * conf / 100, 2), "conf": conf,
                    "model": m, "system": s, "why_not_system": why, "team": team.get(cid, {}).get("verdict")})
    out.sort(key=lambda r: (-r["severity"], r["case_id"]))
    agree = len(both) - len(out)
    print(f"{inst}: {tag} vs system on {len(both)} cases: agree {agree} ({agree / len(both):.0%}), disagree {len(out)}")
    print("  by class:", dict(Counter(r["class"] for r in out)), "  by (model -> system):",
          dict(Counter(f"{r['model']['verdict']}->{r['system']['verdict']}" for r in out)))
    teamed = [r for r in out if r["team"]]
    if teamed:
        print(f"  where a team label exists ({len(teamed)}): team sides with the model {sum(r['team'] == r['model']['verdict'] for r in teamed)}, "
              f"with the system {sum(r['team'] == r['system']['verdict'] for r in teamed)}")
    for r in out[: int(opt.get("--top", 15))]:
        print(f"  [{r['class']} {r['severity']:.1f}] {r['case_id']}: model {r['model']['verdict']} {r['model'].get('reason_code')} "
              f"({r['conf']:.0f}%) vs system {r['system']['verdict']} {r['system']['reason_code']}"
              + (f" | team {r['team']}" if r["team"] else ""))
        print(f"      why not {r['system']['verdict']}: {r['why_not_system'][:220] or '(not given)'}")
    path = os.path.join(ROOT, "eval", "drafts", f"disagreements_{inst}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {inst}: {tag} vs system, {len(out)} disagreements, worst first\n")
        for r in out:
            m, s = r["model"], r["system"]
            f.write(f"\n## [{r['class']} {r['severity']:.1f}] {r['case_id']}\n"
                    f"- **Model**: {m['verdict']} / {m.get('reason_code')} ({r['conf']:.0f}%). SOP: {m.get('sop_basis')}\n"
                    f"  - {m.get('rationale')}\n"
                    f"  - Why not {s['verdict']}: {r['why_not_system'] or '(not given)'}\n"
                    f"  - Doubts: {m.get('doubts') or '-'}\n"
                    f"- **System**: {s['verdict']} / {s['reason_code']}: {s['reason']}\n"
                    + (f"- **Team label**: {r['team']}\n" if r["team"] else ""))
    print("report:", path)


if __name__ == "__main__":
    main(sys.argv[1:])
