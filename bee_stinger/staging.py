"""Bee to-do staging: the single list both Bee and TruCalenZer are fed from.

Order of operations (owner's pipeline, 2026-10-21):

1. A "guide ready" to-do ("Your study guide for <subject> is ready") is
   staged first, together with one to-do per commitment occurrence
   (exams, due dates, readings, and every generated study session).
2. The staged list is written to staged_todos.json and delivered to the
   Bee to-do list (dry-run by default: no Bee token exists yet).
3. The TruCalenZer artifacts (import file, .ics) are generated FROM the
   staged list, never from the raw commitments, so what the user sees on
   Bee is exactly what TruCalenZer receives.

Every dated staged to-do goes to TruCalenZer ("to_trucalenzer": true).
The guide-ready to-do is a notification with no date, so it is the one
item that stays on Bee only ("to_trucalenzer": false) — TruCalenZer
assigns things to dates, and it has none.

A weekly study series is staged as one to-do per session (Bee to-dos and
TruCalenZer tasks have no recurrence), each carrying the series id so the
.ics writer can fold them back into one recurring event.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timezone, tzinfo

from .adapters import BeeTodoAdapter, commitment_key
from .study import occurrences


def guide_ready_text(subject_name: str) -> str:
    return f"Your study guide for {subject_name} is ready"


def _occurrence_items(item: dict) -> list[dict]:
    dates = occurrences(item)
    if len(dates) == 1 and dates[0] == item["date"] and not item.get("recurrence"):
        return [item]
    out = []
    for n, day in enumerate(dates, start=1):
        occ = {k: v for k, v in item.items() if k != "recurrence"}
        occ["date"] = day
        if len(dates) > 1:
            occ["title"] = f"{item['title']} (week {n} of {len(dates)})"
        occ["occurrence"] = n
        occ["of"] = len(dates)
        out.append(occ)
    return out


def _sort_key(occ: dict) -> tuple:
    return (occ["date"], occ.get("start") or "", occ["title"])


def stage_todos(subject: dict, commitments: list[dict], tz: tzinfo = timezone.utc,
                conversation_id=None) -> list[dict]:
    """Build the staged Bee to-do list: guide-ready first, then every
    commitment occurrence in date order. Deterministic."""
    bee = BeeTodoAdapter(tz=tz)
    guide_key = hashlib.sha1(f"{conversation_id}|guide-ready|{subject['slug']}".encode()).hexdigest()[:16]
    staged = [{
        "position": 1,
        "id": f"bee-stinger-{guide_key}",
        "kind": "guide-ready",
        "title": guide_ready_text(subject["name"]),
        "date": None,
        "bee_payload": {"text": guide_ready_text(subject["name"])},
        "to_trucalenzer": False,
    }]
    entries = []
    for item in commitments:
        series_id = f"bee-stinger-{commitment_key(item, conversation_id)}" if item.get("recurrence") else None
        for occ in _occurrence_items(item):
            entries.append((item, occ, series_id))
    entries.sort(key=lambda e: _sort_key(e[1]))
    for item, occ, series_id in entries:
        todo = {
            "position": len(staged) + 1,
            "id": f"bee-stinger-{commitment_key(occ, conversation_id)}",
            "kind": occ["kind"],
            "title": occ["title"],
            "date": occ["date"],
            "bee_payload": bee.payload(occ),
            "to_trucalenzer": True,
            "item": occ,
        }
        if occ.get("start"):
            todo["start"] = occ["start"]
            todo["duration_minutes"] = occ["duration_minutes"]
        if series_id:
            todo["series_id"] = series_id
            todo["series"] = item
        staged.append(todo)
    return staged


def for_trucalenzer(staged: list[dict]) -> list[dict]:
    """The staged to-dos TruCalenZer receives, in staged order."""
    return [t for t in staged if t.get("to_trucalenzer")]


def write_staged(path: str, subject: dict, staged: list[dict], dry_run: bool) -> str:
    public = []
    for todo in staged:
        entry = {k: v for k, v in todo.items() if k not in ("item", "series")}
        public.append(entry)
    doc = {
        "subject": subject,
        "bee_delivery": "dry-run" if dry_run else "live",
        "order": "staged first; TruCalenZer import + .ics are generated from the to_trucalenzer items below",
        "todos": public,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    return path
