"""The audio sources of a recorded meeting (phase 66): list them, choose others, trim them.

A new choice rewrites the meeting's channels with the chosen sources (`remix`), drops its
transcripts and queues its usual job again (transcript, mix, speakers, minutes), under the rule
of `DELETE /sessions/{id}`: a meeting being recorded, queued or processed is refused.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Protocol

from vozata.api.errors import ApiError
from vozata.api.session_manager import SessionManager
from vozata.domain import SessionStatus
from vozata.ports import PcmImport, SessionRepository, TranscriptReset
from vozata.processing.source_remix import UnknownSourceError, remix
from vozata.storage.source_archive import SourceArchive


class Reprocess(Protocol):
    def reprocess(self, session_id: str, prepare: Any) -> None: ...


class SessionSources:
    def __init__(
        self,
        archive: SourceArchive,
        store: SessionRepository,
        audio: PcmImport,
        manager: SessionManager | Reprocess,
        sample_rate: int,
        keep_days: int,
    ) -> None:
        self.archive = archive
        self._store = store
        self._audio = audio
        self._manager = manager
        self._rate = sample_rate
        self._keep_days = keep_days

    def describe(self, session_id: str) -> dict[str, Any]:
        """`{items, kept_until}`: `[]` for a meeting recorded with one device per channel."""
        self._store.read_meta(session_id)  # SessionNotFoundError → 404
        kept = self.archive.kept_at(session_id)
        until = (
            (kept + timedelta(days=self._keep_days)).isoformat(timespec="seconds")
            if kept is not None and self._keep_days > 0
            else None
        )
        return {
            "items": [
                {
                    "id": source.source_id,
                    "kind": source.kind.value,
                    "name": source.name,
                    "selected": source.selected,
                    "preferred": source.preferred,
                    "duration_seconds": round(source.frames / self._rate, 3),
                }
                for source in self.archive.list(session_id)
            ],
            "kept_until": until,
        }

    def apply(self, session_id: str, selected: set[str]) -> None:
        """Remix with `selected` and queue the meeting again; `404 sources_not_kept`,
        `422 unknown_source` / `no_source_selected`, `409 session_still_active`."""
        self._store.read_meta(session_id)
        if not self.archive.has(session_id):
            raise ApiError(404, "sources_not_kept", id=session_id)
        if not selected:
            raise ApiError(422, "no_source_selected")
        known = {source.source_id for source in self.archive.list(session_id)}
        unknown = selected - known
        if unknown:
            raise ApiError(422, "unknown_source", id=", ".join(sorted(unknown)))

        def prepare(target: str) -> None:
            try:
                remix(self.archive, self._audio, target, selected, self._rate)
            except UnknownSourceError as error:  # pragma: no cover - checked above
                raise ApiError(422, "unknown_source", id=str(error)) from None
            if isinstance(self._store, TranscriptReset):
                self._store.reset_transcript(target)
            meta = self._store.read_meta(target)
            meta["status"] = SessionStatus.FINALIZING.value  # a restart queues it again (40)
            self._store.write_meta(target, meta)

        self._manager.reprocess(session_id, prepare)

    def keep_only_selected(self, session_id: str) -> list[str]:
        self._store.read_meta(session_id)
        if not self.archive.has(session_id):
            raise ApiError(404, "sources_not_kept", id=session_id)
        return self.archive.keep_only_selected(session_id)

    def frames(self, session_id: str, source_id: str) -> tuple[bytes, int]:
        """One source as 16-bit PCM bytes and its sample rate (`404 source_not_found`)."""
        self._store.read_meta(session_id)
        try:
            items = {s.source_id: s for s in self.archive.list(session_id)}
            source = items[source_id]
            samples = self.archive.frames(session_id, source_id, 0, source.frames)
        except (KeyError, ValueError):
            raise ApiError(404, "source_not_found", id=source_id) from None
        return samples.tobytes(), self._rate

    def prune(self) -> list[str]:
        return self.archive.prune(self._keep_days)

    def remove(self, session_id: str) -> None:
        self.archive.remove(session_id)
