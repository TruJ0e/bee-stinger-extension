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

Outputs: guide.html, cards.json, quiz.json, commitments.json,
commitments.ics, trucalenzer-import.json, transcript.txt in the output
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
from .commitments import extract_commitments
from .extract import extract_cards
from .quiz import build_quiz
from .render import render_guide

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


def run_pipeline(conversation: dict, out_dir: str, live: bool = False, bee_client=None) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    title = title_of(conversation)
    text = spoken_text(conversation)
    ref = _reference_date(conversation)

    cards, path_used = extract_cards(text, title)
    quiz = build_quiz(cards)
    commitments = extract_commitments(text, ref)

    with open(os.path.join(out_dir, "transcript.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(transcript_lines(conversation)))
    with open(os.path.join(out_dir, "cards.json"), "w", encoding="utf-8") as f:
        json.dump(cards, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, "quiz.json"), "w", encoding="utf-8") as f:
        json.dump(quiz, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, "commitments.json"), "w", encoding="utf-8") as f:
        json.dump(commitments, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, "guide.html"), "w", encoding="utf-8") as f:
        f.write(render_guide(title, cards, quiz, commitments))

    deliveries = []
    dry = not live
    tz = _capture_tz(conversation)
    conv_id = conversation.get("id")
    if live and bee_client is None and os.environ.get("BEE_TOKEN"):
        bee_client = BeeClient()
    bee_adapter = BeeTodoAdapter(client=bee_client if live else None, dry_run=dry, tz=tz)
    cal_adapter = TruCalenZerOutlookAdapter(dry_run=dry, tz=tz, conversation_id=conv_id)
    for item in commitments:
        deliveries.append(bee_adapter.deliver(item))
        deliveries.append(cal_adapter.deliver(item))
    ics_path = IcsAdapter(os.path.join(out_dir, "commitments.ics"), conversation_id=conv_id).deliver_all(commitments)
    import_path = TruCalenZerImportFile(
        os.path.join(out_dir, "trucalenzer-import.json"), course=title, conversation_id=conv_id
    ).deliver_all(commitments)

    return {
        "title": title,
        "extraction_path": path_used,
        "cards": len(cards),
        "quiz_questions": len(quiz),
        "commitments": commitments,
        "ics": ics_path,
        "trucalenzer_import": import_path,
        "deliveries": deliveries,
        "out_dir": out_dir,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bee-stinger")
    sub = parser.add_subparsers(dest="command", required=True)

    p_demo = sub.add_parser("demo", help="run the pipeline on the fixture lecture")
    p_demo.add_argument("--out", default="output")
    p_demo.add_argument("--live", action="store_true", help="allow real adapter sends (needs env credentials)")

    p_fetch = sub.add_parser("fetch", help="run the pipeline on a live Bee conversation")
    p_fetch.add_argument("--conversation", required=True)
    p_fetch.add_argument("--out", default="output")
    p_fetch.add_argument("--live", action="store_true")

    args = parser.parse_args(argv)

    try:
        if args.command == "demo":
            client = FixtureClient(os.path.abspath(FIXTURE))
            conversation = client.conversation()
            summary = run_pipeline(conversation, args.out, live=args.live)
        else:
            bee = BeeClient()
            conversation = bee.conversation(args.conversation)
            if not isinstance(conversation, dict):
                raise BeeError(f"Unexpected conversation response type: {type(conversation).__name__}")
            summary = run_pipeline(conversation, args.out, live=args.live, bee_client=bee)
    except (BeeError, OSError, ValueError) as e:
        print(f"bee-stinger: {e}", file=sys.stderr)
        return 2

    print(f"Title:        {summary['title']}")
    print(f"Extraction:   {summary['extraction_path']}")
    print(f"Cards:        {summary['cards']}")
    print(f"Quiz:         {summary['quiz_questions']} questions")
    if summary["cards"] == 0:
        print("              (no concept cards found — empty or non-lecture transcript?)")
    print(f"Commitments:  {len(summary['commitments'])}")
    for item in summary["commitments"]:
        print(f"  - {item['date']}  {item['title']}  ({item['kind']})")
    sent = [d for d in summary["deliveries"] if not d.get("dry_run")]
    if not args.live:
        print("Deliveries:   dry-run only (nothing sent; pass --live to send)")
    else:
        for d in sent:
            outcome = d.get("error") or d.get("skipped") or "sent"
            print(f"  [{d['adapter']}] {outcome}")
    print(f"Artifacts in: {summary['out_dir']}/ (guide.html, cards.json, quiz.json, commitments.json, "
          "commitments.ics, trucalenzer-import.json, transcript.txt)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
