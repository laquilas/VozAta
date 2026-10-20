from __future__ import annotations

import io
from pathlib import Path

import pytest

from tests.fakes import FakeLocalizer, FakeTranscriber
from tests.session_folders import make_session_folder, write_wav
from vozata import bootstrap, bootstrap_processing
from vozata.cli.console import ConsoleObserver
from vozata.cli.recover import run_recover
from vozata.config import Settings
from vozata.domain import Channel, StorageBackend
from vozata.labels import SpeakerLabeler
from vozata.ports import SessionObserver
from vozata.processing.job import ProcessingJob
from vozata.storage.files.audio import FileAudioStore
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.recovery import SessionRecovery
from vozata.storage.session_store import SessionStore


def _repository(root: Path) -> FileSessionRepository:
    return FileSessionRepository(SessionStore(root))


@pytest.fixture(autouse=True)
def _fake_speech(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(bootstrap.TRANSCRIBERS, "fake", lambda settings: FakeTranscriber())


def _settings(output_dir: Path) -> Settings:
    return Settings(
        output_dir=output_dir,
        storage_backend=StorageBackend.FILES,
        stt_provider="fake",
        generate_minutes=False,
        chunk_mode="fixed",
        chunk_seconds=1.0,
    )


def _run(session_dir: Path | None, default_dir: Path) -> tuple[int, str]:
    """`recover` over the real processing job (repair, transcribe the rest, stop steps)."""
    out = io.StringIO()
    localizer = FakeLocalizer()
    console = ConsoleObserver(localizer, SpeakerLabeler(localizer), out)

    def build(output_dir: Path | None) -> SessionRecovery:
        chosen = _repository(output_dir or default_dir)
        return SessionRecovery(chosen, [FileAudioStore(chosen.store, 16000), chosen])

    def resume(
        output_dir: Path | None, session_id: str, observer: SessionObserver
    ) -> ProcessingJob:
        settings = _settings(output_dir or default_dir)
        return bootstrap_processing.build_resume_job(settings, output_dir, session_id, observer)

    code = run_recover(session_dir, build, console, localizer, resume)
    return code, out.getvalue()


def _done(store: FileSessionRepository, session_id: str) -> bool:
    meta = store.read_meta(session_id)
    return meta["status"] == "done" and meta["ended_at"] is not None


def test_all_recovers_every_interrupted_session_through_the_job(tmp_path: Path) -> None:
    store = _repository(tmp_path / "recordings")
    first = make_session_folder(store, status="recording")
    second = make_session_folder(store, status="interrupted")
    done = make_session_folder(store, status="done")

    code, out = _run(None, tmp_path / "recordings")

    assert code == 0
    assert _done(store, first) and _done(store, second)
    assert store.read_meta(done)["ended_at"] is None  # never touched
    assert f"cli.recovering(id={second})" in out
    assert f"cli.recovered(folder={store.paths(first).root})" in out
    assert store.read_meta(first)["capture_ended_at"]  # the repair step made it finalizing


def test_an_interrupted_meeting_gets_the_rest_transcribed_from_its_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transcriber = FakeTranscriber()
    monkeypatch.setitem(bootstrap.TRANSCRIBERS, "fake", lambda settings: transcriber)
    store = _repository(tmp_path / "recordings")
    session_id = make_session_folder(
        store, status="interrupted", segments=[], mic_seconds=3.0, system_seconds=3.0
    )
    write_wav(store.paths(session_id).wav(Channel.SYSTEM), 3.0, level=0)  # no echo to drop

    code, _ = _run(store.paths(session_id).root, tmp_path / "unused")

    assert code == 0
    assert transcriber.calls  # the rest came from the stored audio (the old path skipped it)
    assert _done(store, session_id)


def test_all_with_nothing_to_recover_says_so(tmp_path: Path) -> None:
    code, out = _run(None, tmp_path / "recordings")

    assert (code, out) == (0, "cli.recover_none\n")


def test_one_folder_is_recovered_with_its_parent_as_the_store(tmp_path: Path) -> None:
    store = _repository(tmp_path / "elsewhere")
    session_id = make_session_folder(store, status="paused")
    other = make_session_folder(store, status="interrupted")

    code, _ = _run(store.paths(session_id).root, tmp_path / "unused")

    assert code == 0
    assert _done(store, session_id)
    assert store.read_meta(other)["status"] == "interrupted"  # only the folder asked for


def test_a_folder_that_is_not_interrupted_or_not_a_session_fails(tmp_path: Path) -> None:
    store = _repository(tmp_path / "recordings")
    done = make_session_folder(store, status="done")
    unused = tmp_path / "unused"

    code, out = _run(store.paths(done).root, unused)
    assert code == 1
    assert out.startswith("cli.recover_not_interrupted(folder=")

    code, out = _run(tmp_path / "20990101_000000", unused)
    assert code == 1
    assert out.startswith("cli.session_not_found(folder=")


def test_a_failed_repair_is_reported_and_the_exit_code_is_1(tmp_path: Path) -> None:
    store = _repository(tmp_path / "recordings")
    broken = make_session_folder(store, status="interrupted")
    store.paths(broken).wav(Channel.MIC).write_bytes(b"garbage")

    code, out = _run(None, tmp_path / "recordings")

    assert code == 1
    assert f"cli.recover_failed(id={broken},reason=" in out
    meta = store.read_meta(broken)
    assert (meta["status"], bool(meta["recovery_error"])) == ("interrupted", True)


def test_a_folder_left_finalizing_by_a_crashed_record_is_finished_with_the_job(
    tmp_path: Path,
) -> None:
    store = _repository(tmp_path / "recordings")
    session_id = make_session_folder(
        store, status="finalizing", capture_ended_at="2026-10-15T20:30:00-03:00"
    )
    all_ids = _run(None, tmp_path / "recordings")  # `--all` leaves it to serve / `recover <dir>`
    assert all_ids[1] == "cli.recover_none\n"

    code, out = _run(store.paths(session_id).root, tmp_path / "unused")

    assert code == 0
    assert out.startswith(f"cli.recovering(id={session_id})")
    assert _done(store, session_id)


def test_a_finalizing_folder_whose_repair_fails_is_reported(tmp_path: Path) -> None:
    store = _repository(tmp_path / "recordings")
    session_id = make_session_folder(
        store, status="finalizing", capture_ended_at="2026-10-15T20:30:00-03:00"
    )
    store.paths(session_id).wav(Channel.MIC).write_bytes(b"garbage")

    code, out = _run(store.paths(session_id).root, tmp_path / "unused")

    assert code == 1
    assert f"cli.recover_failed(id={session_id},reason=" in out
    assert store.read_meta(session_id)["status"] == "interrupted"
