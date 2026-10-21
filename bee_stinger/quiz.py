"""Derive a 3-level quiz from concept cards, following the TRSS pattern.

Level 1 - Recall:       term -> definition (multiple choice)
Level 2 - Understand:   example -> which concept it illustrates (MC)
Level 3 - Apply:        a scenario built from the card's example/apply text;
                        the student must name the concept (MC over terms)

Answer leakage guard: a definition or scenario that names its own term
gives the answer away ("Supply is the quantity..."), so each card's term
is masked as "____" wherever it appears in that card's own text. A
question with no distractor (a one-card lecture) is skipped rather than
emitted as a one-option "multiple choice".

Deterministic: distractors are chosen by stable rotation over the card
list, so the same cards always produce the same quiz (TRSS requires
reproducible output from identical inputs).
"""

from __future__ import annotations

import re

_GENERIC_APPLY = "would show up in a real situation, in your own words."


def mask_term(text: str, term: str) -> str:
    """Replace whole-word occurrences of term (case-insensitive) with ____."""
    if not term:
        return text
    return re.sub(rf"(?<!\w){re.escape(term)}(?!\w)", "____", text, flags=re.IGNORECASE)


def _choices(correct: str, pool: list[str], seed_index: int) -> tuple[list[str], int]:
    """Pick up to 3 distractors from pool by rotation; insert correct at a
    stable position. Returns (choices, answer_index)."""
    distractors: list[str] = []
    n = len(pool)
    if n:
        start = seed_index % n
        for step in range(1, n + 1):
            candidate = pool[(start + step) % n]
            if candidate != correct and candidate not in distractors:
                distractors.append(candidate)
            if len(distractors) == 3:
                break
    choices = distractors[:]
    answer_index = (seed_index % (len(choices) + 1)) if choices else 0
    choices.insert(answer_index, correct)
    return choices, answer_index


def _question(level: int, card: dict, prompt: str, correct: str, pool: list[str], seed: int) -> dict | None:
    choices, idx = _choices(correct, pool, seed)
    if len(choices) < 2:
        return None
    return {
        "level": level,
        "type": "multiple_choice",
        "card_id": card["id"],
        "prompt": prompt,
        "choices": choices,
        "answer_index": idx,
    }


def build_quiz(cards: list[dict]) -> list[dict]:
    quiz: list[dict] = []
    masked = [mask_term(c["simple"], c["term"]) for c in cards]
    terms = [c["term"] for c in cards]
    for i, card in enumerate(cards):
        other_terms = [t for j, t in enumerate(terms) if j != i and t.lower() != card["term"].lower()]
        # Level 1 - recall: term -> (masked) definition
        q1 = _question(1, card, f"What is {card['term']}?", masked[i],
                       [s for j, s in enumerate(masked) if j != i], i)
        # Level 2 - understand: example -> concept (needs an example)
        q2 = None
        if card.get("examples"):
            example = mask_term(card["examples"][0], card["term"])
            q2 = _question(2, card, f"Which concept does this example illustrate? \"{example}\"",
                           card["term"], other_terms, i + 1)
        # Level 3 - apply: the card's application task, term masked. The
        # offline extractor's apply text is a generic template that says
        # nothing once masked, so fall back to the masked explanation.
        if card["apply"].endswith(_GENERIC_APPLY):
            scenario = f"Someone describes it this way: \"{masked[i]}\""
        else:
            scenario = mask_term(card["apply"], card["term"])
        q3 = _question(3, card, f"Application check. {scenario} Which concept is this about?",
                       card["term"], other_terms, i + 2)
        quiz.extend(q for q in (q1, q2, q3) if q is not None)
    return quiz
