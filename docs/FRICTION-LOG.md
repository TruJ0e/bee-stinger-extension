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

## 2026-10-21 — (placeholder, to complete at first live setup)

First-account Developer Mode + token flow: time it, note any step where
the app and the docs disagree, and record whether a Bee Pro subscription
is required for API access or only for capture features.
