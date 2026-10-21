# ENTRY PLAN — Amazon "Build, Ship, Shape" Hackathon, Bee Track

**Project (working title): Bee → TRSS Study Guide** ("Bee hears the lecture. TRSS builds the guide.")
**Track:** Bee (Wearable AI) · **Mini challenge:** Open Source (recommendation, §5)
**Deadline:** Friday, October 23, 2026, 3:00 PM ET / **2:00 PM CT** — single deadline, no staged rounds. Internal target: **submitted by 12:00 PM CT Friday.**
**Prize ceiling on this path:** Bee 1st $12,000 cash + 1:1 meeting with Amazon Developer team, plus Open Source mini $5,000 cash + $5,000 AWS credits = **$17K cash + $5K credits**. (Bee track itself carries no AWS credits.)
**Budget:** $0. Bee Pro 30-day free trial covers the window; no AWS services used; no purchases.
**Status:** Plan approved by Truman 2026-10-20. Devpost submission still needs his final go.

---

## 1. The concept

Bee captures a lecture and produces a summary, suggested to-dos, and — via its Templates feature — a *study plan*: a document telling the student what to review. Then it stops. The student still has to do all the work: reread, extract the concepts, make the flashcards, write their own practice questions. That review burden is why people abandon capture tools — the tax is daily, the payoff is back-loaded.

This entry automates the work after the transcript:

1. **Bee on an Apple Watch** captures a lecture, seminar, or tutoring session (conversation-distance audio, Bee's design case).
2. A new ingestion layer pulls the transcript from Bee's API / live event stream — event-driven, no polling.
3. The transcript feeds **TRSS's existing study-generation skeleton**, which segments it into concepts and emits study cards in TRSS's established schema (`id, term, type, category, cue, simple, examples, apply`).
4. Out comes a **true study guide**: concepts explained, key terms defined, examples and applications — plus flashcards and a quiz generated from the same cards by TRSS's existing 3-level quiz pattern. Not a plan. The material itself.
5. Commitments spoken in class ("the exam is next Thursday," "read chapter 9 by Monday") are extracted and routed to real calendar destinations — Bee to-dos with alarms, calendar export, and a TruCalenZer adapter.

**Why this wins its lane:** Education is one of the Bee track's three stated priority use cases. The entrant is an Academic Support Coordinator who already built and runs TRSS, a free study tool — the impact story is his day job, not a pitch invention. Judged on Tech Implementation (real Bee API + stream integration, real generation pipeline), Design (watch → guide in one flow, zero review steps), Potential Impact (every recorded lecture becomes study material; capture tools stop at documents), Quality of Idea (the gap is post-transcript automation — named, specific, and true of the whole product category).

## 2. Architecture — what gets built

All new code lives in **one new public repo** (proposed name: `TruJ0e/bee-trss-guide`). It must run standalone from a clean clone.

| Component | What it does | New / existing |
|---|---|---|
| Bee client | Auth (Bearer token), fetch conversations/transcripts via REST; subscribe to `GET /v1/stream` (SSE) for `new-conversation` / `update-conversation-summary`; `/v1/changes` cursor as catch-up. Runs against the public endpoint or `bee proxy` on localhost. | **New** |
| Transcript assembler | Takes one Bee conversation → clean, ordered lecture transcript text with speaker/timestamp structure preserved where Bee provides it. | **New** |
| Concept extractor | LLM pass over the transcript → concept cards in the TRSS schema (`term, type, category, cue, simple, examples, apply`), quality bar = TRSS's standing rule: output must match how existing TRSS units are set up, best material selected, regardless of transcript size. LLM endpoint via env var (OpenAI-compatible), so the repo runs with any key the judge/user supplies. | **New** (prompting + mapping; schema and bar are TRSS's) |
| Guide renderer | Emits a self-contained study unit: guide page (concepts explained), flashcards, and a 3-level quiz derived from the cards — following the existing TRSS study-page pattern, runnable standalone in the repo. | **New**, patterned on TRSS (existing) |
| Commitment extractor + adapters | Detects dated commitments in the transcript; writes them to (a) Bee to-dos with `alarm_at`, (b) an `.ics` calendar file, (c) a **TruCalenZer adapter** — a small module that hands the item to Truman's TruCalenZer via its interface. The core layer runs fully without TruCalenZer; the adapter is one destination among three. | **New** |
| Fixture + demo data | A sample lecture transcript fixture so judges (and the build) can run the full pipeline without a Bee account. Live-capture path is the real demo; the fixture keeps the repo self-verifying. | **New** |

**Explicitly out of scope:** Bee Threads API (preview, test-users only — 403 for regular accounts; do not depend on it). Photo-of-schedule → events (buildable via agent attachments, but gated behind the same preview — named in the writeup as future work, not built). Any change to TRSS core or TruCalenZer themselves.

**Pre-existing assets (disclosed as such, §7):** TRSS / Study-Generator- skeleton and card schema; TruCalenZer. Neither is in the submission repo and neither is licensed by it.

## 3. Build schedule

Workers via TruBus, full verbatim task bodies. Primary: **@claude-code** (available again as of Oct 20). Fallback: @codex (spend-limit flaky — do not put on the critical path). @antigravity is out (returns ~Oct 24, after the deadline). Truman's Wed 19:00 CT is Website Roast Wednesday — his evening, not build time. Truman works his university job weekdays; the build must not depend on his hands except where §8 says so.

### Wed Oct 21 — pipeline day
- **Morning (his-hands, ~20 min, before anything else):** Truman does §8 items 1–2 (Bee app, Developer Mode, token, watch check). This is the week's single point of failure — it goes first.
- Repo scaffold: README skeleton, LICENSE, Bee client (auth, `/conversations`, `/changes`), stream listener. Proof: client lists real conversations from Truman's account.
- Transcript assembler + fixture lecture transcript.
- Concept extractor: transcript → TRSS-schema cards. Proof: fixture in, valid card set out, spot-checked against the TRSS quality bar.
- Guide renderer v1: cards → guide page + flashcards.
- **End-of-day gate:** fixture transcript flows end-to-end in the repo. If not, Thu scope shrinks (§9).

### Thu Oct 22 — product day
- Quiz wiring: 3-level quiz derived from generated cards (existing TRSS pattern).
- Commitment extractor + all three adapters (Bee to-do with alarm, .ics, TruCalenZer adapter).
- **Live test (his-hands, ~15 min):** Truman wears the Series 6/7, records a real short lecture/seminar segment; pipeline runs on real Bee data end-to-end. Any Bee-side surprises land in the friction log the same hour.
- README finalized (run instructions from a clean clone), product feedback drafted, friction log drafted.
- Demo rehearsal once, off the script in §4.

### Fri Oct 23 — submission day (deadline 2:00 PM CT; target 12:00 PM CT)
- Morning buffer only: fixes from rehearsal, clean-clone verification of the repo.
- Record final demo video (his-hands, §4 script).
- Truman files on Devpost (§8 item 4) with the §7 checklist. **Submitted by 12:00 PM CT** leaves a 2-hour cushion.

## 4. Demo script (< 3:00 — judges may not watch past 3:00; best material first)

- **0:00–0:20 — The problem.** "Bee records your lecture and hands you a summary and a study plan. Then the work starts — and most students never do it. We built the part that does the work." Show Bee's own summary screen, briefly.
- **0:20–0:45 — Capture.** Watch on wrist, short lecture segment playing live in the room (close-range, seminar-style — Bee's design case). Show the conversation landing in Bee.
- **0:45–1:35 — The guide appears.** Transcript flows in; the study guide renders: concepts explained in order, key terms, examples. This is the money shot — hold on it.
- **1:35–2:10 — The quiz.** Same lecture, now a 3-level quiz and flashcards generated from the same cards. Answer one question on screen.
- **2:10–2:40 — The commitment.** Replay the moment the lecturer says "exam next Thursday, chapters 7 through 9." Show the item landing as a real calendar entry / TruCalenZer item — not a line in a summary.
- **2:40–3:00 — Close.** "Bee hears the lecture. TRSS builds the guide. Built on Bee's API and event stream, on top of TRSS, a free study tool students already use." End card: repo URL.

## 5. Mini challenge recommendation: **Open Source**

- **Open Source (+$5K cash, +$5K credits):** open-source *only the new layer* — it's new code with no proprietary assets in it. MIT license, public repo. This simultaneously satisfies the main repo rule via the public option, so there's one repo decision instead of two, and no collaborator-invite timing risk. The developer-experience angle (a clean, documented Bee integration others can fork) also reinforces the Bee track's DX priority lane.
- **AWS Builder (+$5K cash, +$5K credits) — rejected for this entry:** it would need an AWS service wired in and documented (Bedrock for the extraction pass is the natural fit) inside a 2-day build, on a free-tier account set up from scratch, for a concept that gains nothing from AWS. Cost is not the issue ($0 either way); schedule risk and a second platform to debug is.
- **Hard boundary:** the license covers the new Bee→TRSS layer only. TRSS core and TruCalenZer are never part of the grant. If Truman wants AWS Builder instead, the swap point is Wed morning, not later.

## 6. Repo strategy

- **Public repo + MIT license** (per §5). Contents: Bee client, assembler, extractor, renderer, adapters, fixture, README with clean-clone run instructions, LICENSE.
- The repo must *call Bee in code* — it does: API client + SSE stream are the entry points, not a README mention.
- No secrets in the repo: Bee token and LLM key are env vars, documented in the README.
- Collaborator invites are **not** needed on the public path. (If Truman flips to private: add knmeiss, giolaq, anishamalde, mosesroth, emersonsklar + testing@devpost.com **at submission time** — invites expire in 7 days.)

## 7. Submission checklist (Devpost fields, in order)

- [ ] Project name + one-line description ("Bee hears the lecture. TRSS builds the guide.")
- [ ] Full text description: problem (post-transcript gap), pipeline, what's new, education impact
- [ ] Track selected: **Bee** · Mini challenge selected: **Open Source** (+ its extra fields: contribution/repo URL, GitHub username `TruJ0e`, short description of what was built and why it matters)
- [ ] GitHub repo URL (public, MIT LICENSE file present, README run instructions verified from a clean clone)
- [ ] Demo video: YouTube or Vimeo, public, English, **under 3:00**
- [ ] Product feedback for every tool used — draft points: *Bee API* (docs clear, stream + changes cursor made event-driven design easy); *Bee CLI/proxy* (local proxy auth is the right pattern); *Bee app/watch* (capture is effortless; conversation-distance mic is the honest limit); *Devpost* (submission flow). Written from real build experience Wed–Thu, not invented.
- [ ] **Pre-existing work disclosure:** "TRSS (study-generation skeleton, card schema, quiz pattern) and TruCalenZer (calendar destination) pre-date the hackathon window and are the author's existing products. Everything in this repository — the Bee ingestion layer, concept extraction, guide rendering, and commitment adapters — was built during the submission window."
- [ ] Friction log (up to +10% judging bonus): real entries from the build — seeded candidates: Threads API gated to test users (403); no verbatim dictate mode in Bee's stock Actions; photos add memory context only, no structural conversion; watch-model/OS compatibility ambiguity for the Bee watch app. Each entry: task, steps, expected vs actual, severity, workaround, suggestion.
- [ ] Optional feature requests: verbatim dictate mode; photo → structured events; public Threads API.

## 8. His-hands list (short and exact — everything else is worker-side)

1. **Wed morning:** Install the Bee app (iPhone), create his account, enable **Developer Mode** in the Bee app, and get the API token into the build (via the vault path — never paste it in chat). Start the Bee Pro **free trial** only if Developer Mode/API requires it.
2. **Wed morning, same sitting:** Put Bee on the **Series 6/7** watch (not the Series 3 — it's capped at watchOS 8 and almost certainly can't run the app) and confirm the Bee watch app installs and records. If it won't install, stop and escalate — §9.
3. **Thu:** Wear the watch and record one real short lecture/seminar segment (~10 min) for the live test.
4. **Fri before 12:00 PM CT:** Register on Devpost (amazonappdev2026.devpost.com) if not already registered, record the demo video (his watch, his voice — script §4), and file the submission. Final go/no-go is his.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Bee watch app won't run on his Series 6/7 (compat not published) | §8 item 2 checks this Wed morning, first thing. Fallbacks in order: Bee app capture via iPhone if supported as a track source; his call on a Bee Frontier ($74.99) — **a purchase, never assumed**; last resort, kill the entry Wed while the cost is still zero. |
| Lecture-hall audio (lecturer far from mic) | Real and not hidden: demo and positioning are seminar / tutoring / study-group distance — how students actually use capture in office hours and review sessions. Named in the writeup as the known limit; friction log material, not a secret. |
| Bee Pro paywall on API/Developer Mode | Trial is 30 days free; start it Wed so the whole window is covered at $0. |
| @codex spend-limit flapping | Critical path is @claude-code; @codex only takes overflow that can slip a day. |
| End-to-end not green by Wed night | Thu scope cuts in this order: TruCalenZer adapter → .ics only; quiz → flashcards only. The guide itself is never the cut. |
| Attention competition: Nebius/PFP deadline Fri Oct 30 | Bee closes Fri Oct 23 and is deliberately scoped to end there. PFP's remaining items (calibration go, demo, Devpost) are untouched by this build and stay queued for the following week. |
| Roast Wednesday (Wed 19:00 CT) | Truman's evening is off-limits; the Wed plan front-loads worker tasks so nothing needs him after ~18:00. |

## 10. Definition of done

Devpost shows the project as submitted before 2:00 PM CT Fri Oct 23 with every §7 box checked, the repo public and runnable from a clean clone, and the video live and under 3:00. Anything less is a kill report, not a partial claim.

---

## Addendum — 2026-10-20 21:11 CDT (Truman's direction)

**Assistant replacement across both products.** Truman is replacing the built-in assistants in both products with the Bee chat/agent itself:
- TruCalenZer: its copilot is replaced by Bee chat.
- TRSS: the "funky determiner" is kept but partnered with Bee (determiner + Bee chat together, not a straight swap).
- Alongside: fix up the final pieces of TRSS and TruCalenZer, and set up the sync/router into both.

**Scope ruling for the hackathon (unchanged deadline discipline):** the entry build stays the study-guide pipeline (§2). The commitment pathway into TruCalenZer (adapter, Thu) is the only place the sync/router touches the submission, and its cut order in §9 still applies. The full copilot/determiner replacement is adjacent product work on TRSS/TruCalenZer themselves — it strengthens the demo story ("the same Bee agent that hears your lecture is the assistant inside both products") but it is NOT on the Fri 14:00 CT critical path.

**Known constraint to verify Wed:** the Bee Threads API (programmatic access to Bee's chat agent) is preview/test-users only — 403 for regular accounts (docs.bee.computer). Direct embedding of Bee chat may be gated. Wed check: with Developer Mode on, test a `/v1/threads` call on Truman's account. If gated, the working route to the same UX is Bee context via the official MCP server / bee-skill feeding the assistant surface, with direct threads as the upgrade when access opens. Either way the design intent stands; only the plumbing differs.

---

## Addendum 2 — 2026-10-20 21:21 CDT (Truman's decision)

**Assistant provider: GPT for now, Bee chat later — by design.** Since Bee tester/developer access isn't free for him, Truman is routing **GPT** into both TRSS and TruCalenZer as their assistant for this project, with a **simple switch-out later** if the Bee project goes somewhere.

Implementation rule that follows: the assistant sits behind one provider interface with a config-level switch (`ASSISTANT_PROVIDER=gpt|bee`). Swapping to Bee chat later is a configuration change, not a rewrite. The concept extractor in §2 already specifies an env-configured OpenAI-compatible LLM endpoint — GPT fills that slot as-is.

**Hackathon impact: none.** The submission's Bee integration is the data path (REST + SSE stream: transcripts, conversations, to-dos), which is untouched by which model powers the in-app assistants. Bee supplies the ears and the data; GPT supplies the voice in the apps; the swap point keeps the Bee-chat upgrade open.

---

## Correction — 2026-10-20 21:54 CDT (Truman)

TruCalenZer's **outside route already exists and is secure**. §2's commitment adapter is therefore a **client of that existing route** — Thursday's builder first documents the route's contract from the TruCalenZer side, then writes the adapter against it. No new plumbing inside TruCalenZer, and the §9 cut order is unaffected (fallbacks remain Bee to-dos / .ics if the route integration slips). The updater defect stands as the one known TruCalenZer issue (Windows Application Control allowlist on the desktop build machine; updater key backup completed 2026-10-20).

---

## Repo created — 2026-10-21 02:42 CDT (Truman's order)

**`TruJ0e/bee-stinger-extension`** — created PUBLIC (verified: `private: false`, visibility public), main branch.
Seeded with: `README.md` (concept, architecture, boundaries), `docs/ENTRY-PLAN.md` (this plan), `LICENSE` (MIT, extension layer only). HEAD after seeding: `ffc908c9d13d`.
Repo name is Truman's: "Bee Stinger Extension." The §2 proposed name is superseded. Local seed copies live at `~/workspace/funding/amazon-bee/seed/`; the canonical plan remains this file — sync changes to the repo as the build proceeds.
