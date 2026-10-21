"""Self-tests for the Bee Stinger pipeline. Stdlib only.

Run:  python3 tests/selftest.py
Exercises the offline path end to end against the bundled fixture and
asserts the concrete outputs the demo depends on, then covers edge cases:
date resolution, extractor guards, LLM-output parsing, quiz answer
leakage, adapter payload contracts, the no-network guarantee of dry-run,
SSE parsing, and Bee conversation shapes. No network, no keys.
"""

import contextlib
import io
import os
import sys
import tempfile
import urllib.request
from datetime import date, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bee_stinger import cli  # noqa: E402
from bee_stinger.adapters import (  # noqa: E402
    BeeTodoAdapter, IcsAdapter, TruCalenZerImportFile, TruCalenZerOutlookAdapter,
)
from bee_stinger.assemble import spoken_text, title_of, transcript_lines  # noqa: E402
from bee_stinger.bee_client import (  # noqa: E402
    BeeClient, BeeError, FixtureClient, infer_event_type, parse_sse,
)
from bee_stinger.commitments import extract_commitments  # noqa: E402
from bee_stinger.extract import (  # noqa: E402
    SCHEMA_FIELDS, ExtractionError, extract_cards, extract_cards_offline, parse_llm_cards,
)
from bee_stinger.quiz import build_quiz  # noqa: E402
from bee_stinger.render import render_guide  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "lecture_conversation.json")
FAILURES = []


def check(name: str, condition: bool, detail: str = ""):
    print(("PASS " if condition else "FAIL ") + name + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def fixture_checks() -> list[dict]:
    conv = FixtureClient(FIXTURE).conversation()
    text = spoken_text(conv)
    check("fixture loads with utterances", len(text) > 200)

    cards = extract_cards_offline(text, conv["title"])
    terms = {c["term"] for c in cards}
    check("offline extraction finds >= 6 cards", len(cards) >= 6, f"got {len(cards)}: {terms}")
    for expected in ("Supply", "Demand", "Equilibrium", "Elasticity"):
        check(f"card present: {expected}", expected in terms)
    check(
        "every card carries the full TRSS schema",
        all(all(c.get(f) not in (None, "") for f in SCHEMA_FIELDS) for c in cards),
    )
    check(
        "examples are attached to cards",
        sum(1 for c in cards if c["examples"]) >= 3,
        f"cards with examples: {[c['term'] for c in cards if c['examples']]}",
    )

    quiz = build_quiz(cards)
    levels = {q["level"] for q in quiz}
    check("quiz covers all 3 levels", levels == {1, 2, 3}, f"levels: {levels}")
    check(
        "every quiz answer_index is valid",
        all(0 <= q["answer_index"] < len(q["choices"]) and len(q["choices"]) >= 2 for q in quiz),
    )
    check("quiz is deterministic", build_quiz(cards) == quiz)

    # Fixture was recorded Wednesday 2026-10-21.
    commitments = extract_commitments(text, date(2026, 10, 21))
    by_date = {c["date"]: c for c in commitments}
    check("3 commitments extracted", len(commitments) == 3, f"got {commitments}")
    check("exam lands on 2026-10-29", "2026-10-29" in by_date and by_date["2026-10-29"]["kind"] == "exam")
    check("problem set due Friday 2026-10-23", "2026-10-23" in by_date)
    check("reading before Monday 2026-10-26", "2026-10-26" in by_date)

    with tempfile.TemporaryDirectory() as tmp:
        path = IcsAdapter(os.path.join(tmp, "c.ics")).deliver_all(commitments)
        with open(path, encoding="utf-8", newline="") as f:
            ics = f.read()
    check("ics has one VEVENT per commitment", ics.count("BEGIN:VEVENT") == 3)
    check("ics is a valid calendar shell", ics.startswith("BEGIN:VCALENDAR") and "END:VCALENDAR" in ics)
    check("ics uses CRLF line endings", "\r\n" in ics and "\n" not in ics.replace("\r\n", ""))

    guide = render_guide(conv["title"], cards, quiz, commitments)
    check("guide renders concepts", all(t in guide for t in ("Supply", "Demand", "Elasticity")))
    check("guide renders the 3-level quiz", "Level 3" in guide and "Level 1" in guide)
    check("guide renders commitments", "2026-10-29" in guide)
    return cards


def _dates(text: str, ref: date) -> list[str]:
    return [c["date"] for c in extract_commitments(text, ref)]


def commitment_checks() -> None:
    wed = date(2026, 10, 21)  # a Wednesday
    check("empty transcript -> no commitments", extract_commitments("", wed) == [])
    check("no commitments in plain lecture text",
          extract_commitments("Supply is the quantity sellers offer. Demand is what buyers want.", wed) == [])
    check("invalid date 'February 30' does not crash or emit", _dates("The exam is on February 30.", wed) == [])
    check("invalid then valid date in one sentence: valid one wins",
          _dates("The exam moved from February 30 to March 3.", wed) == ["2027-03-03"])
    check("explicit year honored", _dates("The final exam is December 14, 2027.", wed) == ["2027-12-14"])
    check("month/day > 30 days past rolls to next year",
          _dates("The midterm is January 12.", date(2026, 12, 3)) == ["2027-01-12"])
    check("numeric date resolves", _dates("Homework 2 is due 11/3.", wed) == ["2026-11-03"])
    check("numeric date with 2-digit year", _dates("Homework 2 is due 11/3/27.", wed) == ["2027-11-03"])
    check("numeric non-date (13/40) ignored", _dates("Submit 13/40 of the problems.", wed) == [])
    check("weekday said on that weekday means next week", _dates("The quiz is Wednesday.", wed) == ["2026-10-28"])
    check("'next Friday' two days out skips to the following week",
          _dates("Homework 4 is due next Friday.", wed) == ["2026-10-30"])
    check("'last Friday' (past) is not a commitment", _dates("The quiz was last Friday.", wed) == [])
    final_project = extract_commitments("The final project is due Friday.", wed)
    check("'final project' is a due item, not an exam",
          len(final_project) == 1 and final_project[0]["kind"] == "due", str(final_project))
    check("'the final' alone is an exam",
          [c["kind"] for c in extract_commitments("The final is on December 10.", wed)] == ["exam"])
    q = extract_commitments("Is the quiz on Friday?", wed)
    check("question-mark sentence quote is not mangled", bool(q) and q[0]["quote"] == "Is the quiz on Friday?", str(q))
    dup = extract_commitments("The exam is Friday. Remember, the exam is Friday.", wed)
    check("duplicate commitment de-duplicated", len(dup) == 1, str(dup))


def extractor_checks(fixture_cards: list[dict]) -> None:
    cards, path = extract_cards("", "ECON 101")
    check("empty transcript -> zero cards, labeled", cards == [] and path.startswith("offline"), path)
    dup_cards = extract_cards_offline("Supply is a thing. Supply is another thing. Today is Monday.", "ECON")
    check("duplicate terms produce one card; 'Today is' is not a term",
          [c["term"] for c in dup_cards] == ["Supply"], str(dup_cards))
    check("card ids unique on fixture", len({c["id"] for c in fixture_cards}) == len(fixture_cards))

    good = ('[{"term": "Supply", "simple": "What sellers offer."}, '
            '{"term": "Demand", "simple": "What buyers want.", "examples": "coffee"}]')
    parsed = parse_llm_cards(good, "ECON 101")
    check("LLM: plain JSON array parsed + schema filled",
          len(parsed) == 2 and all(set(SCHEMA_FIELDS) <= set(c) and c["cue"] and c["apply"] for c in parsed))
    check("LLM: string examples coerced to list", parsed[1]["examples"] == ["coffee"])
    check("LLM: fenced JSON with prose parsed",
          len(parse_llm_cards("Here you go:\n```json\n" + good + "\n```", "ECON")) == 2)
    check('LLM: {"cards": [...]} wrapper parsed', len(parse_llm_cards('{"cards": ' + good + "}", "ECON")) == 2)
    dupes = parse_llm_cards(
        '[{"term": "Supply", "simple": "a"}, {"term": "supply", "simple": "b"}, {"term": "", "simple": "c"}, 7]', "ECON")
    check("LLM: duplicates, blank terms, non-objects dropped", [c["term"] for c in dupes] == ["Supply"])
    same_slug = parse_llm_cards('[{"term": "Price-floor", "simple": "a"}, {"term": "Price floor", "simple": "b"}]', "ECON")
    check("LLM: slug collisions get unique ids", len({c["id"] for c in same_slug}) == 2)
    for label, bad in (("garbage", "not json at all"), ("empty list", "[]"), ("no valid cards", '[{"x": 1}]')):
        try:
            parse_llm_cards(bad, "ECON")
            check(f"LLM: {label} raises ExtractionError", False)
        except ExtractionError:
            check(f"LLM: {label} raises ExtractionError", True)

    saved = {k: os.environ.get(k) for k in ("LLM_API_KEY", "LLM_BASE_URL")}
    os.environ["LLM_API_KEY"], os.environ["LLM_BASE_URL"] = "test-key", "http://127.0.0.1:9/v1"
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            fb_cards, fb_path = extract_cards("Supply is what sellers offer.", "ECON")
        check("LLM failure falls back to offline and says so",
              fb_path.startswith("offline (llm failed") and len(fb_cards) == 1, fb_path)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def quiz_checks(fixture_cards: list[dict]) -> None:
    quiz = build_quiz(fixture_cards)
    by_card = {c["id"]: c for c in fixture_cards}
    leaks = [q for q in quiz if q["level"] in (2, 3)
             and by_card[q["card_id"]]["term"].lower() in q["prompt"].lower()]
    check("quiz L2/L3 prompts never contain their own answer", not leaks, str(leaks[:1]))
    l1_leaks = [q for q in quiz if q["level"] == 1
                and by_card[q["card_id"]]["term"].lower() in q["choices"][q["answer_index"]].lower()]
    check("quiz L1 correct choice does not repeat the term", not l1_leaks, str(l1_leaks[:1]))
    check("one-card quiz emits no single-option questions",
          all(len(q["choices"]) >= 2 for q in build_quiz(fixture_cards[:1])))
    check("empty card list -> empty quiz", build_quiz([]) == [])


def adapter_checks() -> None:
    item = {"title": "First Exam", "date": "2026-10-29", "kind": "exam", "quote": "Your first exam is October 29."}
    cdt = timezone(timedelta(hours=-5))
    bee_payload = BeeTodoAdapter(tz=cdt).payload(item)
    check("Bee todo uses documented 'text' + 'alarm_at' fields", set(bee_payload) == {"text", "alarm_at"}, str(bee_payload))
    check("Bee todo alarm is 08:00 lecture-local, sent as UTC", bee_payload["alarm_at"] == "2026-10-29T13:00:00Z")

    graph = TruCalenZerOutlookAdapter(tz=cdt, conversation_id="c1").payload(item)
    check("TruCalenZer Outlook event carries the 'Torgy' category", graph["categories"] == ["Torgy"])
    check("TruCalenZer Outlook event has subject + UTC start/end",
          graph["subject"] == "First Exam"
          and graph["start"] == {"dateTime": "2026-10-29T14:00:00", "timeZone": "UTC"}
          and graph["end"] == {"dateTime": "2026-10-29T14:30:00", "timeZone": "UTC"}, str(graph))
    check("TruCalenZer Outlook event never forges Torgy-Task-ID markers", "Torgy-Task-ID" not in graph["body"]["content"])
    check("TruCalenZer Outlook transactionId stable across runs",
          graph["transactionId"] == TruCalenZerOutlookAdapter(tz=cdt, conversation_id="c1").payload(item)["transactionId"])

    rec = TruCalenZerImportFile("x.json", course="ECON 101", conversation_id="c1").record(item)
    check("TruCalenZer import record uses 'possible date' only",
          rec["possible date"] == "2026-10-29" and not {"official due date", "due date", "date", "due at"} & set(rec))
    check("TruCalenZer import record has title, course, stable source id",
          rec["title"] == "First Exam" and rec["course"] == "ECON 101" and rec["source id"].startswith("bee-stinger-"))
    try:
        TruCalenZerImportFile("x.txt")
        check("TruCalenZer import file must be *.json", False)
    except ValueError:
        check("TruCalenZer import file must be *.json", True)

    ics = IcsAdapter("unused").render([
        {"title": "Quiz; part 1, A\\B", "date": "2026-10-29", "kind": "exam", "quote": "x " * 80},
        {"title": "Quiz 2", "date": "2026-10-29", "kind": "exam", "quote": "q"},
    ])
    check("ics escapes ; , and backslash", "SUMMARY:Quiz\\; part 1\\, A\\\\B" in ics, ics[:300])
    check("ics lines folded to <= 75 octets", all(len(ln.encode()) <= 75 for ln in ics.split("\r\n")))
    uids = [ln for ln in ics.split("\r\n") if ln.startswith("UID:")]
    check("ics UIDs unique for same-date items", len(set(uids)) == 2)

    # Dry-run must send nothing anywhere: any urlopen call is recorded and fails.
    calls = []

    def _no_network(*args, **kwargs):
        calls.append(args)
        raise AssertionError("network call attempted")

    real_urlopen = urllib.request.urlopen
    urllib.request.urlopen = _no_network
    try:
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                summary = cli.run_pipeline(FixtureClient(FIXTURE).conversation(), tmp, live=False)
            produced = sorted(os.listdir(tmp))
        check("pipeline without --live makes zero network calls", calls == [], str(calls))
        check("every delivery reported as dry-run", all(d["dry_run"] for d in summary["deliveries"]))
        check("pipeline writes the TruCalenZer import file + ics",
              "trucalenzer-import.json" in produced and "commitments.ics" in produced, str(produced))
        no_token = TruCalenZerOutlookAdapter(dry_run=False)
        no_token.token = None
        check("--live without TRUCALENZER_GRAPH_TOKEN skips, sends nothing",
              "skipped" in no_token.deliver(item) and calls == [])
        check("--live Bee todo without BEE_TOKEN skips, sends nothing",
              "skipped" in BeeTodoAdapter(client=None, dry_run=False).deliver(item) and calls == [])
    finally:
        urllib.request.urlopen = real_urlopen


class _FakeBee(BeeClient):
    def __init__(self, response):
        self.token, self.base_url, self.response, self.calls = "t", "http://x", response, []

    def _request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        return self.response


def bee_client_checks() -> None:
    stream = [
        b": ping\r\n", b"\r\n",
        b"event: new-utterance\r\n",
        b'data: {"utterance": {"text": "hi", "speaker": "s1"}, "conversation_uuid": "u"}\r\n', b"\r\n",
        b'data: {"todo": {"id": 10, "text": "Call", "completed": false}}\n', b"\n",
        b"event: connected\n", b"data: ok\n", b"\n",
        b"data: line1\n", b"data: line2\n", b"\n",
    ]
    events = list(parse_sse(stream))
    check("SSE: CRLF frames, comments skipped, event names kept",
          [e["event"] for e in events] == ["new-utterance", "todo", "connected", "message"], str(events))
    check("SSE: JSON data parsed", events[0]["data"]["utterance"]["text"] == "hi")
    check("SSE: multi-line data joined", events[3]["data"] == "line1\nline2")
    check("SSE: event inference by payload keys",
          infer_event_type({"conversation_id": 1, "short_summary": "s"}) == "update-conversation-summary"
          and infer_event_type({"journalId": 5, "text": "t"}) == "journal-text")

    live_shape = {
        "id": 123, "start_time": 1792335720000, "timezone": "America/Chicago",
        "short_summary": "ECON 101 lecture",
        "transcriptions": [{"id": 1, "utterances": [
            {"id": 2, "spoken_at": 20, "speaker": "Prof", "text": "Second."},
            {"id": 1, "spoken_at": 10, "speaker": "Prof", "text": "First."},
        ]}],
    }
    check("live conversation shape: transcriptions sorted by spoken_at",
          spoken_text(live_shape) == "First. Second." and transcript_lines(live_shape)[0] == "[Prof] First.")
    check("live conversation shape: title falls back to short_summary", title_of(live_shape) == "ECON 101 lecture")
    check("epoch-ms start_time gives a reference date", cli._reference_date(live_shape).year == 2026)
    fixture = FixtureClient(FIXTURE)
    check("FixtureClient matches an id passed as a string",
          fixture.conversation(str(fixture.conversation()["id"]))["id"] == fixture.conversation()["id"])

    check('BeeClient unwraps {"conversation": {...}}', _FakeBee({"conversation": live_shape}).conversation(123)["id"] == 123)
    try:
        _FakeBee({"error": "nope"}).conversation(1)
        check("BeeClient rejects an unexpected conversation payload", False)
    except BeeError:
        check("BeeClient rejects an unexpected conversation payload", True)
    check("BeeClient.conversations unwraps the list",
          _FakeBee({"conversations": [{"id": 1}]}).conversations() == [{"id": 1}])
    fake = _FakeBee({})
    fake.changes("v1-17707 59786297")
    fake.create_todo("Read ch 4", "2026-10-26T13:00:00Z")
    check("changes cursor is URL-encoded as ?cursor=", fake.calls[0][1] == "/changes?cursor=v1-17707+59786297")
    check("create_todo posts {text, alarm_at}",
          fake.calls[1] == ("POST", "/todos", {"text": "Read ch 4", "alarm_at": "2026-10-26T13:00:00Z"}))


def main() -> int:
    cards = fixture_checks()
    commitment_checks()
    extractor_checks(cards)
    quiz_checks(cards)
    adapter_checks()
    bee_client_checks()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
