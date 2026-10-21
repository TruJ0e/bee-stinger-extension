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
import sys
import urllib.error
import urllib.request

from . import USER_AGENT

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


class ExtractionError(ValueError):
    """The LLM answered, but not with usable cards."""


def _llm_settings() -> tuple[str, str, str]:
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    return api_key, base_url, model


def _call_llm(prompt: str) -> str:
    api_key, base_url, model = _llm_settings()
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You output strict JSON only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    req = urllib.request.Request(base_url + "/chat/completions", data=json.dumps(body).encode(), method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise ExtractionError(f"LLM endpoint HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise ExtractionError(f"LLM endpoint unreachable: {e.reason}") from e
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise ExtractionError(f"LLM response has no choices[0].message.content: {str(payload)[:200]}") from e
    if not isinstance(content, str) or not content.strip():
        raise ExtractionError("LLM returned empty content")
    return content


def parse_llm_cards(content: str, title: str) -> list[dict]:
    """Turn raw LLM output into validated, de-duplicated TRSS cards.

    Tolerates markdown fences, prose around the JSON, and an object wrapper
    ({"cards": [...]}). Drops elements that are not objects or lack a term
    or explanation. Raises ExtractionError when nothing usable remains, so
    the caller can fall back to the offline path.
    """
    text = content.strip()
    data = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        for open_ch, close_ch in (("[", "]"), ("{", "}")):
            i, j = text.find(open_ch), text.rfind(close_ch)
            if i != -1 and j > i:
                try:
                    data = json.loads(text[i:j + 1])
                    break
                except json.JSONDecodeError:
                    continue
    if data is None:
        raise ExtractionError("LLM output is not parseable JSON")
    if isinstance(data, dict):
        data = data.get("cards") if isinstance(data.get("cards"), list) else [data]
    if not isinstance(data, list):
        raise ExtractionError("LLM JSON is not a list of cards")
    cards: list[dict] = []
    seen: set[str] = set()
    for raw in data:
        if not isinstance(raw, dict):
            continue
        card = _normalize(raw, title)
        if card is None or card["term"].lower() in seen:
            continue
        seen.add(card["term"].lower())
        cards.append(card)
    if not cards:
        raise ExtractionError("LLM JSON contained no valid cards")
    return _unique_ids(cards)


def extract_cards_llm(text: str, title: str) -> list[dict]:
    if not _llm_settings()[0]:
        raise ExtractionError("LLM_API_KEY is not set")
    return parse_llm_cards(_call_llm(_LLM_PROMPT.format(title=title, text=text)), title)


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


_NOT_TERMS = {
    "your", "our", "my", "his", "her", "their", "this", "that", "these", "those", "it",
    "today", "there", "here", "what", "which", "everything", "something", "nothing", "everyone",
}
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
    return _unique_ids(cards)


def _str(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _first_str(value) -> str:
    """A string, or the first non-blank string of a list (TRSS data
    carries apply as string[]; providers return either shape)."""
    if isinstance(value, list):
        return next((v.strip() for v in value if isinstance(v, str) and v.strip()), "")
    return _str(value)


def _normalize(card: dict, title: str) -> dict | None:
    """Coerce one LLM card into the schema; None if it has no term or
    explanation (a card without either cannot be studied)."""
    term = _str(card.get("term"))
    simple = _str(card.get("simple"))
    if not term or not simple:
        return None
    examples = card.get("examples")
    if isinstance(examples, str):
        examples = [examples]
    examples = [e.strip() for e in (examples or []) if isinstance(e, str) and e.strip()] if isinstance(examples, list) else []
    return {
        "id": slugify(_str(card.get("id")) or term) or "card",
        "term": term,
        "type": _str(card.get("type")) or "concept",
        "category": _str(card.get("category")) or _category_from_title(title),
        "cue": _str(card.get("cue")) or f"What is {term}?",
        "simple": simple,
        "examples": examples,
        "apply": _first_str(card.get("apply")) or f"Explain how {term} would show up in a real situation, in your own words.",
    }


def _unique_ids(cards: list[dict]) -> list[dict]:
    seen: dict[str, int] = {}
    for card in cards:
        base = card["id"]
        if base in seen:
            seen[base] += 1
            card["id"] = f"{base}-{seen[base]}"
        else:
            seen[base] = 1
    return cards


def extract_cards(text: str, title: str) -> tuple[list[dict], str]:
    """Returns (cards, path_used). path_used is 'llm', 'offline', or
    'offline (llm failed: <reason>)' so a silent quality drop is visible."""
    if not text or not text.strip():
        return [], "offline (empty transcript)"
    if os.environ.get("LLM_API_KEY"):
        try:
            return extract_cards_llm(text, title), "llm"
        except (ExtractionError, OSError, ValueError) as e:
            print(f"[extract] LLM path failed, using offline extractor: {e}", file=sys.stderr)
            return extract_cards_offline(text, title), f"offline (llm failed: {' '.join(str(e).split())[:120]})"
    return extract_cards_offline(text, title), "offline"
