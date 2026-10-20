"""Session folders as a crash or a stopped meeting leaves them, shared by the recovery and
processing tests (phases 17 and 40)."""

from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Any

import numpy as np

from tests.test_session import RATE, STARTED
from vozata.domain import Channel, Word
from vozata.domain import TranscriptSegment as Segment
from vozata.storage.files.repository import FileSessionRepository


def segment(segment_id: str, channel: Channel, start: float, text: str) -> Segment:
    words = (Word(text, start, start + 0.5, 0.9),)
    return Segment(segment_id, channel, channel.value, start, start + 0.5, text, words)


SEGMENTS = [
    segment("mic-000001", Channel.MIC, 0.1, "Hello."),
    segment("system-000002", Channel.SYSTEM, 0.6, "Hi there."),
]


def write_wav(path: Path, seconds: float, level: int = 1000) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(np.full(round(seconds * RATE), level, dtype=np.int16).tobytes())


def interrupted_meta(session_id: str, status: str = "interrupted", **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "id": session_id,
        "status": status,
        "started_at": STARTED.isoformat(timespec="seconds"),
        "ended_at": None,
        "language": "pt",
        "language_source": "selected",
        "app_language": "en",
        "template": "general",
        "vocabulary": ["Avalonia"],
        "devices": {"mic": "Headset Mic", "system": "Speakers [Loopback]"},
        "pauses": [],
        "settings": {"CHUNK_MODE": "vad", "CHUNK_SECONDS": 5, "WHISPER_MODEL": "tiny"},
        **extra,
    }


def make_session_folder(
    store: FileSessionRepository,
    *,
    status: str = "interrupted",
    mic_seconds: float = 1.0,
    system_seconds: float = 1.0,
    segments: list[Segment] = SEGMENTS,
    **meta: Any,
) -> str:
    """A session folder as a crash leaves it (WAVs here are already valid)."""
    paths = store.paths(store.create(STARTED))
    store.write_meta(paths.id, interrupted_meta(paths.id, status, **meta))
    write_wav(paths.wav(Channel.MIC), mic_seconds)
    write_wav(paths.wav(Channel.SYSTEM), system_seconds)
    lines = "".join(json.dumps(s.to_dict()) + "\n" for s in segments)
    paths.transcript_jsonl.write_text(lines, encoding="utf-8", newline="\n")
    return paths.id
