# Alert triage — Fin Crime Hackathon, Track 1 (Transaction monitoring)

A system that reads transaction-monitoring alerts with their evidence and decides, per case,
`CLOSE`, `RFI` or `ESCALATE`, with a reason code, a case-specific reason and the evidence IDs it relied on.

**Principle: the model reads, code decides.** A case climbs tiers — rules, then fast Grok, then big Grok (via OpenRouter) —
stopping at the first that settles it; one rulebook makes every verdict, and model answers are cached so five runs agree.

| Doc | What's in it |
|---|---|
| [`DECISIONS.md`](DECISIONS.md) | Every decision made so far, and why |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | The pipeline, the shared contracts, the decision logic |
| [`TEAM.md`](TEAM.md) | Who owns what, milestones, house rules |
| [`SCORING.md`](SCORING.md) | The brief's constraints and cost maths, and what they imply |
| [`DATA.md`](DATA.md) | What the dataset looks like and how we tune without labels |
| [`RULES.md`](RULES.md) | Every rule and policy setting in the brief, and where the code enforces it |
| [`bank-findings.md`](bank-findings.md) | What decides each bank case shape: the work list for explainers and red flags |
| [`emoney-findings.md`](emoney-findings.md) | Same for e-money |
| [`investment-findings.md`](investment-findings.md) | Same for investment |
| [`kickoff-transcript.md`](kickoff-transcript.md) | The organisers' kick-off talk (Granola transcript) and what it means for us |
| [`CLAUDE.md`](CLAUDE.md) | Rules for coding agents (Claude Code, Cursor, Codex) working in this repo |

## Layout

```
system/        the submission: system/run <institution folder> <output file>, plus system/README.md
output/        our system's answers on the development cases, one file per institution
eval/          scorer, case viewer, hand labels — never read by system/ (labels are git-ignored)
andrei/        these notes (Andrei's decisions and design)
```

The dataset is **not** in this repo (participants only). Put it at `data/hackathon/` locally — it's git-ignored.
