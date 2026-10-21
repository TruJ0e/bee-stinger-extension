"""Bee Stinger command line.

  python -m bee_stinger.cli demo [--out DIR] [--live]
      Run the full pipeline on the bundled fixture lecture: transcript ->
      concept cards -> study guide + flashcards + 3-level quiz, plus
      commitment extraction delivered to the adapters (dry-run unless
      --live, which additionally requires credentials in the environment).

  python -m bee_stinger.cli fetch --conversation ID [--out DIR]
      Same pipeline against a live Bee conversation (requires BEE_TOKEN,
      Developer Mode enabled in the Bee app).

Outputs: guide.html, cards.json, quiz.json, commitments.json,
commitments.ics in the output directory.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime

from .adapters import BeeTodoAdapter, IcsAdapter, TruCalenZerAdapter
from .assemble import spoken_text, title_of, transcript_lines
from .bee_client import BeeClient, FixtureClient
from .commitments import extract_commitments
from .extract import extract_cards
from .quiz import build_quiz
from .render import render_guide

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "lecture_conversation.json")


def _reference_date(conversation: dict) -> date:
    raw = conversation.get("created_at")
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    return date.today()


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
    bee_adapter = BeeTodoAdapter(client=bee_client if live else None, dry_run=dry)
    cal_adapter = TruCalenZerAdapter(dry_run=dry)
    for item in commitments:
        deliveries.append(bee_adapter.deliver(item))
        deliveries.append(cal_adapter.deliver(item))
    ics_path = IcsAdapter(os.path.join(out_dir, "commitments.ics")).deliver_all(commitments)

    return {
        "title": title,
        "extraction_path": path_used,
        "cards": len(cards),
        "quiz_questions": len(quiz),
        "commitments": commitments,
        "ics": ics_path,
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

    if args.command == "demo":
        client = FixtureClient(os.path.abspath(FIXTURE))
        conversation = client.conversation()
        summary = run_pipeline(conversation, args.out, live=args.live)
    else:
        bee = BeeClient()
        conversation = bee.conversation(args.conversation)
        summary = run_pipeline(conversation, args.out, live=args.live, bee_client=bee)

    print(f"Title:        {summary['title']}")
    print(f"Extraction:   {summary['extraction_path']}")
    print(f"Cards:        {summary['cards']}")
    print(f"Quiz:         {summary['quiz_questions']} questions")
    print(f"Commitments:  {len(summary['commitments'])}")
    for item in summary["commitments"]:
        print(f"  - {item['date']}  {item['title']}  ({item['kind']})")
    print(f"Artifacts in: {summary['out_dir']}/ (guide.html, cards.json, quiz.json, commitments.json, commitments.ics, transcript.txt)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
