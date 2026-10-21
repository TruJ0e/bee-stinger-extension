"""Commitment delivery adapters.

Every network adapter is DRY-RUN by default: it prints exactly what it
would send and touches nothing. A real send requires dry_run=False at
construction (the CLI only allows that with --live) AND credentials in the
environment, so an unattended run can never create calendar items or
to-dos by accident. Local file writers (.ics, TruCalenZer import file)
write into the output directory only and send nothing.

Destinations:
- Bee todos: POST /v1/todos {"text", "alarm_at"} (docs.bee.computer/docs/api)
- .ics calendar file (universal; imports into any calendar)
- TruCalenZer, through the two ingress paths its own code accepts. The
  adapter is a client only; TruCalenZer is not modified or included here.

In the pipeline the Bee, .ics and import-file writers are fed from the
staged Bee to-do list (staging.py: deliver_staged / send), so Bee and
TruCalenZer always carry the same items. Study blocks (kind "study") are
timed: a Bee alarm at the block's start, a timed .ics event (weekly
series as one RRULE event), and the time window in the import notes.

TruCalenZer contract (read from TruCalenZer source, origin/main ba1a741,
2026-10-21). TruCalenZer deliberately has NO inbound network listener
("No public listening port in the production desktop build"), so there is
no URL to POST to. It ingests outside items two ways:

1. Academic import file (TruCalenZerImportFile). A local .json file the
   user imports in TruCalenZer; it "does not upload the file anywhere".
   Accepted JSON: an array of records, or {"assignments": [...]}. Keys are
   matched case/punctuation-insensitively; this adapter writes:
     "title"         -> task title (required)
     "course"        -> course
     "possible date" -> possibleDate (YYYY-MM-DD), dateConfidence "possible"
     "source id"     -> sourceRecordId "import:<id>" (stable => re-import
                        updates instead of duplicating)
     "notes"         -> notes
     "student name"  -> optional; resolves the student by display name
   TruCalenZer's date-integrity rule: a date inferred from speech is a
   *possible* date only and must never populate the official due date, so
   this adapter never writes "official due date" / "due date" / "date".

2. Outlook calendar via Microsoft Graph (TruCalenZerOutlookAdapter).
   TruCalenZer delta-syncs the signed-in user's calendar
   (GET /me/calendarView/delta, window -90..+365 days) and imports any
   unlinked event whose categories include "Torgy" and that has a subject
   and start time, as an undated task with scheduledAt = event start.
   Outlook is a *schedule* in TruCalenZer, not a due-date source, so this
   route yields a work block on the date, not a due date. Auth is a
   Microsoft Graph token (Calendars.ReadWrite) for the same account
   TruCalenZer is connected to, supplied to Bee Stinger directly via
   TRUCALENZER_GRAPH_TOKEN. TruCalenZer's own DPAPI-protected token
   cache is never read.
   The event body carries "Torgy-Task-ID: <uuid>" and
   "Torgy-Task-Version: 1" marker lines (INVESTIGATION B1, adapter rule
   1), derived deterministically from the commitment: TruCalenZer's
   importer reads the markers from the event body and links the event to
   that task id instead of creating a duplicate on re-import. The Graph
   transactionId gives the same protection against a retried POST.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
import uuid
from datetime import date, datetime, time, timedelta, timezone, tzinfo

from . import USER_AGENT
from .bee_client import BeeClient, BeeError

GRAPH_EVENTS_URL = "https://graph.microsoft.com/v1.0/me/events"
TRUCALENZER_CATEGORY = "Torgy"  # TruCalenZer's import marker category
_ID_NAMESPACE = uuid.UUID("6b1f3c2e-8f0a-4c55-9d43-2f1e0b7a9c11")


def commitment_key(item: dict, conversation_id=None) -> str:
    """Stable id for one commitment, so re-runs update instead of duplicate."""
    raw = f"{conversation_id}|{item['title'].lower()}|{item['date']}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _hhmm(text: str) -> time:
    hours, minutes = text.split(":")
    return time(int(hours), int(minutes))


def _local_to_utc_iso(day: str, at: time, tz: tzinfo) -> str:
    local = datetime.combine(date.fromisoformat(day), at, tzinfo=tz)
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class BeeTodoAdapter:
    name = "bee-todos"

    def __init__(self, client: BeeClient | None = None, dry_run: bool = True,
                 tz: tzinfo = timezone.utc, alarm_time: time = time(8, 0)):
        self.client = client
        self.dry_run = dry_run
        self.tz = tz
        self.alarm_time = alarm_time

    def payload(self, item: dict) -> dict:
        # Spoken commitments: alarm at 08:00 in the lecture's own timezone.
        # Study blocks: alarm when the block starts. Both sent as UTC.
        if item.get("start"):
            start = _hhmm(item["start"])
            end = (datetime.combine(date.fromisoformat(item["date"]), start)
                   + timedelta(minutes=item["duration_minutes"])).strftime("%H:%M")
            return {
                "text": f"{item['title']} — {item['date']} {item['start']}–{end}",
                "alarm_at": _local_to_utc_iso(item["date"], start, self.tz),
            }
        return {
            "text": f"{item['title']} — {item['date']}",
            "alarm_at": _local_to_utc_iso(item["date"], self.alarm_time, self.tz),
        }

    def deliver(self, item: dict) -> dict:
        return self.send(self.payload(item))

    def send(self, payload: dict) -> dict:
        """Deliver one prepared {text[, alarm_at]} payload (a staged to-do)."""
        if self.dry_run:
            print(f"[dry-run:{self.name}] POST /v1/todos {json.dumps(payload, ensure_ascii=False)}")
            return {"adapter": self.name, "dry_run": True, "payload": payload}
        if self.client is None:
            return {"adapter": self.name, "dry_run": False, "skipped": "BEE_TOKEN not set"}
        try:
            result = self.client.create_todo(payload["text"], payload.get("alarm_at"))
        except BeeError as e:
            return {"adapter": self.name, "dry_run": False, "error": str(e)}
        return {"adapter": self.name, "dry_run": False, "result": result}


def _ics_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", ""))


def _ics_fold(line: str) -> list[str]:
    """RFC 5545 3.1: fold lines longer than 75 octets (UTF-8 safe)."""
    out: list[str] = []
    current, size = "", 0
    for ch in line:
        width = len(ch.encode("utf-8"))
        limit = 75 if not out else 74  # continuation lines start with a space
        if size + width > limit:
            out.append(current)
            current, size = "", 0
        current += ch
        size += width
    out.append(current)
    return [out[0]] + [" " + part for part in out[1:]]


class IcsAdapter:
    name = "ics"

    def __init__(self, path: str, conversation_id=None):
        self.path = path
        self.conversation_id = conversation_id

    def render(self, items: list[dict]) -> str:
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Bee Stinger//EN", "CALSCALE:GREGORIAN"]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for item in items:
            start = date.fromisoformat(item["date"])
            lines += [
                "BEGIN:VEVENT",
                f"UID:bee-stinger-{commitment_key(item, self.conversation_id)}@trujoedigital",
                f"DTSTAMP:{stamp}",
            ]
            if item.get("start"):
                # Generated study block: a timed event in floating local time
                # (5 pm wherever the student is, across DST changes).
                at = _hhmm(item["start"]).strftime("%H%M%S")
                lines += [
                    f"DTSTART:{start.strftime('%Y%m%d')}T{at}",
                    f"DURATION:PT{int(item['duration_minutes'])}M",
                ]
                rec = item.get("recurrence")
                if rec and rec.get("freq") == "weekly":
                    until = date.fromisoformat(rec["until"]).strftime("%Y%m%d")
                    lines.append(f"RRULE:FREQ=WEEKLY;INTERVAL={int(rec.get('interval', 1))};UNTIL={until}T{at}")
                    if rec.get("exdates"):
                        lines.append("EXDATE:" + ",".join(
                            f"{date.fromisoformat(d).strftime('%Y%m%d')}T{at}" for d in rec["exdates"]))
                description = item.get("notes") or "Generated study block (Bee Stinger)."
            else:
                lines += [
                    f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}",
                    f"DTEND;VALUE=DATE:{(start + timedelta(days=1)).strftime('%Y%m%d')}",
                ]
                description = f"Heard in a Bee lecture capture (date not officially confirmed). \"{item['quote']}\""
            lines += [
                f"SUMMARY:{_ics_escape(item['title'])}",
                "DESCRIPTION:" + _ics_escape(description),
                "END:VEVENT",
            ]
        lines.append("END:VCALENDAR")
        folded = [part for line in lines for part in _ics_fold(line)]
        return "\r\n".join(folded) + "\r\n"

    @staticmethod
    def items_from_staged(staged: list[dict]) -> list[dict]:
        """Calendar items for the staged to-dos TruCalenZer receives: one
        per staged to-do, except that the sessions of a weekly study series
        fold back into their one recurring event."""
        items, seen = [], set()
        for todo in staged:
            if not todo.get("to_trucalenzer"):
                continue
            if todo.get("series_id"):
                if todo["series_id"] not in seen:
                    seen.add(todo["series_id"])
                    items.append(todo["series"])
                continue
            items.append(todo["item"])
        return items

    def deliver_staged(self, staged: list[dict]) -> str:
        return self.deliver_all(self.items_from_staged(staged))

    def deliver_all(self, items: list[dict]) -> str:
        with open(self.path, "w", encoding="utf-8", newline="") as f:
            f.write(self.render(items))
        return self.path


class TruCalenZerImportFile:
    """Writes a TruCalenZer academic-import file (contract 1 above)."""

    name = "trucalenzer-import"

    def __init__(self, path: str, course: str | None = None, conversation_id=None,
                 student_name: str | None = None):
        if not path.lower().endswith(".json"):
            raise ValueError("TruCalenZer only parses JSON imports from files named *.json")
        self.path = path
        self.course = course
        self.conversation_id = conversation_id
        self.student_name = student_name if student_name is not None else os.environ.get("TRUCALENZER_STUDENT_NAME")

    def record(self, item: dict) -> dict:
        record = {
            "title": item["title"],
            "course": self.course or "",
            "possible date": item["date"],
            "source id": f"bee-stinger-{commitment_key(item, self.conversation_id)}",
            "notes": self._notes(item),
        }
        if self.student_name:
            record["student name"] = self.student_name
        return record

    @staticmethod
    def _notes(item: dict) -> str:
        if item.get("kind") == "study":
            # TruCalenZer's import has no time or duration fields, so the
            # block's wall-clock window travels in the notes.
            return (f"Study block {item['start']}, {item['duration_minutes']} min. "
                    f"{item.get('notes') or 'Generated by Bee Stinger.'}")
        return f"From a Bee lecture capture ({item['kind']}). Heard: \"{item['quote']}\""

    def deliver_all(self, items: list[dict]) -> str:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"assignments": [self.record(i) for i in items]}, f, indent=2, ensure_ascii=False)
        return self.path

    def deliver_staged(self, staged: list[dict]) -> str:
        """One import record per staged to-do TruCalenZer receives, in
        staged order (each weekly study session is its own dated task)."""
        return self.deliver_all([t["item"] for t in staged if t.get("to_trucalenzer")])


class TruCalenZerOutlookAdapter:
    """Creates a "Torgy"-category Outlook event that TruCalenZer imports on
    its next Outlook sync (contract 2 above). Dry-run by default."""

    name = "trucalenzer-outlook"

    def __init__(self, token: str | None = None, dry_run: bool = True, tz: tzinfo = timezone.utc,
                 start_time: time = time(9, 0), minutes: int = 30, conversation_id=None):
        self.token = token or os.environ.get("TRUCALENZER_GRAPH_TOKEN")
        self.dry_run = dry_run
        self.tz = tz
        self.start_time = start_time
        self.minutes = minutes
        self.conversation_id = conversation_id

    def _task_id(self, item: dict) -> str:
        """Deterministic TruCalenZer task id for one commitment (B1 rule 1).

        UUIDv5 over the same commitment key as the Graph transactionId, in
        its own derivation domain, so re-imports link instead of duplicate.
        """
        return str(uuid.uuid5(_ID_NAMESPACE, commitment_key(item, self.conversation_id) + ":torgy-task"))

    def payload(self, item: dict) -> dict:
        # B1: a commitment arrives as a work block; blocks under 5 minutes
        # fall back to 30 instead of creating a sliver event.
        minutes = self.minutes if self.minutes >= 5 else 30
        start = _local_to_utc_iso(item["date"], self.start_time, self.tz)
        end_dt = datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ") + timedelta(minutes=minutes)
        return {
            "subject": item["title"],
            "categories": [TRUCALENZER_CATEGORY],
            "start": {"dateTime": start.rstrip("Z"), "timeZone": "UTC"},
            "end": {"dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
            "body": {
                "contentType": "text",
                # Markers go on their own lines: TruCalenZer's parser needs a
                # "\n" before each "Name:" line (INVESTIGATION B1).
                "content": f"From a Bee lecture capture ({item['kind']}, date heard in class, "
                           f"not officially confirmed). \"{item['quote']}\"\n\n"
                           f"Torgy-Task-ID: {self._task_id(item)}\n"
                           f"Torgy-Task-Version: 1",
            },
            # Graph de-duplicates event creation on transactionId, so a re-run
            # of the same lecture does not create a second event.
            "transactionId": str(uuid.uuid5(_ID_NAMESPACE, commitment_key(item, self.conversation_id))),
        }

    def deliver(self, item: dict) -> dict:
        payload = self.payload(item)
        if self.dry_run:
            print(f"[dry-run:{self.name}] POST {GRAPH_EVENTS_URL} {json.dumps(payload, ensure_ascii=False)}")
            return {"adapter": self.name, "dry_run": True, "payload": payload}
        if not self.token:
            return {"adapter": self.name, "dry_run": False, "skipped": "TRUCALENZER_GRAPH_TOKEN not set"}
        req = urllib.request.Request(GRAPH_EVENTS_URL, data=json.dumps(payload).encode(), method="POST")
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Content-Type", "application/json")
        req.add_header("Prefer", 'outlook.timezone="UTC", IdType="ImmutableId"')
        req.add_header("User-Agent", USER_AGENT)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode() or "{}")
                return {"adapter": self.name, "dry_run": False, "status": resp.status, "event_id": body.get("id")}
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            return {"adapter": self.name, "dry_run": False, "error": f"Graph HTTP {e.code}: {detail}"}
        except urllib.error.URLError as e:
            return {"adapter": self.name, "dry_run": False, "error": f"Graph unreachable: {e.reason}"}
