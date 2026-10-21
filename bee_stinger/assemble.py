"""Assemble a clean lecture transcript from a Bee conversation object.

Handles the shapes this project actually meets:
- utterances: [{"speaker": ..., "text": ...}, ...] (fixture / segmented capture)
- transcriptions: [{"id": ..., "utterances": [{"text", "speaker",
  "spoken_at", "start", "id"}, ...]}, ...] — the live Bee shape of
  GET /v1/conversations/:id. Not in the published docs; taken from the
  official Bee CLI's ConversationDetail type (bee-cli 84a6e8f), which also
  orders utterances by spoken_at, then start, then id. Unverified against a
  live account until a BEE_TOKEN is available.
- a single "transcript" string (fallback)
"""

from __future__ import annotations


def _utterances(conversation: dict) -> list[dict]:
    if not isinstance(conversation, dict):
        return []
    direct = conversation.get("utterances")
    if isinstance(direct, list) and direct:
        return [u for u in direct if isinstance(u, dict)]
    out: list[dict] = []
    for t in conversation.get("transcriptions") or []:
        if isinstance(t, dict):
            group = [u for u in (t.get("utterances") or []) if isinstance(u, dict)]
            group.sort(key=lambda u: (_num(u.get("spoken_at")) or _num(u.get("start")) or 0, _num(u.get("id")) or 0))
            out.extend(group)
    return out


def _num(value) -> float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _text(u: dict) -> str:
    value = u.get("text")
    return value.strip() if isinstance(value, str) else ""


def _fallback_transcript(conversation: dict) -> str:
    value = conversation.get("transcript") if isinstance(conversation, dict) else None
    return value.strip() if isinstance(value, str) else ""


def transcript_lines(conversation: dict) -> list[str]:
    """One display line per utterance: '[Speaker] text'."""
    lines: list[str] = []
    for u in _utterances(conversation):
        text = _text(u)
        if not text:
            continue
        speaker = str(u.get("speaker") or "").strip()
        lines.append(f"[{speaker}] {text}" if speaker else text)
    if not lines:
        lines = [ln.strip() for ln in _fallback_transcript(conversation).splitlines() if ln.strip()]
    return lines


def spoken_text(conversation: dict) -> str:
    """Just the words, speaker labels removed — the extractor's input."""
    parts = [t for t in (_text(u) for u in _utterances(conversation)) if t]
    if not parts:
        return _fallback_transcript(conversation)
    return " ".join(parts)


def title_of(conversation: dict) -> str:
    if not isinstance(conversation, dict):
        return "Untitled capture"
    for key in ("title", "short_summary"):
        value = conversation.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Untitled capture"
