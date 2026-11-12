from __future__ import annotations

import shutil
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from vozata.domain import Channel
from vozata.processing import ingest_check
from vozata.processing.ingest_check import check_ingest
from vozata.processing.job import HIDDEN_KINDS, StepKind
from vozata.recorder.durable_track import DurableTrack
from vozata.recorder.engine_link import write_link
from vozata.recorder.manifest import RECORDING, STOPPED, Manifest, live_dir, write_manifest

RATE = 1000
NOW = datetime(2026, 11, 3, 11, 0, tzinfo=timezone(timedelta(hours=-3)))


class Stored:
    """The store's frames per channel (`AudioReader.length`)."""

    def __init__(self, mic: int, system: int) -> None:
        self.frames = {Channel.MIC: mic, Channel.SYSTEM: system}

    def length(self, session_id: str, channel: Channel) -> int:
        return self.frames[channel]


def recording(tmp_path: Path, frames: int, status: str = STOPPED) -> Path:
    folder = live_dir(tmp_path) / "20261103_101500"
    folder.mkdir(parents=True)
    manifest = Manifest(id=folder.name, started_at=NOW.isoformat(), sample_rate=RATE)
    lock = threading.RLock()
    for channel in (Channel.MIC, Channel.SYSTEM):
        track = DurableTrack(folder, channel, RATE, manifest.segments(channel), lock, lambda: None)
        track.write(np.full(frames, 0.1, dtype=np.float32), 0.0)
        track.close()
    manifest.status = status
    write_manifest(folder, manifest)
    write_link(folder, "20261103_101500", NOW)
    return folder


META = {"recorder_id": "20261103_101500"}


def run(tmp_path: Path, stored: Stored, meta: dict[str, Any] = META) -> tuple[bool, list[Any]]:
    saved: list[Any] = []
    removed = check_ingest(tmp_path, stored, "20261103_101500", meta, saved.append, lambda s: None)
    return removed, saved


def test_the_files_go_once_the_store_holds_every_frame(tmp_path: Path) -> None:
    folder = recording(tmp_path, 500)

    removed, saved = run(tmp_path, Stored(500, 520))

    assert removed and not folder.exists()
    assert saved == []


def test_missing_frames_keep_the_files_and_are_saved(tmp_path: Path) -> None:
    folder = recording(tmp_path, 500)

    removed, saved = run(tmp_path, Stored(500, 120))

    assert not removed and folder.exists()
    assert saved == [{"system": 380}]


def test_a_folder_linked_to_another_meeting_is_never_touched(tmp_path: Path) -> None:
    folder = recording(tmp_path, 100)
    write_link(folder, "20261103_090000", NOW)

    assert run(tmp_path, Stored(100, 100)) == (False, [])
    assert folder.exists()


def test_a_recording_still_active_is_never_touched(tmp_path: Path) -> None:
    folder = recording(tmp_path, 100, status=RECORDING)

    assert run(tmp_path, Stored(100, 100)) == (False, [])
    assert folder.exists()


@pytest.mark.parametrize("meta", [{}, {"recorder_id": "20261103_999999"}])
def test_meetings_without_a_recording_folder_are_skipped(
    tmp_path: Path, meta: dict[str, Any]
) -> None:
    assert run(tmp_path, Stored(0, 0), meta) == (False, [])


def test_an_unreadable_manifest_keeps_the_files(tmp_path: Path) -> None:
    folder = recording(tmp_path, 100)
    (folder / "recording.json").write_text("{", encoding="utf-8")

    assert run(tmp_path, Stored(100, 100)) == (False, [])


def test_a_locked_folder_is_tried_again_then_left_for_later(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = recording(tmp_path, 100)
    attempts: list[Path] = []

    def locked(path: Path) -> None:
        attempts.append(path)
        raise PermissionError("OneDrive")

    monkeypatch.setattr(ingest_check.shutil, "rmtree", locked)

    assert run(tmp_path, Stored(100, 100)) == (False, [])
    assert len(attempts) == ingest_check._DELETE_ATTEMPTS
    assert folder.exists()


def test_a_folder_removed_meanwhile_counts_as_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recording(tmp_path, 100)
    real = shutil.rmtree

    def gone(path: Path) -> None:
        real(path)
        raise FileNotFoundError(path)

    monkeypatch.setattr(ingest_check.shutil, "rmtree", gone)

    assert run(tmp_path, Stored(100, 100)) == (True, [])


def test_the_ingest_step_is_hidden() -> None:
    assert StepKind.INGEST in HIDDEN_KINDS


def test_the_sources_are_kept_before_the_folder_goes(tmp_path: Path) -> None:
    folder = recording(tmp_path, 500)
    kept: list[tuple[Path, str]] = []

    removed = check_ingest(
        tmp_path,
        Stored(500, 500),
        "20261103_101500",
        META,
        lambda missing: None,
        lambda s: None,
        keep_sources=lambda path, manifest: kept.append((path, manifest.id)) or True,
    )

    assert removed and not folder.exists()
    assert kept == [(folder, "20261103_101500")]


def test_sources_that_cannot_be_kept_keep_the_folder(tmp_path: Path) -> None:
    folder = recording(tmp_path, 500)

    def refuse(path: Path, manifest: Manifest) -> bool:
        raise PermissionError("locked")

    removed = check_ingest(
        tmp_path,
        Stored(500, 500),
        "20261103_101500",
        META,
        lambda m: None,
        lambda s: None,
        keep_sources=refuse,
    )

    assert not removed and folder.exists()
