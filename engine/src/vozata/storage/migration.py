"""`FolderImporter`: session folders recorded before phase 31 into `vozata.db` (phase 33).

Each folder of `OUTPUT_DIR` with a `session.json` and no imported row is copied in one
transaction: metadata, the raw, diarized and edited transcripts, translations, speakers, minutes,
action items and the mic / system audio (the mix is computed on read). The folder keeps its name
as the session id and is never changed, except the phase 17 repair of an interrupted recording
(its row is then `interrupted`, so the recovery prompt offers it). A folder that cannot be read
is recorded in `migration_errors` and skipped. A folder of a phase 31 SQLite session (its WAVs
only, no `session.json`) gets its audio imported into the existing row.
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from vozata.domain import Channel, SessionStatus
from vozata.ports import StoreRepairError
from vozata.storage.files.audio import FileAudioStore
from vozata.storage.files.layout import SESSION_ID, SessionPaths
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.folder_reader import FolderError, read_content, read_meta, wav_blocks
from vozata.storage.sqlite.audio import SqliteAudioStore
from vozata.storage.sqlite.repository import SqliteSessionRepository

SPACE_MARGIN = 1.1  # free space needed: the folder's size x this
_INTERRUPTED = {status.value for status in SessionStatus if status is not SessionStatus.DONE}


class NotEnoughSpaceError(RuntimeError):
    """The database's disk has less free space than the next folder needs."""

    def __init__(self, folder: str, needed: int, free: int) -> None:
        super().__init__(f"{folder} needs {needed} bytes; {free} free")
        self.folder, self.needed, self.free = folder, needed, free


@dataclass(frozen=True)
class MigrationError:
    folder: str
    reason: str
    detail: str


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _free_space(path: Path) -> int:
    path.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(path).free


class FolderImporter:
    """Imports one folder at a time (`pending` then `import_one`); idempotent."""

    def __init__(
        self,
        output_dir: Path,
        files: FileSessionRepository,
        file_audio: FileAudioStore,
        repository: SqliteSessionRepository,
        audio: SqliteAudioStore,
        sample_rate: int,
        free_space: Callable[[Path], int] = _free_space,
        now: Callable[[], datetime] = _local_now,
    ) -> None:
        self._root = output_dir
        self._files = files
        self._file_audio = file_audio
        self._repo = repository
        self._db = repository.database
        self._audio = audio
        self._rate = sample_rate
        self._free_space = free_space
        self._now = now

    def pending(self) -> list[str]:
        """Folders still to import, oldest first."""
        root = self._root
        if not root.is_dir():
            return []
        rows = self._db.connection().execute("SELECT id, imported_from FROM sessions").fetchall()
        known = dict(rows)
        failed = {
            r[0] for r in self._db.connection().execute("SELECT folder FROM migration_errors")
        }
        found = []
        for item in root.iterdir():
            if not SESSION_ID.match(item.name) or str(item) in failed or not item.is_dir():
                continue
            if (item / "session.json").is_file():
                if item.name not in known:
                    found.append(item.name)
            elif item.name in known and known[item.name] is None and self._audio_only(item):
                found.append(item.name)
        return sorted(found)

    def folder_size(self, session_id: str) -> int:
        root = self._files.paths(session_id).root
        return sum(item.stat().st_size for item in root.iterdir() if item.is_file())

    def import_one(self, session_id: str) -> MigrationError | None:
        """Import a folder; a folder that cannot be read is recorded and returned.

        Raises `NotEnoughSpaceError` (nothing is written) when the disk is short of space.
        """
        paths = self._files.paths(session_id)
        needed = round(self.folder_size(session_id) * SPACE_MARGIN)
        free = self._free_space(self._db.path.parent)
        if free < needed:
            raise NotEnoughSpaceError(str(paths.root), needed, free)
        try:
            if paths.meta.is_file():
                self._import_session(paths)
            else:
                self._import_audio_only(paths)
        except FolderError as error:
            return self._record(paths, error.reason, error.detail)
        except sqlite3.IntegrityError as error:
            return self._record(paths, "id_in_use", str(error))
        return None

    def errors(self) -> list[MigrationError]:
        rows = self._db.connection().execute(
            "SELECT folder, reason, detail FROM migration_errors ORDER BY folder"
        )
        return [MigrationError(*row) for row in rows]

    def _import_session(self, paths: SessionPaths) -> None:
        session_id = paths.id
        meta = read_meta(self._files, session_id)
        if meta.get("status") in _INTERRUPTED:
            meta = self._repair(session_id, meta)
        data = read_content(self._files, paths)
        with self._db.write() as db:
            if db.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone():
                raise sqlite3.IntegrityError(f"session {session_id} already exists")
            self._repo.write_meta(session_id, meta)
            for source, segments in data.segments.items():
                if segments:
                    self._repo.replace_segments(session_id, source, segments)
            translations = self._repo.open_translations(session_id)
            for translation in data.translations.values():
                translations.append(translation)
            self._repo.write_speakers(session_id, data.speakers)
            self._repo.rename_speakers(session_id, data.names)
            if data.minutes is not None:
                self._repo.write_minutes(session_id, *data.minutes)
            self._repo.write_action_items(session_id, data.action_items)
            self._import_audio(paths)
            self._mark_imported(db, paths)

    def _import_audio_only(self, paths: SessionPaths) -> None:
        with self._db.write() as db:
            self._import_audio(paths)
            self._mark_imported(db, paths)

    def _repair(self, session_id: str, meta: dict[str, Any]) -> dict[str, Any]:
        """Phase 17 repairs of an interrupted folder (WAV headers, a half-written last line)."""
        try:
            seconds = self._file_audio.repair(session_id)
            self._files.repair(session_id)
        except StoreRepairError as error:
            raise FolderError("unreadable_wav", str(error)) from error
        repaired = {**meta, "status": SessionStatus.INTERRUPTED.value}
        if seconds is not None and repaired.get("duration_seconds") is None:
            repaired["duration_seconds"] = seconds
        return repaired

    def _import_audio(self, paths: SessionPaths) -> None:
        """mic and system WAVs into chunks (a missing WAV is no audio), then equal lengths."""
        for channel in Channel:
            path = paths.wav(channel)
            if path.is_file():
                self._audio.import_pcm(paths.id, channel, self._blocks(path))
        self._audio.repair(paths.id)

    def _blocks(self, path: Path) -> Iterator[bytes]:
        return wav_blocks(path, self._rate)

    def _audio_only(self, root: Path) -> bool:
        """A phase 31 SQLite session's folder: WAVs and a row without audio."""
        if not any((root / f"{channel.value}.wav").is_file() for channel in Channel):
            return False
        row = (
            self._db.connection()
            .execute("SELECT 1 FROM audio_chunks WHERE session_id = ? LIMIT 1", (root.name,))
            .fetchone()
        )
        return row is None

    def _mark_imported(self, db: sqlite3.Connection, paths: SessionPaths) -> None:
        db.execute(
            "UPDATE sessions SET imported_from = ?, imported_at = ? WHERE id = ?",
            (str(paths.root), self._now().isoformat(timespec="seconds"), paths.id),
        )

    def _record(self, paths: SessionPaths, reason: str, detail: str) -> MigrationError:
        error = MigrationError(str(paths.root), reason, detail)
        with self._db.write() as db:
            db.execute(
                "INSERT OR REPLACE INTO migration_errors (folder, reason, detail, at)"
                " VALUES (?, ?, ?, ?)",
                (error.folder, reason, detail, self._now().isoformat(timespec="seconds")),
            )
        return error
