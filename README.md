# Bee Stinger Extension

**Bee hears the lecture. TRSS builds the guide.**

An open-source extension for the [Bee](https://bee.computer) wearable AI. Bee captures a lecture and hands you a summary and a study *plan* — a document telling you what to review. Then it stops, and the real work starts: extracting the concepts, building the flashcards, writing your own practice questions. Most people never do that work, and the capture tool gets abandoned.

Bee Stinger closes that gap. It takes the transcript Bee already captured and does the work after it:

1. **Bee listens** — Bee on an Apple Watch records a lecture, seminar, or tutoring session.
2. **Transcript** — the extension pulls the transcript from Bee's API and live event stream (event-driven, no polling). Until a Bee token exists, GPT (labelled simulated) or a plain-text transcript stands in.
3. **TRSS study material, as a subject** — the lecture becomes concept cards in the TRSS schema (`term, type, category, cue, simple, examples, apply`), a true study guide, flashcards and a 3-level quiz. Not a plan. The material itself. The subject is auto-named from the conversation title, or from the first concepts when the capture has no name yet. The cards are also exported as a ready-to-install **TRSS subject bundle**.
4. **Commitments + study blocks** — things said out loud in class ("the exam is next Thursday") are extracted, and study sessions are planned from them: weekly 17:00–18:00 sessions until the exam and a final review the day before it (4 weekly sessions when no exam date was heard).
5. **Bee to-do list, staged first** — "Your study guide for *subject* is ready" plus every commitment and study session is staged on the Bee to-do list (`staged_todos.json`; dry-run until a Bee token exists).
6. **TruCalenZer** — the TruCalenZer import file and `.ics` are generated *from that staged list*, so what the user sees on Bee is exactly what TruCalenZer receives: a test on its date, an assignment due on its date, study sessions on theirs.

## Run it

Zero dependencies (Python 3.11+, stdlib only). The demo runs the full
pipeline offline on a bundled fixture lecture — no Bee account, no keys:

```bash
python3 -m bee_stinger.cli demo          # writes every artifact into ./output
python3 tests/selftest.py                # 168 checks, all offline
```

What a run writes into `output/`:

| Artifact | What it is |
|---|---|
| `guide.html`, `cards.json`, `quiz.json` | the study guide, its concept cards, the 3-level quiz |
| `commitments.json` | spoken commitments (unchanged) followed by the generated `kind: "study"` blocks (`start`, `duration_minutes`, weekly `recurrence`) |
| `staged_todos.json` | the staged Bee to-do list: guide-ready first, then every commitment occurrence in date order |
| `trucalenzer-import.json`, `commitments.ics` | TruCalenZer artifacts, generated from the staged list |
| `trss-subject/<subject>-chapter-<n>/` | the TRSS subject bundle (lesson/extra cards, targets, study data, quiz wiring, guide, manifest) |
| `transcript.txt` | the assembled transcript |

Study-block options work on every command: `--study-time 17:00`,
`--study-minutes 60`, `--review-minutes 60`, `--study-weeks 4` (used when
no exam date was heard) and `--trss-unit 1` (the unit number in the TRSS
bundle). The values shown are the defaults.

Other inputs — the pipeline doesn't care where a transcript came from:

```bash
python3 -m bee_stinger.cli file --path lecture.txt --title "BIO 101"
python3 -m bee_stinger.cli gpt --topic "Photosynthesis"   # interim stand-in, needs LLM_API_KEY
```

The `gpt` command generates a lecture transcript on a topic with the
configured LLM: an interim input source for exercising the flow before a
Bee token exists, and a demo aid. Its output is labelled simulated
everywhere it surfaces — it is not Bee data, and never a substitute for
a real capture.

A real capture, once you have a Bee developer token (Developer Mode on in
the Bee app, token in the environment — see `.env.example`):

```bash
export BEE_TOKEN=...                      # never commit this
python3 -m bee_stinger.cli fetch --conversation <id>
```

Set `LLM_API_KEY` (any OpenAI-compatible endpoint) to use the LLM
extraction path; without it, a deterministic offline extractor runs
instead. Delivery adapters are dry-run by default and print exactly what
they would send; `--live` enables real sends. TruCalenZer delivery is a
local import file (`output/trucalenzer-import.json`); the Outlook/Graph
route is implemented and contract-verified but **deferred by the owner's
call (2026-10-21)** — current focus is input (Bee, or GPT for now). See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Design and boundaries: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ·
Build plan: [docs/ENTRY-PLAN.md](docs/ENTRY-PLAN.md) ·
Tooling friction log: [docs/FRICTION-LOG.md](docs/FRICTION-LOG.md)

## Status

Built during the **Amazon "Build, Ship, Shape" Developer Hackathon** (Bee track), October 2026. Design and build plan: [docs/ENTRY-PLAN.md](docs/ENTRY-PLAN.md).

## Architecture

| Component | Role |
|---|---|
| Bee client | Auth, conversation/transcript fetch (REST), live stream subscription (SSE), changes-cursor catch-up |
| Transcript assembler | One Bee conversation → clean, ordered lecture transcript |
| Concept extractor | Transcript → TRSS-schema concept cards (LLM endpoint via env var, OpenAI-compatible) |
| Guide renderer | Cards → study guide page + flashcards + 3-level quiz, following the TRSS study-unit pattern |
| Subject namer | Conversation title (or first concepts) → one clean subject name used everywhere |
| Study planner | Exam/due dates → weekly study series + final review, as `kind: "study"` commitments |
| To-do stager | Guide-ready + commitments → the staged Bee to-do list, the single source for TruCalenZer |
| TRSS bundle exporter | Cards → a TRSS study-unit pack in the output dir (TRSS itself is not modified) |
| Commitment adapters | Staged to-dos → Bee to-dos, `.ics` calendar export, TruCalenZer import file (Outlook route deferred) |

Secrets are environment variables only (`BEE_TOKEN`, LLM key) — nothing is committed.

## Boundaries

This repository is the extension layer only. **TRSS** (the study platform whose schema and unit format this project emits) and **TruCalenZer** (the calendar destination) are separate products of TruJoe Digital LLC, are not part of this repository, and are not covered by this repository's license.

## License

MIT — see [LICENSE](LICENSE). The license covers this extension layer only.
