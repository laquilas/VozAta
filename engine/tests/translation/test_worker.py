from __future__ import annotations

import threading

from tests.fakes import FakeTranslator
from vozata.domain import Channel, TranscriptSegment, Translation
from vozata.ports import TranslationError, Translator
from vozata.translation.worker import TranslationWorker


def segment(segment_id: str, text: str = "hello") -> TranscriptSegment:
    return TranscriptSegment(segment_id, Channel.SYSTEM, "system", 0.0, 1.0, text, ())


class RecordingOutput:
    def __init__(self) -> None:
        self.items: list[Translation] = []
        self.closed = False

    def emit(self, translation: Translation) -> None:
        self.items.append(translation)

    def close(self) -> None:
        self.closed = True


class Harness:
    def __init__(
        self,
        translator: FakeTranslator | None = None,
        target: str = "pt",
        source: str | None = "en",
        load_error: Exception | None = None,
    ) -> None:
        self.translator = translator or FakeTranslator()
        self.source = source
        self.output = RecordingOutput()
        self.failures: list[Exception] = []
        self.load_error = load_error
        self.worker = TranslationWorker(
            self._load, target, lambda: self.source, self.output, self.failures.append
        )

    def _load(self) -> Translator:
        if self.load_error is not None:
            raise self.load_error
        return self.translator


def test_fake_translator_satisfies_the_port() -> None:
    assert isinstance(FakeTranslator(), Translator)


def test_translates_segments_in_queue_order() -> None:
    h = Harness()
    h.worker.start()
    for n in range(5):
        h.worker.emit(segment(f"system-{n:06d}", f"line {n}"))
    h.worker.close()

    assert [t.segment_id for t in h.output.items] == [f"system-{n:06d}" for n in range(5)]
    assert h.output.items[0] == Translation("system-000000", "pt", "[pt] line 0")
    assert h.translator.calls[0] == ("line 0", "en", "pt")
    assert h.output.closed
    assert h.translator.closed


def test_emit_never_waits_for_a_slow_translator() -> None:
    release = threading.Event()

    class Slow(FakeTranslator):
        def translate(self, text: str, source: str, target: str) -> str:
            release.wait(5)
            return super().translate(text, source, target)

    h = Harness(Slow())
    h.worker.start()
    for n in range(20):
        h.worker.emit(segment(f"s{n}"))  # returns at once although nothing is translated yet
    assert h.output.items == []
    release.set()
    h.worker.close()
    assert len(h.output.items) == 20


def test_skips_segments_already_in_the_target_language() -> None:
    h = Harness(target="en", source="en")
    h.worker.start()
    h.worker.emit(segment("a"))
    h.worker.close()

    assert h.output.items == []
    assert h.translator.calls == []


def test_skips_blank_text() -> None:
    h = Harness()
    h.worker.start()
    h.worker.emit(segment("a", "   "))
    h.worker.close()

    assert h.translator.calls == []


def test_segments_wait_until_the_language_is_known() -> None:
    h = Harness(source=None)
    gate = threading.Event()
    original = h.worker._translate_waiting

    def tracked() -> None:
        original()
        gate.set()

    h.worker._translate_waiting = tracked  # type: ignore[method-assign]
    h.worker.start()
    h.worker.emit(segment("a", "first"))
    assert gate.wait(5)
    assert h.output.items == []
    h.source = "en"
    h.worker.emit(segment("b", "second"))
    h.worker.close()

    assert [t.segment_id for t in h.output.items] == ["a", "b"]


def test_language_never_known_leaves_segments_untranslated() -> None:
    h = Harness(source=None)
    h.worker.start()
    h.worker.emit(segment("a"))
    h.worker.close()

    assert h.output.items == []
    assert h.translator.closed


def test_a_failing_translation_reports_once_and_disables_translation() -> None:
    error = TranslationError("model broke")
    h = Harness(FakeTranslator(error=error, fail_at=1))
    h.worker.start()
    for n in range(4):
        h.worker.emit(segment(f"s{n}"))
    h.worker.close()

    assert [t.segment_id for t in h.output.items] == ["s0"]
    assert h.failures == [error]
    assert h.worker.failed
    assert len(h.translator.calls) == 2  # nothing is tried after the failure
    assert h.translator.closed


def test_a_failing_load_reports_once_and_drops_every_segment() -> None:
    error = TranslationError("missing extra")
    h = Harness(load_error=error)
    h.worker.start()
    h.worker.emit(segment("a"))
    h.worker.emit(segment("b"))
    h.worker.close()
    h.worker.emit(segment("c"))  # after the failure: ignored

    assert h.failures == [error]
    assert h.output.items == []
    assert h.output.closed


def test_close_without_start_only_closes_the_output() -> None:
    h = Harness()
    h.worker.close()

    assert h.output.closed
    assert h.translator.calls == []


def test_a_failing_close_of_the_translator_is_logged() -> None:
    class BadClose(FakeTranslator):
        def close(self) -> None:
            raise RuntimeError("boom")

    h = Harness(BadClose())
    h.worker.start()
    h.worker.emit(segment("a"))
    h.worker.close()

    assert len(h.output.items) == 1
    assert h.output.closed
