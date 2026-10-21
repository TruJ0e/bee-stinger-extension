"""TRSS subject bundle: an export of one capture as a TRSS study-unit pack.

TRSS (TruJ0e/Study-Generator-, TruJ0e/TRSS-Pages) is a separate product
and is NOT modified here. This module only writes files into the
extension's own output directory, in the layout TRSS's finished-unit
anatomy specifies (INVESTIGATION.md A1, which reads
Study-Generator-/chapter-landing/BASE-MODEL.md and python/trssgen/emit.py):

    trss-subject/<slug>-chapter-<n>/  (emit.py naming)
      trss-session-policy.json        # emit.py's session policy (modes, quiz levels)
      bundle-manifest.json            # what is here, what TRSS supplies, install steps
      guide.html                      # the Bee Stinger study guide, same cards
      digital-reference/
        index.html                    # quiz wiring: window.TRSS_CHAPTER + script order
        core-cards.js                 # window.CH<n>_CORE_CARDS   (book-term; [] for a lecture)
        lesson-cards.js               # window.CH<n>_LESSON_CARDS (lesson-concept)
        extra-cards.js                # window.CH<n>_EXTRA_CARDS  (research-skill; [])
        lesson-targets.js             # window.CH<n>_LESSON_TARGETS (one objective per concept)
        generated-study-data.js       # window.CH<n>_STUDY_DATA (counts derived from the cards)
        quiz-wiring.json              # the 3-level queue study.js derives (3 x cards)

Card rules (A1): ids ch<n>-<core|lesson|extra>-NNN; type matches the
file; non-empty examples; apply is a string[] (study.js reads apply[0]
as the Level-3 prompt). A spoken lecture yields lesson concepts, so every
card lands in lesson-cards.js and core/extra are present but empty (the
audit requires the files; ch14's extra-cards.js is [] too).

What TRSS supplies at install time, and this bundle deliberately does not
copy (TRSS code is not part of this MIT repository): study.js and
reference.css (byte-identical across units, BASE-MODEL §6/§9) and the
study-page shell markup from python/trssgen/templates/index.html. The
manifest lists them and the install commands (apply-landing.py, then
audit-chapter.py, then deploy-pack.py).

Deterministic: generatedAt is the capture time, not the wall clock, so
the same capture always produces byte-identical bundle files.
"""

from __future__ import annotations

import json
import os
import re
import shutil

from .quiz import mask_term

DEFAULT_UNIT_NUMBER = 1
GENERATOR = "bee-stinger"
CARD_FILES = (
    ("book-term", "core", "core-cards.js", "CORE_CARDS"),
    ("lesson-concept", "lesson", "lesson-cards.js", "LESSON_CARDS"),
    ("research-skill", "extra", "extra-cards.js", "EXTRA_CARDS"),
)
TRSS_SUPPLIED = {
    "study.js": "python/trssgen/templates/study.js (byte-identical runtime, BASE-MODEL §9)",
    "reference.css": "python/trssgen/templates/reference.css (byte-identical base CSS, BASE-MODEL §6)",
    "index.html (study shell)": "python/trssgen/templates/index.html, then chapter-landing/apply-landing.py",
}
_GENERIC_APPLY = "would show up in a real situation, in your own words."


def _js_assign(var: str, payload) -> str:
    return f"window.{var} = {json.dumps(payload, ensure_ascii=False, indent=2)};\n"


def _as_list(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    return [v.strip() for v in (value or []) if isinstance(v, str) and v.strip()]


def trss_card(card: dict, unit: int, number: int) -> dict:
    """One Bee Stinger card -> one TRSS lesson-concept card (A1 schema)."""
    term = card["term"]
    masked = mask_term(card["simple"], term)
    examples = _as_list(card.get("examples"))
    if not examples:
        # The audit rejects empty examples; the lecture's own explanation,
        # with the term masked, is the most faithful stand-in.
        examples = [f"From the lecture: {masked}"]
    apply = _as_list(card.get("apply"))
    if not apply or apply[0].endswith(_GENERIC_APPLY):
        # study.js shows apply[0] as the Level-3 prompt and expects the term
        # as the answer, so the prompt must not name it.
        apply = [f"A classmate describes an idea this way: \"{masked}\" Which concept is it?"]
    else:
        apply = [mask_term(a, term) for a in apply]
    out = {
        "id": f"ch{unit}-lesson-{number:03d}",
        "term": term,
        "type": "lesson-concept",
        "category": card.get("category") or "General",
        "cue": card.get("cue") or f"What is {term}?",
        "simple": card["simple"],
        "examples": examples,
        "apply": apply,
    }
    if isinstance(card.get("compare"), str) and card["compare"].strip():
        out["compare"] = card["compare"].strip()
    return out


def lesson_targets(cards: list[dict], subject_name: str) -> list[str]:
    targets = [f"Explain {c['term']} in your own words and recognize it in a new example." for c in cards]
    if len(cards) > 1:
        targets.append(f"Connect the key concepts of {subject_name} to one another.")
    return targets


def quiz_wiring(cards: list[dict], unit_label: str) -> list[dict]:
    """The question set study.js's buildScopedQuizQueue derives from the
    cards (A1): L3 application -> L2 lesson scenario -> L1 core meaning,
    answer always the term. study.js shuffles within each level at run
    time; this is the unshuffled set, for checking and counts."""
    levels = []
    for c in cards:
        levels.append({"level": 3, "label": "Application Scenario", "id": f"{c['id']}-apply",
                       "card_id": c["id"], "prompt": c["apply"][0], "answer": c["term"]})
    for c in cards:
        levels.append({"level": 2, "label": "Lesson Scenario", "id": f"{c['id']}-lesson", "card_id": c["id"],
                       "prompt": f"In the {unit_label} lesson: \"{c['examples'][0]}\". Which concept is being described?",
                       "answer": c["term"]})
    for c in cards:
        levels.append({"level": 1, "label": "Core Meaning", "id": f"{c['id']}-core", "card_id": c["id"],
                       "prompt": f"Which concept means: \"{c['simple']}\"?", "answer": c["term"]})
    return levels


def _wiring_html(unit: int, title: str, prefix: str, course: str) -> str:
    # The TRSS_CHAPTER line matches audit-chapter.py's identity regex
    # exactly ({ num, title, prefix, course } in that order, nothing else);
    # the script order is load-bearing (study.js snapshots the arrays).
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\" />\n"
        f"<title>Chapter {unit}: {title} — TRSS Study Guide</title>\n</head>\n<body>\n"
        "<!-- Bee Stinger wiring stub. Install: replace the body with TRSS's study shell\n"
        "     (python/trssgen/templates/index.html), keep this identity line, run\n"
        "     chapter-landing/apply-landing.py, then audit-chapter.py. See bundle-manifest.json. -->\n"
        "<script>\n"
        f"window.TRSS_CHAPTER = {{ num: {unit}, title: \"{safe_title}\", prefix: \"{prefix}\", course: \"{course}\" }};\n"
        "</script>\n"
        "<script src=\"core-cards.js\"></script>\n"
        "<script src=\"lesson-cards.js\"></script>\n"
        "<script src=\"extra-cards.js\"></script>\n"
        "<script src=\"study.js\"></script>\n"
        "</body>\n</html>\n"
    )


def write_bundle(out_dir: str, subject: dict, cards: list[dict], generated_at: str,
                 guide_path: str | None = None, unit: int = DEFAULT_UNIT_NUMBER,
                 source: str | None = None) -> dict:
    """Write the TRSS subject bundle. Returns a summary dict with the path."""
    if unit < 1:
        raise ValueError("TRSS unit number must be >= 1")
    prefix = f"CH{unit}"
    course = subject["slug"]
    pack = f"{course}-chapter-{unit}"
    title = subject["name"]
    root = os.path.join(out_dir, "trss-subject", pack)
    dr = os.path.join(root, "digital-reference")
    if os.path.isdir(root):
        shutil.rmtree(root)  # a re-run replaces the bundle; never mixes old cards in
    os.makedirs(dr)

    lesson = [trss_card(c, unit, i) for i, c in enumerate(cards, start=1)]
    by_type = {"book-term": [], "lesson-concept": lesson, "research-skill": []}
    for ctype, _key, fname, suffix in CARD_FILES:
        with open(os.path.join(dr, fname), "w", encoding="utf-8") as f:
            f.write(_js_assign(f"{prefix}_{suffix}", by_type[ctype]))

    targets = lesson_targets(lesson, title)
    with open(os.path.join(dr, "lesson-targets.js"), "w", encoding="utf-8") as f:
        f.write(_js_assign(f"{prefix}_LESSON_TARGETS", targets))

    counts = {ctype: len(by_type[ctype]) for ctype, *_ in CARD_FILES}
    total = sum(counts.values())
    categories = sorted({c["category"] for c in lesson})
    study_data = {
        "pack": pack,
        "chapter": unit,
        "subject": course,
        "title": title,
        "prefix": prefix,
        "counts": counts,
        "totalCards": total,
        "totalQuestions": total * 3,
        "categories": categories,
        "generatedAt": generated_at,
        "generator": GENERATOR + (f" ({source})" if source else ""),
    }
    with open(os.path.join(dr, "generated-study-data.js"), "w", encoding="utf-8") as f:
        f.write(_js_assign(f"{prefix}_STUDY_DATA", study_data))

    with open(os.path.join(dr, "index.html"), "w", encoding="utf-8") as f:
        f.write(_wiring_html(unit, title, prefix, course))

    wiring = quiz_wiring(lesson, f"Chapter {unit}")
    with open(os.path.join(dr, "quiz-wiring.json"), "w", encoding="utf-8") as f:
        json.dump({"order": [3, 2, 1], "questionsPerCard": 3, "questions": wiring}, f, indent=2, ensure_ascii=False)

    policy = {
        "pack": pack,
        "chapter": unit,
        "subject": course,
        "title": title,
        "version": "1.0.0",
        "generatedAt": generated_at,
        "generator": study_data["generator"],
        "modes": ["reference", "flashcards", "quiz"],
        "quiz": {
            "questionsPerCard": 3,
            "levels": ["L1 core meaning", "L2 lesson scenario", "L3 application scenario"],
            "optionsPerQuestion": 4,
            "distractorStrategy": "prefer-same-category",
            "shuffleOptions": True,
        },
        "flashcards": {"flipOn": ["tap", "space"], "shuffle": True},
        "counts": {**counts, "total": total, "questions": total * 3},
    }
    with open(os.path.join(root, "trss-session-policy.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(policy, ensure_ascii=False, indent=2) + "\n")

    if guide_path and os.path.exists(guide_path):
        shutil.copyfile(guide_path, os.path.join(root, "guide.html"))

    manifest = {
        "bundle": pack,
        "subject": subject,
        "unit": {"num": unit, "prefix": prefix, "course": course, "title": title},
        "counts": {"cards": total, "questions": total * 3, "sections": len(categories), "targets": len(targets)},
        "files": sorted(
            os.path.relpath(os.path.join(d, n), root).replace(os.sep, "/")
            for d, _dirs, names in os.walk(root) for n in names
        ) + ["bundle-manifest.json"],
        "supplied_by_trss_at_install": TRSS_SUPPLIED,
        "install": [
            "Copy study.js and reference.css from TRSS's python/trssgen/templates/ into digital-reference/.",
            "Build the study page from TRSS's templates/index.html, keeping this bundle's window.TRSS_CHAPTER line and script order.",
            "python3 chapter-landing/apply-landing.py <bundle>  (landing, routing, derived counts)",
            "python3 chapter-landing/audit-chapter.py <bundle> --base-css <TRSS reference.css>  (must exit 0)",
            "python3 chapter-landing/deploy-pack.py <bundle>/digital-reference <course>/chapter-<n>, then add the hub card.",
        ],
        "generatedAt": generated_at,
    }
    with open(os.path.join(root, "bundle-manifest.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {"path": root, "pack": pack, "cards": total, "questions": total * 3}


def read_js_array(path: str) -> list:
    """Parse a window.X = [...]; card file back (same regex as TRSS's audit)."""
    with open(path, encoding="utf-8") as f:
        m = re.search(r"window\.\w+\s*=\s*(\[.*\]);", f.read(), re.S)
    return json.loads(m.group(1)) if m else []
