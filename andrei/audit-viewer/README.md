# Decision Audit Trail

Demo page: https://claude.ai/artifact/87ZpLv46vxDZ5HKcVsGD3b (private until Andrei shares it).

Twelve example cases (one CLOSE, RFI and ESCALATE per institution, each matching our hand label) laid out as the
rulebook's yes/no questions per alert, with the SOP clause, facts and evidence behind each answer, plus the five-run
reproducibility table. Rebuild after code changes:

    for i in bank emoney investment payments_fx; do for n in 1 2 3 4 5; do system/run data/institutions/$i /tmp/runs/r_${i}_$n.jsonl; done; done
    python3 eval/audit_page.py andrei/audit-viewer/index.html /tmp/runs
