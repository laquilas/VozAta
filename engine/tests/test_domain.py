from __future__ import annotations

import dataclasses
import json

import numpy as np
import pytest

from vozata.domain import (
    AppLanguage,
    AudioChunk,
    Channel,
    ConversationLanguage,
    SessionStatus,
    SpeakerTurn,
    TranscriptionResult,
    TranscriptSegment,
    Word,
)


def _segment() -> TranscriptSegment:
    return TranscriptSegment(
        segment_id="mic-000042",
        channel=Channel.MIC,
        speaker_id="mic",
        start=83.12,
        end=87.9,
        text="We will ship the beta on Friday.",
        words=(Word(text="We", start=83.12, end=83.3, probability=0.98),),
    )


def test_enum_values_match_the_data_model() -> None:
    assert [c.value for c in Channel] == ["mic", "system"]
    assert [s.value for s in SessionStatus] == [
        "recording",
        "paused",
        "finalizing",
        "done",
        "interrupted",
    ]
    assert [a.value for a in AppLanguage] == ["en", "pt-BR", "es"]
    assert [c.value for c in ConversationLanguage] == ["en", "pt", "es", "auto"]


def test_segment_to_dict_matches_the_jsonl_schema() -> None:
    assert _segment().to_dict() == {
        "segment_id": "mic-000042",
        "channel": "mic",
        "speaker_id": "mic",
        "start": 83.12,
        "end": 87.9,
        "text": "We will ship the beta on Friday.",
        "words": [{"text": "We", "start": 83.12, "end": 83.3, "probability": 0.98}],
    }


def test_segment_survives_a_jsonl_round_trip() -> None:
    line = json.dumps(_segment().to_dict())

    assert TranscriptSegment.from_dict(json.loads(line)) == _segment()


def test_an_edited_segment_writes_the_flag_and_survives_a_round_trip() -> None:
    edited = dataclasses.replace(_segment(), text="We ship on Friday.", words=(), edited=True)

    data = edited.to_dict()

    assert data["edited"] is True
    assert TranscriptSegment.from_dict(json.loads(json.dumps(data))) == edited


def test_a_raw_segment_has_no_edited_key_and_reads_back_unedited() -> None:
    assert "edited" not in _segment().to_dict()
    assert TranscriptSegment.from_dict(_segment().to_dict()).edited is False


def test_from_dict_accepts_a_segment_without_words() -> None:
    data = _segment().to_dict()
    del data["words"]

    assert TranscriptSegment.from_dict(data).words == ()


def test_from_dict_rejects_an_unknown_channel() -> None:
    data = _segment().to_dict() | {"channel": "speaker"}

    with pytest.raises(ValueError):
        TranscriptSegment.from_dict(data)


def test_values_are_immutable() -> None:
    with pytest.raises(AttributeError):
        _segment().text = "changed"  # type: ignore[misc]


def test_transcription_result_holds_words_and_language() -> None:
    result = TranscriptionResult(words=(), language=None)

    assert result.words == ()
    assert result.language is None


def test_audio_chunk_compares_by_identity_not_by_samples() -> None:
    samples = np.zeros(4, dtype=np.float32)
    chunk = AudioChunk(channel=Channel.SYSTEM, start=1.5, samples=samples)

    assert chunk == chunk
    assert chunk != AudioChunk(channel=Channel.SYSTEM, start=1.5, samples=samples)


def test_speaker_turn_holds_a_time_span_and_a_speaker_index() -> None:
    turn = SpeakerTurn(start=1.0, end=2.5, speaker_index=1)

    assert (turn.start, turn.end, turn.speaker_index) == (1.0, 2.5, 1)
    assert turn.overlap(2.0, 4.0) == 0.5
    assert turn.overlap(3.0, 4.0) == 0.0
