"""Shared test hooks."""

from __future__ import annotations

import sys
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _close_databases() -> Iterator[None]:
    """Close the `vozata.db` connections `bootstrap` opened in a test (phase 31), so the next
    test starts clean and Windows can delete the test's temporary folder."""
    yield
    bootstrap = sys.modules.get("vozata.bootstrap")
    if bootstrap is not None:
        bootstrap.close_databases()
