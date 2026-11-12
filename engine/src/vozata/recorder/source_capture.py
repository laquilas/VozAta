"""Record every source of a recording and mix the selected ones into its channels (phase 65).

Each source has its own `DurableTrack` under `sources/` (nothing is lost whatever the selection)
and feeds a `SourceMixer`; a mix thread writes the mixed blocks to the `mic` / `system` tracks.
The preferred sources open first so the recording starts at once; the others open in the
background, and a source that fails or hangs is skipped and reported.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from vozata.audio.levels import rms_db
from vozata.audio.opener import SourceOpenTimeoutError, open_with_timeout
from vozata.domain import Channel
from vozata.heartbeat import Heartbeat
from vozata.ports import AudioSource
from vozata.recorder.durable_track import DurableTrack
from vozata.recorder.manifest import REASON_START, SOURCES_FOLDER, Manifest
from vozata.recorder.settings import RecorderSettings
from vozata.recorder.source_mix import AUTO, SelectionChange, SourceMixer, SourceSelector
from vozata.recorder.sources import SourceSpec

_log = logging.getLogger(__name__)

STEP_SECONDS = 0.1
REPORT_EVERY = 5  # steps between two `sources` events
OPEN, FAILED, PENDING, GONE = "open", "failed", "pending", "gone"


class Clock(Protocol):
    def now(self) -> float: ...


class SourceObserver(Protocol):
    def on_level(self, channel: Channel, rms_db: float) -> None: ...

    def on_error(self, code: str, message: str) -> None: ...

    def on_sources(self, sources: list[dict[str, Any]]) -> None: ...


class NoSourceError(RuntimeError):
    """Not one source could be opened."""


SourceFactory = Callable[[Any, Clock], AudioSource]
MixedWriter = Callable[[Channel, np.ndarray, float], None]


class SourceCapture:
    def __init__(
        self,
        folder: Path,
        manifest: Manifest,
        specs: Sequence[SourceSpec],
        settings: RecorderSettings,
        lock: threading.RLock,
        save: Callable[[], None],
        source_factory: SourceFactory,
        clock: Clock,
        observer: SourceObserver,
        write_mixed: MixedWriter,
        start_frames: Mapping[str, int] | None = None,
        mix_start: int = 0,
        first_reason: str = REASON_START,
        resumed: bool = False,
    ) -> None:
        self._manifest = manifest
        self._specs = list(specs)
        self._settings = settings
        self._lock = lock
        self._save = save
        self._clock = clock
        self._observer = observer
        self._write_mixed = write_mixed
        self._levels: dict[str, float] = {}
        self._opened: dict[str, AudioSource] = {}
        self._accepting = False
        self._steps = 0
        self._warned_silent = False
        self._opener: threading.Thread | None = None
        folder.mkdir(parents=True, exist_ok=True)
        frames = start_frames or {}
        for spec in self._specs:
            entry = manifest.sources.setdefault(spec.source_id, {})
            entry.update(
                kind=spec.kind.value,
                name=spec.name,
                device_id=spec.device.id,
                preferred=spec.preferred,
                state=PENDING,
                error=None,
            )
            entry.setdefault("mode", AUTO)
            entry.setdefault("segments", [])
        modes = {spec.source_id: manifest.sources[spec.source_id]["mode"] for spec in self._specs}
        previous = (
            [i for i, entry in manifest.sources.items() if entry.get("selected")]
            if resumed
            else None
        )
        selector = SourceSelector(self._specs, modes, previous)
        self._mixer = SourceMixer(self._specs, settings.sample_rate, mix_start, selector)
        self._mark_selection(selector.selected)
        self.tracks = {
            spec.source_id: DurableTrack(
                folder,
                spec.source_id,
                settings.sample_rate,
                manifest.source_segments(spec.source_id),
                lock,
                save,
                fsync_seconds=settings.fsync_seconds,
                max_segment_bytes=settings.max_segment_bytes,
                start_frame=frames.get(spec.source_id, 0),
                first_reason=first_reason,
            )
            for spec in self._specs
        }
        self._sources = {spec.source_id: source_factory(spec.device, clock) for spec in self._specs}
        self._beat = Heartbeat(STEP_SECONDS, self.step, name="source-mix")

    @staticmethod
    def folder_of(recording_folder: Path) -> Path:
        return recording_folder / SOURCES_FOLDER

    # -- control ------------------------------------------------------------------------------

    def start(self) -> None:
        """Open the preferred sources (else the others) now, the rest in the background.

        `NoSourceError` when nothing opens.
        """
        for track in self.tracks.values():
            track.start()
        self._accepting = True
        first = [spec for spec in self._specs if spec.preferred]
        rest = [spec for spec in self._specs if not spec.preferred]
        opened = [spec for spec in first if self._open(spec)]
        if not opened:
            opened = [spec for spec in rest if self._open(spec)]
            rest = []
        if not opened:
            self._accepting = False
            raise NoSourceError("No audio device could be opened")
        self._beat.start()
        if rest:
            self._opener = threading.Thread(
                target=self._open_rest, args=(rest,), name="open-sources", daemon=True
            )
            self._opener.start()
        self._report()

    def stop_sources(self) -> None:
        """Stop capturing (every source); the buffered audio is still mixed by `finish`."""
        self._accepting = False
        if self._opener is not None:
            self._opener.join(1.0)  # a hung open is left behind: its source stops when it opens
        for source_id, source in list(self._opened.items()):
            try:
                source.stop()
            except Exception:
                _log.exception("Stopping source %s failed", source_id)
        self._opened.clear()

    def finish(self) -> None:
        """Stop the mix thread and mix everything captured."""
        self._beat.stop()
        self._emit(*self._mixer.step(self._clock.now(), final=True))
        self._report()

    def set_paused(self, paused: bool) -> None:
        for track in self.tracks.values():
            track.paused = paused

    def set_mode(self, source_id: str, mode: str) -> None:
        """Auto / On / Off for one source; `KeyError` / `ValueError` for a bad id or mode."""
        change = self._mixer.set_mode(source_id, mode)
        with self._lock:
            self._manifest.sources[source_id]["mode"] = mode
            if change is not None:
                self._log_changes([change])
            self._save()
        self._report()

    def step(self) -> None:
        """One mix step (the mix thread runs it every 0.1 s)."""
        self._emit(*self._mixer.step(self._clock.now()))

    def summary(self) -> list[dict[str, Any]]:
        scores = self._mixer.scores()
        selected = self._mixer.selected()
        items = []
        with self._lock:
            for spec in self._specs:
                entry = self._manifest.sources[spec.source_id]
                score = scores[spec.source_id]
                items.append(
                    {
                        "id": spec.source_id,
                        "kind": spec.kind.value,
                        "name": spec.name,
                        "mode": entry["mode"],
                        "selected": spec.source_id in selected,
                        "preferred": spec.preferred,
                        "state": entry["state"],
                        "error": entry.get("error"),
                        "rms_db": round(self._levels.get(spec.source_id, -90.0), 1),
                        "score": round(score.value, 3),
                        "silent": score.silent,
                    }
                )
        return items

    @property
    def pending_seconds(self) -> float:
        return max((track.pending_seconds for track in self.tracks.values()), default=0.0)

    # -- internals ----------------------------------------------------------------------------

    def _open(self, spec: SourceSpec) -> bool:
        if not self._accepting:
            return False
        try:
            open_with_timeout(
                self._sources[spec.source_id],
                self._receiver(spec),
                self._settings.open_timeout,
                lambda: self._accepting,
            )
        except SourceOpenTimeoutError:
            self._failed(spec, f"{spec.name} did not open")
            return False
        except Exception as error:
            self._failed(spec, f"{spec.name}: {error}")
            return False
        self._opened[spec.source_id] = self._sources[spec.source_id]
        with self._lock:
            self._manifest.sources[spec.source_id]["state"] = OPEN
            self._save()
        return True

    def _open_rest(self, specs: Sequence[SourceSpec]) -> None:
        for spec in specs:
            if not self._accepting:
                return
            self._open(spec)
        self._report()

    def _failed(self, spec: SourceSpec, message: str) -> None:
        _log.warning("Source %s skipped: %s", spec.source_id, message)
        with self._lock:
            entry = self._manifest.sources[spec.source_id]
            entry["state"] = FAILED
            entry["error"] = message
            self._save()
        self._observer.on_error("source_failed", message)

    def _receiver(self, spec: SourceSpec) -> Callable[[np.ndarray, float], None]:
        track = self.tracks[spec.source_id]

        def on_samples(samples: np.ndarray, at: float) -> None:
            if not self._accepting:
                return
            track.write(samples, at)
            self._mixer.push(spec.source_id, samples, at)
            level = rms_db(samples)
            self._levels[spec.source_id] = level
            if spec.source_id in self._mixer.selector.selected:
                self._observer.on_level(spec.kind, level)

        return on_samples

    def _emit(
        self, blocks: dict[Channel, tuple[np.ndarray, float]], changes: list[SelectionChange]
    ) -> None:
        for channel, (samples, at) in blocks.items():
            self._write_mixed(channel, samples, at)
        if changes:
            with self._lock:
                self._log_changes(changes)
                self._save()
        self._steps += 1
        if changes or self._steps % REPORT_EVERY == 0:
            self._report()
            self._check_silence()

    def _log_changes(self, changes: Sequence[SelectionChange]) -> None:
        at = round(self._clock.now(), 3)
        for change in changes:
            self._manifest.selection_log.append(
                {"at": at, "source": change.source_id, "selected": change.selected, "by": change.by}
            )
        self._mark_selection(self._mixer.selector.selected)

    def _mark_selection(self, selected: set[str]) -> None:
        for spec in self._specs:
            self._manifest.sources[spec.source_id]["selected"] = spec.source_id in selected

    def _check_silence(self) -> None:
        scores = self._mixer.scores()
        open_ids = [i for i in self._opened if i in scores]
        silent = bool(open_ids) and all(scores[i].silent for i in open_ids)
        if silent and not self._warned_silent:
            self._observer.on_error("all_sources_silent", "Every audio device gives only silence")
        self._warned_silent = silent

    def _report(self) -> None:
        try:
            self._observer.on_sources(self.summary())
        except Exception:
            _log.exception("Reporting the sources failed")
