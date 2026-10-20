from __future__ import annotations

import io
from pathlib import Path

import pytest

from tests.fakes import FakeLocalizer, FakeTranscriber
from tests.test_session_recover import make_session_folder
from vozata import bootstrap, bootstrap_processing
from vozata.cli.console import ConsoleObserver
from vozata.cli.recover import run_recover
from vozata.config import Settings
from vozata.domain import Channel, StorageBackend
from vozata.labels import SpeakerLabeler
from vozata.ports import SessionObserver
from vozata.storage.files.audio import FileAudioStore
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.recovery import SessionRecovery
from vozata.storage.session_store import SessionStore


class _Finisher:
    def __init__(self) -> None:
        self.recovered: list[str] = []

    def build(self, store: FileSessionRepository):  # type: ignore[no-untyped-def]
        def session(session_id: str, observer: SessionObserver) -> _Finisher:
            self.store = store
            return self

        return session

    def recover(self, session_id: str, duration_seconds: float) -> None:
        self.recovered.append(session_id)
        self.store.write_meta(session_id, {**self.store.read_meta(session_id), "status": "done"})


def _repository(root: Path) -> FileSessionRepository:
    return FileSessionRepository(SessionStore(root))


def _run(
    session_dir: Path | None, default_store: FileSessionRepository
) -> tuple[int, str, _Finisher]:
    out = io.StringIO()
    localizer = FakeLocalizer()
    console = ConsoleObserver(localizer, SpeakerLabeler(localizer), out)
    finisher = _Finisher()
    built: list[Path | None] = []

    def build(output_dir: Path | None) -> SessionRecovery:
        built.append(output_dir)
        chosen = _repository(output_dir) if output_dir is not None else default_store
        repairs = [FileAudioStore(chosen.store, 16000), chosen]
        return SessionRecovery(chosen, repairs, finisher.build(chosen))

    code = run_recover(session_dir, build, console, localizer)
    return code, out.getvalue(), finisher


def test_all_recovers_every_interrupted_session(tmp_path: Path) -> None:
    store = _repository(tmp_path / "recordings")
    first = make_session_folder(store, status="recording")
    second = make_session_folder(store, status="interrupted")
    make_session_folder(store, status="done")

    code, out, finisher = _run(None, store)

    assert code == 0
    assert sorted(finisher.recovered) == sorted([first, second])
    assert f"cli.recovering(id={second})" in out
    assert f"cli.recovered(folder={store.paths(first).root})" in out


def test_all_with_nothing_to_recover_says_so(tmp_path: Path) -> None:
    code, out, _ = _run(None, _repository(tmp_path / "recordings"))

    assert (code, out) == (0, "cli.recover_none\n")


def test_one_folder_is_recovered_with_its_parent_as_the_store(tmp_path: Path) -> None:
    store = _repository(tmp_path / "elsewhere")
    session_id = make_session_folder(store, status="paused")
    other = make_session_folder(store, status="interrupted")

    code, _, finisher = _run(store.paths(session_id).root, _repository(tmp_path / "unused"))

    assert code == 0
    assert finisher.recovered == [session_id]  # only the folder asked for
    assert store.read_meta(other)["status"] == "interrupted"


def test_a_folder_that_is_not_interrupted_or_not_a_session_fails(tmp_path: Path) -> None:
    store = _repository(tmp_path / "recordings")
    done = make_session_folder(store, status="done")
    unused = _repository(tmp_path / "unused")

    code, out, _ = _run(store.paths(done).root, unused)
    assert code == 1
    assert out.startswith("cli.recover_not_interrupted(folder=")

    code, out, _ = _run(tmp_path / "20990101_000000", unused)
    assert code == 1
    assert out.startswith("cli.session_not_found(folder=")


def test_a_failed_repair_is_reported_and_the_exit_code_is_1(tmp_path: Path) -> None:
    store = _repository(tmp_path / "recordings")
    broken = make_session_folder(store, status="interrupted")
    store.paths(broken).wav(Channel.MIC).write_bytes(b"garbage")

    code, out, finisher = _run(None, store)

    assert code == 1
    assert finisher.recovered == []
    assert f"cli.recover_failed(id={broken},reason=" in out


def _resume(folder: Path, settings: Settings, localizer: FakeLocalizer) -> tuple[int, str]:
    out = io.StringIO()
    console = ConsoleObserver(localizer, SpeakerLabeler(localizer), out)
    store = _repository(folder.parent)

    def build(output_dir: Path | None) -> SessionRecovery:
        return SessionRecovery(store, [FileAudioStore(store.store, 16000), store], lambda i, o: 1)  # type: ignore[arg-type, return-value]

    code = run_recover(
        folder,
        build,
        console,
        localizer,
        lambda output_dir, session_id, observer: bootstrap_processing.build_resume_job(
            settings, output_dir, session_id, observer
        ),
    )
    return code, out.getvalue()


def test_a_folder_left_finalizing_by_a_crashed_record_is_finished_with_the_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(bootstrap.TRANSCRIBERS, "fake", lambda settings: FakeTranscriber())
    settings = Settings(
        output_dir=tmp_path / "recordings",
        storage_backend=StorageBackend.FILES,
        stt_provider="fake",
        generate_minutes=False,
    )
    store = _repository(tmp_path / "recordings")
    session_id = make_session_folder(
        store, status="finalizing", capture_ended_at="2026-10-15T20:30:00-03:00"
    )
    all_ids = _run(None, store)  # `--all` leaves it to serve / `recover <dir>`
    assert all_ids[1] == "cli.recover_none\n"

    code, out = _resume(store.paths(session_id).root, settings, FakeLocalizer())

    assert code == 0
    assert out.startswith(f"cli.recovering(id={session_id})")
    meta = store.read_meta(session_id)
    assert (meta["status"], meta["ended_at"] is not None) == ("done", True)


def test_a_finalizing_folder_whose_repair_fails_is_reported(tmp_path: Path) -> None:
    settings = Settings(output_dir=tmp_path / "recordings", storage_backend=StorageBackend.FILES)
    store = _repository(tmp_path / "recordings")
    session_id = make_session_folder(
        store, status="finalizing", capture_ended_at="2026-10-15T20:30:00-03:00"
    )
    store.paths(session_id).wav(Channel.MIC).write_bytes(b"garbage")

    code, out = _resume(store.paths(session_id).root, settings, FakeLocalizer())

    assert code == 1
    assert f"cli.recover_failed(id={session_id},reason=" in out
    assert store.read_meta(session_id)["status"] == "interrupted"
