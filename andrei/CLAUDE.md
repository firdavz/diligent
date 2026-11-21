# Agent instructions — Track 1 alert triage

Read `DECISIONS.md` and `ARCHITECTURE.md` before changing code. They are the source of truth.

## Rules you must not break (they are competition rules or scoring-critical)
- `system/` uses the **Python 3 standard library only**. Never add a dependency or a `requirements.txt` for it.
- Models only via OpenRouter (`https://openrouter.ai/api/v1/chat/completions`, key from `OPENROUTER_API_KEY`),
  temperature 0, fixed seed, cached in `system/cache/`.
- `system/` reads only the institution folder it is given and writes only the output file and files inside `system/`.
  No paths relative to the caller's working directory.
- **Never put development-case data into `system/`**: no case IDs, customer names, amounts, document IDs or verdicts,
  in code, prompts, tests or comments. Generalise from the policy and the evidence.
- Never commit the dataset (`data/`, `institutions/`), labels (`eval/labels/`) or keys. The repo is public.
- The model never picks a verdict. Rules do. `unknown` never leads to `CLOSE`.
- A `CLOSE` needs every alert explained, no red flag, and at least one "hard" (structured-data) signal.
- Rules key on document **content** (amounts, payees, dates, parties), never on which document types are present.
- Thresholds come from the institution's policy, never hard-coded in shared code.
- Every `Signal` carries a reason code, one sentence of this case's own facts, and evidence IDs that exist.
- `system/tm/types.py` is the shared contract; change it only when the team agrees.

## Commands
```bash
system/run data/hackathon/institutions/bank output/bank.jsonl   # one institution
python3 eval/score.py bank                                       # score against eval/labels/bank.jsonl
python3 eval/view.py <case_id>                                   # print one case on one screen
```
