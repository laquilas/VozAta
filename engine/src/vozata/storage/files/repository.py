"""`FileSessionRepository`: the `SessionRepository` port over session folders (architecture §8).

It wraps `SessionStore` (folders, `session.json`, transcripts, speakers) and adds the files the
other phases write next to them: `transcript.jsonl` / `transcript.md` while recording,
`transcript.translated.jsonl`, `minutes.md` and `action_items.json`. File names and formats are
the ones described in architecture §8.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import Any

from vozata.domain import ActionItem, PartialMinutes, RequestEntry, TranscriptSegment, Translation
from vozata.labels import SpeakerLabeler
from vozata.output.sinks import CompositeSink, JsonlSink, MarkdownSink
from vozata.ports import (
    Recycler,
    SessionNotFoundError,
    StoreRepairError,
    TranscriptSink,
    TranslationWriter,
)
from vozata.storage import action_items, partial_minutes, requests
from vozata.storage.files.layout import SessionPaths
from vozata.storage.files.repair import repair_transcript
from vozata.storage.files.translations import TranslationsFile, read_translations
from vozata.storage.session_range import newest_in_range
from vozata.storage.session_store import SessionStore


class FileSessionRepository:
    """`SessionRepository` (and `RecoverableStore` for the transcript) of the file backend."""

    def __init__(self, store: SessionStore, recycler: Recycler | None = None) -> None:
        """`recycler` takes deleted session folders (phase 36); without one, `delete` fails."""
        self._store = store
        self._recycler = recycler

    @property
    def store(self) -> SessionStore:
        return self._store

    def paths(self, session_id: str) -> SessionPaths:
        """The session's file names (file backend only; not part of the port)."""
        return self._store.paths(session_id)

    def now(self) -> datetime:
        return self._store.now()

    def create(self, started_at: datetime | None = None) -> str:
        return self._store.create(started_at).id

    def discard(self, session_id: str) -> None:
        self._store.discard(session_id)

    def read_meta(self, session_id: str) -> dict[str, Any]:
        return self._store.read_meta(session_id)

    def write_meta(self, session_id: str, meta: dict[str, Any]) -> None:
        self._store.write_meta(session_id, meta)

    def list_sessions(self) -> list[str]:
        return self._store.list_sessions()

    def open_transcript(self, session_id: str, labeler: SpeakerLabeler) -> TranscriptSink:
        """`transcript.jsonl` (fsynced per segment) and the human-readable `transcript.md`."""
        paths = self.paths(session_id)
        jsonl = JsonlSink(paths.transcript_jsonl)
        try:
            markdown = MarkdownSink(paths.transcript_md, labeler)
        except BaseException:
            jsonl.close()
            raise
        return CompositeSink([jsonl, markdown])

    def load_transcript(self, session_id: str) -> list[TranscriptSegment]:
        return self._store.load_transcript(session_id)

    def load_transcript_with_source(self, session_id: str) -> tuple[str, list[TranscriptSegment]]:
        return self._store.load_transcript_with_source(session_id)

    def load_raw_transcript(self, session_id: str) -> list[TranscriptSegment]:
        return self._store.load_raw_transcript(session_id)

    def load_source(self, session_id: str, source: str) -> list[TranscriptSegment]:
        return self._store.load_source(session_id, source)

    def write_diarized(self, session_id: str, segments: Sequence[TranscriptSegment]) -> None:
        self._store.write_diarized(session_id, segments)

    def write_edited(self, session_id: str, segments: Sequence[TranscriptSegment]) -> None:
        self._store.write_edited(session_id, segments)

    def delete_edited(self, session_id: str) -> bool:
        return self._store.delete_edited(session_id)

    def open_translations(self, session_id: str) -> TranslationWriter:
        return TranslationsFile(self.paths(session_id).translated_jsonl)

    def load_translations(self, session_id: str) -> dict[str, Translation]:
        return read_translations(self.paths(session_id).translated_jsonl)

    def speaker_names(self, session_id: str) -> dict[str, str]:
        return self._store.speaker_names(session_id)

    def write_speakers(self, session_id: str, speaker_ids: Sequence[str]) -> None:
        self._store.write_speakers(session_id, speaker_ids)

    def speaker_ids(self, session_id: str) -> list[str]:
        return self._store.speaker_ids(session_id)

    def rename_speakers(self, session_id: str, names: Mapping[str, str | None]) -> None:
        self._store.rename_speakers(session_id, names)

    def read_minutes(self, session_id: str) -> str | None:
        path = self.paths(session_id).minutes_md
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def write_minutes(self, session_id: str, markdown: str) -> None:
        self.paths(session_id).minutes_md.write_text(markdown, encoding="utf-8", newline="\n")

    def has_minutes(self, session_id: str) -> bool:
        return self.paths(session_id).minutes_md.is_file()

    def read_action_items(self, session_id: str) -> list[ActionItem]:
        return action_items.read_action_items(self.paths(session_id))

    def write_action_items(self, session_id: str, items: Sequence[ActionItem]) -> None:
        action_items.write_action_items(self.paths(session_id), items)

    def action_items_lock(self) -> AbstractContextManager[object]:
        return action_items.action_items_lock

    def read_partial_minutes(self, session_id: str) -> list[PartialMinutes]:
        return partial_minutes.read_partial_minutes(self.paths(session_id))

    def write_partial_minutes(self, session_id: str, items: Sequence[PartialMinutes]) -> None:
        partial_minutes.write_partial_minutes(self.paths(session_id), items)

    def read_requests(self, session_id: str) -> list[RequestEntry]:
        return requests.read_requests(self.paths(session_id))

    def write_requests(self, session_id: str, items: Sequence[RequestEntry]) -> None:
        requests.write_requests(self.paths(session_id), items)

    def folder(self, session_id: str) -> Path | None:
        """The folder as configured (relative when `OUTPUT_DIR` is)."""
        return self.paths(session_id).root

    def files(self, session_id: str) -> list[str] | None:
        root = self.paths(session_id).root
        if not root.is_dir():
            raise SessionNotFoundError(session_id)
        return sorted(item.name for item in root.iterdir() if item.is_file())

    def list_range(self, start: datetime, end: datetime) -> list[str]:
        sessions = []
        for session_id in self.list_sessions():
            try:
                meta = self.read_meta(session_id)
            except (SessionNotFoundError, ValueError):  # removed meanwhile, or unreadable
                continue
            sessions.append((session_id, meta.get("started_at")))
        return newest_in_range(sessions, start, end)

    def speaker_count(self, session_id: str) -> int:
        return sum(
            speaker_id.startswith("system:") for speaker_id in self._store.speaker_ids(session_id)
        )

    def delete(self, session_id: str) -> None:
        """Move the session folder to the Recycle Bin (never deleted permanently, phase 36)."""
        root = self.paths(session_id).root
        if not root.is_dir():
            raise SessionNotFoundError(session_id)
        if self._recycler is None:
            raise RuntimeError("no Recycle Bin to move deleted sessions to")
        self._recycler.recycle(root)

    def repair(self, session_id: str) -> float | None:
        """Set aside a half-written last line of `transcript.jsonl` (phase 17)."""
        try:
            repair_transcript(self.paths(session_id).transcript_jsonl)
        except OSError as error:
            raise StoreRepairError(str(error)) from error
        return None
