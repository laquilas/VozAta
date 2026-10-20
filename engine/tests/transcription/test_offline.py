from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from tests.fakes import FakeAudioReader, FakeLocalizer, FakeRecycler, FakeTranscriber
from vozata.audio.chunker import FixedWindowChunker
from vozata.config import Settings
from vozata.domain import (
    AudioChunk,
    Channel,
    ConversationLanguage,
    TranscriptionResult,
    TranscriptSegment,
    Word,
)
from vozata.labels import SpeakerLabeler
from vozata.ports import Chunker
from vozata.processing.cancel import CancelToken, StepCancelled
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.session_store import SessionStore
from vozata.transcription.language_lock import LanguageLock
from vozata.transcription.offline import OfflineTranscription

RATE = 1000
TONE = 3277  # int16 for ~0.1, above SILENCE_RMS_THRESHOLD
ECHO = "see you on Friday."


def _settings(**overrides: object) -> Settings:
    return Settings(sample_rate=RATE, chunk_seconds=5.0, **overrides)  # type: ignore[arg-type]


def _track(seconds: float, *speech: tuple[float, float]) -> np.ndarray:
    track = np.zeros(round(seconds * RATE), dtype=np.int16)
    for start, end in speech:
        track[round(start * RATE) : round(end * RATE)] = TONE
    return track


def _said(text: str, start: float, end: float) -> TranscriptionResult:
    tokens = text.split()
    step = (end - start) / len(tokens)
    words = tuple(
        Word(f" {token}", start + i * step, start + (i + 1) * step, 0.9)
        for i, token in enumerate(tokens)
    )
    return TranscriptionResult(words=words, language="en")


def _row(segment_id: str, start: float, end: float, text: str = "Before.") -> TranscriptSegment:
    channel = Channel(segment_id.split("-")[0])
    words = (Word(text, start, end, 0.9),)
    return TranscriptSegment(segment_id, channel, channel.value, start, end, text, words)


class _Rig:
    def __init__(
        self,
        tmp_path: Path,
        tracks: dict[Channel, np.ndarray],
        results: list[TranscriptionResult] | None = None,
        existing: list[TranscriptSegment] = (),  # type: ignore[assignment]
        settings: Settings | None = None,
        chunker_factory: Callable[[Channel, Callable[[AudioChunk], None]], Chunker] | None = None,
        rate: int = RATE,
    ) -> None:
        self.store = FileSessionRepository(
            SessionStore(tmp_path / "recordings"), FakeRecycler(tmp_path / "bin")
        )
        self.labeler = SpeakerLabeler(FakeLocalizer())
        self.session_id = self.store.create()
        self.store.write_meta(self.session_id, {"id": self.session_id, "status": "processing"})
        sink = self.store.open_transcript(self.session_id, self.labeler)
        for segment in existing:
            sink.emit(segment)
        sink.close()
        self.audio = FakeAudioReader(tracks, {channel: rate for channel in tracks})
        self.transcriber = FakeTranscriber(results)
        self.loads = 0
        self.progress: list[float] = []
        self.offline = OfflineTranscription(
            settings or _settings(),
            self.store,
            self.audio,
            self._load,
            self.labeler,
            LanguageLock(ConversationLanguage.EN, lambda language: None),
            "Kubernetes",
            chunker_factory,
        )

    def _load(self) -> FakeTranscriber:
        self.loads += 1
        return self.transcriber

    def run(self, token: CancelToken | None = None) -> None:
        self.offline.run(self.session_id, token or CancelToken(), self.progress.append)

    def stored(self) -> list[TranscriptSegment]:
        return self.store.load_raw_transcript(self.session_id)


def test_offline_continues_ids_and_appends_after_existing_segments(tmp_path: Path) -> None:
    old = [_row("mic-000012", 38.0, 40.5), _row("system-000003", 28.0, 30.0)]
    rig = _Rig(
        tmp_path,
        {Channel.MIC: _track(60, (42.0, 43.0)), Channel.SYSTEM: _track(60)},
        [_said("Later.", 1.5, 2.5)],  # mic resumes at 40.5: 42.0 is 1.5 s into its window
        existing=old,
    )

    rig.run()

    stored = rig.stored()
    assert stored[:2] == old
    assert [(s.segment_id, s.text, s.start, s.end) for s in stored[2:]] == [
        ("mic-000013", "Later.", pytest.approx(42.0), pytest.approx(43.0))
    ]
    assert [(language, hints) for _, language, hints in rig.transcriber.calls][0] == (
        "en",
        "Kubernetes",
    )
    assert rig.transcriber.prompts[0] == "Before."  # the context knows the written mic text


def test_offline_feeds_channels_in_lockstep(tmp_path: Path) -> None:
    old = [_row("mic-000001", 10.0, 12.0), _row("system-000001", 1.0, 3.0)]
    rig = _Rig(tmp_path, {Channel.MIC: _track(30), Channel.SYSTEM: _track(30)}, existing=old)

    rig.run()

    probes, feeds = rig.audio.reads[:2], rig.audio.reads[2:]
    assert probes == [(Channel.MIC, 12000, 310), (Channel.SYSTEM, 3000, 310)]  # silent tails
    assert feeds == [
        (Channel.MIC, 12000, 1000),  # mic waits until the shared timeline reaches 12 s
        (Channel.SYSTEM, 3000, 10000),
        (Channel.MIC, 13000, 10000),
        (Channel.SYSTEM, 13000, 10000),
        (Channel.MIC, 23000, 7000),
        (Channel.SYSTEM, 23000, 7000),
    ]


def test_offline_chunker_factory_starts_at_the_resume_point_on_the_session_clock(
    tmp_path: Path,
) -> None:
    chunks: list[tuple[Channel, float, int]] = []  # as the chunker sees them

    def factory(channel: Channel, on_chunk: Callable[[AudioChunk], None]) -> Chunker:
        def record(chunk: AudioChunk) -> None:
            chunks.append((chunk.channel, chunk.start, len(chunk.samples)))
            on_chunk(chunk)

        return FixedWindowChunker(channel, 4.0, RATE, record)

    old = [_row("mic-000001", 1.0, 2.5)]
    rig = _Rig(
        tmp_path,
        {Channel.MIC: _track(10.5, (3.0, 4.0)), Channel.SYSTEM: _track(10.5)},
        [_said("Hi.", 0.5, 1.5)],  # mic resumes at 2.5: 3.0 is 0.5 s into its first chunk
        existing=old,
        chunker_factory=factory,
    )

    rig.run()

    assert sorted(chunks) == [  # no silence padded before the mic resume point
        (Channel.MIC, 0.0, 4000),
        (Channel.MIC, 4.0, 4000),
        (Channel.SYSTEM, 0.0, 4000),
        (Channel.SYSTEM, 4.0, 4000),
        (Channel.SYSTEM, 8.0, 2500),
    ]
    assert [(s.segment_id, s.start, s.end) for s in rig.stored()[1:]] == [
        ("mic-000002", pytest.approx(3.0), pytest.approx(4.0))
    ]


@pytest.mark.parametrize("dedupe", [True, False])
def test_offline_echo_filter_drops_mic_copy_of_system_speech(tmp_path: Path, dedupe: bool) -> None:
    rig = _Rig(
        tmp_path,
        {Channel.MIC: _track(20, (2.0, 3.0)), Channel.SYSTEM: _track(20, (2.0, 3.0))},
        [_said(ECHO, 2.0, 3.0), _said(ECHO, 2.0, 3.0)],
        settings=_settings(echo_dedupe_enabled=dedupe),
    )

    rig.run()

    expected = ["system-000001"] if dedupe else ["mic-000001", "system-000001"]
    assert sorted(s.segment_id for s in rig.stored()) == expected


def test_offline_echo_filter_knows_the_stored_system_speech(tmp_path: Path) -> None:
    old = [_row("system-000001", 2.0, 3.0, ECHO)]
    rig = _Rig(
        tmp_path,
        {Channel.MIC: _track(20, (2.0, 3.0)), Channel.SYSTEM: _track(20)},
        [_said(ECHO, 2.0, 3.0)],
        existing=old,
    )

    rig.run()

    assert rig.stored() == old


def test_offline_progress_reaches_one_and_is_monotonic(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, {Channel.MIC: _track(25), Channel.SYSTEM: _track(25)})
    assert rig.offline.remaining_seconds(rig.session_id) == pytest.approx(50.0)

    rig.run()

    assert rig.progress == [0.4, 0.8, 1.0]


def test_remaining_seconds_start_at_the_resume_points(tmp_path: Path) -> None:
    old = [_row("mic-000001", 8.0, 10.0), _row("system-000001", 20.0, 30.0)]
    rig = _Rig(tmp_path, {Channel.MIC: _track(25), Channel.SYSTEM: _track(25)}, existing=old)

    assert rig.offline.remaining_seconds(rig.session_id) == pytest.approx(15.0)


def test_offline_with_nothing_left_reports_done_without_loading_the_model(
    tmp_path: Path,
) -> None:
    old = [_row("mic-000001", 3.0, 5.0), _row("system-000001", 3.0, 5.0)]
    rig = _Rig(tmp_path, {Channel.MIC: _track(5), Channel.SYSTEM: _track(5)}, existing=old)

    rig.run()

    assert (rig.progress, rig.loads, rig.stored()) == ([1.0], 0, old)


def test_offline_cancel_between_blocks_raises_and_keeps_committed_segments(
    tmp_path: Path,
) -> None:
    rig = _Rig(
        tmp_path,
        {Channel.MIC: _track(30, (0.0, 10.0)), Channel.SYSTEM: _track(30)},
        [_said("Hello", 0.5, 1.0), _said("Hello there.", 0.5, 9.0)],
    )
    token = CancelToken()

    with pytest.raises(StepCancelled):  # the progress callback cancels after the first block
        rig.offline.run(rig.session_id, token, lambda fraction: token.cancel())

    assert [s.text for s in rig.stored()] == ["Hello there."]
    assert len(rig.transcriber.calls) == 2  # the carried tail is not flushed
    assert {channel for channel, _, _ in rig.audio.reads} == {Channel.MIC, Channel.SYSTEM}
    assert len(rig.audio.reads) == 2


def test_offline_cancelled_before_start_loads_nothing(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, {Channel.MIC: _track(10), Channel.SYSTEM: _track(10)})
    token = CancelToken()
    token.cancel()

    with pytest.raises(StepCancelled):
        rig.run(token)

    assert (rig.loads, rig.audio.reads) == (0, [])


def test_offline_closes_transcriber_on_success_and_on_cancel(tmp_path: Path) -> None:
    done = _Rig(tmp_path / "done", {Channel.MIC: _track(10), Channel.SYSTEM: _track(10)})
    done.run()
    assert done.transcriber.closed

    cancelled = _Rig(tmp_path / "cancel", {Channel.MIC: _track(30), Channel.SYSTEM: _track(30)})
    token = CancelToken()
    with pytest.raises(StepCancelled):
        cancelled.offline.run(cancelled.session_id, token, lambda fraction: token.cancel())
    assert cancelled.transcriber.closed


def test_offline_closes_transcriber_when_transcription_fails(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, {Channel.MIC: _track(10, (1.0, 2.0)), Channel.SYSTEM: _track(10)})

    def fail(*args: object) -> TranscriptionResult:
        raise RuntimeError("model error")

    rig.transcriber.transcribe = fail  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="model error"):
        rig.run()

    assert rig.transcriber.closed


def test_offline_refuses_audio_at_another_sample_rate(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, {Channel.MIC: _track(10), Channel.SYSTEM: _track(10)}, rate=RATE * 2)

    with pytest.raises(ValueError, match="sample rate"):
        rig.run()

    assert rig.loads == 0


def test_offline_flushes_the_carried_tail_at_the_end(tmp_path: Path) -> None:
    rig = _Rig(
        tmp_path,
        {Channel.MIC: _track(10, (0.0, 10.0)), Channel.SYSTEM: _track(10)},
        [
            _said("Hello", 0.5, 1.0),
            _said("Hello there", 0.5, 9.0),
            _said("Hello there friend.", 0.5, 9.9),
        ],
    )

    rig.run()

    assert [(s.segment_id, s.text) for s in rig.stored()] == [("mic-000001", "Hello there friend.")]
    assert rig.progress == [1.0]


@pytest.mark.parametrize(
    ("voiced_until", "resume"),
    [
        (None, 10.0),  # silence right after the end: nothing to skip
        (10.2, 10.2),  # a word tail, then silence within 0.3 s: skipped as the live cut did
        (10.3, 10.3),  # the tail reaches the cap, then silence: still a word tail
        (12.0, 10.0),  # still voiced at the cap: likely the next word, resume at the end
    ],
)
def test_offline_resume_skips_a_voiced_tail_only_when_it_ends_in_silence(
    tmp_path: Path, voiced_until: float | None, resume: float
) -> None:
    speech = [(9.0, voiced_until)] if voiced_until else [(9.0, 10.0)]
    old = [_row("mic-000001", 9.0, 10.0)]
    rig = _Rig(
        tmp_path, {Channel.MIC: _track(30, *speech), Channel.SYSTEM: _track(30)}, existing=old
    )

    assert rig.offline.remaining_seconds(rig.session_id) == pytest.approx(30 - resume + 30)
    rig.run()

    mic_feeds = [r for r in rig.audio.reads if r[0] is Channel.MIC and r[2] != 310]  # no probes
    first_mic_feed = mic_feeds[0]
    assert first_mic_feed[1] == round(resume * RATE)


def test_offline_echo_memory_follows_the_timeline_when_the_mic_resumes_far_behind(
    tmp_path: Path,
) -> None:
    # the user was silent while the remote speaker talked: live dropped every mic echo, so the
    # mic resumes at 0 while the system resumes at 50 s, more than SYSTEM_MEMORY_SECONDS later
    old = [
        _row("system-000001", 5.0, 6.0, ECHO),
        _row("system-000002", 20.0, 22.0, "Next item."),
        _row("system-000003", 48.0, 50.0, "That is all."),
    ]
    rig = _Rig(
        tmp_path,
        {Channel.MIC: _track(60, (5.0, 6.0)), Channel.SYSTEM: _track(60)},
        [_said(ECHO, 0.0, 1.0)],  # the mic window [5, 10)
        existing=old,
    )

    rig.run()

    assert rig.stored() == old


def test_offline_resume_skips_a_voiced_tail_that_reaches_the_end_of_the_track(
    tmp_path: Path,
) -> None:
    old = [_row("mic-000001", 9.0, 10.0)]
    rig = _Rig(
        tmp_path,
        {Channel.MIC: _track(10.1, (9.0, 10.1)), Channel.SYSTEM: _track(10.1)},
        existing=old,
    )

    assert rig.offline.remaining_seconds(rig.session_id) == pytest.approx(10.1)  # system only


def _notifying_rig(tmp_path: Path, on_segment: Callable[[TranscriptSegment], None]) -> _Rig:
    rig = _Rig(
        tmp_path,
        {Channel.MIC: _track(10, (1.0, 2.0)), Channel.SYSTEM: _track(10)},
        [_said("Told.", 1.0, 2.0)],
    )
    rig.offline._on_segment = on_segment
    return rig


def test_offline_tells_on_segment_about_every_appended_segment(tmp_path: Path) -> None:
    told: list[TranscriptSegment] = []
    rig = _notifying_rig(tmp_path, told.append)

    rig.run()

    assert [s.text for s in told] == [s.text for s in rig.stored()] == ["Told."]


def test_a_failing_on_segment_is_logged_and_the_segment_still_stored(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(segment: TranscriptSegment) -> None:
        raise RuntimeError("console gone")

    rig = _notifying_rig(tmp_path, broken)

    rig.run()

    assert [s.text for s in rig.stored()] == ["Told."]
    assert "console gone" in caplog.text


def test_a_failing_transcript_write_is_not_swallowed_by_on_segment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _notifying_rig(tmp_path, lambda segment: None)
    real_open = rig.store.open_transcript

    def failing_open(session_id: str, labeler: SpeakerLabeler):  # type: ignore[no-untyped-def]
        sink = real_open(session_id, labeler)

        def broken(segment: TranscriptSegment) -> None:
            raise OSError("disk full")

        sink.emit = broken  # type: ignore[method-assign]
        return sink

    monkeypatch.setattr(rig.store, "open_transcript", failing_open)

    with pytest.raises(OSError, match="disk full"):
        rig.run()
