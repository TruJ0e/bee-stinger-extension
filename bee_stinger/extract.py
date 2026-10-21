"""Concept extraction: lecture transcript -> TRSS-schema concept cards.

Card schema (mirrors TRSS, TruJ0e/Study-Generator-):
    id, term, type, category, cue, simple, examples, apply

Two paths:
- LLM path (preferred): any OpenAI-compatible chat endpoint, configured by
  LLM_API_KEY / LLM_BASE_URL / LLM_MODEL. This is the quality path and is
  provider-swappable by configuration.
- Offline path (fallback): deterministic definitional-pattern extraction.
  Runs with zero keys so the pipeline is always demoable and testable.
  It is deliberately simple; the LLM path exists because surface patterns
  cannot judge conceptual importance.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request

SCHEMA_FIELDS = ["id", "term", "type", "category", "cue", "simple", "examples", "apply"]


def slugify(term: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-")


def _category_from_title(title: str) -> str:
    t = title.lower()
    for key, cat in [
        ("econ", "Economics"), ("bio", "Biology"), ("chem", "Chemistry"),
        ("psych", "Psychology"), ("phys", "Physics"), ("math", "Mathematics"),
        ("history", "History"),
    ]:
        if key in t:
            return cat
    return "General"


# --------------------------------------------------------------------------
# LLM path
# --------------------------------------------------------------------------

_LLM_PROMPT = """You extract study concept cards from a lecture transcript.

Return ONLY a JSON array. Each element is a card with exactly these fields:
  id: slug of the term
  term: the concept name
  type: "concept" unless the card is a process, formula, or person
  category: the subject area
  cue: a one-line recall prompt (a question the student should be able to answer)
  simple: a plain-language explanation of the concept, 1-3 sentences, faithful to the lecture
  examples: array of concrete examples mentioned in or directly implied by the lecture
  apply: one short application task ("Explain how ...", "Predict what happens when ...")

Rules: extract the concepts that matter for an exam, not every noun. Merge
duplicates. Do not invent content that is not in the transcript.

Lecture title: {title}

Transcript:
{text}
"""


def extract_cards_llm(text: str, title: str) -> list[dict]:
    api_key = os.environ["LLM_API_KEY"]
    base_url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You output strict JSON only."},
            {"role": "user", "content": _LLM_PROMPT.format(title=title, text=text)},
        ],
        "temperature": 0.2,
    }
    req = urllib.request.Request(base_url + "/chat/completions", data=json.dumps(body).encode(), method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode())
    content = payload["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content[content.index("["):]
    cards = json.loads(content)
    return [_normalize(card, title) for card in cards]


# --------------------------------------------------------------------------
# Offline path (deterministic)
# --------------------------------------------------------------------------

_DEF_RE = re.compile(
    r"^(?P<term>[A-Z][A-Za-z\- ]{1,44}?)\s+(?:is|are)\s+(?P<def>.+)$"
)
_EXAMPLE_HINTS = ("for example", "for instance", "e.g.")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _clean_term(term: str) -> str:
    term = term.strip()
    for prefix in ("The ", "A ", "An "):
        if term.startswith(prefix):
            term = term[len(prefix):]
    return term.strip()


_MINOR_WORDS = {"of", "the", "and", "in", "on", "a", "an", "to", "for"}


def _display_term(term: str) -> str:
    words = term.split()
    return " ".join(
        w if (i > 0 and w.lower() in _MINOR_WORDS) else w[:1].upper() + w[1:]
        for i, w in enumerate(words)
    )


_NOT_TERMS = {"your", "our", "my", "his", "her", "their", "this", "that", "these", "those", "it"}
_LOGISTICS = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december"
    r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)


def extract_cards_offline(text: str, title: str) -> list[dict]:
    category = _category_from_title(title)
    cards: list[dict] = []
    by_term: dict[str, dict] = {}
    last_card: dict | None = None
    for sentence in _sentences(text):
        low = sentence.lower()
        if any(h in low for h in _EXAMPLE_HINTS):
            if last_card is not None:
                last_card["examples"].append(sentence.rstrip(".") + ".")
            continue
        m = _DEF_RE.match(sentence)
        if not m:
            continue
        # Logistics sentences (exam dates, due days) mention dates and
        # weekdays; definitions of concepts do not. Never card them.
        if _LOGISTICS.search(sentence):
            continue
        term = _clean_term(m.group("term"))
        # Skip sentence fragments that are obviously not terms.
        if len(term) < 3 or len(term.split()) > 6 or term.lower() in by_term:
            continue
        if term.split()[0].lower() in _NOT_TERMS:
            continue
        term = _display_term(term)
        definition = sentence.rstrip(".") + "."
        card = {
            "id": slugify(term),
            "term": term,
            "type": "concept",
            "category": category,
            "cue": f"What is {term}?",
            "simple": definition,
            "examples": [],
            "apply": f"Explain how {term} would show up in a real situation, in your own words.",
        }
        cards.append(card)
        by_term[term.lower()] = card
        last_card = card
    return cards


def _normalize(card: dict, title: str) -> dict:
    out = {field: card.get(field) for field in SCHEMA_FIELDS}
    out["id"] = out["id"] or slugify(out["term"] or "card")
    out["type"] = out["type"] or "concept"
    out["category"] = out["category"] or _category_from_title(title)
    out["examples"] = out["examples"] or []
    return out


def extract_cards(text: str, title: str) -> tuple[list[dict], str]:
    """Returns (cards, path_used) where path_used is 'llm' or 'offline'."""
    if os.environ.get("LLM_API_KEY"):
        try:
            return extract_cards_llm(text, title), "llm"
        except Exception:
            pass  # fall through to the offline path rather than fail the run
    return extract_cards_offline(text, title), "offline"
