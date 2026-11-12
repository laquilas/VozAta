"""The recorder's API: one recording at a time, status and levels as Server-Sent Events.

See `docs/roadmap/api-contract.md`, "Recorder HTTP API". Start-up policy: an active recording
whose heartbeat is recent (the recorder itself crashed and was started again) is continued at
once, after a gap; older active recordings are closed as `recorder_died` so the engine imports
them. Nothing here ever deletes audio that the engine has not stored.
"""

from __future__ import annotations

import contextlib
import logging
import os
import queue
import shutil
import threading
import time
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from vozata import __version__
from vozata.audio.capture import WasapiSource
from vozata.audio.devices import DeviceInfo, resolve_devices
from vozata.domain import Channel
from vozata.recorder.durable_track import TrackWriteError
from vozata.recorder.http import ApiError, Response, Router, Stream
from vozata.recorder.manifest import list_recordings, live_dir, read_manifest
from vozata.recorder.recording import (
    Clock,
    Recording,
    RecordingError,
    heartbeat_age,
    mark_stopped,
)
from vozata.recorder.settings import CAPTURE_ALL, RecorderSettings
from vozata.recorder.source_mix import MODES
from vozata.recorder.sources import SourceSpec, match_saved, resolve_sources

_log = logging.getLogger(__name__)

RESUME_WINDOW = 120.0  # a recording silent for longer is not continued automatically
STATUS_INTERVAL = 1.0
KEEP_ALIVE = 15.0
EVENT_QUEUE = 500


class AudioThread(Protocol):
    pa: Any

    def call(self, function: Callable[[], Any], timeout: float | None = None) -> Any: ...

    def close(self) -> None: ...


class Catalog(Protocol):
    def inputs(self) -> list[DeviceInfo]: ...

    def loopbacks(self) -> list[DeviceInfo]: ...

    def default_input(self) -> DeviceInfo | None: ...

    def default_loopback(self) -> DeviceInfo | None: ...


SourceFactory = Callable[[AudioThread, int], Callable[[DeviceInfo, Clock], Any]]


def wasapi_sources(audio: AudioThread, sample_rate: int) -> Callable[[DeviceInfo, Clock], Any]:
    def make(device: DeviceInfo, clock: Clock) -> WasapiSource:
        return WasapiSource(device, clock, sample_rate, pa=audio.pa, call_audio=audio.call)

    return make


class Events:
    """Fan-out of events to every `/events` client; a slow client loses events, never audio."""

    def __init__(self) -> None:
        self._clients: list[queue.Queue[tuple[str, Any] | None]] = []
        self._lock = threading.Lock()

    def publish(self, event: str, data: Any) -> None:
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            with contextlib.suppress(queue.Full):
                client.put_nowait((event, data))

    def subscribe(self) -> queue.Queue[tuple[str, Any] | None]:
        client: queue.Queue[tuple[str, Any] | None] = queue.Queue(EVENT_QUEUE)
        with self._lock:
            self._clients.append(client)
        return client

    def unsubscribe(self, client: queue.Queue[tuple[str, Any] | None]) -> None:
        with self._lock:
            if client in self._clients:
                self._clients.remove(client)

    def close(self) -> None:
        with self._lock:
            clients, self._clients = self._clients, []
        for client in clients:
            with contextlib.suppress(queue.Full):
                client.put_nowait(None)


class RecorderApp:
    def __init__(
        self,
        settings: RecorderSettings,
        catalog: Catalog,
        audio_factory: Callable[[], AudioThread],
        source_factory: SourceFactory = wasapi_sources,
        wall_clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
        time_source: Callable[[], float] = time.monotonic,
        keep_alive: float = KEEP_ALIVE,
    ) -> None:
        self.settings = settings
        self._catalog = catalog
        self._audio_factory = audio_factory
        self._source_factory = source_factory
        self._wall = wall_clock
        self._time = time_source
        self._keep_alive = keep_alive
        self._lock = threading.RLock()
        self._current: Recording | None = None
        self._audio: AudioThread | None = None
        self.events = Events()
        self.started_at = wall_clock().isoformat(timespec="seconds")
        self._closed = threading.Event()
        self._ticker = threading.Thread(target=self._tick, name="recorder-status", daemon=True)
        self.shutdown_requested = threading.Event()
        self.router = self._routes()

    @property
    def live(self) -> Path:
        return live_dir(self.settings.output_dir)

    @property
    def current(self) -> Recording | None:
        return self._current

    # -- lifecycle ----------------------------------------------------------------------------

    def start_up(self) -> None:
        """Continue a recording the last recorder left running, close the older ones."""
        now = self._wall()
        active = []
        for recording_id in list_recordings(self.settings.output_dir):
            try:
                manifest = read_manifest(self.live / recording_id)
            except (OSError, ValueError):
                _log.warning("Skipping %s: unreadable recording.json", recording_id)
                continue
            if manifest.active:
                active.append(manifest)
        active.sort(key=lambda manifest: manifest.started_at)
        resumable = (
            active[-1] if active and heartbeat_age(active[-1], now) <= RESUME_WINDOW else None
        )
        for manifest in active:
            if manifest is resumable:
                continue
            _log.warning("Recording %s was left by a recorder that died", manifest.id)
            mark_stopped(self.live / manifest.id, "recorder_died", now)
        if resumable is not None:
            try:
                self._resume(resumable.id)
                _log.info("Continued recording %s after a recorder restart", resumable.id)
            except ApiError as error:
                _log.error("Could not continue %s: %s", resumable.id, error.message)
                mark_stopped(self.live / resumable.id, "recorder_died", now)
        self._ticker.start()

    def close(self) -> None:
        """Stop a recording in progress (everything written), end the event streams."""
        with self._lock:
            if self._current is not None and self._current.manifest.active:
                try:
                    self._stop_current("recorder_closed")
                except ApiError:
                    _log.exception("Stopping the recording at shutdown failed")
        self._closed.set()
        self.events.close()

    # -- observer (called by the recording) ---------------------------------------------------

    def on_status(self, summary: dict[str, Any]) -> None:
        self.events.publish("status", summary)

    def on_level(self, channel: Channel, rms_db: float) -> None:
        self.events.publish("level", {"channel": channel.value, "rms_db": round(rms_db, 1)})

    def on_error(self, code: str, message: str) -> None:
        self.events.publish("error", {"code": code, "message": message})

    def on_sources(self, sources: list[dict[str, Any]]) -> None:
        current = self._current
        self.events.publish(
            "sources", {"id": current.id if current is not None else None, "items": sources}
        )

    # -- routes -------------------------------------------------------------------------------

    def _routes(self) -> Router:
        router = Router()
        router.add("GET", "/health", self._health)
        router.add("GET", "/devices", self._devices)
        router.add("POST", "/recordings", self._start)
        router.add("GET", "/recordings", self._list)
        router.add("GET", "/recordings/current", self._get_current)
        router.add("PATCH", "/recordings/current", self._patch_current)
        router.add("POST", "/recordings/current/pause", self._pause)
        router.add("POST", "/recordings/current/resume", self._resume_capture)
        router.add("POST", "/recordings/current/stop", self._stop)
        router.add("GET", "/recordings/current/sources", self._get_sources)
        router.add("PUT", "/recordings/current/sources/{source_id}", self._put_source)
        router.add("GET", "/recordings/{id}", self._get)
        router.add("POST", "/recordings/{id}/resume", self._resume_route)
        router.add("DELETE", "/recordings/{id}", self._delete)
        router.add("GET", "/events", self._events)
        router.add("POST", "/shutdown", self._shutdown)
        return router

    def _health(self, params: dict[str, str], body: Any) -> Response:
        current = self._current
        return Response(
            body={
                "recorder": "ok",
                "version": __version__,
                "pid": os.getpid(),
                "started_at": self.started_at,
                "recording": current.summary() if current is not None else None,
            }
        )

    def _devices(self, params: dict[str, str], body: Any) -> Response:
        try:
            default_input = self._catalog.default_input()
            default_loopback = self._catalog.default_loopback()
            return Response(
                body={
                    "inputs": [_device(info) for info in self._catalog.inputs()],
                    "loopbacks": [_device(info) for info in self._catalog.loopbacks()],
                    "default_input_id": default_input.id if default_input else None,
                    "default_loopback_id": default_loopback.id if default_loopback else None,
                }
            )
        except (OSError, TimeoutError) as error:
            raise ApiError(503, "audio_unavailable", str(error)) from None

    def _start(self, params: dict[str, str], body: Any) -> Response:
        request = _object(body)
        mic = _optional_int(request, "mic_device_id")
        system = _optional_int(request, "system_device_id")
        options = request.get("options")
        options = {} if options is None else options
        if not isinstance(options, dict):
            raise ApiError(422, "invalid_options", "options must be an object")
        with self._lock:
            if self._current is not None and self._current.manifest.active:
                raise ApiError(409, "recording_already_active", "A recording is in progress")
            audio = self._open_audio()
            specs: list[SourceSpec] | None = None
            try:
                if self.settings.capture_sources == CAPTURE_ALL:
                    specs = resolve_sources(
                        audio.call, audio.pa, mic, system, self.settings.capture_exclude
                    )
                    if not specs:
                        raise OSError("No audio device was found")
                    devices = _main_devices(specs)
                else:
                    devices = resolve_devices(audio.call, audio.pa, mic, system)
            except LookupError as error:
                audio.close()
                raise ApiError(404, "device_not_found", str(error)) from None
            except (OSError, TimeoutError) as error:
                audio.close()
                raise ApiError(503, "audio_unavailable", str(error)) from None
            recording = Recording.create(
                self.live,
                self.settings,
                devices,
                self._source_factory(audio, self.settings.sample_rate),
                self,
                options=options,
                wall_clock=self._wall,
                time_source=self._time,
                sources=specs,
            )
            self._begin(recording, audio)
            return Response(201, recording.summary())

    def _list(self, params: dict[str, str], body: Any) -> Response:
        items = []
        for recording_id in list_recordings(self.settings.output_dir):
            current = self._current
            if current is not None and current.id == recording_id:
                items.append(current.summary())
                continue
            try:
                manifest = read_manifest(self.live / recording_id)
            except (OSError, ValueError):
                continue
            items.append(
                {
                    "id": manifest.id,
                    "status": manifest.status,
                    "started_at": manifest.started_at,
                    "duration_seconds": manifest.duration_seconds,
                    "devices": manifest.devices,
                    "incarnation": manifest.incarnation,
                    "segments": {n: len(s) for n, s in manifest.channels.items()},
                    "options": manifest.options,
                    "stop_reason": manifest.stop_reason,
                }
            )
        return Response(body={"items": items})

    def _get_current(self, params: dict[str, str], body: Any) -> Response:
        return Response(body=self._active().summary())

    def _patch_current(self, params: dict[str, str], body: Any) -> Response:
        options = _object(body).get("options")
        if not isinstance(options, dict):
            raise ApiError(422, "invalid_options", "options must be an object")
        recording = self._active()
        recording.update_options(options)
        return Response(body=recording.summary())

    def _pause(self, params: dict[str, str], body: Any) -> Response:
        recording = self._active()
        recording.pause()
        return Response(body=recording.summary())

    def _resume_capture(self, params: dict[str, str], body: Any) -> Response:
        recording = self._active()
        recording.resume_capture()
        return Response(body=recording.summary())

    def _stop(self, params: dict[str, str], body: Any) -> Response:
        with self._lock:
            self._active()
            return Response(body=self._stop_current("user"))

    def _get_sources(self, params: dict[str, str], body: Any) -> Response:
        recording = self._active()
        return Response(body={"id": recording.id, "items": recording.sources() or []})

    def _put_source(self, params: dict[str, str], body: Any) -> Response:
        mode = _object(body).get("mode")
        if mode not in MODES:
            raise ApiError(422, "invalid_mode", f"mode must be one of {', '.join(MODES)}")
        recording = self._active()
        if recording.sources() is None:
            raise ApiError(409, "sources_not_recorded", "This recording has one device per channel")
        try:
            recording.set_source_mode(params["source_id"], mode)
        except LookupError:
            raise ApiError(404, "source_not_found", f"No source {params['source_id']}") from None
        return Response(body={"id": recording.id, "items": recording.sources() or []})

    def _get(self, params: dict[str, str], body: Any) -> Response:
        folder = self._folder(params["id"])
        return Response(body=read_manifest(folder).to_json())

    def _resume_route(self, params: dict[str, str], body: Any) -> Response:
        self._folder(params["id"])
        return Response(body=self._resume(params["id"]))

    def _delete(self, params: dict[str, str], body: Any) -> Response:
        folder = self._folder(params["id"])
        if read_manifest(folder).active:
            raise ApiError(409, "recording_active", "An active recording cannot be deleted")
        shutil.rmtree(folder)
        return Response(204)

    def _events(self, params: dict[str, str], body: Any) -> Stream:
        client = self.events.subscribe()

        def stream() -> Iterator[tuple[str, Any] | None]:
            try:
                current = self._current
                yield ("status", current.summary() if current is not None else _idle())
                while not self._closed.is_set():
                    try:
                        item = client.get(timeout=self._keep_alive)
                    except queue.Empty:
                        yield None
                        continue
                    if item is None:
                        return
                    yield item
            finally:
                self.events.unsubscribe(client)

        return Stream(stream)

    def _shutdown(self, params: dict[str, str], body: Any) -> Response:
        current = self._current
        if current is not None and current.manifest.active:
            raise ApiError(409, "recording_active", "Stop the recording first")
        self.shutdown_requested.set()
        return Response(202, {"shutting_down": True})

    # -- helpers ------------------------------------------------------------------------------

    def _open_audio(self) -> AudioThread:
        try:
            return self._audio_factory()
        except (OSError, TimeoutError) as error:
            raise ApiError(503, "audio_unavailable", str(error)) from None

    def _begin(self, recording: Recording, audio: AudioThread) -> None:
        try:
            recording.start()
        except RecordingError as error:
            audio.close()
            raise ApiError(503, error.code, str(error)) from None
        self._current = recording
        self._audio = audio

    def _resume(self, recording_id: str) -> dict[str, Any]:
        with self._lock:
            if self._current is not None and self._current.manifest.active:
                raise ApiError(409, "recording_already_active", "A recording is in progress")
            folder = self.live / recording_id
            manifest = read_manifest(folder)
            if not manifest.active:
                raise ApiError(409, "recording_stopped", f"Recording {recording_id} was stopped")
            audio = self._open_audio()
            specs: list[SourceSpec] | None = None
            if manifest.sources:
                specs = self._sources_of(audio, manifest.sources)
                devices = _main_devices(specs) or self._devices_of(audio, manifest.devices)
            else:
                devices = self._devices_of(audio, manifest.devices)
            try:
                recording = Recording.resume(
                    folder,
                    self.settings,
                    devices,
                    self._source_factory(audio, self.settings.sample_rate),
                    self,
                    wall_clock=self._wall,
                    time_source=self._time,
                    sources=specs,
                )
            except RecordingError as error:
                audio.close()
                raise ApiError(409, error.code, str(error)) from None
            self._begin(recording, audio)
            return recording.summary()

    def _devices_of(self, audio: AudioThread, saved: dict[str, Any]) -> dict[Channel, DeviceInfo]:
        """The recording's devices, else the defaults (a replugged device can change id)."""
        mic, system = (saved.get(c.value, {}).get("id") for c in (Channel.MIC, Channel.SYSTEM))
        try:
            return resolve_devices(audio.call, audio.pa, mic, system)
        except (LookupError, OSError, TimeoutError):
            _log.warning("The recording's devices are gone; using the default devices")
        try:
            return resolve_devices(audio.call, audio.pa, None, None)
        except (LookupError, OSError, TimeoutError) as error:
            audio.close()
            raise ApiError(503, "audio_unavailable", str(error)) from None

    def _sources_of(self, audio: AudioThread, saved: dict[str, Any]) -> list[SourceSpec]:
        """The saved sources still plugged in (found by name), for a resume."""
        try:
            specs = resolve_sources(audio.call, audio.pa, None, None)
        except (LookupError, OSError, TimeoutError) as error:
            audio.close()
            raise ApiError(503, "audio_unavailable", str(error)) from None
        found = match_saved(saved, specs)
        preferred = {i for i, entry in saved.items() if entry.get("preferred")}
        return [
            SourceSpec(spec.source_id, spec.kind, spec.device, spec.source_id in preferred)
            for spec in found.values()
        ]

    def _stop_current(self, reason: str) -> dict[str, Any]:
        recording, audio = self._current, self._audio
        assert recording is not None
        try:
            recording.stop(reason)
        except TrackWriteError as error:  # stopped; the writer threads keep trying
            _log.error("Recording %s stopped with audio not yet on disk: %s", recording.id, error)
        finally:
            if audio is not None:
                try:
                    audio.close()
                except Exception:
                    _log.exception("Releasing the audio backend failed")
            self._audio = None
        return recording.summary()

    def _active(self) -> Recording:
        current = self._current
        if current is None or not current.manifest.active:
            raise ApiError(404, "no_active_recording", "Nothing is being recorded")
        return current

    def _folder(self, recording_id: str) -> Path:
        folder = self.live / recording_id
        if "/" in recording_id or "\\" in recording_id or recording_id.startswith("."):
            raise ApiError(404, "recording_not_found", f"No recording {recording_id}")
        if not (folder / "recording.json").is_file():
            raise ApiError(404, "recording_not_found", f"No recording {recording_id}")
        return folder

    def _tick(self) -> None:
        while not self._closed.wait(STATUS_INTERVAL):
            current = self._current
            if current is not None and current.manifest.active:
                self.events.publish("status", current.summary())


def _device(info: DeviceInfo) -> dict[str, Any]:
    return {
        "id": info.id,
        "name": info.name,
        "sample_rate": info.sample_rate,
        "channels": info.channels,
    }


def _main_devices(specs: list[SourceSpec]) -> dict[Channel, DeviceInfo]:
    """The device named for each channel: its preferred source, else its first one."""
    devices: dict[Channel, DeviceInfo] = {}
    for spec in sorted(specs, key=lambda spec: not spec.preferred):
        devices.setdefault(spec.kind, spec.device)
    return devices


def _idle() -> dict[str, Any]:
    return {"id": None, "status": "idle", "duration_seconds": 0}


def _object(body: Any) -> dict[str, Any]:
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(422, "invalid_body", "The body must be a JSON object")
    return body


def _optional_int(request: dict[str, Any], key: str) -> int | None:
    value = request.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(422, "invalid_device", f"{key} must be an integer")
    return value
