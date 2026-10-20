from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest

from tests.fakes import FakeAudioReader, FakeLocalizer, FakeRecycler, FakeTranscriber
from vozata.cli.console import ConsoleObserver
from vozata.cli.transcribe import run_transcribe
from vozata.config import Settings
from vozata.domain import (
    Channel,
    ConversationLanguage,
    TranscriptionResult,
    TranscriptSegment,
    Word,
)
from vozata.labels import SpeakerLabeler
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.session_folder import SessionFolder
from vozata.storage.session_store import SessionStore
from vozata.transcription.language_lock import LanguageLock
from vozata.transcription.offline import OfflineTranscription

RATE = 1000
TONE = 3277


def _settings() -> Settings:
    return Settings(sample_rate=RATE, chunk_seconds=5.0)


def _said(text: str, start: float, end: float) -> TranscriptionResult:
    tokens = text.split()
    step = (end - start) / len(tokens)
    words = tuple(
        Word(f" {token}", start + i * step, start + (i + 1) * step, 0.9)
        for i, token in enumerate(tokens)
    )
    return TranscriptionResult(words=words, language="en")


class _Rig:
    def __init__(self, tmp_path: Path, status: str = "done", seconds: int = 30) -> None:
        mic = np.zeros(seconds * RATE, dtype=np.int16)
        mic[1000:2000] = TONE
        self.repository = FileSessionRepository(
            SessionStore(tmp_path / "recordings"), FakeRecycler(tmp_path / "bin")
        )
        self.id = self.repository.create()
        self.repository.write_meta(self.id, {"id": self.id, "status": status})
        audio = FakeAudioReader(
            {Channel.MIC: mic, Channel.SYSTEM: np.zeros_like(mic)},
            {Channel.MIC: RATE, Channel.SYSTEM: RATE},
        )
        path = tmp_path / "recordings" / self.id
        self.folder = SessionFolder(path, self.repository, audio, path, path)  # type: ignore[arg-type]
        self.transcriber = FakeTranscriber([_said("Hello there.", 1.0, 2.0)])
        self.opened: list[Path] = []
        self.out = io.StringIO()
        self.localizer = FakeLocalizer()
        self.console = ConsoleObserver(self.localizer, SpeakerLabeler(self.localizer), self.out)

    def _build(self, settings, folder, on_segment):  # type: ignore[no-untyped-def]
        return OfflineTranscription(
            settings,
            folder.repository,
            folder.audio,
            lambda: self.transcriber,
            SpeakerLabeler(self.localizer),
            LanguageLock(ConversationLanguage.EN, lambda language: None),
            None,
            None,
            on_segment=on_segment,
        )

    def _open(self, path: Path) -> SessionFolder:
        self.opened.append(path)
        return self.folder

    def run(self, target: str | None = None) -> int:
        return run_transcribe(
            target or self.id, _settings(), self.console, self.localizer, self._build, self._open
        )

    def lines(self) -> list[str]:
        return self.out.getvalue().splitlines()


def test_transcribe_writes_the_missing_segments_and_reports_progress(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)

    code = rig.run()

    assert code == 0
    assert [s.text for s in rig.repository.load_raw_transcript(rig.id)] == ["Hello there."]
    lines = rig.lines()
    percents = [int(line.split("percent=")[1].rstrip(")")) for line in lines[:-1]]
    assert percents == sorted(set(percents)) and percents[-1] == 100
    assert all(p % 10 == 0 for p in percents)
    assert lines[-1] == "cli.transcribe_done(count=1)"


def test_transcribe_of_a_fully_transcribed_meeting_adds_nothing(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, seconds=10)
    words = (Word("Done.", 8.0, 9.5, 0.9),)
    sink = rig.repository.open_transcript(rig.id, SpeakerLabeler(rig.localizer))
    sink.emit(TranscriptSegment("mic-000001", Channel.MIC, "mic", 8.0, 9.5, "Done.", words))
    sink.close()

    code = rig.run()

    assert code == 0
    assert len(rig.repository.load_raw_transcript(rig.id)) == 1
    assert rig.lines()[-1] == "cli.transcribe_done(count=0)"
    assert rig.transcriber.calls == []


@pytest.mark.parametrize("status", ["recording", "paused", "finalizing"])
def test_transcribe_refuses_a_busy_session(tmp_path: Path, status: str) -> None:
    rig = _Rig(tmp_path, status=status)

    assert rig.run() == 1
    assert rig.lines() == ["cli.transcribe_busy"]
    assert rig.repository.load_raw_transcript(rig.id) == []


def test_transcribe_refuses_an_unknown_session(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    rig.folder = SessionFolder(
        tmp_path / "recordings" / "nope", rig.repository, rig.folder.audio, tmp_path, tmp_path
    )

    assert rig.run("nope") == 1
    assert rig.lines() == [f"cli.session_not_found(folder={rig.folder.path})"]


def test_transcribe_reports_a_failing_transcription(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)

    def failing(settings, folder, on_segment):  # type: ignore[no-untyped-def]
        raise RuntimeError("model missing")

    code = run_transcribe(rig.id, _settings(), rig.console, rig.localizer, failing, rig._open)

    assert code == 1
    assert rig.lines() == ["cli.transcribe_failed(reason=model missing)"]


def test_a_bare_id_is_looked_up_in_the_output_dir_and_a_path_is_kept(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)

    rig.run("20261015_202358")
    rig.run(str(tmp_path / "elsewhere" / "20261015_202358"))

    assert rig.opened == [
        Path("recordings") / "20261015_202358",
        tmp_path / "elsewhere" / "20261015_202358",
    ]
