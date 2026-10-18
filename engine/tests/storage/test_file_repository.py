"""The file backend (phase 30): the shared contracts plus its file names and formats."""

from __future__ import annotations

import json
import wave
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest

from tests.fakes import FakeAudioMixer, FakeLocalizer, FakeRecycler
from tests.storage.audio_contract import RATE, AudioStoreContract
from tests.storage.repository_contract import RAW, STARTED, RepositoryContract
from vozata.domain import ActionItem, AudioTrack, Channel, Translation
from vozata.labels import SpeakerLabeler
from vozata.ports import (
    RecoverableStore,
    SessionAudio,
    SessionNotFoundError,
    SessionRepository,
    StoreRepairError,
)
from vozata.storage import action_items
from vozata.storage.files.audio import FileAudioStore
from vozata.storage.files.folder import open_session_folder
from vozata.storage.files.recycle_bin import Send2TrashRecycler
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.session_store import SessionStore


def _repository(tmp_path: Path) -> FileSessionRepository:
    recycler = FakeRecycler(tmp_path / "recycle-bin")
    return FileSessionRepository(SessionStore(tmp_path / "recordings"), recycler)


class TestFileSessionRepository(RepositoryContract):
    @pytest.fixture
    def repository(self, tmp_path: Path) -> SessionRepository:
        return _repository(tmp_path)


class TestFileAudioStore(AudioStoreContract):
    @pytest.fixture
    def audio(self, tmp_path: Path) -> SessionAudio:
        return FileAudioStore(SessionStore(tmp_path / "recordings"), RATE)

    @pytest.fixture
    def session_id(self, tmp_path: Path) -> str:
        return _repository(tmp_path).create(STARTED)

    def test_the_mix_is_written_by_the_mixer_to_mixed_wav(
        self, audio: SessionAudio, session_id: str
    ) -> None:
        mixer = FakeAudioMixer()

        audio.write_mix(session_id, mixer)

        [(reader, mixed_id, destination)] = mixer.calls
        assert reader is audio
        assert mixed_id == session_id
        assert destination == audio.materialize_wav(session_id, AudioTrack.MIXED)
        assert destination.name == "mixed.wav"

    def test_delete_leaves_the_wavs_to_the_repository(
        self, audio: SessionAudio, session_id: str
    ) -> None:
        wav = audio.materialize_wav(session_id, AudioTrack.MIC)
        wav.write_bytes(b"RIFF")

        audio.delete(session_id)

        assert wav.exists()  # the folder goes to the Recycle Bin with the session (phase 36)

    def test_a_wav_that_is_not_16_bit_is_refused_as_a_track(
        self, audio: SessionAudio, session_id: str
    ) -> None:
        path = audio.materialize_wav(session_id, AudioTrack.MIC)
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(1)
            wav.setframerate(RATE)
            wav.writeframes(bytes(4))

        with pytest.raises(ValueError, match="16-bit"):
            audio.track(session_id, AudioTrack.MIC)


# FileSessionRepository: the files of architecture §8


def test_the_live_transcript_goes_to_jsonl_and_markdown(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    session_id = repository.create(STARTED)

    sink = repository.open_transcript(session_id, SpeakerLabeler(FakeLocalizer()))
    sink.emit(RAW[0])
    sink.close()

    paths = repository.paths(session_id)
    assert json.loads(paths.transcript_jsonl.read_text(encoding="utf-8")) == RAW[0].to_dict()
    assert paths.transcript_md.read_text(encoding="utf-8") == "[00:00:00] labels.mic: Hello.\n"


def test_a_transcript_that_cannot_open_its_markdown_closes_the_jsonl(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    session_id = repository.create(STARTED)
    repository.paths(session_id).transcript_md.mkdir()  # a folder where the file should be

    with pytest.raises(OSError):
        repository.open_transcript(session_id, SpeakerLabeler(FakeLocalizer()))

    repository.paths(session_id).transcript_jsonl.unlink()  # not held open (Windows)


def test_translations_minutes_and_action_items_use_their_files(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    session_id = repository.create(STARTED)
    paths = repository.paths(session_id)

    writer = repository.open_translations(session_id)
    assert not paths.translated_jsonl.exists()  # nothing until the first translation
    writer.append(Translation("mic-000001", "pt", "Olá."))
    writer.close()
    repository.write_minutes(session_id, "# Minutes\n")
    repository.write_action_items(session_id, [ActionItem("a1", "Call Bob")])

    assert json.loads(paths.translated_jsonl.read_text(encoding="utf-8"))["text"] == "Olá."
    assert paths.minutes_md.read_bytes() == b"# Minutes\n"
    assert action_items.read_action_items(paths) == [ActionItem("a1", "Call Bob")]
    assert repository.action_items_lock() is action_items.action_items_lock


def test_folder_is_the_configured_path_and_files_lists_it(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    session_id = repository.create(STARTED)
    repository.write_meta(session_id, {"id": session_id})
    repository.write_minutes(session_id, "# M\n")

    assert repository.folder(session_id) == tmp_path / "recordings" / session_id
    assert repository.files(session_id) == ["minutes.md", "session.json"]
    with pytest.raises(SessionNotFoundError):
        repository.files("20991231_000000")


def test_repair_sets_aside_a_cut_transcript_line(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    session_id = repository.create(STARTED)
    paths = repository.paths(session_id)
    paths.transcript_jsonl.write_text(
        json.dumps(RAW[0].to_dict()) + '\n{"segment_id": "sys', encoding="utf-8"
    )

    assert isinstance(repository, RecoverableStore)
    assert repository.repair(session_id) is None
    assert repository.load_raw_transcript(session_id) == RAW[:1]
    assert paths.root.joinpath("transcript.jsonl.damaged").is_file()


def test_a_transcript_that_cannot_be_repaired_raises_a_repair_error(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    session_id = repository.create(STARTED)
    paths = repository.paths(session_id)
    paths.transcript_jsonl.write_text('{"segment_id": "sys', encoding="utf-8")
    paths.root.joinpath("transcript.jsonl.damaged").mkdir()  # the side file cannot be written

    with pytest.raises(StoreRepairError):
        repository.repair(session_id)


# FileAudioStore


def _wav(path: Path, samples: list[int], channels: int = 1) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(np.array(samples, dtype=np.int16).tobytes())


def _audio(tmp_path: Path) -> tuple[FileAudioStore, FileSessionRepository, str]:
    repository = _repository(tmp_path)
    return FileAudioStore(repository.store, RATE), repository, repository.create(STARTED)


def test_tracks_are_the_session_wavs(tmp_path: Path) -> None:
    audio, repository, session_id = _audio(tmp_path)
    paths = repository.paths(session_id)
    _wav(paths.wav(Channel.SYSTEM), [1, 2, 3])

    assert audio.materialize_wav(session_id, Channel.SYSTEM) == paths.wav(Channel.SYSTEM)
    assert audio.frames(session_id, Channel.SYSTEM, -5, 2).tolist() == [1, 2]
    assert audio.frames(session_id, Channel.SYSTEM, 9, 2).tolist() == []


def test_the_mix_goes_to_mixed_wav(tmp_path: Path) -> None:
    audio, repository, session_id = _audio(tmp_path)
    calls: list[tuple[object, str, Path]] = []

    class _Mixer:
        def mix(self, reader: object, mixed_id: str, destination: Path) -> None:
            calls.append((reader, mixed_id, destination))

    audio.write_mix(session_id, _Mixer())

    assert calls == [(audio, session_id, repository.paths(session_id).mixed_wav)]


def test_a_track_that_is_not_mono_16_bit_is_refused(tmp_path: Path) -> None:
    audio, repository, session_id = _audio(tmp_path)
    _wav(repository.paths(session_id).wav(Channel.MIC), [1, 2, 3, 4], channels=2)

    with pytest.raises(ValueError, match="mono 16-bit"):
        audio.length(session_id, Channel.MIC)


def test_repair_fixes_and_pads_both_wavs(tmp_path: Path) -> None:
    audio, repository, session_id = _audio(tmp_path)
    paths = repository.paths(session_id)
    _wav(paths.wav(Channel.MIC), [5] * (RATE // 2))  # system.wav never written

    assert isinstance(audio, RecoverableStore)
    assert audio.repair(session_id) == 0.5
    assert audio.length(session_id, Channel.SYSTEM) == RATE // 2


def test_an_unrepairable_wav_raises_a_repair_error_and_is_kept(tmp_path: Path) -> None:
    audio, repository, session_id = _audio(tmp_path)
    mic = repository.paths(session_id).wav(Channel.MIC)
    mic.write_bytes(b"not a wav at all")

    with pytest.raises(StoreRepairError, match="RIFF"):
        audio.repair(session_id)
    assert mic.read_bytes() == b"not a wav at all"


def test_a_session_folder_on_the_command_line_opens_its_parent(tmp_path: Path) -> None:
    session_id = _repository(tmp_path).create(STARTED)

    folder = open_session_folder(tmp_path / "recordings" / session_id, RATE)

    assert folder.session_id == session_id
    assert folder.path == (tmp_path / "recordings" / session_id).resolve()
    assert folder.minutes_file == folder.path / "minutes.md"
    assert folder.diarized_file == folder.path / "transcript.diarized.jsonl"
    assert folder.audio.materialize_wav(session_id, Channel.MIC) == folder.path / "mic.wav"


# Delete (phase 36): the folder goes to the Recycle Bin, never deleted permanently


def test_delete_moves_the_session_folder_to_the_recycle_bin(tmp_path: Path) -> None:
    recycler = FakeRecycler(tmp_path / "recycle-bin")
    repository = FileSessionRepository(SessionStore(tmp_path / "recordings"), recycler)
    session_id = repository.create(STARTED)
    repository.write_meta(session_id, {"id": session_id, "status": "done"})
    folder = repository.paths(session_id).root

    repository.delete(session_id)

    assert recycler.recycled == [folder]
    assert not folder.exists()
    assert (tmp_path / "recycle-bin" / f"0-{session_id}" / "session.json").is_file()


def test_delete_without_a_recycle_bin_keeps_the_folder(tmp_path: Path) -> None:
    repository = FileSessionRepository(SessionStore(tmp_path / "recordings"))
    session_id = repository.create(STARTED)

    with pytest.raises(RuntimeError, match="Recycle Bin"):
        repository.delete(session_id)
    assert repository.paths(session_id).root.is_dir()


def test_a_recycle_bin_failure_keeps_the_folder(tmp_path: Path) -> None:
    recycler = FakeRecycler(tmp_path / "recycle-bin")
    recycler.error = PermissionError("in use")
    repository = FileSessionRepository(SessionStore(tmp_path / "recordings"), recycler)
    session_id = repository.create(STARTED)

    with pytest.raises(PermissionError):
        repository.delete(session_id)
    assert repository.paths(session_id).root.is_dir()


def test_list_range_skips_unreadable_metadata(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    broken = repository.create(STARTED)
    repository.paths(broken).meta.write_text("{not json", encoding="utf-8")
    good = repository.create(STARTED + timedelta(minutes=1))
    repository.write_meta(good, {"id": good, "started_at": STARTED.isoformat()})

    found = repository.list_range(STARTED - timedelta(days=1), STARTED + timedelta(days=1))

    assert found == [good]


def test_the_send2trash_recycler_sends_the_absolute_path(tmp_path: Path) -> None:
    sent: list[str] = []
    folder = tmp_path / "20261015_202358"
    folder.mkdir()

    Send2TrashRecycler(sent.append).recycle(folder)

    assert sent == [str(folder.resolve())]
    assert folder.is_dir()  # the fake did not move it: no real Recycle Bin in unit tests
