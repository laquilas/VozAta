from __future__ import annotations

import io
import logging

import pytest

from vozata import bootstrap
from vozata.config import Settings
from vozata.domain import AppLanguage, ModelKind
from vozata.i18n import TomlLocalizer
from vozata.models.cli_progress import LOG_SECONDS, DownloadReporter, cli_downloader
from vozata.models.download import HubDownloader


def _run_downloads(downloader: object) -> None:
    assert isinstance(downloader, HubDownloader)
    handle = downloader._tracker.start(ModelKind.SPEECH, "small", 2_000_000)
    handle.advance(1_000_000)
    handle.done()
    downloader._tracker.start(ModelKind.SPEAKERS, "x", None).failed("offline")


def test_cli_downloads_print_localized_progress_to_the_stream() -> None:
    stream = io.StringIO()
    downloader = cli_downloader(
        Settings(hf_hub_offline=True), TomlLocalizer(AppLanguage.EN), stream
    )
    assert isinstance(downloader, HubDownloader) and downloader._offline
    assert downloader._tracker._interval == LOG_SECONDS == 5.0

    _run_downloads(downloader)

    assert stream.getvalue().splitlines() == [
        "Downloading the speech recognition model small: 0.0 of 2.0 MB",
        "Downloaded the speech recognition model small (1.0 MB).",
        "Downloading the speaker identification model x: 0.0 of ? MB",
        "The speaker identification model x could not be downloaded (offline).",
    ]


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        (AppLanguage.PT_BR, "Baixando o modelo de tradução ROMANCE-en: 0.5 de 1.0 MB"),
        (AppLanguage.ES, "Descargando el modelo de traducción ROMANCE-en: 0.5 de 1.0 MB"),
    ],
)
def test_the_lines_follow_the_app_language(language: AppLanguage, expected: str) -> None:
    from vozata.models.tracker import DownloadState

    state = DownloadState(ModelKind.TRANSLATION, "ROMANCE-en", 500_000, 1_000_000, "running")

    assert DownloadReporter(TomlLocalizer(language)).line(state) == expected


def test_progress_is_visible_with_the_cli_logging_setup(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # `main()` logs at WARNING only: the progress must not depend on the log level.
    root = logging.getLogger()
    level = root.level
    root.setLevel(logging.WARNING)
    try:
        _run_downloads(bootstrap._downloader(Settings(), None))
    finally:
        root.setLevel(level)

    err = capsys.readouterr().err
    assert "Downloading the speech recognition model small: 0.0 of 2.0 MB" in err
    assert "Downloaded the speech recognition model small (1.0 MB)." in err
    assert "could not be downloaded (offline)" in err
