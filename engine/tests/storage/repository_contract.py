"""Contract every `SessionRepository` must honour (phase 30; reused by SQLite in phase 31).

Reuse from a backend's tests by subclassing and providing the `repository` fixture (an empty
repository, one per test):

    class TestSqliteRepository(RepositoryContract):
        @pytest.fixture
        def repository(self, tmp_path: Path) -> SessionRepository:
            return SqliteSessionRepository(...)
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.fakes import FakeLocalizer
from vozata.domain import ActionItem, Channel, TranscriptSegment, Translation, Word
from vozata.labels import SpeakerLabeler
from vozata.ports import (
    SessionNotFoundError,
    SessionRepository,
    TranscriptSink,
    TranslationWriter,
)

STARTED = datetime(2026, 10, 15, 20, 23, 58, tzinfo=timezone(timedelta(hours=-3)))
SESSION_ID = re.compile(r"^\d{8}_\d{6}(_[1-9]\d*)?$")


def segment(segment_id: str, start: float, text: str, speaker_id: str = "mic") -> TranscriptSegment:
    channel = Channel.SYSTEM if speaker_id.startswith("system") else Channel.MIC
    words = (Word(text, start, start + 0.5, 0.9),)
    return TranscriptSegment(segment_id, channel, speaker_id, start, start + 0.5, text, words)


RAW = [segment("mic-000001", 0.1, "Hello."), segment("system-000002", 0.6, "Hi.", "system")]


class RepositoryContract:
    """Behaviour shared by every storage backend; subclasses provide `repository`."""

    @pytest.fixture
    def repository(self) -> SessionRepository:  # pragma: no cover - overridden by subclasses
        raise NotImplementedError

    def _session(self, repository: SessionRepository, started_at: datetime = STARTED) -> str:
        session_id = repository.create(started_at)
        repository.write_meta(session_id, {"id": session_id, "status": "done"})
        return session_id

    # sessions and metadata

    def test_satisfies_the_port(self, repository: SessionRepository) -> None:
        assert isinstance(repository, SessionRepository)
        now = repository.now()
        assert isinstance(now, datetime) and now.tzinfo is not None

    def test_create_names_sessions_after_their_start_and_never_reuses_an_id(
        self, repository: SessionRepository
    ) -> None:
        first = repository.create(STARTED)
        second = repository.create(STARTED)

        assert first == "20261015_202358"
        assert second != first
        assert SESSION_ID.match(second)
        assert SESSION_ID.match(repository.create())

    def test_metadata_round_trips_and_lists_newest_first(
        self, repository: SessionRepository
    ) -> None:
        older = self._session(repository, STARTED)
        newer = self._session(repository, STARTED + timedelta(minutes=5))
        meta = {"id": newer, "status": "recording", "language": "pt", "pauses": [{"start": 1.0}]}

        repository.write_meta(newer, meta)

        assert repository.read_meta(newer) == meta
        assert repository.list_sessions() == [newer, older]

    def test_a_session_without_metadata_is_not_listed_or_readable(
        self, repository: SessionRepository
    ) -> None:
        session_id = repository.create(STARTED)

        assert repository.list_sessions() == []
        with pytest.raises(SessionNotFoundError):
            repository.read_meta(session_id)

    @pytest.mark.parametrize("session_id", ["20991231_000000", "../etc", "nope", ""])
    def test_unknown_or_invalid_ids_are_not_found(
        self, repository: SessionRepository, session_id: str
    ) -> None:
        with pytest.raises(SessionNotFoundError):
            repository.read_meta(session_id)

    def test_discard_removes_the_session(self, repository: SessionRepository) -> None:
        session_id = self._session(repository)

        repository.discard(session_id)

        assert repository.list_sessions() == []
        with pytest.raises(SessionNotFoundError):
            repository.read_meta(session_id)

    # transcripts

    def test_a_live_transcript_is_readable_segment_by_segment(
        self, repository: SessionRepository
    ) -> None:
        session_id = self._session(repository)
        sink = repository.open_transcript(session_id, SpeakerLabeler(FakeLocalizer()))
        assert isinstance(sink, TranscriptSink)

        sink.emit(RAW[0])
        assert repository.load_raw_transcript(session_id) == RAW[:1]  # durable before close
        sink.emit(RAW[1])
        sink.close()

        assert repository.load_raw_transcript(session_id) == RAW
        assert repository.load_transcript_with_source(session_id) == ("raw", RAW)
        assert repository.load_transcript(session_id) == RAW

    def test_a_session_without_transcript_has_an_empty_raw_one(
        self, repository: SessionRepository
    ) -> None:
        session_id = self._session(repository)

        assert repository.load_transcript_with_source(session_id) == ("raw", [])
        assert repository.load_raw_transcript(session_id) == []

    def test_edited_then_diarized_then_raw_is_the_best_transcript(
        self, repository: SessionRepository
    ) -> None:
        session_id = self._session(repository)
        sink = repository.open_transcript(session_id, SpeakerLabeler(FakeLocalizer()))
        for raw in RAW:
            sink.emit(raw)
        sink.close()
        diarized = [RAW[0], segment("system-000002", 0.6, "Hi.", "system:1")]
        corrected = TranscriptSegment(
            "system-000002", Channel.SYSTEM, "system:1", 0.6, 1.1, "Hi there.", (), edited=True
        )
        edited = [RAW[0], corrected]

        repository.write_diarized(session_id, diarized)
        assert repository.load_transcript_with_source(session_id) == ("diarized", diarized)

        repository.write_edited(session_id, edited)
        assert repository.load_transcript_with_source(session_id) == ("edited", edited)

        assert repository.delete_edited(session_id) is True
        assert repository.delete_edited(session_id) is False
        assert repository.load_transcript_with_source(session_id) == ("diarized", diarized)
        assert repository.load_raw_transcript(session_id) == RAW  # never rewritten

    def test_each_transcript_source_is_readable_on_its_own(
        self, repository: SessionRepository
    ) -> None:
        session_id = self._session(repository)
        sink = repository.open_transcript(session_id, SpeakerLabeler(FakeLocalizer()))
        for raw in RAW:
            sink.emit(raw)
        sink.close()
        diarized = [RAW[0], segment("system-000002", 0.6, "Hi.", "system:1")]
        repository.write_diarized(session_id, diarized)
        repository.write_edited(session_id, [RAW[0]])

        assert repository.load_source(session_id, "raw") == RAW
        assert repository.load_source(session_id, "diarized") == diarized  # under the edited one
        assert repository.load_source(session_id, "edited") == [RAW[0]]
        assert repository.load_source(self._session(repository, STARTED + timedelta(1)), "raw") == []
        with pytest.raises(SessionNotFoundError):
            repository.load_source("not-an-id", "raw")

    # translations

    def test_translations_are_stored_by_segment_and_the_last_one_wins(
        self, repository: SessionRepository
    ) -> None:
        session_id = self._session(repository)
        writer = repository.open_translations(session_id)
        assert isinstance(writer, TranslationWriter)
        assert repository.load_translations(session_id) == {}

        writer.append(Translation("mic-000001", "pt", "Olá."))
        writer.append(Translation("system-000002", "pt", "Oi"))
        writer.append(Translation("system-000002", "pt", "Oi."))
        writer.close()

        assert repository.load_translations(session_id) == {
            "mic-000001": Translation("mic-000001", "pt", "Olá."),
            "system-000002": Translation("system-000002", "pt", "Oi."),
        }

    def test_a_translation_writer_closed_unused_stores_nothing(
        self, repository: SessionRepository
    ) -> None:
        session_id = self._session(repository)

        repository.open_translations(session_id).close()

        assert repository.load_translations(session_id) == {}

    # speakers

    def test_speakers_are_written_without_names_then_renamed(
        self, repository: SessionRepository
    ) -> None:
        session_id = self._session(repository)
        assert repository.speaker_names(session_id) == {}

        repository.write_speakers(session_id, ["system:1", "system:2"])
        assert repository.speaker_names(session_id) == {}
        assert repository.speaker_ids(session_id) == ["system:1", "system:2"]

        repository.rename_speakers(session_id, {"system:1": "  Ana ", "mic": "Me"})
        assert repository.speaker_names(session_id) == {"system:1": "Ana", "mic": "Me"}

        repository.rename_speakers(session_id, {"system:1": "  ", "mic": None})
        assert repository.speaker_names(session_id) == {}
        assert repository.speaker_ids(session_id) == ["system:1", "system:2", "mic"]

    def test_the_speaker_count_is_the_speakers_found_by_diarization(
        self, repository: SessionRepository
    ) -> None:
        session_id = self._session(repository)
        assert repository.speaker_count(session_id) == 0

        repository.write_speakers(session_id, ["system:1", "system:2", "system:3"])
        repository.rename_speakers(session_id, {"mic": "Me", "system:2": "Ana"})

        assert repository.speaker_count(session_id) == 3
        with pytest.raises(SessionNotFoundError):
            repository.speaker_count("../etc")

    # minutes

    def test_minutes_are_stored_exactly_as_written(self, repository: SessionRepository) -> None:
        session_id = self._session(repository)
        assert repository.read_minutes(session_id) is None
        assert repository.has_minutes(session_id) is False

        repository.write_minutes(session_id, "# Minutes\n\n- Ação\n")
        assert repository.read_minutes(session_id) == "# Minutes\n\n- Ação\n"
        assert repository.has_minutes(session_id) is True

        repository.write_minutes(session_id, "# Again\n")
        assert repository.read_minutes(session_id) == "# Again\n"

    # action items

    def test_action_items_round_trip_in_order_under_the_lock(
        self, repository: SessionRepository
    ) -> None:
        session_id = self._session(repository)
        items = [
            ActionItem("a2", "Book the room", "Ana", "2026-10-20", ("mic-000001",)),
            ActionItem("a1", "Send the report", exported_url="https://example.test/1"),
        ]
        assert repository.read_action_items(session_id) == []

        with repository.action_items_lock():
            repository.write_action_items(session_id, items)
            assert repository.read_action_items(session_id) == items
        repository.write_action_items(session_id, [])

        assert repository.read_action_items(session_id) == []

    # meeting title (phase 35): a metadata field every backend keeps

    @pytest.mark.parametrize("title", ["Weekly sync", "Reunião — planejamento 2027", None])
    def test_the_title_round_trips_in_the_metadata(
        self, repository: SessionRepository, title: str | None
    ) -> None:
        session_id = self._session(repository)
        meta = {**repository.read_meta(session_id), "title": title}

        repository.write_meta(session_id, meta)

        assert repository.read_meta(session_id)["title"] == title

    def test_a_title_can_change_after_the_session_ended(
        self, repository: SessionRepository
    ) -> None:
        session_id = self._session(repository)
        repository.write_meta(session_id, {"id": session_id, "status": "done", "title": "Draft"})

        renamed = {**repository.read_meta(session_id), "title": "Final"}
        repository.write_meta(session_id, renamed)

        assert repository.read_meta(session_id) == renamed
        assert repository.list_sessions() == [session_id]

    # meetings page (phase 36): a time range, the speaker count and delete

    def _started(self, repository: SessionRepository, started_at: datetime) -> str:
        session_id = repository.create(started_at)
        meta = {"id": session_id, "status": "done", "started_at": started_at.isoformat()}
        repository.write_meta(session_id, meta)
        return session_id

    def test_list_range_keeps_the_sessions_started_in_the_range_newest_first(
        self, repository: SessionRepository
    ) -> None:
        utc = UTC
        before = self._started(repository, datetime(2026, 10, 11, 23, 59, 59, tzinfo=utc))
        first = self._started(repository, datetime(2026, 10, 12, 0, 0, tzinfo=utc))
        middle = self._started(repository, datetime(2026, 10, 14, 9, 30, tzinfo=utc))
        last = self._started(repository, datetime(2026, 10, 18, 23, 59, 59, tzinfo=utc))
        after = self._started(repository, datetime(2026, 10, 19, 0, 0, tzinfo=utc))
        repository.create(datetime(2026, 10, 13, 8, 0, tzinfo=utc))  # no metadata: not listed

        found = repository.list_range(
            datetime(2026, 10, 12, tzinfo=utc), datetime(2026, 10, 19, tzinfo=utc)
        )

        assert found == [last, middle, first]
        assert before not in found and after not in found

    def test_list_range_compares_instants_across_offsets(
        self, repository: SessionRepository
    ) -> None:
        late_evening = datetime(2026, 10, 15, 23, 30, tzinfo=timezone(timedelta(hours=-3)))
        session_id = self._started(repository, late_evening)  # 02:30 on the 16th in UTC
        utc = UTC

        on_the_16th = repository.list_range(
            datetime(2026, 10, 16, tzinfo=utc), datetime(2026, 10, 17, tzinfo=utc)
        )
        on_the_15th = repository.list_range(
            datetime(2026, 10, 15, tzinfo=utc), datetime(2026, 10, 16, tzinfo=utc)
        )

        assert on_the_16th == [session_id]
        assert on_the_15th == []

    def test_list_range_falls_back_to_the_local_time_in_the_id(
        self, repository: SessionRepository
    ) -> None:
        local = datetime(2026, 10, 15, 20, 23, 58).astimezone()
        session_id = repository.create(local)
        repository.write_meta(session_id, {"id": session_id, "status": "interrupted"})

        assert repository.list_range(local, local + timedelta(seconds=1)) == [session_id]
        assert repository.list_range(local + timedelta(seconds=1), local + timedelta(days=1)) == []

    def test_delete_removes_the_session_and_everything_of_it(
        self, repository: SessionRepository
    ) -> None:
        kept = self._session(repository, STARTED + timedelta(hours=1))
        session_id = self._session(repository)
        sink = repository.open_transcript(session_id, SpeakerLabeler(FakeLocalizer()))
        for raw in RAW:
            sink.emit(raw)
        sink.close()
        repository.write_minutes(session_id, "# Minutes\n")
        repository.write_speakers(session_id, ["system:1"])
        repository.write_action_items(session_id, [ActionItem("a1", "Send the deck", None, None)])

        repository.delete(session_id)

        assert repository.list_sessions() == [kept]
        with pytest.raises(SessionNotFoundError):
            repository.read_meta(session_id)
        assert repository.read_meta(kept)["status"] == "done"
        reused = repository.create(STARTED)  # the id is free again
        assert reused == session_id
        assert repository.load_raw_transcript(reused) == []
        assert repository.read_minutes(reused) is None
        assert repository.speaker_count(reused) == 0
        assert repository.read_action_items(reused) == []

    @pytest.mark.parametrize("session_id", ["20991231_000000", "../etc", ""])
    def test_deleting_an_unknown_session_is_not_found(
        self, repository: SessionRepository, session_id: str
    ) -> None:
        with pytest.raises(SessionNotFoundError):
            repository.delete(session_id)

    # file backend extras (optional in the contract)

    def test_folder_and_files_are_both_present_or_both_absent(
        self, repository: SessionRepository
    ) -> None:
        session_id = self._session(repository)

        folder = repository.folder(session_id)
        files = repository.files(session_id)

        if folder is None:
            assert files is None
        else:
            assert isinstance(folder, Path)
            assert files == sorted(files or [])
