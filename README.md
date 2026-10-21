# Bee Stinger Extension

**Bee hears the lecture. TRSS builds the guide.**

An open-source extension for the [Bee](https://bee.computer) wearable AI. Bee captures a lecture and hands you a summary and a study *plan* — a document telling you what to review. Then it stops, and the real work starts: extracting the concepts, building the flashcards, writing your own practice questions. Most people never do that work, and the capture tool gets abandoned.

Bee Stinger closes that gap. It takes the transcript Bee already captured and does the work after it:

1. **Capture** — Bee on an Apple Watch records a lecture, seminar, or tutoring session.
2. **Ingest** — the extension pulls the transcript from Bee's API and live event stream (event-driven, no polling).
3. **Extract** — an LLM pass segments the lecture into concept cards in the TRSS schema (`term, type, category, cue, simple, examples, apply`).
4. **Build the guide** — a true study guide: concepts explained, key terms defined, examples and applications — plus flashcards and a 3-level quiz generated from the same cards. Not a plan. The material itself.
5. **Route commitments** — things said out loud in class ("the exam is next Thursday") are extracted and delivered to real destinations: Bee to-dos with alarms, calendar files, and TruCalenZer.

## Status

Built during the **Amazon "Build, Ship, Shape" Developer Hackathon** (Bee track), October 2026. Design and build plan: [docs/ENTRY-PLAN.md](docs/ENTRY-PLAN.md).

## Architecture

| Component | Role |
|---|---|
| Bee client | Auth, conversation/transcript fetch (REST), live stream subscription (SSE), changes-cursor catch-up |
| Transcript assembler | One Bee conversation → clean, ordered lecture transcript |
| Concept extractor | Transcript → TRSS-schema concept cards (LLM endpoint via env var, OpenAI-compatible) |
| Guide renderer | Cards → study guide page + flashcards + 3-level quiz, following the TRSS study-unit pattern |
| Commitment adapters | Dated commitments → Bee to-dos, `.ics` calendar export, TruCalenZer route |

Secrets are environment variables only (`BEE_TOKEN`, LLM key) — nothing is committed.

## Boundaries

This repository is the extension layer only. **TRSS** (the study platform whose schema and unit format this project emits) and **TruCalenZer** (the calendar destination) are separate products of TruJoe Digital LLC, are not part of this repository, and are not covered by this repository's license.

## License

MIT — see [LICENSE](LICENSE). The license covers this extension layer only.
