from __future__ import annotations

import numpy as np
import pytest

from tests.fakes import FakeSpeechDetector
from vozata.audio.chunker import FixedWindowChunker
from vozata.audio.vad_chunker import VadChunker
from vozata.domain import AudioChunk, Channel
from vozata.ports import Chunker, SpeechDetector

RATE = 100  # 10 ms per sample keeps the arithmetic readable
BLOCK = 0.1  # capture block length, seconds


class Rig:
    """A `VadChunker` fed in 0.1 s blocks, with the session time of every emitted chunk."""

    def __init__(self, **overrides: float) -> None:
        options = {
            "min_silence": 0.6,
            "min_chunk": 1.0,
            "max_chunk": 15.0,
            "speech_pad": 0.2,
            "check_seconds": 0.2,
        }
        options.update(overrides)
        self.detector = FakeSpeechDetector(RATE)
        self.chunks: list[AudioChunk] = []
        self.emitted_at: list[float] = []
        self.time = 0.0
        self.chunker = VadChunker(Channel.SYSTEM, RATE, self._on_chunk, self.detector, **options)

    def _on_chunk(self, chunk: AudioChunk) -> None:
        self.chunks.append(chunk)
        self.emitted_at.append(self.time)

    def speech(self, seconds: float) -> Rig:
        return self._feed(seconds, 0.5)

    def silence(self, seconds: float) -> Rig:
        return self._feed(seconds, 0.0)

    def _feed(self, seconds: float, value: float) -> Rig:
        for _ in range(round(seconds / BLOCK)):
            block = np.full(round(BLOCK * RATE), value, dtype=np.float32)
            self.chunker.feed(block, self.time)
            self.time = round(self.time + BLOCK, 6)
        return self

    def spans(self) -> list[tuple[float, float]]:
        """Session-time (start, end) of every chunk."""
        return [(c.start, round(c.start + len(c.samples) / RATE, 6)) for c in self.chunks]

    def speech_seconds(self) -> list[float]:
        return [float(np.count_nonzero(c.samples)) / RATE for c in self.chunks]


def test_silence_alone_emits_nothing_and_keeps_the_buffer_short() -> None:
    rig = Rig().silence(30)
    rig.chunker.flush()

    assert rig.chunks == []
    assert max(rig.detector.calls) <= 1.5 * RATE


def test_a_phrase_is_cut_in_the_pause_after_it_with_leading_silence_dropped() -> None:
    rig = Rig().silence(2).speech(2).silence(1.5)

    assert len(rig.chunks) == 1
    chunk = rig.chunks[0]
    assert chunk.channel is Channel.SYSTEM
    assert chunk.complete
    start, end = rig.spans()[0]
    assert start == pytest.approx(1.8)  # speech at 2.0 minus the 0.2 s pad
    assert 4.2 <= end <= 4.5  # inside the pause, at most min_silence / 2 after the speech
    assert rig.speech_seconds() == [2.0]


def test_the_cut_comes_as_soon_as_the_pause_is_long_enough() -> None:
    rig = Rig().speech(2).silence(3)

    assert rig.emitted_at[0] <= 2.0 + 0.6 + 0.2  # speech end + min_silence + one check


def test_a_short_pause_does_not_cut() -> None:
    rig = Rig().speech(2).silence(0.4).speech(2).silence(1)

    assert len(rig.chunks) == 1
    assert rig.speech_seconds() == [4.0]


def test_two_phrases_become_two_chunks_in_session_time() -> None:
    rig = Rig().speech(2).silence(1).speech(1.5).silence(1)

    assert [c.complete for c in rig.chunks] == [True, True]
    assert rig.speech_seconds() == [2.0, 1.5]
    assert rig.spans()[1][0] == pytest.approx(3.0 - 0.2)


def test_long_speech_is_forced_out_at_its_longest_pause() -> None:
    rig = Rig().speech(6).silence(0.2).speech(4).silence(0.3).speech(6)

    first = rig.chunks[0]
    assert not first.complete  # the pause was shorter than min_silence
    start, end = rig.spans()[0]
    assert start == 0.0
    assert 10.3 <= end <= 10.5  # in the 0.3 s pause, not the 0.2 s one
    assert rig.speech_seconds()[0] == 10.0


def test_speech_without_any_pause_is_forced_out_at_the_limit() -> None:
    rig = Rig().speech(16)

    assert len(rig.chunks) == 1
    assert not rig.chunks[0].complete
    assert len(rig.chunks[0].samples) == pytest.approx(15 * RATE, abs=0.2 * RATE)
    rig.chunker.flush()
    assert rig.spans()[1][0] == pytest.approx(rig.spans()[0][1])  # nothing lost


def test_a_blip_joins_the_next_phrase() -> None:
    rig = Rig().silence(1).speech(0.4).silence(1).speech(2).silence(1)

    assert len(rig.chunks) == 1
    assert rig.spans()[0][0] == pytest.approx(0.8)  # the blip's start minus the pad
    assert rig.speech_seconds() == [2.4]


def test_a_lone_blip_leaves_at_the_forced_cut_with_its_pause() -> None:
    rig = Rig().speech(0.4).silence(16)

    assert len(rig.chunks) == 1
    assert rig.chunks[0].complete
    start, end = rig.spans()[0]
    assert (start, rig.speech_seconds()) == (0.0, [0.4])
    assert end <= 0.4 + 0.3 + 1e-9


def test_a_lone_blip_leaves_at_flush() -> None:
    rig = Rig().silence(1).speech(0.4).silence(1)
    rig.chunker.flush()

    assert rig.speech_seconds() == [0.4]
    assert rig.spans()[0][0] == pytest.approx(0.8)


def test_flush_emits_ongoing_speech_as_complete() -> None:
    rig = Rig().silence(1).speech(1.5)
    rig.chunker.flush()

    assert [c.complete for c in rig.chunks] == [True]
    assert rig.spans() == [(pytest.approx(0.8), pytest.approx(2.5))]
    rig.chunker.flush()
    assert len(rig.chunks) == 1


def test_pausing_emits_the_buffer_and_drops_audio_until_resumed() -> None:
    rig = Rig().speech(1.5)
    rig.chunker.paused = True
    assert rig.chunker.paused
    assert rig.speech_seconds() == [1.5]

    rig.speech(3)
    rig.chunker.paused = False
    rig.speech(1.5).silence(1)

    assert rig.speech_seconds() == [1.5, 1.5]
    assert rig.spans()[1][0] == pytest.approx(4.5)  # resumed at 4.5 s, nothing to pad


def test_capture_gaps_are_filled_with_silence_to_keep_session_time() -> None:
    rig = Rig()
    rig.speech(1.5)
    rig.time = 3.0  # loopback delivered nothing for 1.5 s
    rig.speech(1.5).silence(1)

    assert len(rig.chunks) == 2
    assert rig.spans()[1][0] == pytest.approx(3.0 - 0.2)


def test_the_detector_runs_once_per_check_interval() -> None:
    rig = Rig(check_seconds=0.5).speech(2)

    assert len(rig.detector.calls) == 4


def test_both_chunkers_satisfy_the_chunker_port() -> None:
    assert isinstance(Rig().chunker, Chunker)
    assert isinstance(FixedWindowChunker(Channel.MIC, 1.0, RATE, print), Chunker)
    assert isinstance(FakeSpeechDetector(RATE), SpeechDetector)
