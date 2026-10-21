"""Derive a 3-level quiz from concept cards, following the TRSS pattern.

Level 1 - Recall:       term -> definition (multiple choice)
Level 2 - Understand:   example -> which concept it illustrates (MC)
Level 3 - Apply:        a scenario built from the card's example/apply text;
                        the student must name the concept (MC over terms)

Deterministic: distractors are chosen by stable rotation over the card
list, so the same cards always produce the same quiz (TRSS requires
reproducible output from identical inputs).
"""

from __future__ import annotations


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


def build_quiz(cards: list[dict]) -> list[dict]:
    quiz: list[dict] = []
    simples = [c["simple"] for c in cards]
    terms = [c["term"] for c in cards]
    for i, card in enumerate(cards):
        # Level 1 - recall
        choices, idx = _choices(card["simple"], [s for j, s in enumerate(simples) if j != i], i)
        quiz.append({
            "level": 1,
            "type": "multiple_choice",
            "card_id": card["id"],
            "prompt": f"What is {card['term']}?",
            "choices": choices,
            "answer_index": idx,
        })
        # Level 2 - understand (needs an example)
        if card.get("examples"):
            choices, idx = _choices(card["term"], [t for j, t in enumerate(terms) if j != i], i + 1)
            quiz.append({
                "level": 2,
                "type": "multiple_choice",
                "card_id": card["id"],
                "prompt": f"Which concept does this example illustrate? \"{card['examples'][0]}\"",
                "choices": choices,
                "answer_index": idx,
            })
        # Level 3 - apply
        choices, idx = _choices(card["term"], [t for j, t in enumerate(terms) if j != i], i + 2)
        quiz.append({
            "level": 3,
            "type": "multiple_choice",
            "card_id": card["id"],
            "prompt": (
                f"Application check. {card['apply']} "
                f"Which concept is this task about?"
            ),
            "choices": choices,
            "answer_index": idx,
        })
    return quiz
