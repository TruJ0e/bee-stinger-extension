"""Client for the Bee developer API (https://api.developer.bee.amazon.dev/v1).

Contract source: https://docs.bee.computer/docs/api and /docs/realtime
(checked 2026-10-21, docs "last updated October 13, 2026"):
- Public endpoint https://api.developer.bee.amazon.dev, paths under /v1/*.
- Auth: "Authorization: Bearer $BEE_TOKEN".
- POST /v1/todos body: {"text": ..., "alarm_at": "<ISO 8601>"}; responses
  return alarm_at as epoch milliseconds.
- GET /v1/stream is SSE, optional ?types=new-utterance,todo-created,...
- GET /v1/changes returns changed entity ids since a cursor; the next
  cursor comes back in the response (shape below, from the CLI).

Not in the docs, taken from the official open-source Bee CLI
(github.com/bee-computer/bee-cli @ 84a6e8f, 2026-10-13) — see
docs/FRICTION-LOG.md:
- GET /v1/changes?cursor=<cursor> -> {"facts": [ids], "conversations":
  [ids], "dailies": [ids], "journals": [ids], "todos": [ids], "since",
  "until", "updated", "timezone", "next_cursor"} (commands/changed).
- GET /v1/conversations -> {"conversations": [...]}; GET
  /v1/conversations/:id -> {"conversation": {id, start_time (epoch ms),
  timezone, summary, short_summary, state, transcriptions: [{id,
  utterances: [{id, text, speaker, spoken_at, ...}]}], ...}} (commands/sync).
- The stream sends standard SSE `event:` + `data:` lines; the CLI drops
  frames with no `event:` line (commands/stream parseSSEBuffer). This
  client still infers a type from payload keys if one ever arrives bare.

Stdlib-only (urllib). The API token comes from the BEE_TOKEN environment
variable and is never stored in this repository. Developer Mode must be
enabled in the Bee app for the token to work.

Also provides FixtureClient, a drop-in replacement that serves a recorded
conversation from a local JSON file, so the whole pipeline can be built and
demoed offline with zero credentials.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable, Iterator

from . import USER_AGENT

BASE_URL = "https://api.developer.bee.amazon.dev/v1"

# Documented stream event types (docs.bee.computer/docs/realtime).
STREAM_EVENTS = (
    "connected",
    "new-utterance", "new-conversation", "update-conversation",
    "update-conversation-summary", "delete-conversation", "update-location",
    "todo-created", "todo-updated", "todo-deleted",
    "journal-created", "journal-updated", "journal-deleted", "journal-text",
)


class BeeError(Exception):
    """Raised for missing credentials or API failures."""


def infer_event_type(payload) -> str | None:
    """Best-effort event type from a stream payload's structural keys.

    The documented payloads carry no event-name field, and several types
    share a shape (todo-created vs todo-updated, new-conversation vs
    update-conversation), so this returns the most specific name the
    shape supports, or None.
    """
    if not isinstance(payload, dict):
        return None
    if "utterance" in payload:
        return "new-utterance"
    if "short_summary" in payload and "conversation_id" in payload:
        return "update-conversation-summary"
    if "location" in payload and "conversation_id" in payload:
        return "update-location"
    if "todo" in payload:
        return "todo"  # created / updated / deleted share this shape
    if "conversation" in payload:
        return "conversation"  # new / update / delete share this shape
    if "journal" in payload:
        return "journal"
    if "journalId" in payload:
        return "journal-text" if "text" in payload else "journal-deleted"
    return None


def parse_sse(lines: Iterable[bytes | str]) -> Iterator[dict]:
    """Parse a text/event-stream into {"event": name, "data": payload} dicts.

    Follows the SSE framing rules: CRLF/LF line endings, ':' comment lines,
    one optional space after the field colon, multi-line data joined with
    '\\n', dispatch on a blank line. When the server sends no `event:` line
    the name falls back to infer_event_type(), then to "message".
    """
    event_name: str | None = None
    data_lines: list[str] = []

    def dispatch():
        raw = "\n".join(data_lines)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = raw
        return {"event": event_name or infer_event_type(data) or "message", "data": data}

    for raw_line in lines:
        line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else raw_line
        line = line.rstrip("\r\n")
        if line == "":
            if data_lines:
                yield dispatch()
            event_name, data_lines = None, []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            event_name = value.strip() or None
        elif field == "data":
            data_lines.append(value)
    if data_lines:
        yield dispatch()


class BeeClient:
    def __init__(self, token: str | None = None, base_url: str = BASE_URL):
        self.token = token or os.environ.get("BEE_TOKEN")
        if not self.token:
            raise BeeError(
                "BEE_TOKEN is not set. Enable Developer Mode in the Bee app, "
                "create a developer token, and export BEE_TOKEN=<token>. "
                "For offline work, use FixtureClient instead."
            )
        self.base_url = base_url.rstrip("/")

    # -- plumbing ---------------------------------------------------------
    def _request(self, method: str, path: str, payload: dict | None = None):
        url = self.base_url + path
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("User-Agent", USER_AGENT)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            raise BeeError(f"Bee API {method} {path} -> HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise BeeError(f"Bee API {method} {path} -> network error: {e.reason}") from e
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise BeeError(f"Bee API {method} {path} -> non-JSON response: {raw[:200]!r}") from e

    # -- API surface ------------------------------------------------------
    def me(self):
        return self._request("GET", "/me")

    def conversations(self):
        data = self._request("GET", "/conversations")
        return data.get("conversations", []) if isinstance(data, dict) else (data or [])

    def conversation(self, conversation_id):
        data = self._request("GET", f"/conversations/{urllib.parse.quote(str(conversation_id), safe='')}")
        # The API wraps the detail object: {"conversation": {...}}.
        if isinstance(data, dict) and isinstance(data.get("conversation"), dict):
            return data["conversation"]
        if isinstance(data, dict) and "id" in data:
            return data
        raise BeeError(f"Unexpected conversation response for {conversation_id!r}")

    def facts(self):
        return self._request("GET", "/facts")

    def todos(self):
        return self._request("GET", "/todos")

    def create_todo(self, text: str, alarm_at: str | None = None):
        """POST /v1/todos. alarm_at is an ISO 8601 UTC timestamp."""
        body: dict = {"text": text}
        if alarm_at is not None:
            body["alarm_at"] = alarm_at
        return self._request("POST", "/todos", body)

    def changes(self, cursor: str | None = None):
        if cursor is None:
            return self._request("GET", "/changes")
        return self._request("GET", "/changes?" + urllib.parse.urlencode({"cursor": cursor}))

    def stream(self, types: Iterable[str] | None = None):
        """Subscribe to the live SSE stream (GET /v1/stream[?types=...]).

        Yields {"event": <name>, "data": <parsed json or text>}. Delivery is
        at-most-once per the Bee docs: use changes() to catch up after a
        disconnect. Blocks while the stream is open.
        """
        path = "/stream"
        if types:
            path += "?" + urllib.parse.urlencode({"types": ",".join(types)})
        req = urllib.request.Request(self.base_url + path, method="GET")
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("User-Agent", USER_AGENT)
        req.add_header("Accept", "text/event-stream")
        try:
            with urllib.request.urlopen(req, timeout=None) as resp:
                yield from parse_sse(resp)
        except urllib.error.HTTPError as e:
            raise BeeError(f"Bee stream -> HTTP {e.code}") from e
        except urllib.error.URLError as e:
            raise BeeError(f"Bee stream failed: {e.reason}") from e


class FixtureClient:
    """Offline stand-in for BeeClient, backed by one fixture conversation.

    Fixture format (a small, honest subset of the Bee conversation shape):
        {"id": ..., "title": ..., "created_at": ...,
         "utterances": [{"speaker": ..., "text": ...}, ...]}
    """

    def __init__(self, fixture_path: str):
        with open(fixture_path, "r", encoding="utf-8") as f:
            self._conversation = json.load(f)
        if not isinstance(self._conversation, dict) or "id" not in self._conversation:
            raise BeeError(f"Fixture {fixture_path} is not a conversation object with an id")

    def conversations(self):
        c = self._conversation
        return [{"id": c["id"], "title": c.get("title", ""), "created_at": c.get("created_at")}]

    def conversation(self, conversation_id=None):
        # Bee conversation ids are numbers; compare as strings so a CLI
        # argument ("123") matches a numeric id (123).
        if conversation_id is not None and str(conversation_id) != str(self._conversation["id"]):
            raise BeeError(f"Fixture has no conversation {conversation_id!r}")
        return self._conversation
