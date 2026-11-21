# Label Review Desk

Shared review queue for doubtful labels: https://claude.ai/artifact/DoZMRhPuWj44RJcBe4QduS (private until Andrei shares it).

- **Queue** (`queue` collection, written by Claude): cases whose label is not high confidence, where a non-fallback rule
  disagrees with the label, or where the system closes a case the label says not to. Built by
  `python3 eval/review_queue.py <dir>` from `eval/labels/` and the latest `system/traces/`.
- **Decisions** (`decisions` collection): anyone with contributor access confirms the label or picks a new verdict and
  reason code, with a note. Each decision records who made it.
- **Back into the repo:** at each 20-minute check-in Claude reads the decisions, runs
  `python3 eval/review_queue.py --apply decisions.json` (changed labels are updated, reviewed ones marked
  `"reviewed": true`, confidence set to high), commits and pushes `eval/labels/`.
