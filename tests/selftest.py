"""Self-tests for the Bee Stinger pipeline. Stdlib only.

Run:  python3 tests/selftest.py
Exercises the offline path end to end against the bundled fixture and
asserts the concrete outputs the demo depends on, then covers edge cases:
date resolution, extractor guards, LLM-output parsing, quiz answer
leakage, adapter payload contracts, the no-network guarantee of dry-run,
SSE parsing, Bee conversation shapes, subject naming, study blocks, Bee
to-do staging (TruCalenZer fed from the staged list), and the TRSS
subject bundle. No network, no keys: every LLM/API path runs against a
stubbed transport.
"""

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bee_stinger import cli  # noqa: E402
from bee_stinger.adapters import (  # noqa: E402
    GRAPH_EVENTS_URL, BeeTodoAdapter, IcsAdapter, TruCalenZerImportFile, TruCalenZerOutlookAdapter,
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
from bee_stinger.bundle import read_js_array, trss_card  # noqa: E402
from bee_stinger.render import render_guide  # noqa: E402
from bee_stinger.sources import SourceError, conversation_from_text, generate_lecture_conversation  # noqa: E402
from bee_stinger.study import parse_hhmm, plan_study_blocks  # noqa: E402
from bee_stinger.subject import PLACEHOLDER_SUBJECT, derive_subject  # noqa: E402

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
    content = graph["body"]["content"]
    marker = re.search(r"(?:^|\n)Torgy-Task-ID: ([0-9a-f-]{36})\nTorgy-Task-Version: 1$", content)
    check("TruCalenZer Outlook body carries B1 markers on their own lines",
          marker is not None and uuid.UUID(marker.group(1)).version in (1, 2, 3, 4, 5), content)
    check("TruCalenZer Outlook Torgy-Task-ID stable across runs",
          marker is not None
          and marker.group(1) in TruCalenZerOutlookAdapter(tz=cdt, conversation_id="c1").payload(item)["body"]["content"])
    check("TruCalenZer Outlook transactionId stable across runs",
          graph["transactionId"] == TruCalenZerOutlookAdapter(tz=cdt, conversation_id="c1").payload(item)["transactionId"])
    sliver = TruCalenZerOutlookAdapter(tz=cdt, conversation_id="c1", minutes=2).payload(item)
    check("TruCalenZer Outlook block under 5 min falls back to 30 (B1)",
          sliver["end"] == {"dateTime": "2026-10-29T14:30:00", "timeZone": "UTC"}, str(sliver))
    long_block = TruCalenZerOutlookAdapter(tz=cdt, conversation_id="c1", minutes=45).payload(item)
    check("TruCalenZer Outlook block honors durations >= 5 min",
          long_block["end"] == {"dateTime": "2026-10-29T14:45:00", "timeZone": "UTC"}, str(long_block))

    # Live send, captured: the request must hit /me/events carrying the full
    # B1 Prefer header and the adapter's own Bearer token.
    sent = {}

    class _FakeGraphResp:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"id": "evt-1"}'

    def _capture(req, timeout=None):
        sent["req"] = req
        return _FakeGraphResp()

    real_urlopen = urllib.request.urlopen
    urllib.request.urlopen = _capture
    try:
        outcome = TruCalenZerOutlookAdapter(
            token="test-token", dry_run=False, tz=cdt, conversation_id="c1").deliver(item)
    finally:
        urllib.request.urlopen = real_urlopen
    req = sent.get("req")
    check("TruCalenZer live send: /me/events + full B1 Prefer header + own Bearer token",
          req is not None and req.full_url == GRAPH_EVENTS_URL
          and req.get_header("Prefer") == 'outlook.timezone="UTC", IdType="ImmutableId"'
          and req.get_header("Authorization") == "Bearer test-token"
          and outcome.get("status") == 201 and outcome.get("event_id") == "evt-1", str(outcome))

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
    check("SSE: unterminated frame at disconnect is not emitted",
          list(parse_sse(["event: new-utterance\n", 'data: {"utterance":'])) == [])
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


def source_checks():
    import json as _json
    from datetime import datetime as _dt

    text = (
        "Dr. Lee: Photosynthesis is the process by which plants convert sunlight into chemical energy.\n"
        "For example, a sunflower turns toward the light to capture more energy.\n\n"
        "Homework 2 is due Friday at the start of class."
    )
    conv = conversation_from_text(text, title="BIO 101", when=_dt(2026, 10, 21, 9, 0, tzinfo=timezone.utc))
    check("text source keeps an explicit speaker", conv["utterances"][0]["speaker"] == "Dr. Lee")
    check("text source defaults the speaker", conv["utterances"][1]["speaker"] == "Lecturer")
    check("text source marks provenance", conv["source"] == "text" and conv["id"].startswith("text-"))
    spoken = spoken_text(conv)
    cards = extract_cards_offline(spoken, conv["title"])
    check("text source feeds extraction", any(c["term"] == "Photosynthesis" for c in cards))
    items = extract_commitments(spoken, date(2026, 10, 21))
    check("text source feeds commitments", any(i["date"] == "2026-10-23" for i in items), f"got {items}")

    # GPT source without a key: clean, explicit failure, no silent fallback.
    saved = os.environ.pop("LLM_API_KEY", None)
    try:
        generate_lecture_conversation("Photosynthesis")
        check("gpt source without a key fails cleanly", False)
    except SourceError:
        check("gpt source without a key fails cleanly", True)

    # GPT source with a stubbed transport: shape + labelling, no network.
    lecture = (
        "Supply is the quantity of a good producers will sell at a given price.\n\n"
        "Your exam is on Thursday, November 5."
    )

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return _json.dumps({"choices": [{"message": {"content": lecture}}]}).encode()

    real_urlopen = urllib.request.urlopen
    os.environ["LLM_API_KEY"] = "test-key"
    urllib.request.urlopen = lambda *a, **k: _Resp()
    try:
        conv2 = generate_lecture_conversation("Supply", when=_dt(2026, 10, 21, tzinfo=timezone.utc))
    finally:
        urllib.request.urlopen = real_urlopen
        if saved is not None:
            os.environ["LLM_API_KEY"] = saved
        else:
            os.environ.pop("LLM_API_KEY", None)
    check("gpt source labels itself a stand-in",
          conv2["source"] == "gpt-stand-in" and conv2["id"].startswith("gpt-sim-"))
    check("gpt source yields utterances", len(conv2["utterances"]) >= 2)


# --------------------------------------------------------------------------
# Subject naming, study blocks, to-do staging, TRSS bundle
# --------------------------------------------------------------------------

_NO_EXAM_LECTURE = (
    "Photosynthesis is the process by which plants turn light into chemical energy. "
    "For example, a sunflower turns toward the sun. "
    "Chlorophyll is the green pigment that absorbs light. "
    "Problem set 1 is due Friday."
)


def _no_network_run(fn):
    """Run fn() with urlopen replaced by a recorder that fails, output
    silenced. Returns (result, calls)."""
    calls = []

    def _no_network(*args, **kwargs):
        calls.append(args)
        raise AssertionError("network call attempted")

    real_urlopen = urllib.request.urlopen
    urllib.request.urlopen = _no_network
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = fn()
    finally:
        urllib.request.urlopen = real_urlopen
    return result, calls


def subject_checks(fixture_cards: list[dict]) -> None:
    s = derive_subject("ECON 101 — Supply and Demand", fixture_cards)
    check("subject: course code + topic from the title",
          s["name"] == "ECON 101: Supply and Demand" and s["course"] == "ECON 101"
          and s["topic"] == "Supply and Demand" and s["source"] == "title", str(s))
    check("subject: slug is clean", s["slug"] == "econ-101-supply-and-demand", s["slug"])
    check("subject: filler words dropped", derive_subject("Lecture on Photosynthesis", [])["name"] == "Photosynthesis")
    check("subject: trailing 'lecture' dropped", derive_subject("Photosynthesis lecture", [])["name"] == "Photosynthesis")
    unnamed = derive_subject("Untitled lecture", fixture_cards)
    expected = ", ".join(c["term"] for c in fixture_cards[:2]) + " & " + fixture_cards[2]["term"]
    check("subject: unnamed capture is named from the first concepts",
          unnamed["source"] == "concepts" and unnamed["name"] == expected, str(unnamed))
    summary_title = "The professor walked through how markets set prices and why shortages happen"
    check("subject: a Bee summary sentence is not used as a name",
          derive_subject(summary_title, fixture_cards[:1])["name"] == fixture_cards[0]["term"])
    check("subject: nothing to go on -> stable placeholder",
          derive_subject("", [])["name"] == PLACEHOLDER_SUBJECT
          and derive_subject("", [])["source"] == "placeholder")
    check("subject: deterministic", derive_subject("Untitled lecture", fixture_cards) == unnamed)


def study_checks() -> None:
    wed = date(2026, 10, 21)
    exam = {"title": "First Exam", "date": "2026-10-29", "kind": "exam", "quote": "q."}
    blocks = plan_study_blocks("ECON", [exam], wed)
    weekly = [b for b in blocks if b.get("recurrence")]
    reviews = [b for b in blocks if not b.get("recurrence")]
    check("study: every block is kind 'study' with start + duration",
          all(b["kind"] == "study" and b["start"] == "17:00" and b["duration_minutes"] == 60 for b in blocks),
          str(blocks))
    check("study: weekly series starts the day after the capture",
          len(weekly) == 1 and weekly[0]["date"] == "2026-10-22" and weekly[0]["title"] == "Study: ECON",
          str(weekly))
    check("study: final review the day before the exam",
          [(r["date"], r["title"]) for r in reviews] == [("2026-10-28", "Final review: ECON (First Exam)")],
          str(reviews))
    check("study: generated blocks carry no spoken quote", all(b["quote"] is None and b["notes"] for b in blocks))

    month = plan_study_blocks("BIO", [{**exam, "date": "2026-11-19"}], wed)
    rec = month[0]["recurrence"]
    check("study: weekly recurrence runs until the exam",
          rec["freq"] == "weekly" and rec["dates"] == ["2026-10-22", "2026-10-29", "2026-11-05", "2026-11-12"]
          and rec["count"] == 4 and rec["until"] == "2026-11-12", str(rec))
    check("study: review before a later exam", month[1]["date"] == "2026-11-18")

    two = plan_study_blocks("BIO", [exam, {**exam, "title": "Second Exam", "date": "2026-11-12"}], wed)
    rec2 = two[0]["recurrence"]
    check("study: a session on an exam day is skipped and listed as an exdate",
          rec2["dates"] == ["2026-10-22", "2026-11-05"] and rec2["exdates"] == ["2026-10-29"], str(rec2))
    check("study: one review per exam", [b["date"] for b in two[1:]] == ["2026-10-28", "2026-11-11"])

    late_due = plan_study_blocks(
        "BIO", [exam, {"title": "Paper due", "date": "2026-11-13", "kind": "due", "quote": "q."}], wed)
    check("study: a due date after the exam extends the weekly series",
          late_due[0]["recurrence"]["dates"] == ["2026-10-22", "2026-11-05", "2026-11-12"], str(late_due[0]))

    no_exam = plan_study_blocks(
        "BIO", [{"title": "Homework due", "date": "2026-10-23", "kind": "due", "quote": "q."}], wed)
    check("study: no exam -> simple weekly series for 4 weeks, no review",
          len(no_exam) == 1 and no_exam[0]["recurrence"]["dates"]
          == ["2026-10-22", "2026-10-29", "2026-11-05", "2026-11-12"], str(no_exam))
    check("study: weeks without exam is configurable",
          plan_study_blocks("BIO", [], wed, weeks_without_exam=2)[0]["recurrence"]["count"] == 2)
    custom = plan_study_blocks("BIO", [exam], wed, start=parse_hhmm("18:30"), minutes=45, review_minutes=90)
    check("study: start time and durations are configurable",
          custom[0]["start"] == "18:30" and custom[0]["duration_minutes"] == 45
          and custom[1]["duration_minutes"] == 90, str(custom))
    check("study: exam tomorrow -> no blocks squeezed in",
          plan_study_blocks("BIO", [{**exam, "date": "2026-10-22"}], wed) == [])
    check("study: past exams are ignored",
          plan_study_blocks("BIO", [{**exam, "date": "2026-10-01"}], wed)[0]["recurrence"]["count"] == 4)
    check("study: deterministic", plan_study_blocks("ECON", [exam], wed) == blocks)
    for label, call in (("bad HH:MM", lambda: parse_hhmm("5pm")),
                        ("block under 5 minutes", lambda: plan_study_blocks("X", [], wed, minutes=2)),
                        ("zero weeks", lambda: plan_study_blocks("X", [], wed, weeks_without_exam=0))):
        try:
            call()
            check(f"study: {label} rejected", False)
        except ValueError:
            check(f"study: {label} rejected", True)

    cdt = timezone(timedelta(hours=-5))
    payload = BeeTodoAdapter(tz=cdt).payload(blocks[0])
    check("study: Bee to-do alarms when the block starts (17:00 local as UTC)",
          payload == {"text": "Study: ECON — 2026-10-22 17:00–18:00", "alarm_at": "2026-10-22T22:00:00Z"},
          str(payload))


def staging_checks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        summary, calls = _no_network_run(lambda: cli.run_pipeline(FixtureClient(FIXTURE).conversation(), tmp))
        with open(os.path.join(tmp, "staged_todos.json"), encoding="utf-8") as f:
            staged_doc = json.load(f)
        with open(os.path.join(tmp, "trucalenzer-import.json"), encoding="utf-8") as f:
            records = json.load(f)["assignments"]
        with open(os.path.join(tmp, "commitments.json"), encoding="utf-8") as f:
            commitments = json.load(f)
        with open(os.path.join(tmp, "commitments.ics"), encoding="utf-8", newline="") as f:
            ics = f.read()
        with open(os.path.join(tmp, "guide.html"), encoding="utf-8") as f:
            guide = f.read()
    staged = summary["staged"]
    name = summary["subject"]["name"]
    check("pipeline: subject auto-named from the title", name == "ECON 101: Supply and Demand", name)
    check("pipeline: zero network calls with the new stages", calls == [], str(calls))

    spoken = extract_commitments(spoken_text(FixtureClient(FIXTURE).conversation()), date(2026, 10, 21))
    check("pipeline: spoken commitments unchanged and listed first", commitments[:len(spoken)] == spoken)
    study = commitments[len(spoken):]
    check("pipeline: study blocks in the commitments output",
          [b["date"] for b in study] == ["2026-10-22", "2026-10-28"]
          and all(b["kind"] == "study" and b["start"] and b["duration_minutes"] for b in study)
          and "recurrence" in study[0], str(study))

    first = staged[0]
    check("staging: 'guide ready' to-do staged first",
          first["kind"] == "guide-ready" and first["position"] == 1
          and first["bee_payload"] == {"text": f"Your study guide for {name} is ready"}, str(first))
    check("staging: the guide-ready to-do stays on Bee only", first["to_trucalenzer"] is False)
    check("staging: every commitment occurrence staged, in date order",
          [t["date"] for t in staged[1:]] == ["2026-10-22", "2026-10-23", "2026-10-26", "2026-10-28", "2026-10-29"],
          str([t["date"] for t in staged]))
    check("staging: every dated to-do has a Bee alarm", all("alarm_at" in t["bee_payload"] for t in staged[1:]))
    check("staging: staged_todos.json mirrors the staged list, marked dry-run",
          staged_doc["bee_delivery"] == "dry-run" and staged_doc["subject"]["name"] == name
          and [t["bee_payload"] for t in staged_doc["todos"]] == [t["bee_payload"] for t in staged])
    bee_sends = [d for d in summary["deliveries"] if d["adapter"] == "bee-todos"]
    check("staging: Bee receives exactly the staged list (dry-run)",
          [d["payload"] for d in bee_sends] == [t["bee_payload"] for t in staged]
          and all(d["dry_run"] for d in bee_sends))

    to_tcz = [t for t in staged if t["to_trucalenzer"]]
    check("TruCalenZer import is generated from the staged list",
          [(r["title"], r["possible date"]) for r in records] == [(t["title"], t["date"]) for t in to_tcz],
          str(records))
    check("TruCalenZer import keeps 'possible date' only, course from the subject",
          all(r["course"] == "ECON 101" and not {"official due date", "due date", "date"} & set(r) for r in records))
    check("TruCalenZer import source ids unique", len({r["source id"] for r in records}) == len(records))
    summaries = re.findall(r"^SUMMARY:(.*?)\r?$", ics, re.M)
    check("ics is generated from the staged list",
          [s.replace("\\,", ",").replace("\\;", ";") for s in summaries] == [t["title"] for t in to_tcz],
          str(summaries))
    check("ics study blocks are timed, local wall-clock, with a duration",
          "DTSTART:20261022T170000" in ics and "DTSTART:20261028T170000" in ics and "DURATION:PT60M" in ics)
    check("guide is headed by the subject and lists the study plan",
          f"<h1>{name}</h1>" in guide and "Study Plan" in guide and "Final review" in guide)

    # A capture with no exam date: 4 weekly sessions, staged one per week,
    # folded back into one recurring .ics event.
    conv = conversation_from_text(_NO_EXAM_LECTURE, when=datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc))
    with tempfile.TemporaryDirectory() as tmp:
        summary2, calls2 = _no_network_run(lambda: cli.run_pipeline(conv, tmp))
        with open(os.path.join(tmp, "trucalenzer-import.json"), encoding="utf-8") as f:
            records2 = json.load(f)["assignments"]
        with open(os.path.join(tmp, "commitments.ics"), encoding="utf-8", newline="") as f:
            ics2 = f.read()
    sessions = [t for t in summary2["staged"] if t.get("series_id")]
    check("unnamed capture: subject derived from the concepts",
          summary2["subject"]["source"] == "concepts"
          and summary2["subject"]["name"] == "Photosynthesis & Chlorophyll", str(summary2["subject"]))
    check("no exam: 4 weekly sessions staged, one to-do per week",
          [t["title"] for t in sessions]
          == [f"Study: Photosynthesis & Chlorophyll (week {n} of 4)" for n in range(1, 5)]
          and [t["date"] for t in sessions] == ["2026-10-22", "2026-10-29", "2026-11-05", "2026-11-12"],
          str([(t["title"], t["date"]) for t in sessions]))
    check("no exam: TruCalenZer gets one dated task per staged session",
          sum(1 for r in records2 if r["title"].startswith("Study:")) == 4 and calls2 == [])
    check("no exam: the weekly series is one recurring .ics event",
          ics2.count("RRULE:FREQ=WEEKLY;INTERVAL=1;UNTIL=20261112T170000") == 1
          and ics2.count("BEGIN:VEVENT") == 2, ics2)

    # CLI: summary lines, and bad options fail cleanly.
    with tempfile.TemporaryDirectory() as tmp:
        out = io.StringIO()
        real_urlopen = urllib.request.urlopen

        def _refuse(*args, **kwargs):
            raise AssertionError("network call attempted")

        urllib.request.urlopen = _refuse
        try:
            with contextlib.redirect_stdout(out):
                code = cli.main(["demo", "--out", tmp, "--study-time", "18:00"])
            with contextlib.redirect_stderr(io.StringIO()):
                bad = cli.main(["demo", "--out", tmp, "--study-time", "6pm"])
        finally:
            urllib.request.urlopen = real_urlopen
    text = out.getvalue()
    check("CLI prints subject, staged to-dos, TruCalenZer and bundle lines",
          code == 0 and "Subject:      ECON 101: Supply and Demand" in text
          and "Bee to-dos:   6 staged (dry-run)" in text
          and " 1. Your study guide for ECON 101: Supply and Demand is ready  [Bee only]" in text
          and "TruCalenZer:  5 items from the staged list" in text and "TRSS bundle:" in text, text[-1500:])
    check("CLI --study-time is honored", "2026-10-22 18:00–19:00" in text)
    check("CLI rejects a malformed --study-time", bad == 2)


# The identity regex TRSS's chapter-landing/audit-chapter.py applies.
_AUDIT_IDENTITY = re.compile(
    r"window\.TRSS_CHAPTER\s*=\s*\{\s*num:\s*(\d+),\s*title:\s*\"([^\"]*)\","
    r"\s*prefix:\s*\"([^\"]*)\",\s*course:\s*\"([^\"]*)\"\s*\}")


def _read_tree(root: str) -> dict:
    out = {}
    for d, _dirs, names in os.walk(root):
        for n in names:
            p = os.path.join(d, n)
            with open(p, "rb") as f:
                out[os.path.relpath(p, root)] = f.read()
    return out


def _js_payload(path: str):
    with open(path, encoding="utf-8") as f:
        m = re.search(r"window\.\w+\s*=\s*(\[.*\]|\{.*\});", f.read(), re.S)
    return json.loads(m.group(1)) if m else None


def bundle_checks() -> None:
    conv = FixtureClient(FIXTURE).conversation()
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        s1, calls = _no_network_run(lambda: cli.run_pipeline(conv, a))
        s2, _ = _no_network_run(lambda: cli.run_pipeline(conv, b))
        root = s1["bundle"]["path"]
        dr = os.path.join(root, "digital-reference")
        names = set(os.listdir(dr))
        lesson = read_js_array(os.path.join(dr, "lesson-cards.js"))
        core = read_js_array(os.path.join(dr, "core-cards.js"))
        extra = read_js_array(os.path.join(dr, "extra-cards.js"))
        targets = _js_payload(os.path.join(dr, "lesson-targets.js"))
        data = _js_payload(os.path.join(dr, "generated-study-data.js"))
        with open(os.path.join(dr, "index.html"), encoding="utf-8") as f:
            page = f.read()
        with open(os.path.join(dr, "quiz-wiring.json"), encoding="utf-8") as f:
            wiring = json.load(f)
        with open(os.path.join(root, "bundle-manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
        with open(os.path.join(root, "trss-session-policy.json"), encoding="utf-8") as f:
            policy = json.load(f)
        has_guide = os.path.exists(os.path.join(root, "guide.html"))
        same = _read_tree(root) == _read_tree(s2["bundle"]["path"])
        _no_network_run(lambda: cli.run_pipeline(conv, a, trss_unit=3))
        unit3 = os.path.isdir(os.path.join(a, "trss-subject", "econ-101-supply-and-demand-chapter-3"))
        _no_network_run(lambda: cli.run_pipeline(conv, a))
        rerun = sorted(os.listdir(os.path.join(a, "trss-subject")))

    n = s1["cards"]
    check("bundle: written into the output dir with no network",
          calls == [] and os.path.basename(root) == "econ-101-supply-and-demand-chapter-1", root)
    check("bundle: TRSS pack data files present",
          {"core-cards.js", "lesson-cards.js", "extra-cards.js", "lesson-targets.js",
           "generated-study-data.js", "index.html", "quiz-wiring.json"} <= names, str(names))
    check("bundle: guide + session policy + manifest included",
          has_guide and policy["quiz"]["questionsPerCard"] == 3 and manifest["bundle"] == os.path.basename(root))
    check("bundle: lecture concepts are lesson cards; core/extra present and empty",
          len(lesson) == n and core == [] and extra == [])
    check("bundle: card ids ch<n>-lesson-NNN, type matches the file",
          [c["id"] for c in lesson] == [f"ch1-lesson-{i:03d}" for i in range(1, n + 1)]
          and all(c["type"] == "lesson-concept" for c in lesson))
    check("bundle: full TRSS card schema, non-empty examples",
          all(all(c.get(f) for f in SCHEMA_FIELDS) and isinstance(c["examples"], list) and c["examples"]
              for c in lesson))
    check("bundle: apply is a string[] whose first prompt never names its answer",
          all(isinstance(c["apply"], list) and c["apply"] and c["term"].lower() not in c["apply"][0].lower()
              for c in lesson), str([c["apply"] for c in lesson][:2]))
    check("bundle: one learning target per concept (plus a connecting one)",
          isinstance(targets, list) and len(targets) == n + 1 and all(isinstance(t, str) for t in targets))
    check("bundle: study data counts derived from the cards",
          data["totalCards"] == n and data["totalQuestions"] == 3 * n
          and data["counts"] == {"book-term": 0, "lesson-concept": n, "research-skill": 0}
          and data["title"] == "ECON 101: Supply and Demand" and data["prefix"] == "CH1")
    m = _AUDIT_IDENTITY.search(page)
    check("bundle: TRSS_CHAPTER identity matches TRSS's audit regex",
          m is not None and m.groups() == ("1", "ECON 101: Supply and Demand", "CH1", "econ-101-supply-and-demand"),
          page[:400])
    scripts = re.findall(r'<script src="([^"]+)"', page)
    check("bundle: script order is core, lesson, extra, study.js",
          scripts == ["core-cards.js", "lesson-cards.js", "extra-cards.js", "study.js"], str(scripts))
    qs = wiring["questions"]
    by_id = {c["id"]: c for c in lesson}
    check("bundle: quiz wiring is 3 x cards, L3 -> L2 -> L1, answer = term",
          len(qs) == 3 * n and [q["level"] for q in qs] == [3] * n + [2] * n + [1] * n
          and all(q["answer"] == by_id[q["card_id"]]["term"] for q in qs))
    check("bundle: L3 prompt is apply[0], L2 uses examples[0]",
          all(q["prompt"] == by_id[q["card_id"]]["apply"][0] for q in qs if q["level"] == 3)
          and all(by_id[q["card_id"]]["examples"][0] in q["prompt"] for q in qs if q["level"] == 2))
    check("bundle: manifest names what TRSS supplies at install",
          {"study.js", "reference.css"} <= {k.split(" ")[0] for k in manifest["supplied_by_trss_at_install"]}
          and manifest["counts"]["questions"] == 3 * n)
    check("bundle: same capture -> byte-identical bundle", same)
    check("bundle: --trss-unit sets the unit number", unit3)
    check("bundle: re-run replaces only its own unit folder",
          rerun == ["econ-101-supply-and-demand-chapter-1", "econ-101-supply-and-demand-chapter-3"], str(rerun))

    offline_card = {"id": "x", "term": "Chlorophyll", "type": "concept", "category": "Biology", "cue": "?",
                    "simple": "Chlorophyll is the green pigment.", "examples": [],
                    "apply": "Explain how Chlorophyll would show up in a real situation, in your own words."}
    tc = trss_card(offline_card, 2, 7)
    check("bundle: empty examples get a masked stand-in, generic apply is replaced",
          tc["id"] == "ch2-lesson-007" and tc["examples"] and "chlorophyll" not in tc["examples"][0].lower()
          and "chlorophyll" not in tc["apply"][0].lower(), str(tc))


def llm_pipeline_checks() -> None:
    """The LLM extraction path, end to end through the new stages, against
    a stubbed transport: proves the wiring without a billable call."""
    cards_json = json.dumps([
        {"term": "Opportunity Cost", "simple": "The value of the next best alternative given up.",
         "examples": ["Studying instead of working a shift."],
         "apply": ["You skip a paid shift to study. Name the cost."]},
        {"term": "Scarcity", "simple": "Limited resources against unlimited wants.", "examples": ["One evening, two exams."]},
    ])
    seen = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": cards_json}}]}).encode()

    def _stub(req, timeout=None):
        seen.append(req.full_url)
        return _Resp()

    saved = {k: os.environ.get(k) for k in ("LLM_API_KEY", "LLM_BASE_URL")}
    os.environ["LLM_API_KEY"], os.environ["LLM_BASE_URL"] = "test-key", "http://stub.invalid/v1"
    real_urlopen = urllib.request.urlopen
    urllib.request.urlopen = _stub
    try:
        conv = conversation_from_text("Opportunity cost matters. The midterm is on November 4.",
                                      when=datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc))
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                summary = cli.run_pipeline(conv, tmp)
            lesson = read_js_array(os.path.join(summary["bundle"]["path"], "digital-reference", "lesson-cards.js"))
    finally:
        urllib.request.urlopen = real_urlopen
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    check("LLM path (stubbed): only the stub endpoint is called",
          summary["extraction_path"] == "llm" and seen == ["http://stub.invalid/v1/chat/completions"], str(seen))
    check("LLM path (stubbed): subject named from the LLM's concepts",
          summary["subject"]["name"] == "Opportunity Cost & Scarcity", str(summary["subject"]))
    check("LLM path (stubbed): bundle keeps the provider's apply prompt",
          lesson[0]["apply"] == ["You skip a paid shift to study. Name the cost."], str(lesson[0]["apply"]))
    check("LLM path (stubbed): weekly series + midterm review planned",
          [b["date"] for b in summary["study_blocks"]] == ["2026-10-22", "2026-11-03"], str(summary["study_blocks"]))


def main() -> int:
    cards = fixture_checks()
    commitment_checks()
    extractor_checks(cards)
    quiz_checks(cards)
    adapter_checks()
    bee_client_checks()
    source_checks()
    subject_checks(cards)
    study_checks()
    staging_checks()
    bundle_checks()
    llm_pipeline_checks()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
