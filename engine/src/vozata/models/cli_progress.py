"""Model downloads of the CLI commands (phase 42): no WebSocket, so progress is printed.

The lines are localized and go to stderr (whatever the logging level), like the other CLI
progress lines: one every 5 s while bytes arrive, plus one when the download ends.
"""

from __future__ import annotations

import sys
from typing import TextIO

from vozata.config import Settings
from vozata.models.download import HubDownloader
from vozata.models.tracker import DownloadState, DownloadTracker
from vozata.ports import Localizer, ModelDownloader

LOG_SECONDS = 5.0  # how often a running download is printed


def cli_downloader(
    settings: Settings, localizer: Localizer, stream: TextIO | None = None
) -> ModelDownloader:
    """The downloader of `record`, `transcribe`, `recover` and `diarize`.

    `stream` defaults to the current `sys.stderr`, looked up on every line.
    """
    reporter = DownloadReporter(localizer, stream)
    return HubDownloader(DownloadTracker(reporter, interval=LOG_SECONDS), settings.hf_hub_offline)


class DownloadReporter:
    """Prints one localized line per published download state (the tracker serializes calls)."""

    def __init__(self, localizer: Localizer, stream: TextIO | None = None) -> None:
        self._t = localizer.t
        self._stream = stream

    def __call__(self, state: DownloadState) -> None:
        stream = self._stream or sys.stderr
        stream.write(self.line(state) + "\n")
        stream.flush()

    def line(self, state: DownloadState) -> str:
        kind = self._t(f"cli.download_kind_{state.kind.value}")
        done = f"{state.downloaded_bytes / 1e6:.1f}"
        if state.state == "running":
            total = "?" if state.total_bytes is None else f"{state.total_bytes / 1e6:.1f}"
            return self._t(
                "cli.download_running", kind=kind, model=state.model, done=done, total=total
            )
        if state.state == "done":
            return self._t("cli.download_done", kind=kind, model=state.model, done=done)
        return self._t("cli.download_failed", kind=kind, model=state.model, reason=state.reason)
