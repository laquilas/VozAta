from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from vozata.domain import Channel, TranscriptSegment
from vozata.storage.session_store import SessionNotFoundError, SessionStore

BRT = timezone(timedelta(hours=-3))


def _clock(*moments: datetime):
    queue = list(moments)
    return lambda: queue.pop(0) if len(queue) > 1 else queue[0]


def _segment(segment_id: str, channel: Channel, start: float, text: str) -> TranscriptSegment:
    return TranscriptSegment(segment_id, channel, channel.value, start, start + 1, text, ())


def _write_jsonl(path: Path, *segments: TranscriptSegment) -> None:
    lines = [json.dumps(segment.to_dict()) for segment in segments]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_create_makes_a_folder_named_after_the_local_start_time(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "recordings", now=_clock(datetime(2026, 10, 15, 20, 23, 58)))

    paths = store.create()

    assert paths.id == "20261015_202358"
    assert paths.root == tmp_path / "recordings" / "20261015_202358"
    assert paths.root.is_dir()


def test_create_adds_a_suffix_when_the_second_is_taken(tmp_path: Path) -> None:
    moment = datetime(2026, 10, 15, 20, 23, 58)
    store = SessionStore(tmp_path, now=_clock(moment))

    ids = [store.create().id for _ in range(3)]

    assert ids == ["20261015_202358", "20261015_202358_2", "20261015_202358_3"]


def test_paths_name_every_session_file(tmp_path: Path) -> None:
    paths = SessionStore(tmp_path).paths("20261015_202358")
    root = tmp_path / "20261015_202358"

    assert paths.meta == root / "session.json"
    assert paths.wav(Channel.MIC) == root / "mic.wav"
    assert paths.wav(Channel.SYSTEM) == root / "system.wav"
    assert paths.mixed_wav == root / "mixed.wav"
    assert paths.transcript_jsonl == root / "transcript.jsonl"
    assert paths.transcript_md == root / "transcript.md"
    assert paths.minutes_md == root / "minutes.md"
    assert paths.diarized_jsonl == root / "transcript.diarized.jsonl"
    assert paths.edited_jsonl == root / "transcript.edited.jsonl"
    assert paths.speakers_json == root / "speakers.json"


@pytest.mark.parametrize("session_id", ["", "..", "../x", "2026", "20261015_202358/..", "a_b"])
def test_paths_reject_ids_that_are_not_session_ids(tmp_path: Path, session_id: str) -> None:
    with pytest.raises(SessionNotFoundError):
        SessionStore(tmp_path).paths(session_id)


def test_meta_round_trips_as_utf8_json(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    paths = store.create()
    meta = {"id": paths.id, "devices": {"mic": "Microfone (Intel®)"}, "pauses": []}

    store.write_meta(paths.id, meta)

    assert store.read_meta(paths.id) == meta
    assert "Intel®" in paths.meta.read_text(encoding="utf-8")


def test_write_meta_replaces_the_file_without_leaving_temp_files(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    paths = store.create()

    store.write_meta(paths.id, {"status": "recording"})
    store.write_meta(paths.id, {"status": "done"})

    assert store.read_meta(paths.id) == {"status": "done"}
    assert [item.name for item in paths.root.iterdir()] == ["session.json"]


def test_read_meta_of_an_unknown_session_raises(tmp_path: Path) -> None:
    with pytest.raises(SessionNotFoundError):
        SessionStore(tmp_path).read_meta("20261015_202358")


def test_list_sessions_returns_ids_with_metadata_newest_first(tmp_path: Path) -> None:
    store = SessionStore(
        tmp_path,
        now=_clock(datetime(2026, 10, 14, 9, 0, 0), datetime(2026, 10, 15, 9, 0, 0)),
    )
    older, newer = store.create(), store.create()
    store.write_meta(older.id, {})
    store.write_meta(newer.id, {})
    (tmp_path / "20261016_090000").mkdir()  # no session.json: not a session
    (tmp_path / "notes").mkdir()
    (tmp_path / "index.db").write_text("")

    assert store.list_sessions() == [newer.id, older.id]


def test_list_sessions_of_a_missing_output_dir_is_empty(tmp_path: Path) -> None:
    assert SessionStore(tmp_path / "missing").list_sessions() == []


def test_load_transcript_reads_the_raw_transcript(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    paths = store.create()
    segments = [
        _segment("mic-000001", Channel.MIC, 0.0, "Olá"),
        _segment("system-000001", Channel.SYSTEM, 1.0, "Oi"),
    ]
    _write_jsonl(paths.transcript_jsonl, *segments)

    assert store.load_transcript(paths.id) == segments


def test_load_transcript_prefers_edited_then_diarized(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    paths = store.create()
    raw = _segment("mic-000001", Channel.MIC, 0.0, "raw")
    diarized = _segment("mic-000001", Channel.MIC, 0.0, "diarized")
    edited = _segment("mic-000001", Channel.MIC, 0.0, "edited")
    _write_jsonl(paths.transcript_jsonl, raw)
    _write_jsonl(paths.diarized_jsonl, diarized)

    assert store.load_transcript(paths.id) == [diarized]

    _write_jsonl(paths.edited_jsonl, edited)

    assert store.load_transcript(paths.id) == [edited]


def test_load_transcript_skips_blank_lines_and_is_empty_without_files(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    paths = store.create()

    assert store.load_transcript(paths.id) == []

    segment = _segment("mic-000001", Channel.MIC, 0.0, "a")
    paths.transcript_jsonl.write_text(
        "\n" + json.dumps(segment.to_dict()) + "\n\n", encoding="utf-8"
    )

    assert store.load_transcript(paths.id) == [segment]


def test_load_transcript_of_an_unknown_session_raises(tmp_path: Path) -> None:
    with pytest.raises(SessionNotFoundError):
        SessionStore(tmp_path).load_transcript("20261015_202358")


def test_discard_removes_the_session_folder(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    paths = store.create()
    paths.transcript_jsonl.write_text("", encoding="utf-8")

    store.discard(paths.id)

    assert not paths.root.exists()


def test_default_clock_uses_local_time_with_offset(tmp_path: Path) -> None:
    before = datetime.now(UTC)

    stamp = SessionStore(tmp_path).now()

    assert stamp.tzinfo is not None
    assert stamp >= before - timedelta(seconds=1)


def test_injected_clock_is_exposed(tmp_path: Path) -> None:
    moment = datetime(2026, 10, 15, 20, 23, 58, tzinfo=BRT)

    assert SessionStore(tmp_path, now=_clock(moment)).now() == moment


def test_failed_write_meta_keeps_the_old_file_and_removes_the_temp_file(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    paths = store.create()
    store.write_meta(paths.id, {"status": "recording"})

    with pytest.raises(TypeError):
        store.write_meta(paths.id, {"status": object()})

    assert store.read_meta(paths.id) == {"status": "recording"}
    assert [item.name for item in paths.root.iterdir()] == ["session.json"]


def test_create_uses_the_given_start_time(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, now=_clock(datetime(2030, 1, 1)))

    paths = store.create(datetime(2026, 10, 15, 20, 23, 58, tzinfo=BRT))

    assert paths.id == "20261015_202358"


def test_load_transcript_with_source_names_the_file_used(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    paths = store.create()
    segment = _segment("mic-000001", Channel.MIC, 0.0, "a")

    assert store.load_transcript_with_source(paths.id) == ("raw", [])

    _write_jsonl(paths.transcript_jsonl, segment)
    assert store.load_transcript_with_source(paths.id) == ("raw", [segment])
    _write_jsonl(paths.diarized_jsonl, segment)
    assert store.load_transcript_with_source(paths.id)[0] == "diarized"
    _write_jsonl(paths.edited_jsonl, segment)
    assert store.load_transcript_with_source(paths.id)[0] == "edited"


def test_load_raw_transcript_ignores_derived_transcripts(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    paths = store.create()
    assert store.load_raw_transcript(paths.id) == []
    raw = _segment("system-000001", Channel.SYSTEM, 0.0, "raw")
    _write_jsonl(paths.transcript_jsonl, raw)
    _write_jsonl(paths.diarized_jsonl, _segment("system-000001", Channel.SYSTEM, 0.0, "x"))

    assert store.load_raw_transcript(paths.id) == [raw]


def test_write_diarized_is_read_back_first_and_leaves_the_raw_transcript(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    paths = store.create()
    raw = _segment("system-000001", Channel.SYSTEM, 0.0, "Olá")
    _write_jsonl(paths.transcript_jsonl, raw)
    before = paths.transcript_jsonl.read_bytes()
    diarized = TranscriptSegment("system-000001", Channel.SYSTEM, "system:1", 0.0, 1.0, "Olá", ())

    store.write_diarized(paths.id, [diarized])

    assert store.load_transcript_with_source(paths.id) == ("diarized", [diarized])
    assert paths.transcript_jsonl.read_bytes() == before
    assert b"\r\n" not in paths.diarized_jsonl.read_bytes()


def test_write_edited_wins_over_diarized_and_delete_edited_reverts(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    paths = store.create()
    diarized = TranscriptSegment("system-000001", Channel.SYSTEM, "system:1", 0.0, 1.0, "Olá", ())
    store.write_diarized(paths.id, [diarized])
    edited = TranscriptSegment(
        "system-000001", Channel.SYSTEM, "system:1", 0.0, 1.0, "Oi", (), edited=True
    )

    store.write_edited(paths.id, [edited])

    assert store.load_transcript_with_source(paths.id) == ("edited", [edited])
    assert b"\r\n" not in paths.edited_jsonl.read_bytes()
    assert store.delete_edited(paths.id) is True
    assert store.load_transcript_with_source(paths.id) == ("diarized", [diarized])
    assert store.delete_edited(paths.id) is False


def test_speakers_are_written_without_names_and_names_are_read_back(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    paths = store.create()
    assert store.speaker_names(paths.id) == {}

    store.write_speakers(paths.id, ["system:1", "system:2"])

    assert json.loads(paths.speakers_json.read_text(encoding="utf-8")) == {
        "system:1": {"name": None},
        "system:2": {"name": None},
    }
    assert store.speaker_names(paths.id) == {}
    paths.speakers_json.write_text(
        json.dumps({"system:1": {"name": "Ana"}, "system:2": {}, "system:3": "x"}),
        encoding="utf-8",
    )
    assert store.speaker_names(paths.id) == {"system:1": "Ana"}


@pytest.mark.parametrize("content", ["{not json", "[1, 2]"])
def test_unreadable_speakers_files_give_no_names(tmp_path: Path, content: str) -> None:
    store = SessionStore(tmp_path)
    paths = store.create()
    paths.speakers_json.write_text(content, encoding="utf-8")

    assert store.speaker_names(paths.id) == {}


def test_a_failed_replace_removes_the_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    store = SessionStore(tmp_path)
    paths = store.create()

    def fail(source: str, target: object) -> None:
        raise PermissionError("locked by a sync tool")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(PermissionError):
        store.write_speakers(paths.id, ["system:1"])

    assert list(paths.root.iterdir()) == []
