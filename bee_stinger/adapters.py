"""Commitment delivery adapters.

Every adapter is DRY-RUN by default: it prints exactly what it would send
and touches nothing. A real send requires dry_run=False at construction
(the CLI only allows that with --live), so an unattended run can never
create calendar items or to-dos by accident.

Destinations:
- Bee todos (via BeeClient.create_todo, with alarm_at)
- .ics calendar file (universal; imports into any calendar, incl. TruCalenZer)
- TruCalenZer's existing secure outside route (HTTP client)

NOTE on the TruCalenZer adapter: Truman confirms the route exists and is
secure. Its precise contract (endpoint, auth, payload) is being documented
by a dedicated investigation (see docs/ENTRY-PLAN.md addenda). The payload
shape below is PROVISIONAL until that contract lands; the adapter is a
client of the route and must never modify TruCalenZer itself.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, time, timezone

from .bee_client import BeeClient


class BeeTodoAdapter:
    name = "bee-todos"

    def __init__(self, client: BeeClient | None = None, dry_run: bool = True):
        self.client = client
        self.dry_run = dry_run

    def deliver(self, item: dict) -> dict:
        payload = {
            "title": f"{item['title']} — {item['date']}",
            "alarm_at": f"{item['date']}T08:00:00Z",
        }
        if self.dry_run or self.client is None:
            print(f"[dry-run:{self.name}] POST /todos {json.dumps(payload)}")
            return {"adapter": self.name, "dry_run": True, "payload": payload}
        result = self.client.create_todo(payload)
        return {"adapter": self.name, "dry_run": False, "result": result}


class IcsAdapter:
    name = "ics"

    def __init__(self, path: str):
        self.path = path

    def deliver_all(self, items: list[dict]) -> str:
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Bee Stinger//EN"]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for i, item in enumerate(items):
            d = item["date"].replace("-", "")
            lines += [
                "BEGIN:VEVENT",
                f"UID:bee-stinger-{d}-{i}@trujoedigital",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{d}",
                f"SUMMARY:{item['title']}",
                f"DESCRIPTION:From a Bee lecture capture. \"{item['quote']}\"",
                "END:VEVENT",
            ]
        lines.append("END:VCALENDAR")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("\r\n".join(lines) + "\r\n")
        return self.path


class TruCalenZerAdapter:
    name = "trucalenzer"

    def __init__(self, route_url: str | None = None, token: str | None = None, dry_run: bool = True):
        self.route_url = route_url or os.environ.get("TRUCALENZER_ROUTE_URL")
        self.token = token or os.environ.get("TRUCALENZER_ROUTE_TOKEN")
        self.dry_run = dry_run

    def deliver(self, item: dict) -> dict:
        # PROVISIONAL payload — replace with the documented route contract.
        payload = {
            "title": item["title"],
            "date": item["date"],
            "kind": item["kind"],
            "source": "bee-stinger",
            "quote": item["quote"],
        }
        if self.dry_run or not self.route_url:
            print(f"[dry-run:{self.name}] POST {self.route_url or '<TRUCALENZER_ROUTE_URL unset>'} {json.dumps(payload)}")
            return {"adapter": self.name, "dry_run": True, "payload": payload}
        req = urllib.request.Request(
            self.route_url, data=json.dumps(payload).encode(), method="POST"
        )
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return {"adapter": self.name, "dry_run": False, "status": resp.status}
