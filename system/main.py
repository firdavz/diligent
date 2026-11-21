"""Entry point: system/run <institution folder> <output file>."""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from functools import partial
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tm.audit import annotate, code_fp, fp  # noqa: E402
from tm.check import check  # noqa: E402
from tm.load import load_institution  # noqa: E402
from tm.live import LiveRun, intake_fields  # noqa: E402
from tm.pipeline import run_case  # noqa: E402
from tm.types import Decision  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def _safe(b, live: LiveRun | None = None):
    observe = live.case(b.case["case_id"]) if live else None
    try:
        if observe:
            observe("intake", "done", intake_fields(b))
        d = run_case(b, observe=observe) if observe else run_case(b)
    except Exception as e:  # one bad case must not lose the whole file
        if observe:
            observe("rulebook", "error", {"reason": "Automatic assessment failed. Referred for review."})
        d = Decision(
            case_id=b.case["case_id"], alert_ids=list(b.case["alert_ids"]), verdict="ESCALATE",
            reason_code="ESC_UNEXPLAINED_FUNDS",
            reason="The case could not be assessed automatically and is passed to the MLRO for review.",
            evidence=[t for a in b.alerts for t in a.get("transaction_ids", [])][:3],
            trace={"error": repr(e)},
        )
    if observe:
        observe("validate", "start", {})
    problems = check(d, b)
    annotate(b, d)
    if observe:
        observe("validate", "error" if problems else "done",
                {"problems": problems, "audit": d.trace.get("audit", {}), "alerts": d.trace.get("alerts", [])})
        observe("verdict", "done", d.output_row())
    return d, problems


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: system/run <institution folder> <output file>", file=sys.stderr)
        return 2
    folder, out = os.path.abspath(argv[1]), os.path.abspath(argv[2])
    live = LiveRun(Path(HERE) / "traces" / "live") if os.environ.get("TM_LIVE") == "1" else nullcontext()
    with live as stream:
        try:
            return _run(folder, out, stream)
        except Exception:
            if stream:
                stream.emit("run", "error", {"reason": "The run failed. See the engine terminal for details."})
            raise


def _run(folder: str, out: str, live: LiveRun | None) -> int:
    t0 = time.time()
    inst = os.path.basename(folder.rstrip("/"))
    if live:
        live.emit("run", "start", {"institution": inst})
    bundles = load_institution(folder)
    if live:
        live.emit("run", "ready", {"cases": len(bundles)})
    workers = int(os.environ.get("TM_WORKERS", "8"))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(partial(_safe, live=live), bundles))  # map keeps case order

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for d, _ in results:
            f.write(json.dumps(d.output_row(), ensure_ascii=False) + "\n")

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
    if live:
        live.emit("run", "done", {"cases": len(results), "verdicts": dict(verdicts),
                                 "errors": errors, "problems": len(problems), "output_fp": manifest["output_fp"]})
    print(f"{inst}: {len(results)} cases in {time.time() - t0:.1f}s  {dict(verdicts)}  "
          f"errors={errors} problems={len(problems)}  output_fp={manifest['output_fp']} code_fp={manifest['code_fp']}",
          file=sys.stderr)
    for p in problems[:10]:
        print("  " + p, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
