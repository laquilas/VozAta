from __future__ import annotations

import logging

import pytest

from vozata.config import Settings
from vozata.domain import ModelKind
from vozata.models.cli_progress import cli_downloader


def test_cli_downloads_log_their_progress(caplog: pytest.LogCaptureFixture) -> None:
    from vozata.models.download import HubDownloader

    downloader = cli_downloader(Settings(hf_hub_offline=True))
    assert isinstance(downloader, HubDownloader) and downloader._offline

    with caplog.at_level(logging.INFO, logger="vozata.models.cli_progress"):
        handle = downloader._tracker.start(ModelKind.SPEECH, "small", 2_000_000)
        handle.advance(1_000_000)
        handle.done()
        downloader._tracker.start(ModelKind.SPEAKERS, "x", None).failed("offline")

    assert "Downloading speech model small: 0.0 of 2.0 MB" in caplog.text
    assert "speech model small: done (1.0 MB)" in caplog.text
    assert "speakers model x: failed (offline)" in caplog.text
