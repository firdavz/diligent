# Architecture (draft v2 — tiered escalation)

**One idea:** a case climbs a ladder of increasingly expensive readers and stops at the first rung that can settle it.
**Every rung only gathers facts. The same rulebook makes the verdict at every rung.** So escalating to a bigger model
buys better *reading*, never a different *policy*, and the answer stays reproducible and explainable.

```
               case
                │
                ▼
 ┌───────────────────────────────┐
 │ TIER 0 — RULES (free, ~ms)    │  load + parse "**Field:** value" docs, compute facts
 │ red flags (C) + explainers (B)│  → hard signals only
 └──────────────┬────────────────┘
                │ settled? ──── yes ──► DECIDE
                │ no (prose needed, or only partial explanation)
                ▼
 ┌───────────────────────────────┐
 │ TIER 1 — FAST GROK (D)        │  narrow yes/no questions on prose docs
 │ cheap, temp 0, cached         │  (chats, notes, letters, emails)
 └──────────────┬────────────────┘  → soft signals with quotes + IDs
                │ settled? ──── yes ──► DECIDE
                │ no (escalation trigger fired)
                ▼
 ┌───────────────────────────────┐
 │ TIER 2 — BIG GROK (D)         │  same questions, whole case in context,
 │ reasoning model, temp 0,      │  must quote the sentence it relies on
 │ cached, budget-capped         │
 └──────────────┬────────────────┘
                │ still unsettled ──► DECIDE treats it as unknown (never CLOSE)
                ▼
 ┌───────────────────────────────┐
 │ DECIDE (A) — one rulebook     │  per alert: red flag → ESCALATE
 │                               │             explained (≥1 hard signal) → CLOSE
 │                               │             else → RFI (what to ask)
 │                               │  per case: worst alert wins
 └──────────────┬────────────────┘
                ▼
   output line + trace (tier reached, signals, questions, answers, quotes)
```

## When a case climbs a tier (escalation triggers)
"Settled" means the rulebook would give the same verdict whatever the unanswered questions say.

| From → to | Trigger |
|---|---|
| 0 → 1 | An alert is neither explained nor red-flagged by hard signals, **and** a prose document is on file that could change that |
| 0 → 1 | A candidate `CLOSE` exists but a prose document (chat, note) could contradict it — always check before closing |
| 1 → 2 | Tier 1 answered `unknown`, or gave no quote, on a question that decides the verdict |
| 1 → 2 | Tier 1 contradicts a hard signal (e.g. says "explains" where amounts don't match) |
| 1 → 2 | The verdict would be `CLOSE` and rests on a tier-1 answer (the 10-point mistake gets the best reader) |
| 1 → 2 | `RFI` vs `ESCALATE` hinges on whether a chat shows suspicion (tipping-off rule) |
| stop | Tier 2 still `unknown` → treated as unknown: `RFI` if no suspicion, otherwise `ESCALATE` |

Hard red flags (sending-bank fraud report, confirmed listed party, structuring pattern) end at tier 0: `ESCALATE` without
spending a model call.

## Why this beats "cheap model decides, bigger model double-checks"
- **Reproducibility:** a verdict-picking model can flip between runs on borderline cases; a rulebook over cached answers
  can't. (20% of the score; the organisers stressed it.)
- **Explainability:** every verdict traces to rule → signal → quote → document ID. That's the reason text and the demo.
- **Cost goes where the risk is:** the big model is spent on would-be `CLOSE`s and genuine ambiguity, not on clear escalations.
- **Safety in one place:** unknown never closes, whichever tier it came from.

## Budget (≤ $4 and ≤ 30 min per 200 cases)
- Tier 0: every case, free.
- Tier 1: only cases with an open question and prose on file. ~1–3 short calls per case (one per question, or one batched call).
- Tier 2: capped at a fixed share of cases per run (start at 25%), ranked by risk (would-be `CLOSE` first). Over the cap → unknown.
- Thread pool of ~8–16 workers; per-call timeout; log tokens and cost per tier into the trace. D measures the real model prices
  on OpenRouter and sets the cap.

## Determinism
- Temperature 0, fixed seed, inputs sorted, prompt built only from the case's own data.
- Every answer cached on disk, key = hash(model, prompt) (`system/cache/`; see open question D6 in `DECISIONS.md`).
- The tier-2 cap is applied by a deterministic risk ranking, not by arrival order.
- JSON output with a fixed schema; an unparsable answer = `unknown` (never retried with different wording).

## Shared contract — `system/tm/types.py` (A owns it; change only by team agreement)

```python
@dataclass
class CaseBundle:
    institution: str; case: dict; alerts: list[dict]; customer: dict
    txns: dict[str, dict]            # id -> transaction (the customer's)
    docs: dict[str, dict]            # id -> {meta, text, fields}  (fields = parsed "**Key:** value" pairs)
    reviews: list[dict]; list_entries: dict[str, dict]
    policy: dict                     # thresholds + higher-risk countries for this institution

@dataclass
class Question:                      # raised by B or C when hard data can't settle an alert
    id: str                          # stable, e.g. "chat_explains_cash_source"
    alert_id: str
    text: str                        # yes/no question, filled with this case's facts
    doc_ids: list[str]               # the prose documents to read
    if_yes: "Signal"; if_no: "Signal"   # what each answer turns into

@dataclass
class Answer:
    value: Literal["yes", "no", "unknown"]; quote: str; evidence: list[str]; tier: int

@dataclass
class Signal:
    alert_id: str                    # which alert it concerns ("*" = the whole case)
    kind: Literal["red_flag", "explains", "partial", "unknown"]
    code: str                        # a reason code from the README table
    facts: str                       # one sentence with this case's names, amounts, dates
    evidence: list[str]              # IDs exactly as in the files
    strength: Literal["hard", "soft"] = "hard"   # soft = came from a model answer

def red_flags(b: CaseBundle) -> tuple[list[Signal], list[Question]]: ...    # C — system/tm/red_flags.py
def explainers(b: CaseBundle) -> tuple[list[Signal], list[Question]]: ...   # B — system/tm/explainers.py
def ask(q: Question, b: CaseBundle, tier: int) -> Answer: ...               # D — system/tm/reader.py
def decide(b, signals, open_questions) -> Decision: ...                     # A — system/tm/decide.py
def settled(b, signals, open_questions) -> bool: ...                        # A — same verdict whatever the open answers are
```

B and C never call the model themselves: they return `Question`s, and the orchestrator (A) walks the tiers, calling D's
`ask()` and turning answers into signals with `if_yes`/`if_no`. That keeps all four people decoupled.

## Policy specials the rulebook must respect (all four `POLICY.md`s)
- Own-account transfers explain activity only with a document showing the customer holds the other account;
  at ≥ 5× declared income/volume → `RFI_UPDATED_PROFILE`, below → `CLOSE` `OWN_ACCOUNT`.
- Internal-list match: evidence shows a different party → `CLOSE` `LIST_MATCH_DIFFERENT_PARTY`; nothing settles it and
  nothing else concerning → `RFI`; listed party is or controls the counterparty → `ESCALATE` `ESC_LISTED_PARTY`.
- An earlier review covers only what it describes, never new or larger activity.
- Payments and FX: a held payment of ≥ £10,000 to anyone other than the client needs an invoice or contract on file.
- Context only, never a trigger on its own: round amounts, shared device/IP/contact details, same-day recipient,
  crypto or gambling counterparties.
