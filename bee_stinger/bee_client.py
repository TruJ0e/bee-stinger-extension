"""Client for the Bee developer API (https://api.developer.bee.amazon.dev/v1).

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
import urllib.request

BASE_URL = "https://api.developer.bee.amazon.dev/v1"


class BeeError(Exception):
    """Raised for missing credentials or API failures."""


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
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            raise BeeError(f"Bee API {method} {path} -> HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise BeeError(f"Bee API {method} {path} -> network error: {e.reason}") from e

    # -- API surface ------------------------------------------------------
    def me(self):
        return self._request("GET", "/me")

    def conversations(self):
        return self._request("GET", "/conversations")

    def conversation(self, conversation_id: str):
        return self._request("GET", f"/conversations/{conversation_id}")

    def facts(self):
        return self._request("GET", "/facts")

    def todos(self):
        return self._request("GET", "/todos")

    def create_todo(self, payload: dict):
        return self._request("POST", "/todos", payload)

    def changes(self, cursor: str | None = None):
        path = "/changes" if cursor is None else f"/changes?cursor={cursor}"
        return self._request("GET", path)

    def stream(self):
        """Subscribe to the live SSE stream (GET /v1/stream).

        Yields event dicts: {"event": <name>, "data": <parsed json or text>}.
        Event names include new-utterance, new-conversation,
        update-conversation-summary, todo-created, and journal events.
        Blocks while the stream is open; intended for a listener process.
        """
        req = urllib.request.Request(self.base_url + "/stream", method="GET")
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "text/event-stream")
        event_name = None
        data_lines: list[str] = []
        try:
            with urllib.request.urlopen(req, timeout=None) as resp:
                for raw in resp:
                    line = raw.decode(errors="replace").rstrip("\n")
                    if line.startswith("event:"):
                        event_name = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line.split(":", 1)[1].strip())
                    elif line == "":
                        if data_lines:
                            data = "\n".join(data_lines)
                            try:
                                data = json.loads(data)
                            except json.JSONDecodeError:
                                pass
                            yield {"event": event_name or "message", "data": data}
                        event_name, data_lines = None, []
        except urllib.error.URLError as e:
            raise BeeError(f"Bee stream failed: {e}") from e


class FixtureClient:
    """Offline stand-in for BeeClient, backed by one fixture conversation.

    Fixture format (a small, honest subset of the Bee conversation shape):
        {"id": ..., "title": ..., "created_at": ...,
         "utterances": [{"speaker": ..., "text": ...}, ...]}
    """

    def __init__(self, fixture_path: str):
        with open(fixture_path, "r", encoding="utf-8") as f:
            self._conversation = json.load(f)

    def conversations(self):
        c = self._conversation
        return [{"id": c["id"], "title": c.get("title", ""), "created_at": c.get("created_at")}]

    def conversation(self, conversation_id: str | None = None):
        if conversation_id is not None and conversation_id != self._conversation["id"]:
            raise BeeError(f"Fixture has no conversation {conversation_id!r}")
        return self._conversation
