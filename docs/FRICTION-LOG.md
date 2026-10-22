# Friction log — Bee / Amazon developer tooling

Format per entry: task, steps taken, expected vs actual, severity,
workaround, suggestion. (The hackathon awards up to +10% for product
feedback; this log is written to be submittable as-is.)

## 2026-10-21 — Programmatic Bee chat (Threads API) is gated to test users

- **Task:** Evaluate Bee's developer surfaces for a hackathon project that
  combines Bee data with an assistant.
- **Steps:** Read the Bee developer documentation end to end; mapped the
  REST API, CLI/MCP, SSE stream, and the Threads (chat) API.
- **Expected:** A documented API is usable by any developer account,
  possibly behind a paid tier.
- **Actual:** The Threads API returns 403 for regular accounts; it is a
  preview limited to designated test users, with no self-serve path to
  become one.
- **Severity:** Medium — blocks any design that routes through Bee's own
  chat agent; the data APIs are unaffected.
- **Workaround:** Architected around it: Bee supplies data (REST + stream);
  the assistant is a separate provider behind a config switch, so Bee chat
  can be adopted later without a rewrite.
- **Suggestion:** Publish the test-user criteria and a waitlist/application
  path in the docs, next to the API reference, so developers can plan
  against it instead of discovering the gate at integration time.

## 2026-10-21 — Minimum watchOS for the Bee Apple Watch app is not published

- **Task:** Determine whether an existing Apple Watch can serve as the
  capture device (Bee hardware not required if the watch app works).
- **Steps:** Searched Bee's site and docs for system requirements.
- **Expected:** A stated minimum watchOS / Series.
- **Actual:** No minimum OS published that we could find. Empirically, a
  Series 3 (capped at watchOS 8) is very unlikely to qualify; a Series 6/7
  on current watchOS is the realistic floor, but that is inference, not
  documentation.
- **Severity:** Low-medium — costs setup time and could strand a user who
  buys into the ecosystem around an older watch.
- **Workaround:** Test on the newest watch available; treat older hardware
  as unsupported until told otherwise.
- **Suggestion:** Publish the minimum watchOS and supported Series on the
  developer page and the App Store listing.

## 2026-10-21 — Gaps in the published API contract

- **Task:** Implement a stdlib client against docs.bee.computer/docs/api
  and /docs/realtime (docs last updated October 13, 2026).
- **Expected:** Request/response shapes for every listed endpoint.
- **Actual:** Paths, Bearer auth, the todo body (`text`, `alarm_at`), and
  stream event names/payloads are documented. Not documented: (1) the
  query parameter name for the `/v1/changes` cursor (only the CLI's
  `--cursor` flag and `meta.next_cursor` are shown); (2) the SSE wire
  framing of `/v1/stream` — the docs show `bee stream --json` payloads,
  which carry no event-name field, but not whether the HTTP stream sends
  `event:` lines; (3) the JSON shape of `GET /v1/conversations/:id`
  (transcript/utterance layout is only visible via `bee sync` markdown);
  (4) pagination of list endpoints.
- **Severity:** Medium — every client has to guess or reverse-engineer
  the CLI.
- **Workaround:** Read the official open-source Bee CLI
  (bee-computer/bee-cli @ 84a6e8f) to recover what the docs omit: the
  cursor parameter is `?cursor=`, the changes response is a flat object
  with id lists and `next_cursor`, the stream sends `event:` lines, and
  the conversation detail is wrapped as `{"conversation": {...}}` with
  utterances under `transcriptions[].utterances[]` and epoch-ms times.
  Pagination of list endpoints is still unknown.
- **Suggestion:** Publish an OpenAPI document (or at least one example
  response per endpoint) next to the reference list.

## 2026-10-21 — First-account setup: no sign-in page exists, and the pairing scan reads as an error

- **Task:** First-time Bee setup for this project (developer account,
  Developer Mode, CLI token), performed by the project owner on his own
  phone and desktop.
- **Steps:** Opened docs.bee.computer looking for a developer sign-in /
  token page; installed the Bee iOS app; opened the desktop repo page.
- **Expected:** A web sign-in where a developer enables Developer Mode
  and copies a token (the flow most developer platforms use, and the one
  we planned around).
- **Actual:** There is no desktop sign-in page — the docs site leads to
  the CLI repo and to hardware purchase pages. The real flow is:
  (1) in the iOS app, unlock Developer Mode by tapping the app
  **Version 5 times**; (2) run `bee login` / `bee login --qr` on the
  desktop, which prints an auth link/QR; (3) approve the pairing in the
  phone app by scanning. The owner's firsthand report on hitting the
  scan prompt cold: "the app asks to scan desktop app so something is
  wrong" — the pairing step presents as an error state when you arrive
  at it without the desktop half running. Onboarding also surfaces the
  Bee Pro paywall ($11.99/mo) before the free plan is obvious; the free
  plan (conversation processing, summaries, 14 days of history) exists,
  and the CLI docs list no Pro prerequisite for Developer Mode — only
  the app plus the 5-tap unlock.
- **Severity:** Medium — the actual flow is sound and arguably more
  secure (the token is minted by the phone approving a pairing, per
  Amazon's Bee Private Compute design), but a first-time developer can
  burn an evening discovering it, and the paywall ordering makes the
  free path look unavailable when it is not.
- **Workaround:** Follow the CLI-first order: app → tap Version 5x →
  `bee login --qr` on desktop → scan/approve in the app → `bee status`.
- **Suggestion:** Put the 5-tap unlock and the QR pairing on the docs'
  front page as the stated authentication flow (today the unlock is a
  prerequisite line inside the CLI guide), and show the free plan's
  scope next to the Pro paywall during app onboarding.

## 2026-10-21 — Addendum: the Pro sheet has no free option on it at all

Screen captured during the same setup (owner's phone, 20:41 CDT): the
Bee Pro paywall sheet offers exactly two choices — Monthly $11.99 or
Yearly $99.00 — above a single "Subscribe now" button. There is no
free-plan option, no "continue free," no "skip" label anywhere on the
sheet. The owner's report: "I can't choose anything that isn't
paying." The only exit is an unlabeled X in the top-left corner. A user
who does not already know a free plan exists will reasonably conclude
the app requires payment. Suggestion: put "Continue with Free" on the
sheet itself, next to the paid plans — the free tier is a documented
plan, not a dismissal gesture.

## 2026-10-21 — Correction + second addendum: "Connect Bee Desktop" is a Pro upsell wearing a pairing costume

Correction to the first-setup entry above: the pairing confusion has a
sharper cause than we first wrote. The app's device-setup screen offers
"Set up a Bee device", "Try with Apple Watch", "Connect Bee Desktop"
(with a QR-scan icon), and "Get a Bee device". Tapping "Connect Bee
Desktop" — the option a developer naturally reads as "pair my desktop
tooling" — drops straight onto the Pro paywall, because it links the
Bee desktop *app* (a Pro feature), not the developer CLI. The CLI's own
pairing (`bee login --qr` from a terminal) is a separate flow that this
menu never mentions. Two different features, one misleading label.
Owner's verdict stands: nothing on the paywall sheet offers a non-paid
choice. Suggestion: label the menu item for what it is ("Connect Bee
Desktop app — Pro") and surface the Apple Watch and CLI paths with the
same prominence as the purchase paths.
