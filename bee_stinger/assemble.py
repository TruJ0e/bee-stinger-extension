"""Assemble a clean lecture transcript from a Bee conversation object.

Handles the shapes this project actually meets:
- utterances: [{"speaker": ..., "text": ...}, ...] (segmented capture)
- a single "transcript" string (fallback)
"""

from __future__ import annotations


def transcript_lines(conversation: dict) -> list[str]:
    """One display line per utterance: '[Speaker] text'."""
    lines: list[str] = []
    utterances = conversation.get("utterances") or []
    for u in utterances:
        text = (u.get("text") or "").strip()
        if not text:
            continue
        speaker = (u.get("speaker") or "").strip()
        lines.append(f"[{speaker}] {text}" if speaker else text)
    if not lines and conversation.get("transcript"):
        lines = [ln.strip() for ln in conversation["transcript"].splitlines() if ln.strip()]
    return lines


def spoken_text(conversation: dict) -> str:
    """Just the words, speaker labels removed — the extractor's input."""
    parts: list[str] = []
    utterances = conversation.get("utterances") or []
    for u in utterances:
        text = (u.get("text") or "").strip()
        if text:
            parts.append(text)
    if not parts and conversation.get("transcript"):
        return conversation["transcript"].strip()
    return " ".join(parts)


def title_of(conversation: dict) -> str:
    return (conversation.get("title") or "Untitled capture").strip()
