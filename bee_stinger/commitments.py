"""Extract spoken commitments (exams, due dates, reading) from a transcript.

Deterministic pattern extraction with real date resolution:
- explicit dates: "October 29", "Oct 29", "10/29"
- relative weekdays: "due Friday", "before Monday's class", "next Thursday"
  resolved against the conversation's reference date.

Each item: {"title", "date" (ISO yyyy-mm-dd), "kind", "quote"}.

These are dates *heard in speech*, so downstream destinations must treat
them as suggestions, never as an authoritative/official due date (the
TruCalenZer adapter enforces this; see adapters.py).

Heuristic limits (deliberate, documented): one commitment per sentence;
the first date in a sentence wins; "3/4" is read as a date only when it
is a valid month/day; "last Friday" (past) is ignored.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
_WD_ALT = "|".join(_WEEKDAYS)

_EXPLICIT_DATE = re.compile(
    rf"\b(?P<month>{_MONTH_ALT})\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(?P<year>20\d\d)\b)?",
    re.IGNORECASE,
)
_NUMERIC_DATE = re.compile(r"\b(?P<month>\d{1,2})/(?P<day>\d{1,2})(?:/(?P<year>20\d\d|\d\d))?\b")
_WEEKDAY = re.compile(rf"\b(?:(next|this|last)\s+)?(?P<wd>{_WD_ALT})\b", re.IGNORECASE)

# "final" alone means the final exam; "final project/paper/..." is a deliverable.
_FINAL_NOT_EXAM = r"(?!\s+(?:project|paper|draft|essay|report|version|presentation|submission))"
_KIND_PATTERNS = [
    ("exam", re.compile(rf"\b(exam|midterm|test|quiz)\b|\bfinal\b{_FINAL_NOT_EXAM}", re.IGNORECASE)),
    ("due", re.compile(r"\b(due|submit|turn in|deadline)\b", re.IGNORECASE)),
    ("reading", re.compile(r"\b(read|reading|chapter)\b", re.IGNORECASE)),
]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _resolve_weekday(name: str, ref: date, modifier: str | None) -> date:
    target = _WEEKDAYS[name.lower()]
    delta = (target - ref.weekday()) % 7
    if modifier and modifier.lower() == "next" and delta <= 3:
        delta += 7
    if delta == 0:
        delta = 7  # "due Friday" said on Friday means next Friday
    return ref + timedelta(days=delta)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None  # "February 30", "13/40", ...


def _calendar_date(month: int, day: int, year_text: str | None, ref: date) -> date | None:
    """Resolve month/day (+ optional year) near the reference date. Without
    a year, a date more than 30 days in the past rolls to next year (a
    December lecture announcing a "January 12" exam)."""
    if year_text:
        year = int(year_text)
        return _safe_date(year + 2000 if year < 100 else year, month, day)
    candidate = _safe_date(ref.year, month, day)
    if candidate is not None and candidate < ref - timedelta(days=30):
        candidate = _safe_date(ref.year + 1, month, day)
    return candidate


def _find_date(sentence: str, ref: date) -> date | None:
    for m in _EXPLICIT_DATE.finditer(sentence):
        found = _calendar_date(_MONTHS[m.group("month").lower()], int(m.group("day")), m.group("year"), ref)
        if found:
            return found
    for m in _NUMERIC_DATE.finditer(sentence):
        found = _calendar_date(int(m.group("month")), int(m.group("day")), m.group("year"), ref)
        if found:
            return found
    for m in _WEEKDAY.finditer(sentence):
        if m.group(1) and m.group(1).lower() == "last":
            continue
        return _resolve_weekday(m.group("wd"), ref, m.group(1))
    return None


def _title_for(sentence: str, kind: str) -> str:
    s = sentence.strip().rstrip(".")
    # Prefer a compact noun phrase when one is obvious.
    m = re.search(r"\b(problem set\s*\d+|homework\s*\d+|assignment\s*\d+|chapter\s*\d+)\b", s, re.IGNORECASE)
    if kind == "exam":
        m2 = re.search(r"\b(first|second|third|final)?\s*(exam|midterm|final|test|quiz)\b", s, re.IGNORECASE)
        if m2:
            words = (m2.group(0).strip()).title()
            return words if words else "Exam"
    if m:
        base = m.group(0).title()
        return f"{base} due" if kind == "due" else f"Read {base}" if kind == "reading" else base
    return s[:80]


def extract_commitments(text: str, reference_date: date) -> list[dict]:
    items: list[dict] = []
    if not text or not text.strip():
        return items
    seen: set[tuple[str, str]] = set()
    for sentence in _sentences(text):
        kind = None
        for name, pattern in _KIND_PATTERNS:
            if pattern.search(sentence):
                kind = name
                break
        if kind is None:
            continue
        when = _find_date(sentence, reference_date)
        if when is None:
            continue
        title = _title_for(sentence, kind)
        key = (title.lower(), when.isoformat())
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "title": title,
            "date": when.isoformat(),
            "kind": kind,
            "quote": sentence if sentence[-1:] in ".!?" else sentence + ".",
        })
    items.sort(key=lambda i: i["date"])
    return items
