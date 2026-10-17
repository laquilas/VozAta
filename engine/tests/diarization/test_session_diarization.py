from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fakes import FakeDiarizer
from vozata.diarization.session_diarization import diarize_session
from vozata.domain import Channel, SpeakerTurn, TranscriptSegment, Word
from vozata.ports import DiarizationError
from vozata.storage.session_store import SessionStore


def _segment(segment_id: str, channel: Channel, start: float, text: str) -> TranscriptSegment:
    word = Word(text, start, start + 0.5, 0.9)
    return TranscriptSegment(segment_id, channel, channel.value, start, start + 0.5, text, (word,))


def _session(tmp_path: Path, *segments: TranscriptSegment) -> tuple[SessionStore, str]:
    store = SessionStore(tmp_path)
    paths = store.create()
    lines = "".join(json.dumps(segment.to_dict()) + "\n" for segment in segments)
    paths.transcript_jsonl.write_text(lines, encoding="utf-8")
    return store, paths.id


class _ClosingFailsDiarizer(FakeDiarizer):
    def close(self) -> None:
        super().close()
        raise RuntimeError("driver")


def test_writes_the_diarized_transcript_and_the_speakers(tmp_path: Path) -> None:
    store, session_id = _session(
        tmp_path,
        _segment("mic-000001", Channel.MIC, 0.0, "Hi"),
        _segment("system-000001", Channel.SYSTEM, 1.0, "Hello"),
        _segment("system-000002", Channel.SYSTEM, 3.0, "Hey"),
    )
    diarizer = FakeDiarizer([SpeakerTurn(0.5, 2.0, 5), SpeakerTurn(2.5, 4.0, 2)])

    found = diarize_session(store, session_id, lambda: diarizer, 2, 4)

    paths = store.paths(session_id)
    assert found == 2
    assert diarizer.calls == [(paths.wav(Channel.SYSTEM), 2, 4)]
    assert diarizer.closed
    source, segments = store.load_transcript_with_source(session_id)
    assert source == "diarized"
    assert [segment.speaker_id for segment in segments] == ["mic", "system:1", "system:2"]
    assert json.loads(paths.speakers_json.read_text(encoding="utf-8")) == {
        "system:1": {"name": None},
        "system:2": {"name": None},
    }


def test_without_system_speech_the_diarizer_is_never_built(tmp_path: Path) -> None:
    store, session_id = _session(tmp_path, _segment("mic-000001", Channel.MIC, 0.0, "Hi"))

    def build() -> FakeDiarizer:
        raise AssertionError("built")

    assert diarize_session(store, session_id, build, None, None) is None
    assert not store.paths(session_id).diarized_jsonl.exists()


def test_a_failure_closes_the_diarizer_writes_nothing_and_propagates(tmp_path: Path) -> None:
    store, session_id = _session(tmp_path, _segment("system-000001", Channel.SYSTEM, 1.0, "Hi"))
    diarizer = FakeDiarizer(error=DiarizationError("no token"))

    with pytest.raises(DiarizationError):
        diarize_session(store, session_id, lambda: diarizer, None, None)

    assert diarizer.closed
    paths = store.paths(session_id)
    assert not paths.diarized_jsonl.exists()
    assert not paths.speakers_json.exists()


def test_a_failing_close_is_logged_and_the_result_kept(tmp_path: Path) -> None:
    store, session_id = _session(tmp_path, _segment("system-000001", Channel.SYSTEM, 1.0, "Hi"))
    diarizer = _ClosingFailsDiarizer([SpeakerTurn(0.0, 5.0, 0)])

    assert diarize_session(store, session_id, lambda: diarizer, None, None) == 1
    assert store.load_transcript(session_id)[0].speaker_id == "system:1"


def test_no_overlapping_turn_keeps_system_and_lists_no_speaker(tmp_path: Path) -> None:
    store, session_id = _session(tmp_path, _segment("system-000001", Channel.SYSTEM, 9.0, "Hi"))

    found = diarize_session(store, session_id, lambda: FakeDiarizer([]), None, None)

    assert found == 0
    assert store.load_transcript(session_id)[0].speaker_id == "system"
    assert store.speaker_names(session_id) == {}
