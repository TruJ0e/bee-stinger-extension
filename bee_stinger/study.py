"""Study blocks: generated study sessions as a first-class commitment type.

Spoken commitments say *when* things happen (an exam, a due date). The
study blocks say *when to prepare*. From the capture date and the
extracted commitments this module plans, deterministically:

- a recurring weekly session, "Study: <Subject>", starting the day after
  the capture, at a fixed local time (default 17:00 for 60 minutes),
  running until the last exam (or the last due date, if that is later);
- a final review block the day before each exam;
- with no exam date at all, a plain weekly series of N sessions
  (default 4).

A weekly occurrence that would land on an exam day or a review day is
skipped (and listed in "exdates"), so a day never holds two blocks.

Each block is a commitment item with kind "study":
    {"title", "date" (first session, ISO), "kind": "study",
     "start": "HH:MM", "duration_minutes": int,
     "recurrence": {"freq": "weekly", "interval": 1, "count", "until",
                    "dates": [...], "exdates": [...]}   # weekly series only
     "quote": None, "notes": "..."}
"quote" is None because nothing was said aloud: these are generated,
not heard. Extracted spoken commitments are never modified.

Times are local to the capture (a floating wall-clock time): "17:00"
means 5 pm where the student is, across DST changes.
"""

from __future__ import annotations

from datetime import date, time, timedelta

DEFAULT_STUDY_START = time(17, 0)
DEFAULT_STUDY_MINUTES = 60
DEFAULT_REVIEW_MINUTES = 60
DEFAULT_WEEKS_WITHOUT_EXAM = 4


def parse_hhmm(text: str) -> time:
    """'17:00' -> time(17, 0); raises ValueError on anything else."""
    hours, _, minutes = (text or "").strip().partition(":")
    if not (hours.isdigit() and minutes.isdigit() and len(minutes) == 2):
        raise ValueError(f"study time must be HH:MM, got {text!r}")
    return time(int(hours), int(minutes))


def _block(title: str, day: date, start: time, minutes: int, notes: str) -> dict:
    return {
        "title": title,
        "date": day.isoformat(),
        "kind": "study",
        "start": start.strftime("%H:%M"),
        "duration_minutes": minutes,
        "quote": None,
        "notes": notes,
    }


def plan_study_blocks(
    subject_name: str,
    commitments: list[dict],
    capture_date: date,
    start: time = DEFAULT_STUDY_START,
    minutes: int = DEFAULT_STUDY_MINUTES,
    review_minutes: int = DEFAULT_REVIEW_MINUTES,
    weeks_without_exam: int = DEFAULT_WEEKS_WITHOUT_EXAM,
) -> list[dict]:
    if minutes < 5 or review_minutes < 5:
        raise ValueError("study blocks must be at least 5 minutes")
    if weeks_without_exam < 1:
        raise ValueError("weeks_without_exam must be at least 1")

    def future(kind: str) -> list[tuple[date, dict]]:
        out = []
        for item in commitments:
            if item.get("kind") != kind:
                continue
            day = date.fromisoformat(item["date"])
            if day > capture_date:
                out.append((day, item))
        return sorted(out, key=lambda pair: (pair[0], pair[1]["title"]))

    exams = future("exam")
    dues = future("due")
    first = capture_date + timedelta(days=1)

    reviews: list[dict] = []
    review_days: set[date] = set()
    for exam_day, exam in exams:
        review_day = exam_day - timedelta(days=1)
        if review_day <= capture_date or review_day in review_days:
            continue
        review_days.add(review_day)
        reviews.append(_block(
            f"Final review: {subject_name} ({exam['title']})", review_day, start, review_minutes,
            f"Generated final review the day before {exam['title']} on {exam_day.isoformat()}.",
        ))

    exdates: list[date] = []
    if exams:
        end = max([exams[-1][0]] + [d for d, _ in dues])
        blocked = review_days | {d for d, _ in exams}
        sessions: list[date] = []
        day = first
        while day < end:
            (exdates if day in blocked else sessions).append(day)
            day += timedelta(days=7)
        why = f"until {exams[-1][1]['title']} on {exams[-1][0].isoformat()}"
        if end != exams[-1][0]:
            why += f" and the last due date {end.isoformat()}"
    else:
        sessions = [first + timedelta(days=7 * k) for k in range(weeks_without_exam)]
        why = f"{weeks_without_exam} weeks (no exam date was heard)"

    blocks: list[dict] = []
    if sessions:
        weekly = _block(
            f"Study: {subject_name}", sessions[0], start, minutes,
            f"Generated weekly study session, every {sessions[0].strftime('%A')} "
            f"{start.strftime('%H:%M')}, {why}.",
        )
        weekly["recurrence"] = {
            "freq": "weekly",
            "interval": 1,
            "count": len(sessions),
            "until": sessions[-1].isoformat(),
            "dates": [d.isoformat() for d in sessions],
            "exdates": [d.isoformat() for d in exdates if sessions[0] < d < sessions[-1]],
        }
        blocks.append(weekly)
    blocks.extend(reviews)
    return blocks


def occurrences(item: dict) -> list[str]:
    """Every date a commitment occupies: its recurrence dates, or its date."""
    rec = item.get("recurrence")
    if rec and rec.get("dates"):
        return list(rec["dates"])
    return [item["date"]]
