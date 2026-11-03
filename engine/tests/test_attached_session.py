"""A session that follows a recording of the recorder process (phase 61), end to end."""

from __future__ import annotations

import threading
import wave
from pathlib import Path

import numpy as np

from tests.fakes import FakeSessionObserver
from vozata.bootstrap import build_session, build_store
from vozata.config import Settings
from vozata.domain import Channel, SessionStatus, StorageBackend
from vozata.recorder.attach import RecordingAttach
from vozata.recorder.durable_track import DurableTrack
from vozata.recorder.manifest import STOPPED, Manifest, read_manifest, write_manifest

RATE = 16000


def record(folder: Path, seconds: float, started_at: str) -> Manifest:
    """Write a stopped recording the way the recorder process does."""
    folder.mkdir(parents=True)
    manifest = Manifest(id=folder.name, started_at=started_at, sample_rate=RATE)
    manifest.devices = {"mic": {"id": 15, "name": "JBL mic"}, "system": {"id": 16, "name": "JBL"}}
    lock = threading.RLock()

    def save() -> None:
        write_manifest(folder, manifest)

    frames = round(seconds * RATE)
    for channel, value in ((Channel.MIC, 0.25), (Channel.SYSTEM, -0.5)):
        track = DurableTrack(folder, channel, RATE, manifest.segments(channel), lock, save)
        track.write(np.full(frames, value, dtype=np.float32), 0.0)
        track.close()
    manifest.status = STOPPED
    manifest.duration_seconds = seconds
    save()
    return manifest


def settings(tmp_path: Path) -> Settings:
    return Settings(
        output_dir=tmp_path / "recordings",
        storage_backend=StorageBackend.FILES,
        generate_minutes=False,
        live_transcription=False,
    )


def test_an_attached_session_stores_every_frame_of_the_recording_under_its_id(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "recordings" / "live" / "20261103_101500"
    manifest = record(folder, 1.25, "2026-11-03T10:15:00-03:00")
    current = settings(tmp_path)
    observer = FakeSessionObserver()

    session = build_session(
        current,
        observer,
        attach=RecordingAttach.of(folder, read_manifest(folder)),
        live_transcription=False,
    )
    session.start()
    session.end_at(manifest.duration_seconds)
    closed = session.stop_capture()

    assert closed.wait(10)
    assert session.id == "20261103_101500"
    assert session.recorder_id == "20261103_101500"
    assert session.duration_seconds == 1.25
    meta = build_store(current).read_meta(session.id)
    assert meta["started_at"] == "2026-11-03T10:15:00-03:00"
    assert (meta["capture_source"], meta["recorder_id"]) == ("recorder", "20261103_101500")
    assert meta["devices"] == {"mic": "JBL mic", "system": "JBL"}
    assert meta["status"] == SessionStatus.FINALIZING.value
    for name, value in (("mic", 0.25), ("system", -0.5)):
        with wave.open(str(tmp_path / "recordings" / session.id / f"{name}.wav"), "rb") as wav:
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
        assert len(samples) == 20000
        assert np.all(np.abs(samples.astype(int) - int(value * 32767)) <= 1)  # 16-bit rounding


def test_a_session_without_attach_has_no_recorder_link(tmp_path: Path) -> None:
    from vozata.session import SessionComponents

    assert SessionComponents.__dataclass_fields__["recorder_id"].default is None
