from __future__ import annotations

import numpy as np
import pytest

from vozata.audio.devices import DeviceInfo
from vozata.domain import Channel
from vozata.recorder.source_mix import (
    ACTIVATE_SECONDS,
    HOLD_SECONDS,
    OFF,
    ON,
    SourceBuffer,
    SourceMixer,
    SourceScore,
    SourceScorer,
    SourceSelector,
    automix,
)
from vozata.recorder.sources import SourceSpec

RATE = 1000  # 20 frames of 20 ms per second
FRAME = 20


def _spec(source_id: str, kind: Channel = Channel.MIC, preferred: bool = False) -> SourceSpec:
    device = DeviceInfo(len(source_id), source_id, 1, 48000, kind == Channel.SYSTEM)
    return SourceSpec(source_id, kind, device, preferred)


def _speech(seconds: float, seed: int = 1, level: float = 0.3, period: int = 200) -> np.ndarray:
    """Bursts of noise (words) with pauses: `period` frames on, `period` off."""
    rng = np.random.default_rng(seed)
    n = round(seconds * RATE)
    signal = rng.normal(0, level, n).astype(np.float32)
    envelope = (np.arange(n) // period % 2 == 0).astype(np.float32)
    return signal * envelope


def _noise(seconds: float, level: float = 0.001, seed: int = 9) -> np.ndarray:
    return np.random.default_rng(seed).normal(0, level, round(seconds * RATE)).astype(np.float32)


# -- SourceBuffer ---------------------------------------------------------------------------


def test_buffer_places_blocks_on_the_timeline_and_fills_gaps() -> None:
    buffer = SourceBuffer(start=0, tolerance=5)
    buffer.push(np.ones(10, np.float32), 0)
    buffer.push(np.ones(10, np.float32), 13)  # jitter: appended right after
    buffer.push(np.ones(5, np.float32), 40)  # a real gap: silence first
    assert buffer.end == 45
    data = buffer.read(0, 50)
    assert data[:20].tolist() == [1.0] * 20
    assert data[20:40].tolist() == [0.0] * 20
    assert data[40:45].tolist() == [1.0] * 5
    assert data[45:].tolist() == [0.0] * 5


def test_buffer_read_outside_the_data_is_zeros_and_drop_moves_the_start() -> None:
    buffer = SourceBuffer(start=100, tolerance=5)
    assert buffer.read(0, 10).tolist() == [0.0] * 10
    buffer.drop_before(150)  # nothing pushed yet: the start just moves
    assert buffer.end == 150
    buffer.push(np.arange(10, dtype=np.float32), 150)
    buffer.drop_before(155)
    assert buffer.read(150, 160).tolist() == [0, 0, 0, 0, 0, 5, 6, 7, 8, 9]
    buffer.drop_before(155)  # already dropped: nothing changes
    assert buffer.end == 160


# -- automix --------------------------------------------------------------------------------


def test_automix_of_one_block_is_the_block_and_of_none_is_empty() -> None:
    block = np.array([0.1, -0.2, 0.3], np.float32)
    assert automix([block], FRAME).tolist() == pytest.approx(block.tolist())
    assert automix([], FRAME).size == 0
    assert automix([np.zeros(0, np.float32)] * 2, FRAME).size == 0


def test_automix_lets_the_loud_source_through_and_hides_the_quiet_one() -> None:
    loud = _speech(1.0, level=0.3)
    quiet = _noise(1.0, level=0.001)
    mixed = automix([loud, quiet], FRAME)
    speaking = np.abs(loud) > 0
    assert float(np.mean(np.abs(mixed - loud)[speaking])) < 0.01
    assert float(np.max(np.abs(mixed[~speaking]))) < 0.01
    assert len(mixed) == len(loud)


def test_automix_of_two_silent_sources_is_silent() -> None:
    assert not automix([np.zeros(100, np.float32)] * 2, FRAME).any()


# -- SourceScorer ---------------------------------------------------------------------------


def test_scorer_counts_active_speech_and_ignores_steady_noise() -> None:
    scorer = SourceScorer(RATE)
    scorer.update("speech", _speech(4.0), 4.0)
    scorer.update("fan", _noise(4.0, level=0.05), 4.0)
    speech, fan = scorer.score("speech"), scorer.score("fan")
    assert speech.active_seconds == pytest.approx(2.0, abs=0.2)
    assert speech.value == pytest.approx(0.2, abs=0.02)
    assert speech.level_db > -20
    assert fan.active_seconds < ACTIVATE_SECONDS
    assert not speech.silent and not fan.silent
    assert scorer.last_active("speech") == pytest.approx(3.8, abs=0.05)
    assert scorer.last_active("fan") is None


def test_scorer_marks_digital_silence_after_a_second() -> None:
    scorer = SourceScorer(RATE)
    scorer.update("zeros", np.zeros(500, np.float32), 0.5)
    assert not scorer.score("zeros").silent  # too early to tell
    scorer.update("zeros", np.zeros(500, np.float32), 1.0)
    assert scorer.score("zeros") == SourceScore(0.0, -90.0, True, 1.0)
    assert scorer.score("unknown") == SourceScore(0.0, -90.0, False, 0.0)


def test_scorer_ignores_a_block_shorter_than_a_frame() -> None:
    scorer = SourceScorer(RATE)
    scorer.update("a", np.ones(FRAME - 1, np.float32), 0.1)
    assert scorer.score("a").seen_seconds == 0.0


def test_correlation_finds_the_same_audio_in_two_sources() -> None:
    scorer = SourceScorer(RATE)
    speech = _speech(4.0)
    scorer.update("a", speech, 4.0)
    scorer.update("b", speech * 0.5 + _noise(4.0), 4.0)
    scorer.update("c", _speech(4.0, seed=5) * np.roll(np.arange(4000) // 300 % 2, 0), 4.0)
    scorer.update("flat", np.zeros(4000, np.float32), 4.0)
    assert scorer.correlation("a", "b") > 0.9
    assert scorer.correlation("a", "c") < 0.7
    late = np.concatenate([np.zeros(60, np.float32), speech[:-60]])  # 60 ms later: 3 frames
    scorer.update("late", late, 4.0)
    assert scorer.correlation("a", "late") > 0.9
    assert scorer.correlation("a", "flat") == 0.0
    assert scorer.correlation("a", "missing") == 0.0


# -- SourceSelector -------------------------------------------------------------------------


def test_selector_starts_with_the_preferred_sources_and_the_forced_modes() -> None:
    specs = [_spec("in-a", preferred=True), _spec("in-b"), _spec("out-a", Channel.SYSTEM)]
    selector = SourceSelector(specs, modes={"in-a": OFF, "out-a": ON})
    assert selector.selected == {"out-a"}
    assert selector.of_kind(Channel.SYSTEM) == ["out-a"]
    resumed = SourceSelector(specs, selected=["in-b", "gone"])
    assert resumed.selected == {"in-b"}


def test_set_mode_applies_at_once_and_auto_keeps_the_selection() -> None:
    selector = SourceSelector([_spec("in-a", preferred=True), _spec("in-b")])
    assert selector.set_mode("in-a", ON) is None  # already selected
    change = selector.set_mode("in-b", ON)
    assert change is not None and (change.source_id, change.selected, change.by) == (
        "in-b",
        True,
        "user",
    )
    assert selector.set_mode("in-b", "auto") is None
    assert selector.selected == {"in-a", "in-b"}
    assert selector.set_mode("in-a", OFF) is not None
    with pytest.raises(KeyError):
        selector.set_mode("nope", ON)
    with pytest.raises(ValueError):
        selector.set_mode("in-a", "maybe")


def test_update_selects_the_source_that_speaks_and_drops_the_silent_preferred() -> None:
    selector = SourceSelector([_spec("in-dead", preferred=True), _spec("in-live")])
    scorer = SourceScorer(RATE)
    scorer.update("in-dead", np.zeros(2000, np.float32), 2.0)
    scorer.update("in-live", _speech(2.0), 2.0)
    changes = selector.update(scorer, 2.0)
    assert {(c.source_id, c.selected) for c in changes} == {("in-dead", False), ("in-live", True)}
    assert selector.selected == {"in-live"}


def test_update_keeps_the_previous_selection_when_nothing_speaks() -> None:
    selector = SourceSelector([_spec("in-a", preferred=True), _spec("in-b")])
    scorer = SourceScorer(RATE)
    scorer.update("in-a", _noise(2.0), 2.0)
    scorer.update("in-b", _noise(2.0, seed=3), 2.0)
    assert selector.update(scorer, 2.0) == []
    assert selector.selected == {"in-a"}


def test_update_keeps_a_quiet_source_for_the_hold_time_then_drops_it() -> None:
    selector = SourceSelector([_spec("in-a"), _spec("in-b")])
    scorer = SourceScorer(RATE)
    scorer.update("in-a", _speech(2.0), 2.0)
    scorer.update("in-b", _speech(2.0, seed=4, period=330), 2.0)
    selector.update(scorer, 2.0)
    assert selector.selected == {"in-a", "in-b"}
    for second in range(3, 13):  # in-b goes quiet; in-a keeps speaking
        scorer.update("in-a", _speech(1.0, seed=second), float(second))
        scorer.update("in-b", _noise(1.0, seed=second), float(second))
    selector.update(scorer, 12.0)
    assert selector.selected == {"in-a", "in-b"}  # quiet, but within the hold time
    later = 2.0 + HOLD_SECONDS + 1
    scorer.update("in-a", _speech(1.0, seed=99), later)
    scorer.update("in-b", _noise(1.0, seed=98), later)
    changes = selector.update(scorer, later)
    assert [(c.source_id, c.selected) for c in changes] == [("in-b", False)]


def test_update_keeps_only_the_best_of_two_duplicated_sources() -> None:
    selector = SourceSelector([_spec("in-near"), _spec("in-far"), _spec("in-other-room")])
    scorer = SourceScorer(RATE)
    speech = _speech(4.0)
    scorer.update("in-near", speech, 4.0)
    scorer.update("in-far", speech * 0.9 + _noise(4.0), 4.0)  # same room, a bit quieter
    other = _speech(4.0, seed=7) * (np.arange(4000) // 300 % 2).astype(np.float32)
    scorer.update("in-other-room", other, 4.0)
    selector.update(scorer, 4.0)
    assert "in-other-room" in selector.selected
    assert len({"in-near", "in-far"} & selector.selected) == 1


def test_update_never_selects_an_off_source_and_keeps_an_on_one() -> None:
    selector = SourceSelector(
        [_spec("in-a"), _spec("in-b", preferred=True)], modes={"in-a": OFF, "in-b": ON}
    )
    scorer = SourceScorer(RATE)
    scorer.update("in-a", _speech(2.0), 2.0)
    scorer.update("in-b", np.zeros(2000, np.float32), 2.0)
    assert selector.update(scorer, 2.0) == []
    assert selector.selected == {"in-b"}


# -- SourceMixer ----------------------------------------------------------------------------


def _mixer(specs: list[SourceSpec], start: int = 0) -> SourceMixer:
    return SourceMixer(specs, RATE, start, SourceSelector(specs), delay=2.0)


def test_mixer_mixes_the_selected_sources_two_seconds_behind() -> None:
    specs = [_spec("in-a", preferred=True), _spec("out-a", Channel.SYSTEM, preferred=True)]
    mixer = _mixer(specs)
    speech = _speech(5.0)
    mixer.push("in-a", speech, 0.0)
    mixer.push("out-a", speech * 0.5, 0.0)
    blocks, _ = mixer.step(5.0)
    mic, at = blocks[Channel.MIC]
    assert at == 0.0
    assert len(mic) == 5000 - 300 - 2000  # head minus latency minus delay
    assert np.allclose(mic, speech[: len(mic)])
    assert np.allclose(blocks[Channel.SYSTEM][0], speech[: len(mic)] * 0.5)
    assert mixer.step(5.0) == ({}, [])  # nothing new


def test_mixer_selects_a_speaking_source_before_its_words_are_mixed() -> None:
    specs = [_spec("in-dead", preferred=True), _spec("in-live")]
    mixer = _mixer(specs)
    silence = np.zeros(3000, np.float32)
    speech = np.concatenate([silence, _speech(3.0)])
    mixer.push("in-dead", np.zeros(6000, np.float32), 0.0)
    mixer.push("in-live", speech, 0.0)
    blocks, changes = mixer.step(4.5)
    assert ("in-live", True) in {(c.source_id, c.selected) for c in changes}
    first, _ = blocks[Channel.MIC]
    assert not first.any()  # before the words
    final, changes = mixer.step(6.0, final=True)
    mixed, at = final[Channel.MIC]
    assert at == pytest.approx(len(first) / RATE)
    start = 3000 - len(first)
    assert np.allclose(mixed[start:], speech[3000:6000])  # the first words are in the mix
    assert mixer.selected() == {"in-live"}
    assert mixer.scores()["in-dead"].silent


def test_mixer_writes_silence_for_a_kind_without_sources_and_user_modes() -> None:
    specs = [_spec("in-a", preferred=True)]
    mixer = _mixer(specs, start=1000)
    mixer.push("in-a", _speech(2.0), 1.0)
    change = mixer.set_mode("in-a", OFF)
    assert change is not None and not change.selected
    blocks, _ = mixer.step(3.0, final=True)
    assert blocks[Channel.MIC][1] == 1.0
    assert not blocks[Channel.MIC][0].any()  # switched off
    assert not blocks[Channel.SYSTEM][0].any()
    assert len(blocks[Channel.SYSTEM][0]) == 2000


def test_a_source_that_failed_is_dropped_even_as_the_fallback() -> None:
    specs = [_spec("in-dead", preferred=True), _spec("in-quiet")]
    mixer = _mixer(specs)
    mixer.mark_unavailable("in-dead")
    mixer.push("in-quiet", _noise(3.0), 0.0)

    _, changes = mixer.step(3.0)

    assert [(c.source_id, c.selected) for c in changes] == [("in-dead", False)]
    assert mixer.selected() == set()


def test_a_digitally_silent_source_is_not_kept_as_the_fallback() -> None:
    selector = SourceSelector([_spec("in-zeros", preferred=True), _spec("in-b")])
    scorer = SourceScorer(RATE)
    scorer.update("in-zeros", np.zeros(2000, np.float32), 2.0)
    scorer.update("in-b", _noise(2.0), 2.0)

    changes = selector.update(scorer, 2.0)

    assert [(c.source_id, c.selected) for c in changes] == [("in-zeros", False)]


def test_a_source_is_scored_only_from_its_first_block() -> None:
    specs = [_spec("in-late", preferred=True), _spec("out-a", Channel.SYSTEM, preferred=True)]
    mixer = _mixer(specs)
    mixer.push("out-a", _speech(3.0), 0.0)
    mixer.step(2.0)  # in-late has not delivered anything yet
    assert mixer.scores()["in-late"].seen_seconds == 0.0
    mixer.push("in-late", _noise(1.0), 2.5)

    mixer.step(4.0, final=True)

    late = mixer.scores()["in-late"]
    assert late.seen_seconds == pytest.approx(1.0, abs=0.05)
    assert not late.silent
    assert mixer.selected() == {"in-late", "out-a"}  # the late, quiet mic is kept


def test_the_first_frame_of_a_buffer() -> None:
    buffer = SourceBuffer(start=0, tolerance=5)
    assert buffer.first is None
    buffer.push(np.ones(10, np.float32), 50)
    assert buffer.first == 50
    other = SourceBuffer(start=0, tolerance=5)
    other.push(np.ones(10, np.float32), 3)  # within the tolerance: right at the start
    assert other.first == 0
