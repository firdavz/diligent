import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "system"))
DATA = os.environ.get("TM_DATA", os.path.join(ROOT, "data", "institutions"))
INSTITUTIONS = ("bank", "emoney", "investment", "payments_fx")
PREFIX = {"BK": "bank", "EM": "emoney", "IV": "investment", "PX": "payments_fx"}

from tm.load import load_institution  # noqa: E402

BASE_DOC_TYPES = {"due_diligence_summary", "proof_of_address", "contact_note", "company_register_extract"}


def institution_of(case_id: str) -> str:
    return PREFIX[case_id.split("-")[0]]


def bundles(inst: str):
    return load_institution(os.path.join(DATA, inst))


def shape(b) -> tuple:
    rules = tuple(sorted({a["rule_id"] for a in b.alerts}))
    docs = tuple(sorted({d.type for d in b.docs.values() if d.type not in BASE_DOC_TYPES}))
    return rules, docs
