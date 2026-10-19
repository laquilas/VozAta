"""The `BundleImporter`s of phase 39: a meeting folder into the database or into `OUTPUT_DIR`."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.fakes import FakeLocalizer
from tests.storage.test_migration import RATE, Rig
from vozata.audio.mixer import MonoMixer
from vozata.domain import AudioTrack, Channel, ImportedSession
from vozata.labels import SpeakerLabeler
from vozata.storage.bundle_import import BundleError, SessionExistsError
from vozata.storage.files.audio import FileAudioStore
from vozata.storage.files.bundle_import import FileBundleImporter
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.folder_writer import write_folder
from vozata.storage.session_store import SessionStore
from vozata.storage.sqlite.bundle_import import SqliteBundleImporter


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    rig = Rig(tmp_path / "library")
    yield rig
    rig.database.close()


def _bundle_folder(tmp_path: Path, mic: float = 1.0, system: float = 1.0) -> Path:
    """An unpacked meeting ZIP: a session folder alone in its own directory."""
    source = Rig(tmp_path / "bundle")
    session_id = source.folder(mic=mic, system=system)
    source.database.close()
    return source.files.paths(session_id).root


def _sqlite(rig: Rig) -> SqliteBundleImporter:
    return SqliteBundleImporter(rig.repo, rig.audio, RATE, free_space=lambda _path: 1 << 40)


def _length(rig: Rig, session_id: str) -> int:
    return rig.audio.length(session_id, Channel.MIC)


# SQLite


def test_a_new_session_is_imported_with_its_audio(rig: Rig, tmp_path: Path) -> None:
    folder = _bundle_folder(tmp_path, mic=1.5, system=1.0)

    result = _sqlite(rig).import_folder(folder)

    assert result == ImportedSession(folder.name, "imported")
    assert rig.repo.read_meta(folder.name)["title"] == "Weekly sync"
    assert _length(rig, folder.name) == round(1.5 * RATE)
    assert rig.importer.errors() == []


def test_the_audio_comes_back_to_a_session_whose_audio_was_deleted(
    rig: Rig, tmp_path: Path
) -> None:
    session_id = rig.folder(mic=2.0)
    assert rig.import_all() == [None]
    labeler = SpeakerLabeler(FakeLocalizer())
    folder = write_folder(rig.repo, rig.audio, session_id, tmp_path / "unpacked", labeler)
    rig.audio.discard(session_id)
    rig.repo.write_meta(session_id, {**rig.repo.read_meta(session_id), "title": "Renamed"})

    result = _sqlite(rig).import_folder(folder)

    assert result == ImportedSession(session_id, "audio_restored")
    assert _length(rig, session_id) == round(2.0 * RATE)
    assert rig.repo.read_meta(session_id)["title"] == "Renamed"  # the row is kept as it is


def test_a_session_that_still_has_its_audio_is_refused(rig: Rig, tmp_path: Path) -> None:
    session_id = rig.folder()
    assert rig.import_all() == [None]
    labeler = SpeakerLabeler(FakeLocalizer())
    folder = write_folder(rig.repo, rig.audio, session_id, tmp_path / "unpacked", labeler)

    with pytest.raises(SessionExistsError):
        _sqlite(rig).import_folder(folder)
    assert (folder / "session.json").is_file()


def test_a_kept_session_and_a_bundle_without_audio_is_refused(rig: Rig, tmp_path: Path) -> None:
    session_id = rig.folder(mic=0, system=0)
    assert rig.import_all() == [None]
    labeler = SpeakerLabeler(FakeLocalizer())
    folder = write_folder(rig.repo, rig.audio, session_id, tmp_path / "unpacked", labeler)

    with pytest.raises(SessionExistsError):
        _sqlite(rig).import_folder(folder)


def test_an_unreadable_folder_is_refused_and_not_listed_as_a_migration_error(
    rig: Rig, tmp_path: Path
) -> None:
    folder = _bundle_folder(tmp_path)
    (folder / "session.json").write_text("{", encoding="utf-8")

    with pytest.raises(BundleError, match="unreadable_json"):
        _sqlite(rig).import_folder(folder)
    assert rig.importer.errors() == []
    assert rig.repo.list_sessions() == []


def test_the_default_free_space_reads_the_disk(rig: Rig, tmp_path: Path) -> None:
    folder = _bundle_folder(tmp_path)

    result = SqliteBundleImporter(rig.repo, rig.audio, RATE).import_folder(folder)

    assert result.mode == "imported"


# Files


@pytest.fixture
def library(tmp_path: Path) -> FileSessionRepository:
    return FileSessionRepository(SessionStore(tmp_path / "recordings"))


def _files(library: FileSessionRepository) -> FileBundleImporter:
    return FileBundleImporter(library, FileAudioStore(library.store, RATE), MonoMixer())


def test_a_new_folder_is_moved_into_the_output_folder_with_its_mix(
    library: FileSessionRepository, tmp_path: Path
) -> None:
    folder = _bundle_folder(tmp_path)

    result = _files(library).import_folder(folder)

    assert result == ImportedSession(folder.name, "imported")
    assert not folder.exists()
    assert library.read_meta(folder.name)["title"] == "Weekly sync"
    audio = FileAudioStore(library.store, RATE)
    assert audio.track(folder.name, AudioTrack.MIXED) is not None


def test_the_wavs_come_back_to_a_kept_folder_without_audio(
    library: FileSessionRepository, tmp_path: Path
) -> None:
    folder = _bundle_folder(tmp_path)
    kept = library.paths(folder.name).root
    kept.mkdir(parents=True)
    (kept / "session.json").write_text('{"title": "Kept"}', encoding="utf-8")

    result = _files(library).import_folder(folder)

    assert result == ImportedSession(folder.name, "audio_restored")
    assert sorted(path.name for path in kept.iterdir()) == [
        "mic.wav",
        "mixed.wav",
        "session.json",
        "system.wav",
    ]
    assert library.read_meta(folder.name) == {"title": "Kept"}


def test_a_kept_folder_with_audio_is_refused(
    library: FileSessionRepository, tmp_path: Path
) -> None:
    folder = _bundle_folder(tmp_path)
    kept = library.paths(folder.name).root
    kept.mkdir(parents=True)
    (kept / "mic.wav").write_bytes(b"RIFF")

    with pytest.raises(SessionExistsError):
        _files(library).import_folder(folder)
    assert (folder / "mic.wav").is_file()


def test_a_folder_with_unreadable_metadata_is_refused(
    library: FileSessionRepository, tmp_path: Path
) -> None:
    folder = _bundle_folder(tmp_path)
    (folder / "session.json").write_text("[]", encoding="utf-8")

    with pytest.raises(BundleError, match="unreadable_json"):
        _files(library).import_folder(folder)
    assert not library.paths(folder.name).root.exists()
