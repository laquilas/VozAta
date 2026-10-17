"""Terminal `SessionObserver`: transcript lines plus a one-line level meter."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TextIO

from vozata.domain import Channel, ConversationLanguage, SessionStatus, TranscriptSegment
from vozata.formatting import format_timestamp, render_line
from vozata.labels import SpeakerLabeler
from vozata.ports import Localizer

METER_CELLS = 8
METER_FLOOR_DB = -60.0
METER_INTERVAL = 0.2  # seconds between meter redraws


def meter_bar(rms_db: float) -> str:
    """`[####....]`: -60 dBFS (or less) is empty, 0 dBFS is full."""
    fraction = (rms_db - METER_FLOOR_DB) / -METER_FLOOR_DB
    filled = max(0, min(METER_CELLS, round(fraction * METER_CELLS)))
    return "[" + "#" * filled + "." * (METER_CELLS - filled) + "]"


class ConsoleObserver:
    """Print session events; thread-safe (events arrive from capture and worker threads).

    On a terminal, the meter line `hh:mm:ss  Me [####....]  Others [##......]` is redrawn in
    place and cleared before every printed line. Redirected output gets the lines only.
    """

    def __init__(
        self,
        localizer: Localizer,
        labeler: SpeakerLabeler,
        stream: TextIO,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._t = localizer.t
        self._labeler = labeler
        self._stream = stream
        self._clock = clock
        self._meter = stream.isatty()
        self._lock = threading.Lock()
        self._levels = {channel: METER_FLOOR_DB for channel in Channel}
        self._status: SessionStatus | None = None
        self._started_at: float | None = None
        self._drawn_at = float("-inf")
        self._meter_width = 0

    def say(self, text: str) -> None:
        """Print a full line (also used by the CLI for its own messages)."""
        with self._lock:
            self._print(text)

    def on_status(self, status: SessionStatus, duration_seconds: float) -> None:
        with self._lock:
            previous, self._status = self._status, status
            if self._started_at is None:
                self._started_at = self._clock() - duration_seconds
            if status is SessionStatus.PAUSED:
                self._print(self._t("cli.paused"))
            elif status is SessionStatus.RECORDING and previous is SessionStatus.PAUSED:
                self._print(self._t("cli.resumed"))
            elif status is SessionStatus.FINALIZING:
                self._clear_meter()
                self._meter = False
                self._print(self._t("cli.finalizing"))

    def on_level(self, channel: Channel, rms_db: float) -> None:
        with self._lock:
            self._levels[channel] = rms_db
            now = self._clock()
            if self._meter and now - self._drawn_at >= METER_INTERVAL:
                self._drawn_at = now
                self._draw_meter()

    def on_segment(self, segment: TranscriptSegment) -> None:
        with self._lock:
            self._print(render_line(segment, self._labeler.label(segment.speaker_id)))

    def on_language_detected(self, language: ConversationLanguage) -> None:
        with self._lock:
            name = self._t(f"languages.{language.value}")
            self._print(self._t("cli.language_detected", language=name))

    def on_minutes_ready(self, session_id: str) -> None:
        with self._lock:
            self._print(self._t("cli.minutes_ready"))

    def on_speakers_relabeled(self, session_id: str) -> None:
        pass  # the console already printed the live lines; the files hold the final speakers

    def on_partial(self, channel: Channel, speaker_id: str, start: float, text: str) -> None:
        pass  # interim text is a desktop feature (phase 28 scope)

    def on_model_loading(self, loading: bool) -> None:
        with self._lock:
            self._print(self._t("cli.loading_model" if loading else "cli.model_ready"))

    def on_translation(self, segment_id: str, language: str, text: str) -> None:
        with self._lock:
            self._print(f"    ({language}) {text}")  # under its line (phase 29)

    def on_error(self, code: str, message: str) -> None:
        with self._lock:
            self._print(message)

    def _print(self, text: str) -> None:
        self._clear_meter()
        self._stream.write(text + "\n")
        if self._meter and self._status is not None:
            self._draw_meter()
        self._stream.flush()

    def _draw_meter(self) -> None:
        elapsed = self._clock() - (self._started_at or self._clock())
        parts = [format_timestamp(elapsed)]
        for channel in Channel:
            parts.append(f"{self._labeler.label(channel.value)} {meter_bar(self._levels[channel])}")
        if self._status is SessionStatus.PAUSED:
            parts.append(self._t("cli.paused_marker"))
        line = "  ".join(parts)
        padding = " " * max(0, self._meter_width - len(line))
        self._stream.write("\r" + line + padding)
        self._stream.flush()
        self._meter_width = len(line)

    def _clear_meter(self) -> None:
        if self._meter_width:
            self._stream.write("\r" + " " * self._meter_width + "\r")
            self._meter_width = 0
