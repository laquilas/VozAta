"""`RecordingSession.recover()` (phase 17): the stop steps from the mix onwards, on a folder."""

from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.fakes import FakeDiarizer
from tests.test_session import RATE, STARTED, _Rig
from vozata.domain import Channel, ConversationLanguage, SessionStatus, SpeakerTurn, Word
from vozata.domain import TranscriptSegment as Segment
from vozata.storage.search_index import SearchIndex
from vozata.storage.session_store import SessionStore


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
    store: SessionStore,
    *,
    status: str = "interrupted",
    mic_seconds: float = 1.0,
    system_seconds: float = 1.0,
    segments: list[Segment] = SEGMENTS,
    **meta: Any,
) -> str:
    """A session folder as a crash leaves it (WAVs here are already valid)."""
    paths = store.create(STARTED)
    store.write_meta(paths.id, interrupted_meta(paths.id, status, **meta))
    write_wav(paths.wav(Channel.MIC), mic_seconds)
    write_wav(paths.wav(Channel.SYSTEM), system_seconds)
    lines = "".join(json.dumps(s.to_dict()) + "\n" for s in segments)
    paths.transcript_jsonl.write_text(lines, encoding="utf-8", newline="\n")
    return paths.id


def _recover_rig(tmp_path: Path, **options: Any) -> tuple[_Rig, str]:
    rig = _Rig(tmp_path, **options)
    rig.store.now()  # the rig's first moment is the start; recovery only reads the end
    return rig, make_session_folder(rig.store)


def test_recover_runs_the_stop_steps_from_the_mix_and_ends_done(tmp_path: Path) -> None:
    rig, session_id = _recover_rig(tmp_path)

    rig.session.recover(session_id, 1.0)

    assert rig.log.entries == ["mix", "llm.generate"]  # no capture, no transcriber
    assert rig.session.status is SessionStatus.DONE
    assert rig.session.id == session_id
    assert rig.session.duration_seconds == 1.0
    assert rig.session.paths.minutes_md.read_text(encoding="utf-8") == "# Minutes\n"
    meta = rig.store.read_meta(session_id)
    assert (meta["status"], meta["ended_at"], meta["duration_seconds"]) == (
        "done",
        "2026-10-15T20:30:00-03:00",
        1.0,
    )
    assert meta["vocabulary"] == ["Avalonia"]  # the rest of session.json is kept
    assert rig.observer.of("status") == [
        (SessionStatus.FINALIZING, 1.0),
        (SessionStatus.DONE, 1.0),
    ]
    assert rig.observer.of("minutes_ready") == [(session_id,)]


def test_recover_writes_the_minutes_in_the_stored_language(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, session_id = _recover_rig(tmp_path)
    languages: list[ConversationLanguage] = []
    minutes = rig.session._c.minutes
    assert minutes is not None
    original = minutes.generate

    def spy(segments, labeler, language, vocabulary=()):  # type: ignore[no-untyped-def]
        languages.append(language)
        return original(segments, labeler, language, vocabulary)

    monkeypatch.setattr(minutes, "generate", spy)

    rig.session.recover(session_id, 1.0)

    assert languages == [ConversationLanguage.PT]


def test_recover_identifies_speakers_and_indexes_the_transcript(tmp_path: Path) -> None:
    diarizer = FakeDiarizer([SpeakerTurn(0.0, 9.0, 1)])
    index = SearchIndex(tmp_path / "index.db")
    rig, session_id = _recover_rig(tmp_path, diarizer_factory=lambda: diarizer, search_index=index)

    rig.session.recover(session_id, 1.0)

    assert diarizer.closed
    assert rig.store.load_transcript_with_source(session_id)[0] == "diarized"
    [hit] = index.search("there")
    assert (hit.session_id, hit.segment_id) == (session_id, "system-000002")


def test_recover_with_auto_language_never_locked_uses_auto(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    rig.store.now()
    paths = rig.store.create(STARTED)
    meta = interrupted_meta(paths.id)
    del meta["language"], meta["language_source"]
    rig.store.write_meta(paths.id, meta)
    write_wav(paths.wav(Channel.MIC), 0.5)
    write_wav(paths.wav(Channel.SYSTEM), 0.5)

    rig.session.recover(paths.id, 0.5)

    assert rig.session._lock.language is ConversationLanguage.AUTO
    assert rig.log.entries == ["mix"]  # no transcript: no minutes
    assert rig.store.read_meta(paths.id)["status"] == "done"


def test_recover_twice_or_after_start_raises(tmp_path: Path) -> None:
    rig, session_id = _recover_rig(tmp_path)
    rig.session.recover(session_id, 1.0)

    with pytest.raises(RuntimeError):
        rig.session.recover(session_id, 1.0)
    with pytest.raises(RuntimeError):
        rig.session.start()
