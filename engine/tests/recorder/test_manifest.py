from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from vozata.domain import Channel
from vozata.recorder import manifest as manifest_module
from vozata.recorder.manifest import (
    MANIFEST,
    PAUSED,
    REASON_RESTART,
    STOPPED,
    Gap,
    Manifest,
    Segment,
    list_recordings,
    live_dir,
    read_manifest,
    segment_file,
    write_manifest,
)


def _manifest() -> Manifest:
    manifest = Manifest(
        id="20261103_101500", started_at="2026-11-03T10:15:00-03:00", sample_rate=16000
    )
    manifest.segments(Channel.MIC).extend(
        [
            Segment("mic.wav", 0, 1000, closed=True),
            Segment("mic-0002.wav", 1500, 200, reason=REASON_RESTART),
        ]
    )
    manifest.gaps.append(Gap("mic", 1000, 1500))
    manifest.options = {"language": "pt", "title": "Weekly"}
    return manifest


def test_a_manifest_round_trips_through_its_file(tmp_path: Path) -> None:
    write_manifest(tmp_path, _manifest())

    loaded = read_manifest(tmp_path)

    assert loaded == _manifest()
    assert loaded.segments(Channel.MIC)[1].reason == REASON_RESTART
    assert not (tmp_path / f"{MANIFEST}.tmp").exists()


def test_frames_total_is_the_end_of_the_last_segment() -> None:
    manifest = _manifest()

    assert manifest.frames_total(Channel.MIC) == 1700
    assert manifest.frames_total(Channel.SYSTEM) == 0


def test_open_segment_is_the_last_unclosed_one() -> None:
    manifest = _manifest()

    assert manifest.open_segment(Channel.MIC) == Segment(
        "mic-0002.wav", 1500, 200, reason=REASON_RESTART
    )
    assert manifest.open_segment(Channel.SYSTEM) is None
    manifest.segments(Channel.MIC)[-1].closed = True
    assert manifest.open_segment(Channel.MIC) is None


@pytest.mark.parametrize(
    ("status", "active"), [("recording", True), (PAUSED, True), (STOPPED, False)]
)
def test_active_statuses(status: str, active: bool) -> None:
    manifest = _manifest()
    manifest.status = status

    assert manifest.active is active


def test_unknown_keys_from_a_newer_recorder_are_ignored(tmp_path: Path) -> None:
    data = _manifest().to_json() | {"future_key": 1}
    (tmp_path / MANIFEST).write_text(json.dumps(data), encoding="utf-8")

    assert read_manifest(tmp_path).id == "20261103_101500"


def test_a_manifest_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    (tmp_path / MANIFEST).write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="not an object"):
        read_manifest(tmp_path)


def test_a_locked_manifest_is_replaced_once_the_lock_goes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = os.replace
    failures = [PermissionError("locked by OneDrive")] * 2

    def flaky(source: object, target: object) -> None:
        if failures:
            raise failures.pop()
        real(source, target)  # type: ignore[arg-type]

    monkeypatch.setattr(manifest_module.os, "replace", flaky)
    monkeypatch.setattr(manifest_module, "_REPLACE_WAIT", 0)

    write_manifest(tmp_path, _manifest())

    assert read_manifest(tmp_path).id == "20261103_101500"


def test_a_lock_that_never_goes_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def locked(source: object, target: object) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(manifest_module.os, "replace", locked)
    monkeypatch.setattr(manifest_module, "_REPLACE_WAIT", 0)

    with pytest.raises(PermissionError):
        write_manifest(tmp_path, _manifest())


def test_segment_files_are_named_by_channel_and_index() -> None:
    assert segment_file(Channel.MIC, 1) == "mic.wav"
    assert segment_file(Channel.SYSTEM, 2) == "system-0002.wav"


def test_list_recordings_finds_the_folders_with_a_manifest(tmp_path: Path) -> None:
    assert list_recordings(tmp_path) == []
    for name in ("20261103_120000", "20261103_101500"):
        (live_dir(tmp_path) / name).mkdir(parents=True)
        write_manifest(live_dir(tmp_path) / name, _manifest())
    (live_dir(tmp_path) / "stray").mkdir()

    assert list_recordings(tmp_path) == ["20261103_101500", "20261103_120000"]
