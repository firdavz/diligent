# Track 1 Build Board

The team's live progress board: https://claude.ai/artifact/7QiR1BeKfc1A91YcRnYWi3 (private until Andrei shares it).

| File | What it is |
|---|---|
| `index.html` | The board's page as stored in the artifact (a Data-type artifact: d3 + the `dash` API) |
| `dataset-board.json` | Its one dataset: the uploaded `board.json` snapshot |
| `board-snapshot.json` | The latest snapshot uploaded to it |

**How it updates:** every 20 minutes (12:57–16:45) Claude runs `python3 eval/board.py board.json`, which runs `system/run`
twice per institution, scores the output against `eval/labels/`, reads the branch's git log, and writes the four tables
(streams, checks, scores, reproducibility). The snapshot is uploaded to the artifact and the dataset is pointed at it.

**Run it yourself:** `python3 eval/board.py /tmp/board.json` prints the same numbers locally.
