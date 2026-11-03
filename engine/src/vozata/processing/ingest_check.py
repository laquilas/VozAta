"""The `ingest` step (phase 61): the recorder's files go only once the store holds every frame.

A meeting recorded by the recorder process keeps its files in `live/<id>/` until this step
compares, channel by channel, the frames the store holds with the frames of the recording's
files (their size is the truth). Only when nothing is missing, and the folder is linked to this
very meeting (`engine.json`), is the folder deleted. Otherwise it is kept, the mismatch is
logged and saved in `session.json`, and the meeting is processed anyway: the audio stays safe on
disk, and nothing is ever deleted that the store does not hold.
"""

from __future__ import annotations

import logging
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from vozata.domain import Channel
from vozata.ports import AudioReader
from vozata.recorder.engine_link import read_link
from vozata.recorder.manifest import live_dir, read_manifest
from vozata.recorder.segment_reader import SegmentReader

_log = logging.getLogger(__name__)

_DELETE_ATTEMPTS = 10
_DELETE_WAIT = 0.5  # OneDrive briefly locks files it syncs


def check_ingest(
    output_dir: Path,
    audio: AudioReader,
    session_id: str,
    meta: dict[str, Any],
    save_mismatch: Callable[[dict[str, int]], None],
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Delete the meeting's recording folder when the store holds all of it; True if deleted."""
    recording_id = meta.get("recorder_id")
    if not recording_id:
        return False
    folder = live_dir(output_dir) / str(recording_id)
    if not folder.is_dir() or read_link(folder) != session_id:
        return False
    try:
        manifest = read_manifest(folder)
    except (OSError, ValueError):
        _log.warning("Recording %s has no readable recording.json; kept", recording_id)
        return False
    if manifest.active:
        return False  # still being recorded (cannot happen after Stop): never touch it
    reader = SegmentReader(folder, manifest)
    missing = {}
    for channel in (Channel.MIC, Channel.SYSTEM):
        recorded = reader.length(channel)
        stored = audio.length(session_id, channel)
        if stored < recorded:
            missing[channel.value] = recorded - stored
    if missing:
        _log.error(
            "Meeting %s holds fewer frames than recording %s (%s); its files are kept in %s",
            session_id,
            recording_id,
            missing,
            folder,
        )
        save_mismatch(missing)
        return False
    for attempt in range(_DELETE_ATTEMPTS):
        try:
            shutil.rmtree(folder)
            _log.info(
                "Recording %s is stored in meeting %s; its files were removed",
                recording_id,
                session_id,
            )
            return True
        except FileNotFoundError:
            return True
        except OSError as error:
            if attempt == _DELETE_ATTEMPTS - 1:
                _log.warning("Could not remove %s (%s); removed at a later start", folder, error)
                return False
            sleep(_DELETE_WAIT)
    return False
