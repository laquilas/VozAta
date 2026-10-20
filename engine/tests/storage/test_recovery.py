from __future__ import annotations

import json
import wave
from datetime import timedelta
from pathlib import Path

import pytest

from tests.session_folders import SEGMENTS, make_session_folder, write_wav
from tests.test_session import ENDED, STARTED
from vozata.domain import Channel
from vozata.ports import RecoverableStore, SessionNotFoundError, StoreRepairError
from vozata.storage.files.audio import FileAudioStore
from vozata.storage.files.repair import repair_transcript
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.recovery import SessionRecovery, find_interrupted
from vozata.storage.session_store import SessionStore

RATE = 16000


def _store(tmp_path: Path) -> FileSessionRepository:
    return FileSessionRepository(SessionStore(tmp_path / "recordings", now=lambda: ENDED))


def _repairs(store: FileSessionRepository) -> list[RecoverableStore]:
    return [FileAudioStore(store.store, RATE), store]


def _status(store: FileSessionRepository, session_id: str) -> str:
    return store.read_meta(session_id)["status"]


def _frames(path: Path) -> int:
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes()


def _break_header(path: Path, cut_bytes: int = 0) -> None:
    """What a crash leaves: data size still 0, maybe the tail never written."""
    with path.open("r+b") as file:
        file.seek(40)
        file.write(b"\x00\x00\x00\x00")
        if cut_bytes:
            file.truncate(file.seek(0, 2) - cut_bytes)


def _recovery(store: FileSessionRepository) -> SessionRecovery:
    return SessionRecovery(store, _repairs(store))


# find_interrupted


@pytest.mark.parametrize("status", ["recording", "paused", "finalizing"])
def test_an_active_session_nobody_runs_is_marked_interrupted(tmp_path: Path, status: str) -> None:
    store = _store(tmp_path)
    session_id = make_session_folder(store, status=status)

    assert find_interrupted(store) == [session_id]
    meta = store.read_meta(session_id)
    assert meta["status"] == "interrupted"
    assert meta["vocabulary"] == ["Avalonia"]  # nothing else changes


def test_finalizing_without_capture_ended_is_still_interrupted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session_id = make_session_folder(store, status="finalizing")  # crashed during capture

    assert find_interrupted(store) == [session_id]
    assert _status(store, session_id) == "interrupted"


@pytest.mark.parametrize("stale_after", [0.0, 25.0])
def test_finalizing_with_capture_ended_is_requeued_not_interrupted(
    tmp_path: Path, stale_after: float
) -> None:
    store = _store(tmp_path)
    # the heartbeat stopped at capture end, so another process's `recover --all` sees it stale
    stopped = make_session_folder(
        store,
        status="finalizing",
        capture_ended_at=(ENDED - timedelta(minutes=5)).isoformat(),
        last_heartbeat_at=(ENDED - timedelta(minutes=10)).isoformat(),
    )

    assert find_interrupted(store, stale_after=stale_after) == []
    assert _status(store, stopped) == "finalizing"


def test_a_failed_repair_with_capture_ended_is_still_listed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session_id = make_session_folder(
        store, status="interrupted", capture_ended_at=ENDED.isoformat()
    )

    assert find_interrupted(store) == [session_id]


def test_done_sessions_are_left_alone_and_interrupted_ones_are_listed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    done = make_session_folder(store, status="done")
    interrupted = make_session_folder(store, status="interrupted")

    assert find_interrupted(store) == [interrupted]
    assert _status(store, done) == "done"


def test_a_live_session_of_this_process_is_not_interrupted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    live = make_session_folder(store, status="recording")

    assert find_interrupted(store, live_ids={live}) == []
    assert _status(store, live) == "recording"


def test_with_stale_after_a_recent_heartbeat_is_left_for_its_process(tmp_path: Path) -> None:
    store = _store(tmp_path)
    fresh = make_session_folder(
        store, status="recording", last_heartbeat_at=(ENDED - timedelta(seconds=5)).isoformat()
    )
    old = make_session_folder(
        store, status="recording", last_heartbeat_at=(ENDED - timedelta(seconds=60)).isoformat()
    )
    no_beat = make_session_folder(store, status="paused")  # falls back to started_at (6 min ago)
    broken = make_session_folder(store, status="recording", last_heartbeat_at="yesterday")

    found = find_interrupted(store, stale_after=25)

    assert sorted(found) == sorted([old, no_beat, broken])
    assert _status(store, fresh) == "recording"


def test_an_unreadable_session_json_is_skipped(tmp_path: Path) -> None:
    store = _store(tmp_path)
    good = make_session_folder(store, status="recording")
    bad = store.paths(store.create(STARTED + timedelta(seconds=1)))
    bad.meta.write_text("{not json", encoding="utf-8")

    assert find_interrupted(store) == [good]


# file repair


def test_unequal_wavs_with_stale_headers_are_repaired_and_padded(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session_id = make_session_folder(store, mic_seconds=1.0, system_seconds=0.5)
    paths = store.paths(session_id)
    _break_header(paths.wav(Channel.MIC), cut_bytes=RATE // 2)  # the last 0.25 s never landed
    _break_header(paths.wav(Channel.SYSTEM))

    duration = FileAudioStore(store.store, RATE).repair(session_id)

    assert duration == 0.75
    assert _frames(paths.wav(Channel.MIC)) == _frames(paths.wav(Channel.SYSTEM)) == RATE * 3 // 4


def test_a_cut_last_transcript_line_is_set_aside(tmp_path: Path) -> None:
    path = tmp_path / "transcript.jsonl"
    good = "".join(json.dumps(segment.to_dict()) + "\n" for segment in SEGMENTS)
    path.write_text(good + '{"segment_id": "mic-0000', encoding="utf-8")

    assert repair_transcript(path) == 1
    assert path.read_text(encoding="utf-8") == good
    assert (tmp_path / "transcript.jsonl.damaged").read_text(encoding="utf-8") == (
        '{"segment_id": "mic-0000\n'
    )
    assert repair_transcript(path) == 0  # idempotent


def test_a_missing_or_intact_transcript_is_untouched(tmp_path: Path) -> None:
    path = tmp_path / "transcript.jsonl"
    assert repair_transcript(path) == 0
    path.write_text(json.dumps(SEGMENTS[0].to_dict()) + "\n\n", encoding="utf-8")
    before = path.read_bytes()

    assert repair_transcript(path) == 0
    assert path.read_bytes() == before
    assert not (tmp_path / "transcript.jsonl.damaged").exists()


# SessionRecovery (the processing job finishes the meeting, phase 40)


def test_is_interrupted_and_is_resumable_read_the_status(tmp_path: Path) -> None:
    store = _store(tmp_path)
    recording = make_session_folder(store, status="recording")
    interrupted = make_session_folder(store, status="interrupted")
    stopped = make_session_folder(store, status="finalizing", capture_ended_at=ENDED.isoformat())
    recovery = _recovery(store)

    assert (recovery.is_interrupted(recording), recovery.is_interrupted(interrupted)) == (
        False,
        True,
    )
    assert (recovery.is_resumable(interrupted), recovery.is_resumable(stopped)) == (False, True)
    with pytest.raises(SessionNotFoundError):
        recovery.is_interrupted("20990101_000000")


def test_find_interrupted_uses_the_configured_staleness(tmp_path: Path) -> None:
    store = _store(tmp_path)
    fresh = make_session_folder(store, status="recording", last_heartbeat_at=ENDED.isoformat())

    assert SessionRecovery(store, _repairs(store), stale_after=30).find_interrupted() == []
    assert _recovery(store).find_interrupted() == [fresh]
    assert _recovery(store).store is store


def test_repair_fixes_a_crashed_folder_and_returns_the_longest_length(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session_id = make_session_folder(store, status="recording", mic_seconds=0.5)
    paths = store.paths(session_id)
    _break_header(paths.wav(Channel.SYSTEM))
    with paths.transcript_jsonl.open("a", encoding="utf-8") as file:
        file.write('{"segment_id": "system-00')

    assert _recovery(store).repair(session_id) == 1.0

    assert _frames(paths.wav(Channel.MIC)) == _frames(paths.wav(Channel.SYSTEM)) == RATE
    assert [s.segment_id for s in store.load_transcript(session_id)] == [
        "mic-000001",
        "system-000002",
    ]


def test_a_failed_repair_raises_and_never_deletes_data(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session_id = make_session_folder(store)
    mic = store.paths(session_id).wav(Channel.MIC)
    mic.write_bytes(b"not a wav at all")

    with pytest.raises(StoreRepairError, match="RIFF"):
        _recovery(store).repair(session_id)

    assert mic.read_bytes() == b"not a wav at all"
    write_wav(mic, 1.0)  # the user fixed the file by hand: a retry works
    assert _recovery(store).repair(session_id) == 1.0


def test_fail_stores_the_reason_and_marks_the_session_interrupted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session_id = make_session_folder(store, status="finalizing")

    _recovery(store).fail(session_id, "bad header")

    meta = store.read_meta(session_id)
    assert (meta["status"], meta["recovery_error"]) == ("interrupted", "bad header")
