"""Shared test hooks."""

from __future__ import annotations

import hashlib
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from vozata import config


@pytest.fixture(autouse=True)
def _no_onedrive_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never read the real Windows registry (OneDrive accounts, phase 31)."""
    monkeypatch.setattr(config, "onedrive_registry_roots", lambda registry=None: ())


@pytest.fixture(autouse=True)
def _no_audio_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never read the real Windows audio sessions (meeting detection, phase 54)."""
    from vozata.audio import sessions

    monkeypatch.setattr(sessions.WindowsAudioSessions, "active_apps", lambda self: set())


@pytest.fixture(autouse=True)
def _close_databases() -> Iterator[None]:
    """Close the `vozata.db` connections `bootstrap` opened in a test (phase 31), so the next
    test starts clean and Windows can delete the test's temporary folder."""
    yield
    bootstrap = sys.modules.get("vozata.bootstrap")
    if bootstrap is not None:
        bootstrap.close_databases()


@pytest.fixture(autouse=True, scope="session")
def _real_env_file_untouched() -> Iterator[None]:
    """Fail the session if any test wrote to the developer's real `engine/.env`."""
    env_file = Path(__file__).resolve().parents[1] / ".env"
    before = hashlib.sha256(env_file.read_bytes()).hexdigest() if env_file.exists() else None
    yield
    after = hashlib.sha256(env_file.read_bytes()).hexdigest() if env_file.exists() else None
    if before != after:
        pytest.fail(f"A test modified the real {env_file}; pass env_file=tmp_path / '.env'.")


_LEAK_GRACE_SECONDS = 2.0


@pytest.fixture(autouse=True, scope="session")
def _no_leaked_threads() -> Iterator[None]:
    """Fail the session if a test left a non-daemon thread running (e.g. a started session's
    `transcription`, `live-speakers`, `capture-*` or `stop-capture` thread): such a thread keeps
    the pytest process alive after the summary. Each one gets a short grace period to finish."""
    before = set(threading.enumerate())
    yield
    leaked = [
        thread
        for thread in threading.enumerate()
        if thread not in before and not thread.daemon and thread is not threading.current_thread()
    ]
    for thread in leaked:
        thread.join(_LEAK_GRACE_SECONDS)
    alive = sorted(thread.name for thread in leaked if thread.is_alive())
    if alive:
        pytest.fail(f"Tests leaked non-daemon threads that are still running: {', '.join(alive)}.")
