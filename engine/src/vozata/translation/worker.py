"""The translation worker: its own thread and queue of committed segments (phase 29)."""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable
from typing import Protocol

from vozata.domain import TranscriptSegment, Translation
from vozata.ports import Translator

_log = logging.getLogger(__name__)
_STOP = object()


class TranslationOutput(Protocol):
    """Where translations go: `transcript.translated.jsonl` and the `translation` event."""

    def emit(self, translation: Translation) -> None: ...

    def close(self) -> None: ...


class TranslationWorker:
    """Translate committed segments into `target` without ever blocking transcription.

    It is a `TranscriptSink`: `emit` only enqueues. The thread started by `start()` builds the
    translator with `load` (model loading stays off the transcription thread), then translates the
    segments in order. `source()` is the session's conversation language; while it is None
    (`auto` not locked yet) segments wait and are translated once it is known. Segments already in
    `target` and blank texts are skipped. The first failure (load or translate) calls `on_failed`
    once and disables translation for the session; transcription is not affected. `close()`
    translates what is queued, then closes the translator and the output.
    """

    def __init__(
        self,
        load: Callable[[], Translator],
        target: str,
        source: Callable[[], str | None],
        output: TranslationOutput,
        on_failed: Callable[[Exception], None],
    ) -> None:
        self.target = target
        self._load = load
        self._source = source
        self._output = output
        self._on_failed = on_failed
        self._queue: queue.Queue[object] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="translation", daemon=True)
        self._translator: Translator | None = None
        self._waiting: list[TranscriptSegment] = []
        self.failed = False

    def start(self) -> None:
        self._thread.start()

    def emit(self, segment: TranscriptSegment) -> None:
        if not self.failed:
            self._queue.put(segment)

    def close(self) -> None:
        """Translate the queued segments, then release the translator and close the output."""
        if self._thread.is_alive():
            self._queue.put(_STOP)
            self._thread.join()
        self._output.close()

    def _run(self) -> None:
        try:
            self._translator = self._load()
        except Exception as error:
            self._fail(error)
        while (item := self._queue.get()) is not _STOP:
            if self._translator is not None and isinstance(item, TranscriptSegment):
                self._waiting.append(item)
                self._translate_waiting()
        self._translate_waiting()  # the language may have been locked after the last segment
        if self._waiting:
            _log.info(
                "%d segments left untranslated: the language was never known", len(self._waiting)
            )
        self._release()

    def _translate_waiting(self) -> None:
        source = self._source()
        if source is None:
            return
        waiting, self._waiting = self._waiting, []
        for segment in waiting:
            if self._translator is None:
                return
            self._translate(self._translator, segment, source)

    def _translate(self, translator: Translator, segment: TranscriptSegment, source: str) -> None:
        if source == self.target or not segment.text.strip():
            return
        try:
            text = translator.translate(segment.text, source, self.target)
        except Exception as error:
            self._fail(error)
            return
        self._output.emit(Translation(segment.segment_id, self.target, text))

    def _fail(self, error: Exception) -> None:
        _log.warning("Live translation stopped: %s", error)
        self.failed = True
        self._release()
        self._on_failed(error)

    def _release(self) -> None:
        translator, self._translator = self._translator, None
        if translator is None:
            return
        try:
            translator.close()
        except Exception:
            _log.exception("Releasing the translator failed")
