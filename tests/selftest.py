"""Self-tests for the Bee Stinger pipeline. Stdlib only.

Run:  python3 tests/selftest.py
Exercises the offline path end to end against the bundled fixture and
asserts the concrete outputs the demo depends on. No network, no keys.
"""

import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bee_stinger.adapters import IcsAdapter  # noqa: E402
from bee_stinger.assemble import spoken_text  # noqa: E402
from bee_stinger.bee_client import FixtureClient  # noqa: E402
from bee_stinger.commitments import extract_commitments  # noqa: E402
from bee_stinger.extract import SCHEMA_FIELDS, extract_cards_offline  # noqa: E402
from bee_stinger.quiz import build_quiz  # noqa: E402
from bee_stinger.render import render_guide  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "lecture_conversation.json")
FAILURES = []


def check(name: str, condition: bool, detail: str = ""):
    print(("PASS " if condition else "FAIL ") + name + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def main() -> int:
    conv = FixtureClient(FIXTURE).conversation()
    text = spoken_text(conv)
    check("fixture loads with utterances", len(text) > 200)

    cards = extract_cards_offline(text, conv["title"])
    terms = {c["term"] for c in cards}
    check("offline extraction finds >= 6 cards", len(cards) >= 6, f"got {len(cards)}: {terms}")
    for expected in ("Supply", "Demand", "Equilibrium", "Elasticity"):
        check(f"card present: {expected}", expected in terms)
    check(
        "every card carries the full TRSS schema",
        all(all(c.get(f) not in (None, "") for f in SCHEMA_FIELDS) for c in cards),
    )
    check(
        "examples are attached to cards",
        sum(1 for c in cards if c["examples"]) >= 3,
        f"cards with examples: {[c['term'] for c in cards if c['examples']]}",
    )

    quiz = build_quiz(cards)
    levels = {q["level"] for q in quiz}
    check("quiz covers all 3 levels", levels == {1, 2, 3}, f"levels: {levels}")
    check(
        "every quiz answer_index is valid",
        all(0 <= q["answer_index"] < len(q["choices"]) and len(q["choices"]) >= 2 for q in quiz),
    )
    check("quiz is deterministic", build_quiz(cards) == quiz)

    # Fixture was recorded Wednesday 2026-10-21.
    commitments = extract_commitments(text, date(2026, 10, 21))
    by_date = {c["date"]: c for c in commitments}
    check("3 commitments extracted", len(commitments) == 3, f"got {commitments}")
    check("exam lands on 2026-10-29", "2026-10-29" in by_date and by_date["2026-10-29"]["kind"] == "exam")
    check("problem set due Friday 2026-10-23", "2026-10-23" in by_date)
    check("reading before Monday 2026-10-26", "2026-10-26" in by_date)

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = IcsAdapter(os.path.join(tmp, "c.ics")).deliver_all(commitments)
        ics = open(path, encoding="utf-8").read()
    check("ics has one VEVENT per commitment", ics.count("BEGIN:VEVENT") == 3)
    check("ics is a valid calendar shell", ics.startswith("BEGIN:VCALENDAR") and "END:VCALENDAR" in ics)

    guide = render_guide(conv["title"], cards, quiz, commitments)
    check("guide renders concepts", all(t in guide for t in ("Supply", "Demand", "Elasticity")))
    check("guide renders the 3-level quiz", "Level 3" in guide and "Level 1" in guide)
    check("guide renders commitments", "2026-10-29" in guide)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
