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
from .red_flags import red_flags
from .types import CaseBundle, Decision, Question, Signal


def _answer_to_signal(q: Question, value: str) -> Signal | None:
    s = q.if_yes if value == "yes" else q.if_no if value == "no" else None
    return replace(s, strength="soft") if s else None


def run_case(b: CaseBundle) -> Decision:
    signals: list[Signal] = []
    questions: list[Question] = []
    for produce in (red_flags, explainers):
        s, q = produce(b)
        signals += s
        questions += q

    answers: list[dict] = []
    open_qs = sorted(questions, key=lambda q: (q.alert_id, q.id))  # deterministic order
    if reader.enabled():
        for tier in range(1, reader.MAX_TIER + 1):
            if not open_qs:
                break
            still_open = []
            for q in open_qs:
                a = reader.ask(q, b, tier)
                answers.append({"question": q.id, "alert_id": q.alert_id, "text": q.text, **vars(a)})
                sig = _answer_to_signal(q, a.value)
                if sig:
                    signals.append(sig)
                elif a.value == "unknown":
                    still_open.append(q)
            open_qs = still_open

    return decide(b, signals, answers)
