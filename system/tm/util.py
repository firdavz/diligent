"""Small parsing helpers shared by every module. Standard library only."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}
_AMOUNT = re.compile(r"£\s?(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)")


def amounts(text: str) -> list[float]:
    """Every £ amount in a string, in order: '£12,550.00 and £74.08' -> [12550.0, 74.08]."""
    return [float(m.replace(",", "")) for m in _AMOUNT.findall(text or "")]


def amount(text: str) -> float | None:
    a = amounts(text)
    return a[0] if a else None


def money(x: float) -> str:
    """12550 -> '£12,550.00' (for reason text)."""
    return f"£{x:,.2f}"


def parse_date(text: str | None) -> date | None:
    """'2026-10-18', '2026-10-18T06:00:00Z' or '18 October 2026' -> date. None if unreadable."""
    if not text:
        return None
    s = text.strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", s)
    if m and m[2].lower() in _MONTHS:
        return date(int(m[3]), _MONTHS[m[2].lower()], int(m[1]))
    return None


def parse_dt(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def fmt_date(d: date) -> str:
    return f"{d.day} {d.strftime('%B %Y')}"


def norm(text: str | None) -> str:
    """Lower-case, strip accents and punctuation, collapse spaces."""
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9 ]+", " ", t.lower())
    return " ".join(t.split())


_COMPANY_FORMS = {"ltd", "limited", "plc", "llp", "llc", "inc", "bv", "gmbh", "sa", "sas", "srl", "spa", "co", "company"}


def name_key(name: str | None) -> str:
    """Comparable form of a person or company name: 'Halford Timber Supplies Ltd' -> 'halford supplies timber'."""
    parts = [p for p in norm(name).split() if p not in _COMPANY_FORMS]
    return " ".join(sorted(parts))


def same_name(a: str | None, b: str | None) -> bool:
    return bool(a and b) and name_key(a) == name_key(b)
