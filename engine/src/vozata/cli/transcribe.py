"""`python -m vozata transcribe <id>`: transcribe a stored meeting from its audio (phase 41).

Writes whatever the raw transcript does not cover yet (all of it for a meeting recorded with live
transcription off). It runs neither the speakers nor the minutes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from vozata.cli.console import ConsoleObserver
from vozata.config import Settings
from vozata.domain import SessionStatus, TranscriptSegment
from vozata.ports import Localizer, SessionNotFoundError
from vozata.processing.cancel import CancelToken
from vozata.storage.session_folder import SessionFolder
from vozata.transcription.offline import OfflineTranscription

# (settings, the session folder, told every appended segment) -> the transcription to run
TranscribeFactory = Callable[
    [Settings, SessionFolder, Callable[[TranscriptSegment], None] | None], OfflineTranscription
]
_log = logging.getLogger(__name__)
# recording, paused or queued/running in a job of `serve` (a second writer would duplicate
# segments), or interrupted (its audio is not repaired yet: `recover` finishes it)
BUSY = (
    SessionStatus.RECORDING,
    SessionStatus.PAUSED,
    SessionStatus.FINALIZING,
    SessionStatus.INTERRUPTED,
)
PROGRESS_STEP = 10  # percent between two progress lines


def run_transcribe(
    target: str,
    settings: Settings,
    console: ConsoleObserver,
    localizer: Localizer,
    build: TranscribeFactory,
    open_folder: Callable[[Path], SessionFolder],
) -> int:
    """Transcribe the missing part of one meeting; `target` is its id (in `OUTPUT_DIR`) or folder.

    Exit code 0 on success (also when nothing was missing), 1 for an unknown session, a meeting
    still recording, paused, finalizing or interrupted, or a transcription that failed.
    """
    t = localizer.t
    path = Path(target)
    if path.name == target:  # a bare id
        path = settings.output_dir / target
    folder = open_folder(path)
    try:
        meta = folder.repository.read_meta(folder.session_id)
    except SessionNotFoundError:
        console.say(t("cli.session_not_found", folder=folder.path))
        return 1
    if meta.get("status") in BUSY:
        console.say(t("cli.transcribe_busy"))
        return 1
    before = len(folder.repository.load_raw_transcript(folder.session_id))
    shown = 0

    def progress(fraction: float) -> None:
        nonlocal shown
        step = int(fraction * 100) // PROGRESS_STEP * PROGRESS_STEP
        if step > shown:
            shown = step
            console.say(t("cli.transcribe_progress", percent=step))

    try:
        build(settings, folder, None).run(folder.session_id, CancelToken(), progress)
    except Exception as error:
        _log.exception("Transcribing session %s failed", folder.session_id)
        console.say(t("cli.transcribe_failed", reason=error))
        return 1
    added = len(folder.repository.load_raw_transcript(folder.session_id)) - before
    console.say(t("cli.transcribe_done", count=added))
    return 0
