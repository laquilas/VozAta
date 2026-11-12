"""One recording of the recorder process: capture → `DurableTrack`s → `live/<id>/` (phase 61).

The recording owns its manifest (`recording.json`): every change is saved under one lock, and a
failing save is logged and retried by the next change or heartbeat, never ending the recording.
Pause keeps capturing and writes silence (the timeline stays continuous). A recording whose
recorder died is continued by `Recording.resume`: the open segments are repaired from their
file size and closed, the lost time becomes a gap, and new segments start at the current time.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from vozata.audio.devices import DeviceInfo
from vozata.audio.levels import rms_db
from vozata.audio.opener import SourceOpenTimeoutError, open_with_timeout
from vozata.domain import Channel
from vozata.heartbeat import Heartbeat
from vozata.ports import AudioSource
from vozata.recorder.durable_track import DurableTrack, TrackWriteError
from vozata.recorder.manifest import (
    PAUSED,
    REASON_RESTART,
    REASON_START,
    RECORDING,
    STOPPED,
    Gap,
    Manifest,
    read_manifest,
    write_manifest,
)
from vozata.recorder.segment_reader import segment_frames
from vozata.recorder.settings import RecorderSettings
from vozata.recorder.source_capture import GONE, NoSourceError, SourceCapture
from vozata.recorder.sources import SourceSpec

_log = logging.getLogger(__name__)

CHANNELS = (Channel.MIC, Channel.SYSTEM)


class Clock(Protocol):
    def now(self) -> float: ...


class RecordingObserver(Protocol):
    def on_status(self, summary: dict[str, Any]) -> None: ...

    def on_level(self, channel: Channel, rms_db: float) -> None: ...

    def on_error(self, code: str, message: str) -> None: ...

    def on_sources(self, sources: list[dict[str, Any]]) -> None: ...


class RecordingError(RuntimeError):
    """A recording could not start; `code` is the API error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


SourceFactory = Callable[[DeviceInfo, Clock], AudioSource]


class OffsetClock:
    """Seconds since the recording started: monotonic time plus the offset of a restart."""

    def __init__(self, offset: float = 0.0, time_source: Callable[[], float] = time.monotonic):
        self._offset = offset
        self._time = time_source
        self._started: float | None = None

    def start(self) -> None:
        self._started = self._time()

    def now(self) -> float:
        if self._started is None:
            return self._offset
        return self._offset + self._time() - self._started


def new_recording_id(now: datetime, taken: Callable[[str], bool]) -> str:
    """`YYYYMMDD_HHMMSS` of the local start time (the engine's session id), `_2`... if taken."""
    base = now.strftime("%Y%m%d_%H%M%S")
    candidate, n = base, 1
    while taken(candidate):
        n += 1
        candidate = f"{base}_{n}"
    return candidate


class Recording:
    def __init__(
        self,
        folder: Path,
        manifest: Manifest,
        settings: RecorderSettings,
        devices: Mapping[Channel, DeviceInfo],
        source_factory: SourceFactory,
        observer: RecordingObserver,
        clock: OffsetClock,
        wall_clock: Callable[[], datetime],
        start_frames: Mapping[Channel, int] | None = None,
        first_reason: str = REASON_START,
        sources: Sequence[SourceSpec] | None = None,
        source_frames: Mapping[str, int] | None = None,
        resumed: bool = False,
    ) -> None:
        """Use `Recording.create` or `Recording.resume`.

        With `sources` (phase 65) every source is recorded and the channels are their mix;
        without, each channel records its own device (`devices`).
        """
        self.folder = folder
        self.manifest = manifest
        self._settings = settings
        self._devices = dict(devices)
        self._observer = observer
        self._clock = clock
        self._wall = wall_clock
        self._lock = threading.RLock()
        self._save_failed = False
        self._warned_backlog = False
        frames = start_frames or {}
        self._tracks = {
            channel: DurableTrack(
                folder,
                channel,
                settings.sample_rate,
                manifest.segments(channel),
                self._lock,
                self.save,
                fsync_seconds=settings.fsync_seconds,
                max_segment_bytes=settings.max_segment_bytes,
                start_frame=frames.get(channel, 0),
                first_reason=first_reason,
            )
            for channel in CHANNELS
        }
        self._capture: SourceCapture | None = None
        self._sources: dict[Channel, AudioSource] = {}
        if sources is not None:
            self._capture = SourceCapture(
                SourceCapture.folder_of(folder),
                manifest,
                sources,
                settings,
                self._lock,
                self.save,
                source_factory,
                clock,
                observer,
                lambda channel, samples, at: self._tracks[channel].write(samples, at),
                start_frames=source_frames,
                mix_start=max(frames.values(), default=0),
                first_reason=first_reason,
                resumed=resumed,
            )
        else:
            self._sources = {
                channel: source_factory(self._devices[channel], clock) for channel in CHANNELS
            }
        self._heartbeat = Heartbeat(settings.autosave_seconds, self._beat, name="recording-beat")
        self._accepting = False

    # -- construction -------------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        live: Path,
        settings: RecorderSettings,
        devices: Mapping[Channel, DeviceInfo],
        source_factory: SourceFactory,
        observer: RecordingObserver,
        options: Mapping[str, Any] | None = None,
        wall_clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
        time_source: Callable[[], float] = time.monotonic,
        sources: Sequence[SourceSpec] | None = None,
    ) -> Recording:
        started = wall_clock()
        live.mkdir(parents=True, exist_ok=True)
        recording_id = new_recording_id(started, lambda name: (live / name).exists())
        folder = live / recording_id
        folder.mkdir()
        manifest = Manifest(
            id=recording_id,
            started_at=started.isoformat(timespec="seconds"),
            sample_rate=settings.sample_rate,
            recorder_pid=os.getpid(),
            devices={c.value: _device(d) for c, d in devices.items()},
            options=dict(options or {}),
        )
        write_manifest(folder, manifest)
        return cls(
            folder,
            manifest,
            settings,
            devices,
            source_factory,
            observer,
            OffsetClock(time_source=time_source),
            wall_clock,
            sources=sources,
        )

    @classmethod
    def resume(
        cls,
        folder: Path,
        settings: RecorderSettings,
        devices: Mapping[Channel, DeviceInfo],
        source_factory: SourceFactory,
        observer: RecordingObserver,
        wall_clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
        time_source: Callable[[], float] = time.monotonic,
        sources: Sequence[SourceSpec] | None = None,
    ) -> Recording:
        """Continue a recording whose recorder died: repair, close, add the gap, go on.

        `sources` are the saved sources found again (with their saved ids); the saved ones not
        found are closed and marked `gone`.
        """
        manifest = read_manifest(folder)
        if not manifest.active:
            raise RecordingError("recording_stopped", f"Recording {manifest.id} was stopped")
        offset = max(
            0.0, (wall_clock() - datetime.fromisoformat(manifest.started_at)).total_seconds()
        )
        now_frame = round(offset * manifest.sample_rate)
        starts: dict[Channel, int] = {}
        for channel in CHANNELS:
            segment = manifest.open_segment(channel)
            if segment is not None:  # the crash left it open: its file size is the truth
                segment.frames = segment_frames(folder / segment.file)
                segment.closed = True
            end = manifest.frames_total(channel)
            start = max(end, now_frame)
            if start > end:
                manifest.gaps.append(Gap(channel.value, end, start))
            starts[channel] = start
        found = {spec.source_id for spec in sources or ()}
        source_starts: dict[str, int] = {}
        for source_id, entry in manifest.sources.items():
            _close_open_segment(SourceCapture.folder_of(folder), entry)
            end = manifest.source_frames_total(source_id)
            start = max(end, now_frame)
            if start > end:
                manifest.gaps.append(Gap(source_id, end, start))
            source_starts[source_id] = start
            if source_id not in found:
                entry["state"] = GONE
        manifest.incarnation += 1  # a paused recording stays paused: its open pause goes on
        manifest.recorder_pid = os.getpid()
        manifest.devices = {c.value: _device(d) for c, d in devices.items()}
        write_manifest(folder, manifest)
        recording = cls(
            folder,
            manifest,
            settings,
            devices,
            source_factory,
            observer,
            OffsetClock(offset, time_source),
            wall_clock,
            start_frames=starts,
            first_reason=REASON_RESTART,
            sources=sources if manifest.sources else None,
            source_frames=source_starts,
            resumed=True,
        )
        if manifest.status == PAUSED:
            recording._set_paused(True)
        return recording

    # -- control ------------------------------------------------------------------------------

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def status(self) -> str:
        return self.manifest.status

    def start(self) -> None:
        """Open both devices and start writing; `RecordingError` when a device fails."""
        self._clock.start()
        for track in self._tracks.values():
            track.start()
        self._accepting = True
        if self._capture is not None:
            try:
                self._capture.start()
            except NoSourceError as error:
                self._abort([])
                raise RecordingError("device_failed", str(error)) from None
            self._heartbeat.start()
            self._report()
            return
        opened: list[AudioSource] = []
        for channel, source in self._sources.items():
            name = self._devices[channel].name
            try:
                open_with_timeout(
                    source,
                    self._receiver(channel),
                    self._settings.open_timeout,
                    lambda: self._accepting,
                )
            except SourceOpenTimeoutError:
                self._abort(opened)
                raise RecordingError("device_timeout", f"{name} did not open") from None
            except Exception as error:
                self._abort(opened)
                raise RecordingError("device_failed", f"{name}: {error}") from error
            opened.append(source)
        self._heartbeat.start()
        self._report()

    def pause(self) -> None:
        with self._lock:
            if self.manifest.status != RECORDING:
                return
            self.manifest.pauses.append({"start": round(self._clock.now(), 3), "end": None})
            self.manifest.status = PAUSED
            self._set_paused(True)
            self.save()
        self._report()

    def resume_capture(self) -> None:
        with self._lock:
            if self.manifest.status != PAUSED:
                return
            self._close_pause()
            self.manifest.status = RECORDING
            self._set_paused(False)
            self.save()
        self._report()

    def update_options(self, options: Mapping[str, Any]) -> None:
        with self._lock:
            self.manifest.options.update(options)
            self.save()
        self._report()

    def set_source_mode(self, source_id: str, mode: str) -> None:
        """Auto / On / Off for one source (phase 65).

        `LookupError` without sources or for an unknown id, `ValueError` for a bad mode.
        """
        if self._capture is None:
            raise LookupError("This recording does not record every device")
        self._capture.set_mode(source_id, mode)
        self._report()

    def sources(self) -> list[dict[str, Any]] | None:
        """Every source with its level, score and selection; None in pair mode."""
        return self._capture.summary() if self._capture is not None else None

    def stop(self, reason: str = "user") -> None:
        """Stop capture, write and fsync every sample, close the segments, mark `stopped`.

        `TrackWriteError` when some audio could not be made durable in time: the manifest is
        still `stopped`, the audio stays in memory and the writer threads keep trying.
        """
        if self.manifest.status == STOPPED:
            return
        self._accepting = False
        if self._capture is not None:
            self._capture.stop_sources()
        for source in self._sources.values():
            try:
                source.stop()
            except Exception:
                _log.exception("Stopping a source failed")
        self._heartbeat.stop()
        if self._capture is not None:
            self._capture.finish()
        tracks = self._all_tracks()
        length = max(track.samples_written for track in tracks)
        failures: list[TrackWriteError] = []
        for track in tracks:
            track.pad_to(length)
            try:
                track.close()
            except TrackWriteError as error:
                failures.append(error)
        with self._lock:
            if self.manifest.status == PAUSED:
                self._close_pause()
            self.manifest.status = STOPPED
            self.manifest.stop_reason = reason
            self.manifest.stopped_at = self._wall().isoformat(timespec="seconds")
            self.manifest.duration_seconds = round(length / self.manifest.sample_rate, 3)
            self.save()
        self._report()
        if failures:
            self._observer.on_error("write_failed", str(failures[0]))
            raise failures[0]

    def summary(self) -> dict[str, Any]:
        with self._lock:
            manifest = self.manifest
            return {
                "id": manifest.id,
                "status": manifest.status,
                "started_at": manifest.started_at,
                "duration_seconds": round(self.duration(), 3),
                "devices": manifest.devices,
                "incarnation": manifest.incarnation,
                "segments": {name: len(items) for name, items in manifest.channels.items()},
                "options": dict(manifest.options),
                **({"capture": "all"} if self._capture is not None else {}),
            }

    def duration(self) -> float:
        if self.manifest.status == STOPPED:
            return self.manifest.duration_seconds
        return self._clock.now()

    def save(self) -> None:
        """Write the manifest (called under the lock by the tracks too); never raises."""
        with self._lock:
            try:
                write_manifest(self.folder, self.manifest)
            except OSError as error:
                if not self._save_failed:
                    _log.warning("Saving %s/recording.json failed: %s", self.id, error)
                    self._observer.on_error("manifest_write_failed", str(error))
                self._save_failed = True
                return
            self._save_failed = False

    # -- internals ----------------------------------------------------------------------------

    def _receiver(self, channel: Channel) -> Callable[[np.ndarray, float], None]:
        track = self._tracks[channel]

        def on_samples(samples: np.ndarray, at: float) -> None:
            if not self._accepting:
                return
            track.write(samples, at)
            self._observer.on_level(channel, rms_db(samples))

        return on_samples

    def _abort(self, opened: list[AudioSource]) -> None:
        self._accepting = False
        if self._capture is not None:
            self._capture.stop_sources()
        for source in opened:
            try:
                source.stop()
            except Exception:
                _log.exception("Stopping a source after a failed start failed")
        for track in self._all_tracks():
            try:
                track.close(timeout=5.0)
            except TrackWriteError:
                _log.warning("Audio of the failed start was not all written")
        with self._lock:
            self.manifest.status = STOPPED
            self.manifest.stop_reason = "device_failed"
            self.manifest.stopped_at = self._wall().isoformat(timespec="seconds")
            self.save()

    def _all_tracks(self) -> list[DurableTrack]:
        raw = list(self._capture.tracks.values()) if self._capture is not None else []
        return [*self._tracks.values(), *raw]

    def _set_paused(self, paused: bool) -> None:
        for track in self._tracks.values():
            track.paused = paused
        if self._capture is not None:
            self._capture.set_paused(paused)

    def _close_pause(self) -> None:
        if self.manifest.pauses and self.manifest.pauses[-1].get("end") is None:
            self.manifest.pauses[-1]["end"] = round(self._clock.now(), 3)

    def _beat(self) -> None:
        with self._lock:
            self.manifest.last_heartbeat_at = self._wall().isoformat(timespec="seconds")
            self.manifest.duration_seconds = round(self._clock.now(), 3)
            self.save()
        backlog = max(track.pending_seconds for track in self._all_tracks())
        if backlog > self._settings.buffer_warn_seconds and not self._warned_backlog:
            self._warned_backlog = True
            message = f"{backlog:.0f} s of audio wait in memory for the disk"
            _log.warning(message)
            self._observer.on_error("disk_backlog", message)
        elif backlog <= self._settings.buffer_warn_seconds:
            self._warned_backlog = False

    def _report(self) -> None:
        try:
            self._observer.on_status(self.summary())
        except Exception:
            _log.exception("Reporting the status failed")


def _device(device: DeviceInfo) -> dict[str, Any]:
    return {"id": device.id, "name": device.name}


def _close_open_segment(folder: Path, entry: dict[str, Any]) -> None:
    """A source segment the crash left open ends at its file size."""
    segments = entry.get("segments") or []
    if segments and not segments[-1].closed:
        segments[-1].frames = segment_frames(folder / segments[-1].file)
        segments[-1].closed = True


def heartbeat_age(manifest: Manifest, now: datetime) -> float:
    """Seconds since the recording last showed life (its heartbeat, else its start)."""
    last = manifest.last_heartbeat_at or manifest.started_at
    return (now - datetime.fromisoformat(last)).total_seconds()


def mark_stopped(folder: Path, reason: str, now: datetime) -> Manifest:
    """Close a recording nobody records any more: open segments end at their file size."""
    manifest = read_manifest(folder)
    if not manifest.active:
        return manifest
    for channel in CHANNELS:
        segment = manifest.open_segment(channel)
        if segment is not None:
            segment.frames = segment_frames(folder / segment.file)
            segment.closed = True
    for entry in manifest.sources.values():
        _close_open_segment(SourceCapture.folder_of(folder), entry)
    if manifest.pauses and manifest.pauses[-1].get("end") is None:
        manifest.pauses[-1]["end"] = manifest.duration_seconds
    frames = max((manifest.frames_total(channel) for channel in CHANNELS), default=0)
    manifest.status = STOPPED
    manifest.stop_reason = reason
    manifest.stopped_at = manifest.last_heartbeat_at or now.isoformat(timespec="seconds")
    manifest.duration_seconds = round(frames / manifest.sample_rate, 3)
    write_manifest(folder, manifest)
    return manifest
