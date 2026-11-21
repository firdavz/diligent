# The reader (role D, Fedya)

Code: `system/tm/reader.py`. Tests: `system/tests/test_reader.py`. Checks: `eval/reader_smoke.py`, `eval/reader_check.py`.

## What it does
- The rules (`red_flags.py`, `explainers.py`) raise yes/no **questions** about prose documents (support chats, emails).
- The reader answers each question with `yes`, `no` or `unknown`, and gives the IDs of the documents it read.
- The reader **never picks a verdict**. The rulebook (`decide.py`) does. A model answer is a "soft" signal, so it can
  never close a case on its own, and `unknown` never leads to `CLOSE`.
- Only the question and the documents named in the question are sent. Nothing else from the case.

## Models (decisions D17, D18)
| Tier | Model | Endpoint | Output |
|---|---|---|---|
| 1 | `typesafe/jev-1.13` (pinned snapshot `jev-1.13-20260917`) | `POST /api/alpha/decisions`, type `noul` | probability that the answer is yes |
| 2 | `openai/gpt-4.1-mini` | `POST /api/v1/chat/completions`, JSON mode | `{"answer", "quote", "evidence"}` |

A question goes to tier 2 only if tier 1 says `unknown`.

## Thresholds
- Tier 1: round the probability to 2 decimals, then **≥ 0.90 → yes**, **≤ 0.10 → no**, anything between → unknown.
  The probability is stored on the answer, so the audit trail can show it.
- Tier 2: temperature 0, seed 7, max 400 tokens. A `yes` must come with a quote that is found word for word in one of
  the documents (checked in code). No valid quote → `unknown`.

## Cache and reproducibility
- Every answer is saved in `system/cache/reader/`, keyed by a SHA-256 of (prompt version, endpoint, full request body).
  A cached answer is returned without a call. `TM_READER_CACHE=0` turns the cache off (to test the models themselves).
- Change `PROMPT_VERSION` whenever a prompt changes, so old answers are not reused.
- Every call (live or cached) is logged in `system/traces/reader_calls.jsonl` with tier, model, seconds and cost.
- The cache and traces are git-ignored.

## Failures
No key, no documents, HTTP error, timeout, rate limit, or an answer we cannot read → `unknown`. Never an exception into
the pipeline. Timeout 20 s per attempt, one retry of the identical request (on 429, 5xx or network error) after 1.5 s.

## Measured results (21 Nov 2026)
`eval/reader_check.py <institution>` on 1,000 development cases per institution, scored against `eval/labels/`.
Code on `track1-alert-closing` (`code_fp 373fe4a4a87edfd5`), models as above.

| | payments_fx | bank | emoney | investment |
|---|---|---|---|---|
| Labelled cases | 55 | 58 | 53 | 60 |
| **Wrongful closes**, without → with reader | 0 → **0** | 0 → **0** | 0 → **0** | 0 → **0** |
| % of escalate-all cost saved, without → with | 17% → 17% | 64% → 64% | 71% → 71% | 51% → 51% |
| Closable closed, without → with | 2/24 → 2/24 | 18/29 → 18/29 | 18/25 → 18/25 | 17/28 → 17/28 |
| Right reason code, without → with | 13/23 → 13/23 | 37/43 → 37/43 | 33/42 → 32/42 | 30/36 → 30/36 |
| run1 == run2 (verdict + code) | 1000/1000 | 1000/1000 | 1000/1000 | 1000/1000 |
| Questions asked | 0 | 180 | 128 | 95 |
| Model calls (tier 1 / tier 2) | 0 | 307 (180 / 127) | 218 (128 / 90) | 136 (95 / 41) |
| Settled by tier 1 (Jev) | – | 53 of 180 | 38 of 128 | 54 of 95 |
| Still unknown after tier 2 | – | 12 | 1 | 1 |
| Errors | 0 | 0 | 0 | 0 |
| Cost (first run, empty cache) | $0.0000 | $0.0244 | $0.0175 | $0.0088 |

The live calls were made on `fedya/reader` (`code_fp f7110bcd6cb57f5e`). The re-check on `track1-alert-closing`
asked exactly the same questions, so every answer came from the cache (0 new calls).

Per call (661 live calls, 0 errors):

| Tier | Calls | Cost per call | Median time | 95th percentile | Slowest |
|---|---|---|---|---|---|
| 1 Jev | 403 | $0.000024 | 0.24 s | 0.44 s | 2.4 s |
| 2 gpt-4.1-mini | 258 | $0.000160 | 0.82 s | 1.17 s | 6.5 s |

## Time and cost per 200 cases (for `system/README.md`)
- **Cost:** at most **~$0.005 per 200 cases** (bank, the busiest institution: 307 calls per 1,000 cases). E-money ~$0.0035,
  investment ~$0.002, payments and FX $0. The limit is $4.
- **Time:** a full 1,000-case run with an empty cache took 25 s (bank) with 8 workers; rules only take ~4 s. So the
  reader adds **~4 s per 200 cases**. With a filled cache it adds ~0 s. The limit is 30 minutes.

## What the numbers show
- **Safe:** the only question today (`chat_shows_third_party_money`, from `red_flags.py`) can only add a red flag on
  `yes`. A `no` adds nothing. So the reader can move a case towards `ESCALATE`, never towards `CLOSE`.
- **No verdict changes yet:** every `yes` (19 bank, 26 emoney, 2 investment) landed on a case the rules already
  escalated. The reader adds evidence to the trail but does not change the score yet.
- **Jev is cautious:** its highest probability on this question was 0.34, so it never said `yes`; it settled 145 of
  403 questions as `no` and sent the rest to tier 2. This matches D23.
- **Tier 2 says yes too easily:** a customer sending their own money to help family was read as "other people's money".
  On one labelled emoney case this replaced the right reason code (`ESC_HIGH_RISK_CORRIDOR`) with `ESC_ACCOUNT_MISUSE`.
  The verdict stayed right (`ESCALATE`).

## Next steps
1. Tier-1 model: D23 recommends `pplx-decider v1.3` with Jev as fallback. Re-test on this question before switching.
2. Tier-2 prompt: say that money the customer sends from their own funds to family, or for someone's bills, is the
   customer's own money. Bump `PROMPT_VERSION`, then re-run `reader_check.py` on bank and emoney.
3. `eval/audit.py`: show the tier-1 probability next to each model answer (the trace already has it).

## Re-run
```bash
export OPENROUTER_API_KEY=...                       # never commit it
export TM_DATA=/path/to/hackathon/institutions
PYTHONUTF8=1 python3 eval/reader_check.py bank      # one institution at a time (credit is limited)
```
