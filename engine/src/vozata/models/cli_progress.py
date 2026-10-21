"""Model downloads of the CLI commands (phase 42): no WebSocket, so progress goes to the log."""

from __future__ import annotations

import logging

from vozata.config import Settings
from vozata.models.download import HubDownloader
from vozata.models.tracker import DownloadState, DownloadTracker
from vozata.ports import ModelDownloader

LOG_SECONDS = 5.0  # how often a running download is logged

_log = logging.getLogger(__name__)


def cli_downloader(settings: Settings) -> ModelDownloader:
    """The downloader of `record`, `transcribe`, `recover` and `diarize`."""
    return HubDownloader(
        DownloadTracker(log_download, interval=LOG_SECONDS), settings.hf_hub_offline
    )


def log_download(state: DownloadState) -> None:
    what = f"{state.kind.value} model {state.model}"
    megabytes = state.downloaded_bytes / 1e6
    if state.state == "running":
        total = "?" if state.total_bytes is None else f"{state.total_bytes / 1e6:.1f}"
        _log.info("Downloading %s: %.1f of %s MB", what, megabytes, total)
    elif state.state == "done":
        _log.info("Downloaded %s: done (%.1f MB)", what, megabytes)
    else:
        _log.warning("Download of %s: failed (%s)", what, state.reason)
