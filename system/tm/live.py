"""Optional local event stream for the judge's case canvas."""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from uuid import uuid4

Observe = Callable[[str, str, dict], None]
CheckObserver = Callable[[str, list, list], None]


def question_fields(q) -> dict:
    return {"id": q.id, "alert_id": q.alert_id, "text": q.text, "doc_ids": q.doc_ids}


def intake_fields(b) -> dict:
    alerted = dict.fromkeys(tid for a in b.alerts for tid in a.get("transaction_ids", []))
    return {
        "institution": b.institution,
        "customer": {k: b.customer[k] for k in ("name", "kind", "risk_rating") if k in b.customer},
        "window": b.case.get("review_window", {}),
        "counts": {"alerts": len(b.alerts), "transactions": len(b.txns), "documents": len(b.docs),
                   "prior_reviews": len(b.reviews), "list_matches": len(b.list_entries)},
        "alerts": [
            {**{k: a[k] for k in ("alert_id", "rule_id", "rule_name", "message", "measured") if k in a},
             "policy": b.policy.get("rules", {}).get(a["rule_id"], {})}
            for a in b.alerts
        ],
        "transactions": [
            {k: b.txns[tid][k] for k in ("transaction_id", "booked_at", "direction", "amount_gbp", "channel",
                                        "counterparty_name", "counterparty_country") if k in b.txns[tid]}
            for tid in alerted if tid in b.txns
        ],
        "documents": [{"id": d.doc_id, "title": d.title, "type": d.type, "date": d.dated} for d in b.docs.values()],
        "held_payment_id": b.case.get("held_payment_id"),
        "policy_limits": {k: v for k, v in b.policy.items()
                          if k in ("cash_reporting_threshold", "own_account_rfi_multiple",
                                   "third_party_invoice_threshold") and v is not None},
    }


class LiveRun:
    """Append flushed, ordered events from multiple case workers."""

    def __init__(self, directory: Path):
        self.lock = Lock()
        self.sequence = 0
        self.file = None
        try:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            path = directory / f"{uuid4().hex}.jsonl"
            self.file = open(path, "x", encoding="utf-8", buffering=1,
                             opener=lambda file, flags: os.open(file, flags, 0o600))
        except OSError as error:
            print(f"Live canvas unavailable: {error}", file=sys.stderr)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self.file:
            self.file.close()

    def emit(self, stage: str, state: str, data: dict, case_id: str | None = None) -> None:
        with self.lock:
            if not self.file:
                return
            self.sequence += 1
            event = {"seq": self.sequence, "at": time.time(), "case_id": case_id,
                     "stage": stage, "state": state, "data": data}
            try:
                self.file.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
            except OSError as error:
                print(f"Live canvas stopped: {error}", file=sys.stderr)
                try:
                    self.file.close()
                except OSError:
                    pass
                self.file = None

    def case(self, case_id: str) -> Observe:
        return lambda stage, state, data: self.emit(stage, state, data, case_id)
