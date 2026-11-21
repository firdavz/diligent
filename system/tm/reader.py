"""D (Fedya): answers Questions about prose documents via OpenRouter. Never picks a verdict.

Contract: ask(question, bundle, tier) -> Answer(value="yes"|"no"|"unknown", quote, evidence, tier, model).
- Tier 1: fast/cheap model. Tier 2: bigger model, only for what tier 1 couldn't settle.
- temperature 0, fixed seed, JSON output; unparsable -> "unknown"; cache on disk in system/cache/ keyed by
  hash(model, prompt). Only send the question and the docs in question.doc_ids.
- No key (OPENROUTER_API_KEY unset) -> "unknown" for everything, so the system still runs on rules alone.

This stub returns "unknown" until the real client lands.
"""

from __future__ import annotations

import os

from .types import Answer, CaseBundle, Question

TIER_MODELS = {1: "x-ai/grok-4.3", 2: "x-ai/grok-4.7"}
MAX_TIER = 2


def enabled() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY"))


def ask(q: Question, b: CaseBundle, tier: int) -> Answer:
    return Answer(value="unknown", tier=tier, model="stub")
