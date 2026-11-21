"""Run the fixed BinEval threshold experiment on a case list before opening its reference labels."""

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import bineval
from _common import DATA, INSTITUTIONS, ROOT, bundles, institution_of
from metrics import VERDICTS, stats
from score import rows
from tm import pipeline
from tm.audit import code_fp

EXPERIMENT = {"r_contradict": 0.60, "r_corridor": 0.60}
MODES = ("rules", "bineval_070", "bineval_candidate")


def previously_answered():
    root = Path(ROOT) / "eval"
    return {
        path.stem
        for folder in ("results/bineval", "drafts/bineval")
        for path in (root / folder).glob("sop-*/*/*.json")
    }


def read_references(paths):
    reference = {}
    for path in paths:
        labels = rows(path)
        if labels.keys() & reference.keys():
            raise SystemExit("Reference files must contain disjoint case IDs. Score each labeller separately.")
        reference.update(labels)
    return reference


def fresh_sample():
    """Select by institution from the case inventory, independent of verdicts."""
    root = Path(ROOT)
    excluded = previously_answered()
    for folder in ("labels", "labels_model", "drafts/llm"):
        for path in (root / "eval" / folder).glob("*.jsonl"):
            excluded.update(rows(path))
    rng = random.Random("bineval-threshold-holdout-v1")
    for inst in INSTITUTIONS:
        n = 40 if inst == "payments_fx" else 20
        pool = sorted(set(rows(root / "output" / f"{inst}.jsonl")) - excluded)
        if len(pool) < n:
            raise SystemExit(f"{inst}: only {len(pool)} eligible cases, need {n}")
        yield from sorted(rng.sample(pool, n))


def unseen_reference_ids(paths):
    reference = read_references(paths)
    seen = previously_answered()
    for file in (Path(ROOT) / "eval" / "labels").glob("*.jsonl"):
        seen.update(rows(file))
    eligible = sorted(c for c in reference.keys() - seen if reference[c].get("verdict") in VERDICTS)
    if not eligible:
        raise SystemExit("No valid reference verdicts for cases outside previously labelled or answered cases.")
    return eligible


def review_needed(rule_decision, bin_verdict):
    if rule_decision.verdict == "CLOSE" or rule_decision.verdict == bin_verdict:
        return False
    if rule_decision.verdict == "ESCALATE":
        # Preserve positive red flags. Disagreements on fallback escalations can be reviewed.
        return not any(a["path"] == "red_flag" for a in rule_decision.trace["alerts"])
    return True


def predict(ids_path):
    ids = Path(ids_path).read_text(encoding="utf-8").split()
    if not ids or len(set(ids)) != len(ids):
        raise SystemExit("The case list must be nonempty and have unique IDs.")
    selected = {inst: set() for inst in INSTITUTIONS}
    for cid in ids:
        try:
            selected[institution_of(cid)].add(cid)
        except KeyError:
            raise SystemExit(f"Unrecognised case prefix: {cid}") from None
    fingerprint = code_fp()
    for inst, wanted in selected.items():
        if not wanted:
            continue
        policy_path = Path(DATA) / inst / "POLICY.md"
        if not policy_path.is_file():
            raise SystemExit(f"Missing {policy_path}. Point TM_DATA at the institutions directory.")
        policy = policy_path.read_text(encoding="utf-8")
        cases = {b.case["case_id"]: b for b in bundles(inst) if b.case["case_id"] in wanted}
        if missing := wanted - cases.keys():
            raise SystemExit(f"{inst}: {len(missing)} requested cases are missing from the dataset.")
        for cid, case in cases.items():
            with patch.object(pipeline.reader, "enabled", return_value=False):
                rule = pipeline.run_case(case)
            text = subprocess.run(
                [sys.executable, str(Path(ROOT) / "eval" / "view.py"), cid],
                check=True, capture_output=True, text=True,
            ).stdout
            got = bineval.ask(cid, inst, {"sop": policy, "case_file": text},
                              bineval.build_questions(policy, case.alerts))
            if not got:
                raise SystemExit(f"No BinEval response for {cid}. Retry to reuse completed cache entries.")
            baseline = bineval.decide(got["answers"], case)
            candidate = bineval.decide(got["answers"], case, red_thresholds=EXPERIMENT)
            yield {
                "case_id": cid,
                "institution": inst,
                "code_fp": fingerprint,
                "bank_version": bineval.BANK_VERSION,
                "model": got["model"],
                "rules": [rule.verdict, rule.reason_code],
                "bineval_070": baseline,
                "bineval_candidate": candidate,
                "hybrid_review": review_needed(rule, candidate[0]),
            }


def compare(predictions_path, label_paths):
    predictions = rows(predictions_path)
    reference = read_references(label_paths)
    if not predictions:
        raise SystemExit("No predictions to score.")
    if missing := predictions.keys() - reference.keys():
        raise SystemExit(f"The reference is missing labels for {len(missing)} predicted cases.")
    if any(reference[c]["verdict"] not in VERDICTS for c in predictions):
        raise SystemExit("Each predicted case needs a reference verdict of CLOSE, RFI or ESCALATE.")

    report = {"red_threshold_overrides": EXPERIMENT, "results": {}}
    for inst in (*INSTITUTIONS, "all"):
        cases = [r for r in predictions.values() if inst == "all" or r["institution"] == inst]
        if not cases:
            continue
        result = report["results"][inst] = {}
        for mode in MODES:
            confusion = {(actual, pred): 0 for actual in VERDICTS for pred in VERDICTS}
            for row in cases:
                confusion[reference[row["case_id"]]["verdict"], row[mode][0]] += 1
            result[mode] = stats(confusion)
            result[mode]["missed_escalations"] = sum(confusion["ESCALATE", v] for v in ("RFI", "CLOSE"))
            result[mode]["extra_escalations"] = sum(confusion[v, "ESCALATE"] for v in ("RFI", "CLOSE"))
            coded = [r for r in cases if reference[r["case_id"]].get("reason_code")]
            result[mode]["reason_codes"] = {
                "reference_count": len(coded),
                "matches": sum(r[mode][1] == reference[r["case_id"]]["reason_code"] for r in coded),
            }
        flagged = [r for r in cases if r["hybrid_review"]]
        result["hybrid_review"] = {
            "queued": len(flagged),
            "rules_errors_queued": sum(r["rules"][0] != reference[r["case_id"]]["verdict"] for r in flagged),
            "candidate_matches_reference_in_queue": sum(
                r["bineval_candidate"][0] == reference[r["case_id"]]["verdict"] for r in flagged
            ),
        }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("sample", help="print 100 case IDs outside the known evaluation samples")
    select = commands.add_parser("unseen", help="print unseen IDs with verdicts from an independent labeller")
    select.add_argument("--reference", nargs="+", required=True)
    run = commands.add_parser("predict", help="save predictions without loading reference labels")
    run.add_argument("--ids", required=True)
    run.add_argument("--out", type=Path, required=True)
    score = commands.add_parser("score", help="compare saved predictions to independent reference JSONL")
    score.add_argument("--predictions", required=True)
    score.add_argument("--reference", nargs="+", required=True)
    args = parser.parse_args()

    if args.action == "sample":
        print("\n".join(fresh_sample()))
    elif args.action == "unseen":
        print("\n".join(unseen_reference_ids(args.reference)))
    elif args.action == "predict":
        predictions = list(predict(args.ids))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("".join(json.dumps(r) + "\n" for r in predictions), encoding="utf-8")
        print(f"Saved {len(predictions)} blind predictions to {args.out}.")
    else:
        print(json.dumps(compare(args.predictions, args.reference), indent=2))


if __name__ == "__main__":
    main()
