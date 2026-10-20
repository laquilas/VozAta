"""`FileBundleImporter`: a meeting ZIP into `OUTPUT_DIR` as a session folder (phase 39)."""

from __future__ import annotations

import shutil
from pathlib import Path

from vozata.domain import Channel, ImportedSession
from vozata.ports import AudioMixer
from vozata.storage.bundle_import import BundleError, SessionExistsError
from vozata.storage.files.audio import FileAudioStore
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.folder_reader import FolderError, read_meta
from vozata.storage.session_store import SessionStore

_WAVS = tuple(f"{channel.value}.wav" for channel in Channel)


class FileBundleImporter:
    """`BundleImporter`: the folder is moved into `OUTPUT_DIR`, or only its WAVs into a kept
    folder that has none; `mixed.wav` is then written by `mixer`."""

    def __init__(
        self, repository: FileSessionRepository, audio: FileAudioStore, mixer: AudioMixer
    ) -> None:
        self._repo = repository
        self._audio = audio
        self._mixer = mixer

    def import_folder(self, folder: Path) -> ImportedSession:
        session_id = folder.name
        try:
            read_meta(FileSessionRepository(SessionStore(folder.parent)), session_id)
        except FolderError as error:
            raise BundleError(f"{error.reason}: {error.detail}") from error
        target = self._repo.paths(session_id).root
        has_wavs = any((folder / name).is_file() for name in _WAVS)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(folder, target)
            mode = "imported"
        elif not has_wavs or any((target / name).is_file() for name in _WAVS):
            raise SessionExistsError(session_id)
        else:
            for name in (*_WAVS, "mixed.wav"):
                if (folder / name).is_file():
                    shutil.move(folder / name, target / name)
            mode = "audio_restored"
        if has_wavs:
            self._audio.write_mix(session_id, self._mixer)
        return ImportedSession(session_id, mode)
