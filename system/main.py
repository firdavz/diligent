"""Entry point: system/run <institution folder> <output file>."""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tm.audit import annotate, code_fp, fp  # noqa: E402
from tm.check import check  # noqa: E402
from tm.load import load_institution  # noqa: E402
from tm.pipeline import run_case  # noqa: E402
from tm.types import Decision  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def _safe(b):
    try:
        d = run_case(b)
    except Exception as e:  # one bad case must not lose the whole file
        d = Decision(
            case_id=b.case["case_id"], alert_ids=list(b.case["alert_ids"]), verdict="ESCALATE",
            reason_code="ESC_UNEXPLAINED_FUNDS",
            reason="The case could not be assessed automatically and is passed to the MLRO for review.",
            evidence=[t for a in b.alerts for t in a.get("transaction_ids", [])][:3],
            trace={"error": repr(e)},
        )
    problems = check(d, b)
    annotate(b, d)
    return d, problems


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: system/run <institution folder> <output file>", file=sys.stderr)
        return 2
    folder, out = os.path.abspath(argv[1]), os.path.abspath(argv[2])
    t0 = time.time()
    bundles = load_institution(folder)
    workers = int(os.environ.get("TM_WORKERS", "8"))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_safe, bundles))  # map keeps case order

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for d, _ in results:
            f.write(json.dumps(d.output_row(), ensure_ascii=False) + "\n")

    inst = os.path.basename(folder.rstrip("/"))
    trace_dir = os.path.join(HERE, "traces")
    os.makedirs(trace_dir, exist_ok=True)
    with open(os.path.join(trace_dir, f"{inst}.jsonl"), "w", encoding="utf-8") as f:
        for d, problems in results:
            f.write(json.dumps({**d.output_row(), "trace": d.trace, "problems": problems},
                               ensure_ascii=False, default=str) + "\n")

    from tm import reader
    manifest = {
        "institution": inst,
        "cases": len(results),
        "code_fp": code_fp(),
        "policy_fp": fp(bundles[0].policy.get("text", "")) if bundles else None,
        "models": reader.TIER_MODELS if reader.enabled() else "rules only (no OPENROUTER_API_KEY)",
        "output_fp": fp(open(out, encoding="utf-8").read()),
        "verdicts": dict(sorted(Counter(d.verdict for d, _ in results).items())),
        "paths": dict(sorted(Counter(a["path"] for d, _ in results for a in d.trace.get("alerts", [])).items())),
    }
    with open(os.path.join(trace_dir, f"{inst}.manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    problems = [p for _, ps in results for p in ps]
    errors = sum(1 for d, _ in results if "error" in d.trace)
    verdicts = Counter(d.verdict for d, _ in results)
    print(f"{inst}: {len(results)} cases in {time.time() - t0:.1f}s  {dict(verdicts)}  "
          f"errors={errors} problems={len(problems)}  output_fp={manifest['output_fp']} code_fp={manifest['code_fp']}",
          file=sys.stderr)
    for p in problems[:10]:
        print("  " + p, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
