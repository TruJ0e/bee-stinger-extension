"""Bee Stinger command line.

  python -m bee_stinger.cli demo [--out DIR] [--live]
      Run the full pipeline on the bundled fixture lecture: transcript ->
      concept cards -> study guide + flashcards + 3-level quiz, plus
      commitment extraction delivered to the adapters (dry-run unless
      --live, which additionally requires credentials in the environment:
      BEE_TOKEN for Bee todos, TRUCALENZER_GRAPH_TOKEN for the TruCalenZer
      Outlook route). Without --live nothing is sent anywhere.

  python -m bee_stinger.cli fetch --conversation ID [--out DIR]
      Same pipeline against a live Bee conversation (requires BEE_TOKEN,
      Developer Mode enabled in the Bee app).

  python -m bee_stinger.cli file --path TRANSCRIPT.txt [--title T] [--out DIR]
      Same pipeline on a plain-text transcript from any source.

  python -m bee_stinger.cli gpt --topic "Photosynthesis" [--out DIR]
      INTERIM stand-in input: generate a lecture transcript on the topic
      with the configured LLM (requires LLM_API_KEY), then run the same
      pipeline. Simulated data for development/demo — not a Bee capture.

Inputs: Bee is the real source. GPT is the interim source until a Bee
developer token is available. Plain text takes a transcript from anywhere.
See bee_stinger/sources.py.

Pipeline order: transcript -> cards + quiz + guide, named as a subject
-> commitments (spoken + generated study blocks) -> the Bee to-do list is
STAGED first (staged_todos.json: "guide ready" + every commitment) ->
TruCalenZer artifacts (import file, .ics) are generated from that staged
list -> the TRSS subject bundle is exported.

Study-block options (every command): --study-time HH:MM (default 17:00),
--study-minutes N (60), --review-minutes N (60), --study-weeks N (4,
used when no exam date was heard), --trss-unit N (1, the TRSS unit
number in the bundle).

Outputs: guide.html, cards.json, quiz.json, commitments.json,
staged_todos.json, commitments.ics, trucalenzer-import.json,
transcript.txt and trss-subject/<subject>-chapter-<n>/ in the output
directory.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone, tzinfo

from .adapters import BeeTodoAdapter, IcsAdapter, TruCalenZerImportFile, TruCalenZerOutlookAdapter
from .assemble import spoken_text, title_of, transcript_lines
from .bee_client import BeeClient, BeeError, FixtureClient
from .bundle import DEFAULT_UNIT_NUMBER, write_bundle
from .commitments import extract_commitments
from .extract import extract_cards
from .quiz import build_quiz
from .render import render_guide
from .sources import SourceError, conversation_from_text, generate_lecture_conversation
from .staging import for_trucalenzer, stage_todos, write_staged
from .study import (
    DEFAULT_REVIEW_MINUTES, DEFAULT_STUDY_MINUTES, DEFAULT_STUDY_START, DEFAULT_WEEKS_WITHOUT_EXAM,
    parse_hhmm, plan_study_blocks,
)
from .subject import derive_subject

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "lecture_conversation.json")


def _captured_at(conversation: dict) -> datetime | None:
    raw = conversation.get("start_time") or conversation.get("created_at")
    if isinstance(raw, (int, float)):  # Bee returns some times as epoch ms
        return datetime.fromtimestamp(raw / 1000, tz=timezone.utc)
    if isinstance(raw, str) and raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _reference_date(conversation: dict) -> date:
    when = _captured_at(conversation)
    if when is None:
        return date.today()
    return when.astimezone(_capture_tz(conversation)).date() if when.tzinfo else when.date()


def _capture_tz(conversation: dict) -> tzinfo:
    name = conversation.get("timezone")
    if isinstance(name, str) and name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name)
        except Exception:  # unknown zone, or no tz database (Windows without tzdata)
            pass
    when = _captured_at(conversation)
    return when.tzinfo if when and when.tzinfo else timezone.utc


def _write_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def run_pipeline(conversation: dict, out_dir: str, live: bool = False, bee_client=None,
                 study: dict | None = None, trss_unit: int = DEFAULT_UNIT_NUMBER) -> dict:
    """Run the whole pipeline. study holds plan_study_blocks keyword
    options (start, minutes, review_minutes, weeks_without_exam)."""
    os.makedirs(out_dir, exist_ok=True)
    title = title_of(conversation)
    text = spoken_text(conversation)
    ref = _reference_date(conversation)
    tz = _capture_tz(conversation)
    conv_id = conversation.get("id")

    # 1. Study material, named as a subject.
    cards, path_used = extract_cards(text, title)
    quiz = build_quiz(cards)
    subject = derive_subject(title, cards)

    # 2. Commitments: what was said aloud (unchanged), then the study
    #    blocks planned from it.
    spoken = extract_commitments(text, ref)
    study_blocks = plan_study_blocks(subject["name"], spoken, ref, **(study or {}))
    commitments = spoken + study_blocks

    with open(os.path.join(out_dir, "transcript.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(transcript_lines(conversation)))
    _write_json(os.path.join(out_dir, "cards.json"), cards)
    _write_json(os.path.join(out_dir, "quiz.json"), quiz)
    _write_json(os.path.join(out_dir, "commitments.json"), commitments)
    guide_path = os.path.join(out_dir, "guide.html")
    with open(guide_path, "w", encoding="utf-8") as f:
        f.write(render_guide(title, cards, quiz, commitments, subject=subject["name"]))

    # 3. Stage the Bee to-do list FIRST: "guide ready" + every commitment.
    dry = not live
    staged = stage_todos(subject, commitments, tz=tz, conversation_id=conv_id)
    staged_path = write_staged(os.path.join(out_dir, "staged_todos.json"), subject, staged, dry_run=dry)
    if live and bee_client is None and os.environ.get("BEE_TOKEN"):
        bee_client = BeeClient()
    bee_adapter = BeeTodoAdapter(client=bee_client if live else None, dry_run=dry, tz=tz)
    deliveries = [bee_adapter.send(todo["bee_payload"]) for todo in staged]

    # 4. TruCalenZer receives exactly the staged list (its dated items).
    ics_path = IcsAdapter(os.path.join(out_dir, "commitments.ics"), conversation_id=conv_id).deliver_staged(staged)
    import_path = TruCalenZerImportFile(
        os.path.join(out_dir, "trucalenzer-import.json"), course=subject["course"] or subject["name"],
        conversation_id=conv_id,
    ).deliver_staged(staged)
    # The Outlook/Graph route is deferred (owner's call, 2026-10-21); it is
    # left exactly as it was: dry-run printouts for the spoken commitments.
    cal_adapter = TruCalenZerOutlookAdapter(dry_run=dry, tz=tz, conversation_id=conv_id)
    for item in spoken:
        deliveries.append(cal_adapter.deliver(item))

    # 5. Export the TRSS subject bundle.
    when = _captured_at(conversation)
    generated_at = when.isoformat() if when else ref.isoformat()
    bundle = write_bundle(out_dir, subject, cards, generated_at, guide_path=guide_path,
                          unit=trss_unit, source=conversation.get("source"))

    return {
        "title": title,
        "subject": subject,
        "extraction_path": path_used,
        "cards": len(cards),
        "quiz_questions": len(quiz),
        "commitments": commitments,
        "spoken_commitments": spoken,
        "study_blocks": study_blocks,
        "staged": staged,
        "staged_path": staged_path,
        "trucalenzer_items": len(for_trucalenzer(staged)),
        "ics": ics_path,
        "trucalenzer_import": import_path,
        "bundle": bundle,
        "deliveries": deliveries,
        "out_dir": out_dir,
    }


def _study_options(args) -> dict:
    return {
        "start": parse_hhmm(args.study_time),
        "minutes": args.study_minutes,
        "review_minutes": args.review_minutes,
        "weeks_without_exam": args.study_weeks,
    }


def _print_summary(summary: dict, live: bool) -> None:
    subject = summary["subject"]
    print(f"Title:        {summary['title']}")
    print(f"Subject:      {subject['name']}  (named from {subject['source']})")
    print(f"Extraction:   {summary['extraction_path']}")
    print(f"Cards:        {summary['cards']}")
    print(f"Quiz:         {summary['quiz_questions']} questions")
    if summary["cards"] == 0:
        print("              (no concept cards found — empty or non-lecture transcript?)")
    print(f"Commitments:  {len(summary['spoken_commitments'])} spoken + "
          f"{len(summary['study_blocks'])} study blocks")
    for item in summary["commitments"]:
        when = item["date"] + (f" {item['start']}" if item.get("start") else "")
        rec = item.get("recurrence")
        extra = f", weekly x{rec['count']}" if rec else ""
        print(f"  - {when}  {item['title']}  ({item['kind']}{extra})")
    mode = "live" if live else "dry-run"
    print(f"Bee to-dos:   {len(summary['staged'])} staged ({mode}) -> {summary['staged_path']}")
    for todo in summary["staged"]:
        flag = "" if todo["to_trucalenzer"] else "  [Bee only]"
        print(f"  {todo['position']:>2}. {todo['bee_payload']['text']}{flag}")
    print(f"TruCalenZer:  {summary['trucalenzer_items']} items from the staged list -> "
          f"{summary['trucalenzer_import']}, {summary['ics']}")
    bundle = summary["bundle"]
    print(f"TRSS bundle:  {bundle['path']}  ({bundle['cards']} cards, {bundle['questions']} questions)")
    if not live:
        print("Deliveries:   dry-run only (nothing sent; pass --live to send)")
    else:
        for d in summary["deliveries"]:
            if not d.get("dry_run"):
                outcome = d.get("error") or d.get("skipped") or "sent"
                print(f"  [{d['adapter']}] {outcome}")
    print(f"Artifacts in: {summary['out_dir']}/ (guide.html, cards.json, quiz.json, commitments.json, "
          "staged_todos.json, commitments.ics, trucalenzer-import.json, transcript.txt, trss-subject/)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bee-stinger")
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--study-time", default=DEFAULT_STUDY_START.strftime("%H:%M"),
                        help="local start time of generated study blocks (HH:MM)")
    common.add_argument("--study-minutes", type=int, default=DEFAULT_STUDY_MINUTES)
    common.add_argument("--review-minutes", type=int, default=DEFAULT_REVIEW_MINUTES)
    common.add_argument("--study-weeks", type=int, default=DEFAULT_WEEKS_WITHOUT_EXAM,
                        help="weekly sessions to plan when no exam date was heard")
    common.add_argument("--trss-unit", type=int, default=DEFAULT_UNIT_NUMBER,
                        help="TRSS unit (chapter) number for the subject bundle")

    p_demo = sub.add_parser("demo", parents=[common], help="run the pipeline on the fixture lecture")
    p_demo.add_argument("--out", default="output")
    p_demo.add_argument("--live", action="store_true", help="allow real adapter sends (needs env credentials)")

    p_fetch = sub.add_parser("fetch", parents=[common], help="run the pipeline on a live Bee conversation")
    p_fetch.add_argument("--conversation", required=True)
    p_fetch.add_argument("--out", default="output")
    p_fetch.add_argument("--live", action="store_true")

    p_file = sub.add_parser("file", parents=[common], help="run the pipeline on a plain-text transcript")
    p_file.add_argument("--path", required=True)
    p_file.add_argument("--title")
    p_file.add_argument("--out", default="output")
    p_file.add_argument("--live", action="store_true")

    p_gpt = sub.add_parser("gpt", parents=[common],
                           help="INTERIM: generate a lecture on a topic with the LLM, then run the pipeline")
    p_gpt.add_argument("--topic", required=True)
    p_gpt.add_argument("--out", default="output")
    p_gpt.add_argument("--live", action="store_true")

    args = parser.parse_args(argv)

    try:
        opts = {"study": _study_options(args), "trss_unit": args.trss_unit}
        if args.command == "demo":
            client = FixtureClient(os.path.abspath(FIXTURE))
            conversation = client.conversation()
            summary = run_pipeline(conversation, args.out, live=args.live, **opts)
        elif args.command == "file":
            with open(args.path, "r", encoding="utf-8") as f:
                conversation = conversation_from_text(f.read(), title=args.title)
            summary = run_pipeline(conversation, args.out, live=args.live, **opts)
        elif args.command == "gpt":
            conversation = generate_lecture_conversation(args.topic)
            print("Input:        GPT stand-in (simulated lecture on the topic — NOT Bee data)")
            summary = run_pipeline(conversation, args.out, live=args.live, **opts)
        else:
            bee = BeeClient()
            conversation = bee.conversation(args.conversation)
            if not isinstance(conversation, dict):
                raise BeeError(f"Unexpected conversation response type: {type(conversation).__name__}")
            summary = run_pipeline(conversation, args.out, live=args.live, bee_client=bee, **opts)
    except (BeeError, SourceError, OSError, ValueError) as e:  # ValueError also covers bad --study-* values
        print(f"bee-stinger: {e}", file=sys.stderr)
        return 2

    _print_summary(summary, args.live)
    return 0


if __name__ == "__main__":
    sys.exit(main())
