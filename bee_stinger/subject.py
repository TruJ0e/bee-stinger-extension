"""Subject auto-naming: one clean subject name per capture.

A capture may not be named yet (a Bee conversation with no title, a
pasted transcript, a long Bee short_summary sentence), so the subject is
derived in this order:

1. the conversation title, when it is a real title: separators and
   filler ("lecture", "notes", "class") are cleaned up, and a leading
   course code ("ECON 101 — Supply and Demand") is kept as the course;
2. otherwise the first concepts the extractor found ("Supply, Demand &
   Equilibrium");
3. otherwise a stable placeholder.

Deterministic: the same title and cards always give the same subject.
The result is used everywhere a subject surfaces: the CLI summary, the
guide, the staged Bee to-dos, and the TRSS subject bundle.
"""

from __future__ import annotations

import re

from .extract import slugify

PLACEHOLDER_SUBJECT = "Untitled Subject"
MAX_TITLE_WORDS = 8          # longer "titles" are Bee summary sentences, not names
MAX_CONCEPTS_IN_NAME = 3

# Titles that name nothing (our own sources' defaults, and Bee's).
_GENERIC_TITLES = {
    "untitled", "untitled capture", "untitled lecture", "untitled conversation",
    "lecture", "class", "conversation", "new conversation", "recording",
    "transcript", "notes", "meeting", "capture",
}
_SEPARATORS = re.compile(r"\s+[—–-]\s+|\s*:\s+|\s*\|\s*")
_COURSE_CODE = re.compile(r"^[A-Z]{2,5}[- ]?\d{2,4}[A-Z]?$")
_FILLER_PREFIX = re.compile(r"^(?:(?:a|the)\s+)?(?:lecture|class|talk|seminar|session)\s+(?:on|about)\s+", re.IGNORECASE)
_FILLER_SUFFIX = re.compile(r"\s+(?:lecture|class|notes|session|recording)$", re.IGNORECASE)


def _tidy(text: str) -> str:
    text = " ".join(text.split()).strip(" .,;:-—–")
    text = _FILLER_PREFIX.sub("", text)
    text = _FILLER_SUFFIX.sub("", text)
    return text.strip(" .,;:-—–")


def _from_title(title: str) -> tuple[str | None, str] | None:
    """(course, topic) from a usable title, or None if it names nothing."""
    raw = " ".join((title or "").split())
    if not raw or raw.lower().strip(" .") in _GENERIC_TITLES:
        return None
    if len(raw.split()) > MAX_TITLE_WORDS:
        return None
    parts = [_tidy(p) for p in _SEPARATORS.split(raw)]
    parts = [p for p in parts if p and p.lower() not in _GENERIC_TITLES]
    if not parts:
        return None
    course = parts[0] if len(parts) > 1 and _COURSE_CODE.match(parts[0]) else None
    topic_parts = parts[1:] if course else parts
    topic = " — ".join(topic_parts) if topic_parts else ""
    if not topic:
        return (None, course) if course else None
    return course, topic


def _from_concepts(cards: list[dict]) -> str | None:
    terms: list[str] = []
    for card in cards:
        term = (card.get("term") or "").strip()
        if term and term.lower() not in {t.lower() for t in terms}:
            terms.append(term)
        if len(terms) == MAX_CONCEPTS_IN_NAME:
            break
    if not terms:
        return None
    if len(terms) == 1:
        return terms[0]
    return ", ".join(terms[:-1]) + " & " + terms[-1]


def derive_subject(title: str | None, cards: list[dict]) -> dict:
    """Returns {"name", "course", "topic", "slug", "source"}.

    source is "title", "concepts" or "placeholder" so a reader can tell a
    named subject from a derived one.
    """
    named = _from_title(title or "")
    if named is not None:
        course, topic = named
        name = f"{course}: {topic}" if course else topic
        source = "title"
    else:
        topic = _from_concepts(cards)
        course = None
        source = "concepts" if topic else "placeholder"
        topic = topic or PLACEHOLDER_SUBJECT
        name = topic
    return {
        "name": name,
        "course": course,
        "topic": topic,
        "slug": slugify(name) or slugify(PLACEHOLDER_SUBJECT),
        "source": source,
    }
