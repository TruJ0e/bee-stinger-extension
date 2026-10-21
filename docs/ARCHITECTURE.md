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

```
Bee device / Apple Watch app
        |  capture
        v
Bee API (REST + SSE stream)          <- bee_client.py
        |  conversation
        v
Transcript assembler                 <- assemble.py
        |  clean spoken text
        +--------------------+---------------------+
        v                    v                     v
Concept extractor      Commitment extractor    (raw transcript kept)
(extract.py)           (commitments.py)
        |                    |
        v                    v
TRSS-schema cards      Commitment items {title, date, kind, quote}
        |                    |
        +--> Quiz builder (quiz.py, 3 levels, deterministic)
        |                    |
        v                    v
Guide renderer         Adapters (adapters.py, dry-run by default)
(render.py)              - Bee todos (POST /v1/todos {text, alarm_at})
        |                - .ics export
        v                - TruCalenZer: import file + Outlook "Torgy" route
Study guide HTML
+ flashcards + quiz
```

## Components

| File | Role |
|---|---|
| `bee_stinger/bee_client.py` | Bee REST client + SSE stream subscriber; `FixtureClient` for offline runs |
| `bee_stinger/assemble.py` | Conversation object → transcript lines / spoken text |
| `bee_stinger/extract.py` | Transcript → TRSS-schema cards. LLM path (any OpenAI-compatible endpoint, env-configured) with a deterministic offline fallback |
| `bee_stinger/quiz.py` | Cards → 3-level quiz (recall / understand / apply), deterministic |
| `bee_stinger/render.py` | Cards + quiz + commitments → single-file study-guide HTML |
| `bee_stinger/commitments.py` | Spoken commitments → dated items, with explicit and relative-weekday date resolution |
| `bee_stinger/adapters.py` | Delivery: Bee todos, .ics, TruCalenZer import file, TruCalenZer Outlook route. Network sends are dry-run by default; real sends only behind `--live` |
| `bee_stinger/cli.py` | `demo` (fixture) and `fetch` (live Bee) entry points |

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
