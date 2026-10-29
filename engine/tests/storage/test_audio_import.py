"""`AudioFileImporter` (phase 60): an audio file as a new meeting, ready for the queue."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from tests.storage.test_migration import RATE, Rig
from vozata.audio.mixer import MonoMixer
from vozata.config import Settings
from vozata.domain import AudioTrack, Channel, ConversationLanguage
from vozata.ports import AudioDecodeError
from vozata.storage.audio_import import AudioFileImporter

NOW = datetime(2026, 10, 29, 10, 0, 0)
RECORDED = datetime(2026, 10, 20, 15, 30, 0)
SETTINGS = Settings(transcription_language=ConversationLanguage.AUTO, minutes_template="general")


@dataclass
class FakeDecoder:
    """`AudioDecoder` over fixed samples; `estimate` is the container's announced duration."""

    samples: np.ndarray
    estimate: float | None = None
    fail_after: int | None = None  # raise after this many blocks
    block: int = RATE // 2

    def duration(self, path: Path) -> float | None:
        return self.estimate

    def blocks(self, path: Path) -> Iterator[bytes]:
        for index, start in enumerate(range(0, len(self.samples), self.block)):
            if self.fail_after is not None and index >= self.fail_after:
                raise AudioDecodeError("corrupt frame")
            yield self.samples[start : start + self.block].astype("<i2").tobytes()


def _tone(seconds: float) -> np.ndarray:
    return (np.arange(round(seconds * RATE)) % 200 + 1).astype(np.int16)


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    rig = Rig(tmp_path)
    yield rig
    rig.database.close()


@pytest.fixture(params=["sqlite", "files"])
def backend(request: pytest.FixtureRequest, rig: Rig):  # type: ignore[no-untyped-def]
    if request.param == "sqlite":
        return rig.repo, rig.audio
    return rig.files, rig.file_audio


def _importer(backend, decoder: FakeDecoder, settings: Settings = SETTINGS) -> AudioFileImporter:  # type: ignore[no-untyped-def]
    repository, audio = backend
    return AudioFileImporter(
        repository,
        audio,
        decoder,
        lambda: settings,
        MonoMixer(),
        vocabulary=lambda: ("VozAta",),
        now=lambda: NOW,
    )


def test_the_file_becomes_the_system_track_and_the_mic_is_silence(backend, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    repository, audio = backend
    samples = _tone(2.25)

    session_id = _importer(backend, FakeDecoder(samples)).import_file(
        tmp_path / "weekly.mp3", "weekly.mp3", None
    )

    assert audio.frames(session_id, Channel.SYSTEM, 0, len(samples)).tolist() == samples.tolist()
    assert audio.length(session_id, Channel.MIC) == len(samples)
    assert not audio.frames(session_id, Channel.MIC, 0, len(samples)).any()
    assert audio.track(session_id, AudioTrack.MIXED) is not None


def test_the_meta_is_ready_for_the_processing_queue(backend, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    repository, _audio = backend

    session_id = _importer(backend, FakeDecoder(_tone(2.0))).import_file(
        tmp_path / "x.m4a", "Board meeting.m4a", None
    )

    meta = repository.read_meta(session_id)
    assert meta["status"] == "finalizing"
    assert meta["title"] == "Board meeting"
    assert meta["duration_seconds"] == 2.0
    assert meta["capture_ended_at"] == NOW.isoformat(timespec="seconds")
    assert meta["started_at"] == (NOW - timedelta(seconds=2)).isoformat(timespec="seconds")
    assert meta["live_transcription"] is False
    assert meta["template"] == "general"
    assert meta["vocabulary"] == ["VozAta"]
    assert meta["devices"] == {}
    assert meta["source"] == "imported_audio"
    assert meta["imported_file"] == "Board meeting.m4a"
    assert "language" not in meta  # auto: detected by the transcription
    assert repository.list_sessions() == [session_id]


def test_the_meeting_ends_at_the_files_time(backend, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    repository, _audio = backend
    decoder = FakeDecoder(_tone(3.0), estimate=3.0)

    session_id = _importer(backend, decoder).import_file(tmp_path / "a.wav", "a.wav", RECORDED)

    assert session_id == "20261020_152957"  # named after the start: 3 s before the file time
    meta = repository.read_meta(session_id)
    assert meta["started_at"] == "2026-10-20T15:29:57"


def test_a_fixed_language_is_kept_as_selected(backend, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    repository, _audio = backend
    settings = Settings(transcription_language=ConversationLanguage.PT)

    session_id = _importer(backend, FakeDecoder(_tone(1.0)), settings).import_file(
        tmp_path / "a.wav", "a.wav", None
    )

    meta = repository.read_meta(session_id)
    assert (meta["language"], meta["language_source"]) == ("pt", "selected")


def test_an_empty_file_is_refused_and_leaves_nothing(backend, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    repository, _audio = backend

    with pytest.raises(AudioDecodeError, match="audio_empty"):
        _importer(backend, FakeDecoder(_tone(0))).import_file(tmp_path / "a.wav", "a.wav", None)

    assert repository.list_sessions() == []


def test_a_decoding_error_leaves_nothing(backend, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    repository, _audio = backend
    decoder = FakeDecoder(_tone(3.0), fail_after=2)

    with pytest.raises(AudioDecodeError, match="corrupt"):
        _importer(backend, decoder).import_file(tmp_path / "a.wav", "a.wav", None)

    assert repository.list_sessions() == []
    assert repository.create(NOW) == NOW.strftime("%Y%m%d_%H%M%S")  # the id was given back


def test_the_title_drops_any_folder_the_client_sent(backend, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    repository, _audio = backend

    session_id = _importer(backend, FakeDecoder(_tone(1.0))).import_file(
        tmp_path / "a", r"C:\Users\me\Calls\  Sprint   review .webm", None
    )

    assert repository.read_meta(session_id)["title"] == "Sprint review"


def test_a_cleanup_that_fails_is_logged_and_the_error_kept(
    rig: Rig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def refuse(session_id: str) -> None:
        raise OSError("locked by OneDrive")

    monkeypatch.setattr(rig.files, "discard", refuse)

    with pytest.raises(AudioDecodeError, match="audio_empty"):
        _importer((rig.files, rig.file_audio), FakeDecoder(_tone(0))).import_file(
            tmp_path / "a.wav", "a.wav", None
        )

    assert "half-imported" in caplog.text
