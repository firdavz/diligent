"""One case through the tier ladder. Owned by A.

Tier 0: B's explainers + C's red flags (rules, no model) -> signals + open questions.
Tier 1..MAX: D's reader answers the open questions; "yes"/"no" become soft signals, "unknown" climbs a tier.
Then the rulebook (decide) makes the verdict. The model never chooses it.
"""

from __future__ import annotations

from dataclasses import replace

from . import reader
from .decide import decide
from .explainers import explainers
from .live import Observe, question_fields
from .red_flags import red_flags
from .types import CaseBundle, Decision, Question, Signal


def _answer_to_signal(q: Question, value: str) -> Signal | None:
    s = q.if_yes if value == "yes" else q.if_no if value == "no" else None
    return replace(s, strength="soft") if s else None


def run_case(b: CaseBundle, observe: Observe | None = None) -> Decision:
    signals: list[Signal] = []
    questions: list[Question] = []
    for produce in (red_flags, explainers):
        if observe:
            stage = produce.__name__
            observe(stage, "start", {})

            def on_check(name, found, raised):
                observe(stage, "check", {"function": name, "signals": [vars(s) for s in found],
                                         "questions": [question_fields(q) for q in raised]})

            s, q = produce(b, on_check)
            observe(stage, "done", {"signal_count": len(s), "question_count": len(q)})
        else:
            s, q = produce(b)
        signals += s
        questions += q

    answers: list[dict] = []
    open_qs = sorted(questions, key=lambda q: (q.alert_id, q.id))  # deterministic order
    reader_enabled = reader.enabled()
    if observe:
        if not open_qs or not reader_enabled:
            observe("reader", "skip", {"reason": "No reader questions" if not open_qs else "Model access not configured",
                                       "questions": [question_fields(q) for q in open_qs]})
        else:
            observe("reader", "start", {"questions": [question_fields(q) for q in open_qs]})
    if reader_enabled:
        for tier in range(1, reader.MAX_TIER + 1):
            if not open_qs:
                break
            still_open = []
            for q in open_qs:
                if observe:
                    observe("reader", "question", {**question_fields(q), "tier": tier,
                                                   "model": reader.TIER_MODELS.get(tier)})
                a = reader.ask(q, b, tier)
                answers.append({"question": q.id, "alert_id": q.alert_id, "text": q.text, **vars(a)})
                sig = _answer_to_signal(q, a.value)
                if observe:
                    observe("reader", "answer", {**answers[-1], "signal": vars(sig) if sig else None})
                if sig:
                    signals.append(sig)
                elif a.value == "unknown":
                    still_open.append(q)
            open_qs = still_open

    if observe:
        if answers:
            observe("reader", "done", {"answer_count": len(answers), "unresolved": len(open_qs)})
        observe("rulebook", "start", {"signal_count": len(signals), "answer_count": len(answers)})
    decision = decide(b, signals, answers)
    if observe:
        observe("rulebook", "done", {"verdict": decision.verdict, "reason_code": decision.reason_code,
                                     "alerts": decision.trace.get("alerts", [])})
    return decision
