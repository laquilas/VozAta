"""Shared test hooks."""

from __future__ import annotations

import sys
from collections.abc import Iterator

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
