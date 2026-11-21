"""One readable file of the cases worth a human look for an institution, worst first.

python3 eval/doubts.py <institution> [--out output/<inst>.jsonl] [--llm openai_gpt-5.6-luna]
-> eval/drafts/doubts_<institution>.md  (git-ignored: it contains case data)

A case is in when: the system disagrees with a team label (gold); or with a confident model label (silver, p_verdict >= 0.7);
or the silver label is unsure (p_verdict < 0.7); or a blind labeller (--llm) disagrees with the system. Each case shows every
opinion side by side, the system's reason, and the full case as the labellers saw it.
"""

import json
import os
import sys

from _common import ROOT, bundles
import llm_label as L
from metrics import rows
from score import COST


def main(argv):
    inst = argv[0]
    opt = {argv[i]: argv[i + 1] for i in range(1, len(argv) - 1) if argv[i].startswith("--")}
    system = rows(opt.get("--out", os.path.join(ROOT, "output", f"{inst}.jsonl")))
    gold = rows(os.path.join(ROOT, "eval", "labels", f"{inst}.jsonl"))
    silver = rows(os.path.join(ROOT, "eval", "labels_model", f"{inst}.new.jsonl"))
    llm = rows(os.path.join(ROOT, "eval", "drafts", "llm", f"{inst}.{opt.get('--llm', 'openai_gpt-5.6-luna')}.jsonl"))
    picked = {}
    for cid, s in system.items():
        why, worst = [], 0
        for name, key in (("gold", gold), ("silver", silver), ("blind", llm)):
            lab = key.get(cid)
            if not lab:
                continue
            unsure = name == "silver" and lab.get("p_verdict", 1) < 0.7
            if lab["verdict"] != s["verdict"]:
                worst = max(worst, COST[(lab["verdict"], s["verdict"])] * (0.5 if unsure else 1))
                why.append(f"{name} says {lab['verdict']}")
            elif unsure:
                why.append("silver unsure")
        if why and (worst or "silver unsure" in why):
            picked[cid] = (worst, why)
    order = sorted(picked, key=lambda c: (-picked[c][0], c))
    bs = {b.case["case_id"]: b for b in bundles(inst)}
    out = [f"# {inst}: {len(order)} cases worth a look, worst first\n",
           "Weight = cost from the brief's table if the other opinion is right (10 = the system would wrongly close). "
           "gold = team label, silver = pplx-decider model label (p = its probability), blind = blind model labeller.\n"]
    for n, cid in enumerate(order, 1):
        s, (w, why) = system[cid], picked[cid]
        out.append(f"\n---\n\n## {n}. {cid} — weight {w:g} — {'; '.join(why)}\n")
        out.append(f"- **System:** {s['verdict']} / {s['reason_code']}: {s['reason']}  \n  evidence: {', '.join(s.get('evidence', []))}")
        if cid in gold:
            g = gold[cid]
            out.append(f"- **Gold (team):** {g['verdict']} / {g.get('reason_code')}: {g.get('note', '')}")
        if cid in silver:
            v = silver[cid]
            out.append(f"- **Silver (pplx, p={v.get('p_verdict', 0):.2f}):** {v['verdict']} / {v.get('reason_code')}")
        if cid in llm:
            m = llm[cid]
            why_not = (m.get("why_not") or {}).get(s["verdict"]) if isinstance(m.get("why_not"), dict) else None
            out.append(f"- **Blind ({m.get('confidence')}):** {m['verdict']} / {m.get('reason_code')}: {m.get('rationale', '')}"
                       + (f"  \n  why not {s['verdict']}: {why_not}" if why_not else "")
                       + (f"  \n  doubts: {m['doubts']}" if m.get("doubts") else ""))
        out.append(f"\n<details><summary>Full case</summary>\n\n```\n{L.render(bs[cid])}\n```\n</details>")
    path = os.path.join(ROOT, "eval", "drafts", f"doubts_{inst}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"{inst}: {len(order)} cases -> {path}")


if __name__ == "__main__":
    main(sys.argv[1:])
