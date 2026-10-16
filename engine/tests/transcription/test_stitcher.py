from __future__ import annotations

import numpy as np
import pytest

from tests.fakes import FakeTranscriber
from tests.transcription.contract import check_transcriber_contract
from vozata.config import Settings
from vozata.domain import AudioChunk, Channel, TranscriptionResult, Word
from vozata.transcription.stitcher import CarryOverStitcher, SegmentIds

RATE = 16000


def w(text: str, start: float, end: float, probability: float = 0.9) -> Word:
    return Word(text=text, start=start, end=end, probability=probability)


def result(*words: Word, language: str | None = "en") -> TranscriptionResult:
    return TranscriptionResult(words=words, language=language)


def chunk(start: float, seconds: float = 5.0, level: float = 0.1) -> AudioChunk:
    samples = np.full(round(seconds * RATE), level, dtype=np.float32)
    return AudioChunk(channel=Channel.MIC, start=start, samples=samples)


class FakeLanguage:
    def __init__(self, code: str | None = "en") -> None:
        self.code = code
        self.observed: list[tuple[str | None, float]] = []

    def current(self) -> str | None:
        return self.code

    def observe(self, language: str | None, speech_seconds: float) -> None:
        self.observed.append((language, speech_seconds))


def make(
    transcriber: FakeTranscriber,
    settings: Settings | None = None,
    language: FakeLanguage | None = None,
    hints: str | None = None,
) -> CarryOverStitcher:
    return CarryOverStitcher(
        Channel.MIC,
        transcriber,
        settings or Settings(),
        language or FakeLanguage(),
        SegmentIds().next,
        hints=hints,
    )


def audio_seconds(transcriber: FakeTranscriber, call: int) -> float:
    return len(transcriber.calls[call][0]) / RATE


def test_fake_transcriber_honours_the_transcriber_contract() -> None:
    fake = FakeTranscriber([result(w(" hi", 0.1, 0.4))])

    check_transcriber_contract(fake, np.full(RATE, 0.1, dtype=np.float32), "en")


def test_cuts_after_the_last_sentence_end_and_carries_the_rest() -> None:
    fake = FakeTranscriber(
        [result(w(" Hello", 0.5, 0.9), w(" world.", 1.0, 1.4), w(" Next", 4.5, 4.9))]
    )
    stitcher = make(fake)

    segments = stitcher.on_chunk(chunk(start=100.0))
    stitcher.on_chunk(chunk(start=105.0))

    assert [s.text for s in segments] == ["Hello world."]
    segment = segments[0]
    assert (segment.start, segment.end) == (100.5, 101.4)
    assert [word.text for word in segment.words] == ["Hello", "world."]
    assert segment.words[1].start == 101.0  # absolute times
    assert audio_seconds(fake, 1) == pytest.approx(5 - 2.95 + 5)  # carried tail + new window


def test_cuts_at_the_last_pause_gap_when_there_is_no_sentence_end() -> None:
    fake = FakeTranscriber(
        [result(w(" a", 0.0, 0.3), w(" b", 1.0, 1.2), w(" c", 1.25, 1.5), w(" d", 4.7, 4.9))]
    )

    segments = make(fake).on_chunk(chunk(start=0.0))

    assert [s.text for s in segments] == ["a b c"]


def test_words_inside_the_tail_margin_are_never_committed() -> None:
    fake = FakeTranscriber([result(w(" Done.", 4.5, 4.9))])  # ends within 0.6 s of the edge

    assert make(fake).on_chunk(chunk(start=0.0)) == []


def test_without_a_safe_cut_the_whole_window_is_carried() -> None:
    fake = FakeTranscriber([result(w(" x", 0.1, 0.4), w(" y", 0.45, 4.8))])
    stitcher = make(fake)

    first = stitcher.on_chunk(chunk(start=10.0))
    stitcher.on_chunk(chunk(start=15.0))

    assert first == []
    assert audio_seconds(fake, 1) == pytest.approx(10.0)


def test_commit_is_forced_once_carried_audio_reaches_the_maximum() -> None:
    fake = FakeTranscriber(
        [
            result(w(" x", 0.1, 0.4), w(" y", 0.45, 4.8)),
            result(w(" x", 0.1, 0.4), w(" y", 0.45, 9.0)),
        ]
    )
    stitcher = make(fake, Settings(max_carry_seconds=8))

    stitcher.on_chunk(chunk(start=0.0))
    segments = stitcher.on_chunk(chunk(start=5.0))
    stitcher.on_chunk(chunk(start=10.0))

    assert [s.text for s in segments] == ["x y"]
    assert audio_seconds(fake, 2) == pytest.approx(0.7 + 5.0)  # after the last word + 0.3 s tail


def test_silent_window_without_pending_audio_skips_the_transcriber() -> None:
    fake = FakeTranscriber()

    assert make(fake).on_chunk(chunk(start=0.0, level=0.0)) == []
    assert fake.calls == []


def test_silent_window_is_still_transcribed_when_audio_is_pending() -> None:
    fake = FakeTranscriber([result(w(" x", 0.1, 0.4), w(" y", 0.45, 4.8))])
    stitcher = make(fake)

    stitcher.on_chunk(chunk(start=0.0))
    stitcher.on_chunk(chunk(start=5.0, level=0.0))

    assert len(fake.calls) == 2


def test_a_window_without_words_drops_pending_audio() -> None:
    fake = FakeTranscriber([result(w(" x", 0.1, 0.4), w(" y", 0.45, 4.8)), result()])
    stitcher = make(fake)

    stitcher.on_chunk(chunk(start=0.0))
    stitcher.on_chunk(chunk(start=5.0))
    stitcher.on_chunk(chunk(start=10.0))

    assert audio_seconds(fake, 2) == pytest.approx(5.0)


def test_flush_commits_every_pending_word_once() -> None:
    fake = FakeTranscriber(
        [
            result(w(" x", 0.1, 0.4), w(" y", 0.45, 4.8)),
            result(w(" x", 0.1, 0.4), w(" y.", 0.45, 4.8)),
        ]
    )
    stitcher = make(fake)

    stitcher.on_chunk(chunk(start=20.0))
    flushed = stitcher.flush()

    assert [s.text for s in flushed] == ["x y."]
    assert flushed[0].start == 20.1
    assert stitcher.flush() == []
    assert len(fake.calls) == 2


def test_carried_words_are_not_duplicated_across_windows() -> None:
    fake = FakeTranscriber(
        [
            result(w(" One.", 0.2, 0.6), w(" Two", 4.6, 4.9)),
            result(w(" Two", 0.2, 0.5), w(" three.", 0.6, 1.0)),
        ]
    )
    stitcher = make(fake)

    first = stitcher.on_chunk(chunk(start=0.0))
    second = stitcher.on_chunk(chunk(start=5.0))

    assert [s.text for s in first + second] == ["One.", "Two three."]
    cut = (0.6 + 4.6) / 2
    assert second[0].start == pytest.approx(cut + 0.2)


def test_segment_ids_count_per_channel() -> None:
    ids = SegmentIds()

    assert [ids.next(Channel.MIC), ids.next(Channel.SYSTEM), ids.next(Channel.MIC)] == [
        "mic-000001",
        "system-000001",
        "mic-000002",
    ]


def test_segments_carry_channel_speaker_and_sequential_ids() -> None:
    fake = FakeTranscriber([result(w(" A.", 0.1, 0.4), w(" B.", 1.0, 1.3), w(" C", 4.6, 4.9))])

    segment = make(fake).on_chunk(chunk(start=0.0))[0]

    assert (segment.segment_id, segment.channel, segment.speaker_id) == (
        "mic-000001",
        Channel.MIC,
        "mic",
    )


def test_language_and_hints_reach_the_transcriber_and_detections_are_observed() -> None:
    fake = FakeTranscriber([result(w(" Oi.", 0.1, 0.5), w(" tudo", 0.6, 1.0), language="pt")])
    language = FakeLanguage(code=None)

    make(fake, language=language, hints="Avalonia").on_chunk(chunk(start=0.0))

    _, code, hints = fake.calls[0]
    assert (code, hints) == (None, "Avalonia")
    assert language.observed == [("pt", pytest.approx(0.8))]


def voiced_chunk(start: float, voiced_until: float, seconds: float = 5.0) -> AudioChunk:
    samples = np.zeros(round(seconds * RATE), dtype=np.float32)
    samples[: round(voiced_until * RATE)] = 0.1
    return AudioChunk(channel=Channel.MIC, start=start, samples=samples)


def test_cut_after_the_last_word_extends_through_its_voiced_tail() -> None:
    # Whisper word ends run early: the voice continues 0.2 s after "Done." is said to end.
    fake = FakeTranscriber([result(w(" Done.", 0.5, 2.0))])
    stitcher = make(fake)

    stitcher.on_chunk(voiced_chunk(start=0.0, voiced_until=2.2))
    stitcher.flush()

    assert audio_seconds(fake, 1) == pytest.approx(5.0 - 2.2, abs=0.011)


def test_voiced_tail_extension_is_capped() -> None:
    fake = FakeTranscriber([result(w(" Done.", 0.5, 2.0))])
    stitcher = make(fake)

    stitcher.on_chunk(voiced_chunk(start=0.0, voiced_until=5.0))
    stitcher.flush()

    assert audio_seconds(fake, 1) == pytest.approx(5.0 - 2.3)
