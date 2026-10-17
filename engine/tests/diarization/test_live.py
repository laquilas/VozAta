from __future__ import annotations

import logging

import numpy as np
import pytest

from tests.fakes import FakeEmbedder
from vozata.diarization.live import LiveSpeakerTagger
from vozata.domain import Channel, TranscriptSegment

CLIP = np.ones(16000, dtype=np.float32)


def _segment(
    start: float, end: float, channel: Channel = Channel.SYSTEM, number: int = 1
) -> TranscriptSegment:
    return TranscriptSegment(
        f"{channel.value}-{number:06d}", channel, channel.value, start, end, "hello", ()
    )


class _Clock:
    """Each read advances by the next queued step (0 when none are left)."""

    def __init__(self, *steps: float) -> None:
        self.now = 0.0
        self.steps = list(steps)

    def __call__(self) -> float:
        self.now += self.steps.pop(0) if self.steps else 0.0
        return self.now


def _tagger(embedder: FakeEmbedder, **options: object) -> LiveSpeakerTagger:
    return LiveSpeakerTagger(embedder, threshold=0.7, **options)  # type: ignore[arg-type]


def test_the_first_voice_becomes_speaker_one_and_a_different_voice_speaker_two() -> None:
    tagger = _tagger(FakeEmbedder([[1, 0], [0, 1]]))

    first = tagger.tag(_segment(0, 2), CLIP)
    second = tagger.tag(_segment(2, 4, number=2), CLIP)

    assert (first.speaker_id, second.speaker_id) == ("system:1", "system:2")
    assert tagger.speakers == 2


def test_a_voice_above_the_threshold_joins_the_closest_speaker() -> None:
    tagger = _tagger(FakeEmbedder([[1, 0], [0, 1], [0.9, 0.1], [0.1, 0.9]]))

    ids = [tagger.tag(_segment(i * 2, i * 2 + 2, number=i), CLIP).speaker_id for i in range(4)]

    assert ids == ["system:1", "system:2", "system:1", "system:2"]
    assert tagger.speakers == 2


DEG_25 = [0.9063, 0.4226]
DEG_36 = [0.8090, 0.5878]


def test_the_centroid_is_the_running_mean_of_the_speaker_embeddings() -> None:
    # 0° then 25° (cos 0.906 ≥ 0.9: same speaker); the centroid moves to 12.5°, so 36° has
    # cos(23.5°) ≈ 0.917 with it and joins too, although cos(36°) ≈ 0.81 with the first voice.
    tagger = LiveSpeakerTagger(FakeEmbedder([[1, 0], DEG_25, DEG_36]), threshold=0.9)

    ids = [tagger.tag(_segment(i * 2, i * 2 + 2, number=i), CLIP).speaker_id for i in range(3)]

    assert ids == ["system:1", "system:1", "system:1"]


def test_without_the_centroid_update_the_third_voice_would_be_new() -> None:
    tagger = LiveSpeakerTagger(FakeEmbedder([[1, 0], DEG_36]), threshold=0.9)

    ids = [tagger.tag(_segment(i * 2, i * 2 + 2, number=i), CLIP).speaker_id for i in range(2)]

    assert ids == ["system:1", "system:2"]


def test_a_short_segment_reuses_the_previous_speaker_without_embedding() -> None:
    embedder = FakeEmbedder([[1, 0], [0, 1]])
    tagger = _tagger(embedder)

    tagger.tag(_segment(0, 2), CLIP)
    tagger.tag(_segment(2, 4, number=2), CLIP)
    short = tagger.tag(_segment(4, 4.5, number=3), CLIP[:8000])

    assert short.speaker_id == "system:2"
    assert len(embedder.calls) == 2


def test_a_short_first_segment_stays_system() -> None:
    embedder = FakeEmbedder()
    tagger = _tagger(embedder, min_seconds=1.0)

    assert tagger.tag(_segment(0, 0.4), CLIP[:6400]).speaker_id == "system"
    assert embedder.calls == []


def test_microphone_segments_are_never_tagged() -> None:
    embedder = FakeEmbedder()
    tagger = _tagger(embedder)
    mic = _segment(0, 3, Channel.MIC)

    assert tagger.tag(mic, CLIP) is mic
    assert embedder.calls == []


def test_a_segment_without_audio_reuses_the_previous_speaker() -> None:
    embedder = FakeEmbedder([[1, 0]])
    tagger = _tagger(embedder)
    tagger.tag(_segment(0, 2), CLIP)

    assert tagger.tag(_segment(2, 4, number=2), np.zeros(0, np.float32)).speaker_id == "system:1"
    assert len(embedder.calls) == 1


def test_an_unusable_embedding_reuses_the_previous_speaker() -> None:
    tagger = _tagger(FakeEmbedder([[1, 0], [0, 0], [float("nan"), 1]]))
    tagger.tag(_segment(0, 2), CLIP)

    assert tagger.tag(_segment(2, 4, number=2), CLIP).speaker_id == "system:1"
    assert tagger.tag(_segment(4, 6, number=3), CLIP).speaker_id == "system:1"
    assert tagger.speakers == 1


def test_slow_embedding_disables_the_tagger_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    embedder = FakeEmbedder([[1, 0], [0, 1]])
    tagger = _tagger(embedder, max_seconds=5.0, clock=_Clock(0, 1, 0, 6))

    first = tagger.tag(_segment(0, 2), CLIP)
    with caplog.at_level(logging.WARNING):
        second = tagger.tag(_segment(2, 4, number=2), CLIP)
    third = tagger.tag(_segment(4, 6, number=3), CLIP)

    assert (first.speaker_id, second.speaker_id, third.speaker_id) == (
        "system:1",
        "system:2",
        "system",
    )
    assert tagger.disabled
    assert len(embedder.calls) == 2
    assert "disabled" in caplog.text


def test_a_failing_embedder_disables_the_tagger(caplog: pytest.LogCaptureFixture) -> None:
    embedder = FakeEmbedder(error=RuntimeError("model crashed"))
    tagger = _tagger(embedder)

    with caplog.at_level(logging.WARNING):
        segment = tagger.tag(_segment(0, 2), CLIP)

    assert segment.speaker_id == "system"
    assert tagger.disabled
    assert "model crashed" in caplog.text
    tagger.tag(_segment(2, 4, number=2), CLIP)
    assert len(embedder.calls) == 1


def test_close_releases_the_embedder_and_logs_a_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _FailingClose(FakeEmbedder):
        def close(self) -> None:
            super().close()
            raise RuntimeError("pipe closed")

    embedder = _FailingClose()

    _tagger(embedder).close()

    assert embedder.closed
    assert "Releasing the speaker embedder failed" in caplog.text


def test_disable_turns_tagging_off() -> None:
    embedder = FakeEmbedder([[1, 0]])
    tagger = _tagger(embedder)

    tagger.disable("no model")
    tagger.disable("again")  # logged once

    assert tagger.tag(_segment(0, 2), CLIP).speaker_id == "system"
    assert embedder.calls == []
