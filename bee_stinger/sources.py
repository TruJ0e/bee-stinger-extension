"""Input sources: where a conversation comes from.

1. **Bee** (`bee_client.py`) — the real source: captures from a Bee device
   or the Apple Watch app, via the Bee developer API.
2. **GPT stand-in** (this module) — INTERIM. Generates a realistic lecture
   transcript on a topic through the same OpenAI-compatible endpoint the
   extractor uses. It exists so the whole flow can be exercised before a
   Bee developer token is available, and as a demo aid. It is *not* Bee
   data: the conversation is labelled `source: "gpt-stand-in"` with an id
   prefixed `gpt-sim-`, and the CLI says so when it runs.
3. **Plain text** (this module) — a transcript from anywhere (pasted,
   exported, dictated) wrapped into the conversation shape.

All three produce the same conversation dict, so the pipeline downstream
(assemble -> extract -> quiz -> render -> commitments) never cares which
source fed it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from datetime import datetime

from .bee_client import BeeError

_SPEAKER_RE = re.compile(r"^([A-Z][A-Za-z .'-]{1,40}):\s+(.*)$")


class SourceError(BeeError):
    """Raised when an input source cannot produce a conversation."""


def conversation_from_text(
    text: str,
    title: str | None = None,
    speaker: str = "Lecturer",
    when: datetime | None = None,
    source: str = "text",
) -> dict:
    """Wrap raw transcript text into a Bee-Stinger conversation dict.

    Utterances are split on lines/paragraphs. A line starting with
    ``Name:`` sets that line's speaker; other lines use the default.
    """
    utterances: list[dict] = []
    for chunk in re.split(r"\n\s*\n|\n", text):
        line = chunk.strip()
        if not line:
            continue
        m = _SPEAKER_RE.match(line)
        if m:
            utterances.append({"speaker": m.group(1).strip(), "text": m.group(2).strip()})
        else:
            utterances.append({"speaker": speaker, "text": line})
    if not utterances:
        raise SourceError("No transcript text found in the input.")
    stamp = (when or datetime.now().astimezone()).isoformat(timespec="seconds")
    digest = hashlib.sha1(text.encode()).hexdigest()[:10]
    return {
        "id": f"{source}-{digest}",
        "title": title or "Untitled lecture",
        "created_at": stamp,
        "source": source,
        "utterances": utterances,
    }


_PROMPT = """Write a realistic transcript of a university lecture on: {topic}

Today's date is {today}. Requirements:
- One professor speaking, plain paragraphs, no stage directions, no markdown.
- About 500-700 words, at a real lecture's pace.
- Define each key concept in a full sentence of the form "X is ..." and
  give two or three concrete examples introduced with "For example".
- End by announcing, in the professor's voice, three commitments:
  an exam on a named weekday with its explicit calendar date about two
  weeks from today, an assignment due this coming Friday, and a reading
  to finish before Monday's class.
"""


def generate_lecture_conversation(topic: str, when: datetime | None = None) -> dict:
    """Generate a lecture transcript on `topic` via the configured LLM.

    Uses the same environment configuration as the extractor
    (LLM_API_KEY / LLM_BASE_URL / LLM_MODEL). The result is a SIMULATED
    capture for development and demo use — never a substitute for a real
    Bee recording in a submission or evaluation.
    """
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        raise SourceError(
            "GPT input needs LLM_API_KEY in the environment (any OpenAI-compatible "
            "endpoint; see .env.example). Without it, use the fixture demo, a Bee "
            "capture, or a plain-text transcript instead."
        )
    base_url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    now = when or datetime.now().astimezone()
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You write realistic lecture transcripts."},
            {"role": "user", "content": _PROMPT.format(topic=topic, today=now.strftime("%A, %B %d, %Y"))},
        ],
        "temperature": 0.7,
    }
    req = urllib.request.Request(
        base_url + "/chat/completions", data=json.dumps(body).encode(), method="POST"
    )
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode())
        content = payload["choices"][0]["message"]["content"].strip()
    except Exception as e:
        raise SourceError(f"GPT input failed: {e}") from e
    if not content:
        raise SourceError("GPT input returned an empty transcript.")
    conv = conversation_from_text(content, title=topic, speaker="Professor", when=now, source="gpt-stand-in")
    conv["id"] = "gpt-sim-" + conv["id"].split("-", 1)[1]
    return conv
