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

## 2026-10-21 — (placeholder, to complete at first live setup)

First-account Developer Mode + token flow: time it, note any step where
the app and the docs disagree, and record whether a Bee Pro subscription
is required for API access or only for capture features.
