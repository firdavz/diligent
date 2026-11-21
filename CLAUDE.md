# Team rules for coding agents (Claude Code, Cursor, Codex)

Track 1 alert triage. The design and the rules you must not break are in [`andrei/CLAUDE.md`](andrei/CLAUDE.md) and
[`andrei/ARCHITECTURE.md`](andrei/ARCHITECTURE.md): read them before changing code.

## Commit and push as you go
- Work on `track1-alert-closing`. `git pull --rebase` before you start and before every push.
- **After any labelling or label review** (lines added or changed in `eval/labels/*.jsonl`): run
  `python3 eval/score.py <institution>`, then commit and push straight away, e.g.
  `git add eval/labels && git commit -m "chore(eval): label N <institution> cases" && git push`.
  Labels only count once they are pushed: the scorer, the team board and the review desk all read the pushed copy.
- After any code change: run your institution(s) and score them; push only if wrongful closes stayed at 0.
- Small commits, conventional messages (`feat:`, `fix:`, `chore:`, `docs:`). Never commit the dataset (`data/`) or keys.

## Where to look
- Your work list: `andrei/<institution>-findings.md` (what decides each case shape).
- Live progress: the Track 1 Build Board (link in `andrei/board/README.md`).
- Doubtful labels to review: the Label Review Desk (link in `andrei/review-desk/README.md`).
