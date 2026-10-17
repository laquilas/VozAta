from __future__ import annotations

import io
from pathlib import Path

from tests.fakes import FakeLocalizer
from tests.test_session_recover import make_session_folder
from vozata.cli.console import ConsoleObserver
from vozata.cli.recover import run_recover
from vozata.domain import Channel
from vozata.labels import SpeakerLabeler
from vozata.ports import SessionObserver
from vozata.storage.recovery import SessionRecovery
from vozata.storage.session_store import SessionStore


class _Finisher:
    def __init__(self) -> None:
        self.recovered: list[str] = []

    def build(self, store: SessionStore):  # type: ignore[no-untyped-def]
        def session(session_id: str, observer: SessionObserver) -> _Finisher:
            self.store = store
            return self

        return session

    def recover(self, session_id: str, duration_seconds: float) -> None:
        self.recovered.append(session_id)
        self.store.write_meta(session_id, {**self.store.read_meta(session_id), "status": "done"})


def _run(session_dir: Path | None, default_store: SessionStore) -> tuple[int, str, _Finisher]:
    out = io.StringIO()
    localizer = FakeLocalizer()
    console = ConsoleObserver(localizer, SpeakerLabeler(localizer), out)
    finisher = _Finisher()
    built: list[SessionStore | None] = []

    def build(store: SessionStore | None) -> SessionRecovery:
        built.append(store)
        chosen = store or default_store
        return SessionRecovery(chosen, 16000, finisher.build(chosen))

    code = run_recover(session_dir, build, console, localizer)
    return code, out.getvalue(), finisher


def test_all_recovers_every_interrupted_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "recordings")
    first = make_session_folder(store, status="recording")
    second = make_session_folder(store, status="interrupted")
    make_session_folder(store, status="done")

    code, out, finisher = _run(None, store)

    assert code == 0
    assert sorted(finisher.recovered) == sorted([first, second])
    assert f"cli.recovering(id={second})" in out
    assert f"cli.recovered(folder={store.paths(first).root})" in out


def test_all_with_nothing_to_recover_says_so(tmp_path: Path) -> None:
    code, out, _ = _run(None, SessionStore(tmp_path / "recordings"))

    assert (code, out) == (0, "cli.recover_none\n")


def test_one_folder_is_recovered_with_its_parent_as_the_store(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "elsewhere")
    session_id = make_session_folder(store, status="paused")
    other = make_session_folder(store, status="interrupted")

    code, _, finisher = _run(store.paths(session_id).root, SessionStore(tmp_path / "unused"))

    assert code == 0
    assert finisher.recovered == [session_id]  # only the folder asked for
    assert store.read_meta(other)["status"] == "interrupted"


def test_a_folder_that_is_not_interrupted_or_not_a_session_fails(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "recordings")
    done = make_session_folder(store, status="done")
    unused = SessionStore(tmp_path / "unused")

    code, out, _ = _run(store.paths(done).root, unused)
    assert code == 1
    assert out.startswith("cli.recover_not_interrupted(folder=")

    code, out, _ = _run(tmp_path / "20990101_000000", unused)
    assert code == 1
    assert out.startswith("cli.session_not_found(folder=")


def test_a_failed_repair_is_reported_and_the_exit_code_is_1(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "recordings")
    broken = make_session_folder(store, status="interrupted")
    store.paths(broken).wav(Channel.MIC).write_bytes(b"garbage")

    code, out, finisher = _run(None, store)

    assert code == 1
    assert finisher.recovered == []
    assert f"cli.recover_failed(id={broken},reason=" in out
