"""Shared test hooks."""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from vozata import config


@pytest.fixture(autouse=True)
def _no_onedrive_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never read the real Windows registry (OneDrive accounts, phase 31)."""
    monkeypatch.setattr(config, "onedrive_registry_roots", lambda registry=None: ())


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
