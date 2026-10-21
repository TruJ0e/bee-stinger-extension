# Architecture

## The gap this fills

Bee captures a conversation and returns a summary, facts, suggested to-dos,
and — through its Templates — a study *plan*: a document that tells a
student what to review. What it does not produce is the study material
itself. The work after the transcript (extracting concepts, writing the
explanations, building flashcards and practice questions) is left to the
student, and that is where most people stop.

Bee Stinger is the automation layer after the transcript.

## Data flow

The owner's pipeline (2026-10-21): Bee listens -> transcript -> TRSS study
material as a subject -> the user is informed on the Bee to-do list ->
the staged to-dos go to TruCalenZer, assigned to dates.

```
Bee device / Apple Watch app       (interim: GPT stand-in, plain text  <- sources.py)
        |  capture
        v
Bee API (REST + SSE stream)          <- bee_client.py
        |  conversation
        v
Transcript assembler                 <- assemble.py
        |  clean spoken text
        +--------------------------------------+
        v                                      v
Concept extractor (extract.py)         Commitment extractor (commitments.py)
        |  TRSS-schema cards                   |  spoken items {title, date, kind, quote}
        v                                      |
Subject namer (subject.py)  ---- subject ----->+
        |                                      v
        +--> Quiz builder (quiz.py)     Study planner (study.py)
        |                                      |  + kind "study" blocks
        v                                      v
Guide renderer (render.py)             commitments.json (spoken, then study)
        |                                      |
        |                                      v
        |                     1. To-do stager (staging.py) -> staged_todos.json
        |                        "Your study guide for <subject> is ready" first,
        |                        then every commitment occurrence, date order
        |                                      |
        |                     2. Bee to-dos (adapters.py, dry-run by default)
        |                                      |
        |                     3. TruCalenZer, FROM the staged list:
        |                        trucalenzer-import.json + commitments.ics
        v
guide.html + flashcards + quiz
        |
        v
TRSS subject bundle (bundle.py) -> trss-subject/<subject>-chapter-<n>/
```

Order matters: the staged Bee list is built before any TruCalenZer
artifact, and both TruCalenZer writers read only that list, so what the
user sees on Bee is exactly what TruCalenZer receives. Every dated staged
to-do goes to TruCalenZer; the guide-ready to-do has no date, so it is
the one item that stays on Bee only (`"to_trucalenzer": false` in
`staged_todos.json`). A weekly study series is staged as one to-do per
session (neither Bee to-dos nor TruCalenZer imports carry recurrence);
the `.ics` writer folds the sessions back into one recurring event.

## Components

| File | Role |
|---|---|
| `bee_stinger/bee_client.py` | Bee REST client + SSE stream subscriber; `FixtureClient` for offline runs |
| `bee_stinger/sources.py` | Input sources beyond Bee: plain-text transcripts, and the interim GPT stand-in (labelled simulated, never presented as Bee data) |
| `bee_stinger/assemble.py` | Conversation object → transcript lines / spoken text |
| `bee_stinger/extract.py` | Transcript → TRSS-schema cards. LLM path (any OpenAI-compatible endpoint, env-configured) with a deterministic offline fallback |
| `bee_stinger/subject.py` | Subject auto-naming: the conversation title (course code kept, filler dropped), else the first concepts, else a placeholder |
| `bee_stinger/quiz.py` | Cards → 3-level quiz (recall / understand / apply), deterministic |
| `bee_stinger/render.py` | Cards + quiz + commitments → single-file study-guide HTML, headed by the subject |
| `bee_stinger/commitments.py` | Spoken commitments → dated items, with explicit and relative-weekday date resolution |
| `bee_stinger/study.py` | Study blocks (`kind: "study"`, `start`, `duration_minutes`, weekly `recurrence`), deterministic — see below |
| `bee_stinger/staging.py` | The staged Bee to-do list (`staged_todos.json`) that Bee and TruCalenZer are both fed from |
| `bee_stinger/adapters.py` | Delivery: Bee todos, .ics, TruCalenZer import file, TruCalenZer Outlook route. Network sends are dry-run by default; real sends only behind `--live` |
| `bee_stinger/bundle.py` | TRSS subject bundle export — see below |
| `bee_stinger/cli.py` | `demo` (fixture), `fetch` (live Bee), `file` (plain text) and `gpt` (interim stand-in) entry points |

**Status note (2026-10-21, owner's call):** the Outlook/Microsoft Graph
delivery route is implemented and verified against TruCalenZer's B1
contract, but its live use is deferred. It is left as it was — dry-run
printouts for the spoken commitments only — and is not part of the
staged-list flow. The project's current focus is the input side (Bee
captures, with GPT as the interim source) and the guaranteed delivery
artifacts (guide, staged Bee to-dos, .ics, import file, TRSS bundle).

## Study blocks

From the capture date and the spoken commitments, `study.py` plans:

- a weekly session, "Study: <Subject>", from the day after the capture
  until the last exam (or a due date after it, if later);
- a final review, "Final review: <Subject> (<exam>)", the day before each
  exam;
- with no exam date at all, a plain weekly series of 4 sessions.

A weekly session that would land on an exam day or a review day is
skipped and listed in `recurrence.exdates`. Times are a floating local
wall-clock time (17:00 means 5 pm where the student is, across DST
changes). Bee alarms fire when a block starts (spoken commitments keep
their 08:00 alarm). TruCalenZer's import has no time or duration fields,
so a block's window travels in its notes and its date arrives as a
*possible* date, like every other date Bee Stinger sends. Every value is
a CLI option: `--study-time`, `--study-minutes`, `--review-minutes`,
`--study-weeks`.

## TRSS subject bundle

`trss-subject/<subject-slug>-chapter-<n>/` follows TRSS's finished-unit
anatomy (`chapter-landing/BASE-MODEL.md`, `python/trssgen/emit.py`):

- `digital-reference/lesson-cards.js` — `window.CH<n>_LESSON_CARDS`; a
  spoken lecture yields lesson concepts. Ids `ch<n>-lesson-NNN`, type
  `lesson-concept`, non-empty `examples`, `apply` as `string[]` whose
  first prompt never names its own answer (study.js shows `apply[0]` as
  the Level-3 question).
- `core-cards.js` / `extra-cards.js` — present and empty (`[]`).
- `lesson-targets.js` — one learning objective per concept.
- `generated-study-data.js` — counts derived from the cards
  (questions = 3 × cards).
- `index.html` — the quiz wiring: the `window.TRSS_CHAPTER` identity line
  in the exact form TRSS's audit parses, then the load-bearing script
  order (core, lesson, extra, study.js).
- `quiz-wiring.json` — the L3 → L2 → L1 question set study.js derives.
- `trss-session-policy.json`, `guide.html`, `bundle-manifest.json`.

TRSS's own runtime (`study.js`, `reference.css`, the study-page shell) is
not copied into this MIT repository; the manifest names those files and
the install steps (apply-landing.py, audit-chapter.py, deploy-pack.py).
Checked by hand on 2026-10-21 against Study-Generator- `8ff3ad2`, in a
scratch copy: the fixture bundle, with those three files added from
`python/trssgen/templates/`, passes `apply-landing.py` and
`audit-chapter.py` ("in line, 7 cards, 21 questions"). The `--trss-unit`
option sets the unit number. The bundle is byte-identical for the same
capture (`generatedAt` is the capture time, not the wall clock).

## Design rules

- **Event-driven, never polling.** Live ingestion subscribes to Bee's SSE
  stream (`GET /v1/stream`); the `/changes` cursor is the catch-up path
  after downtime. Nothing in this project polls on a timer.
- **Deterministic where it counts.** Same transcript → same cards (offline
  path), same quiz, every run. TRSS's standing requirement for generated
  study material is reproducibility; the LLM path is the quality upgrade,
  not a license for variance in structure.
- **Dry-run delivery.** Adapters print exactly what they would send.
  Nothing creates a to-do or calendar item unless a human runs `--live`.
- **No billable calls in tests.** Every LLM/API path in the selftest runs
  against a stubbed transport, and dry-run runs are asserted to make zero
  network calls.
- **Secrets are environment variables only.** `BEE_TOKEN`, `LLM_API_KEY`,
  `TRUCALENZER_GRAPH_TOKEN` — see `.env.example`.

## Boundaries

This repository is the extension layer only:

- **TRSS** (`TruJ0e/Study-Generator-`, private) is the study platform whose
  card schema and unit format this project emits. It is referenced, not
  included, and is not covered by this repo's license. A guide produced
  here follows the TRSS unit pattern so it can be embedded into TRSS later.
- **TruCalenZer** (TruJoe Digital) is a calendar destination. By design it
  has no inbound network listener, so there is no URL to post to. The
  adapters here are *clients* of the two ingress paths TruCalenZer's own
  code accepts (contract documented in `bee_stinger/adapters.py`):
  1. **Academic import file** — `output/trucalenzer-import.json`
     (`{"assignments": [{"title", "course", "possible date", "source id",
     "notes"}]}`), imported by the user inside TruCalenZer. Spoken dates
     are written as *possible* dates only, per TruCalenZer's rule that a
     date inferred from speech never becomes an official due date. Stable
     source ids make re-imports update rather than duplicate.
  2. **Outlook "Torgy" category** — with `--live` and
     `TRUCALENZER_GRAPH_TOKEN`, a Microsoft Graph event categorized
     `Torgy` is created; TruCalenZer's Outlook delta sync imports it as a
     scheduled (undated) task. Outlook is a schedule in TruCalenZer, never
     a due-date source, so route 1 is the one that carries the date.
- The in-app assistants of both products are being moved behind a provider
  switch (`ASSISTANT_PROVIDER=gpt|bee`): GPT today, Bee chat if and when
  access and the project justify it. That work lives in those products,
  not in this repo.

## Deliberate non-goals (v1)

- No dependence on Bee's Threads API (programmatic Bee chat) — it is a
  preview surface gated to test users.
- No photo-to-schedule conversion; Bee treats photos as memory context.
- No publishing automation. Delivery targets are drafts, to-dos, and
  calendar items a human reviews.
