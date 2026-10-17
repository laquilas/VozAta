"""Live translation inside a recording session (phase 29)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from tests.fakes import FakeTranslator
from tests.test_session import _Rig, _voice, _words
from vozata.domain import SessionStatus
from vozata.ports import TranslationError, Translator
from vozata.storage.files.translations import read_translations


def _with_translation(rig: _Rig, translator: Translator, target: str = "pt") -> None:
    rig.session._c = dataclasses.replace(
        rig.session._c, translate_to=target, translator_factory=lambda: translator
    )


def test_committed_segments_are_translated_to_the_file_and_the_observer(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, results=[_words("Hello", " world.")])
    translator = FakeTranslator()
    _with_translation(rig, translator)
    rig.session.start()
    rig.mic.push(_voice(1.0), 0.0)

    rig.session.stop()

    assert rig.observer.of("translation") == [("mic-000001", "pt", "[pt] Hello world.")]
    translations = read_translations(rig.paths.translated_jsonl)
    assert translations["mic-000001"].text == "[pt] Hello world."
    assert translator.calls == [("Hello world.", "en", "pt")]
    assert translator.closed
    names = [event[0] for event in rig.observer.events]
    assert names.index("translation") < names.index("status", names.index("segment") + 1)


def test_a_meeting_already_in_the_target_language_is_not_translated(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, results=[_words("Hello.")])
    translator = FakeTranslator()
    _with_translation(rig, translator, target="en")
    rig.session.start()
    rig.mic.push(_voice(1.0), 0.0)

    rig.session.stop()

    assert translator.calls == []
    assert not rig.paths.translated_jsonl.exists()


def test_a_failing_translator_reports_once_and_transcription_continues(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, results=[_words("One."), _words("Two.")])
    _with_translation(rig, FakeTranslator(error=TranslationError("model missing")))
    rig.session.start()
    rig.mic.push(_voice(1.0), 0.0)
    rig.mic.push(_voice(1.0), 1.0)

    rig.session.stop()

    [(code, message)] = rig.observer.of("error")
    assert code == "translation_failed"
    assert "model missing" in message
    assert [s.text for (s,) in rig.observer.of("segment")] == ["One.", "Two."]
    assert rig.session.status is SessionStatus.DONE


def test_without_a_target_no_worker_runs(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, results=[_words("Hello.")])
    rig.session.start()
    rig.mic.push(_voice(1.0), 0.0)

    rig.session.stop()

    assert rig.observer.of("translation") == []
    assert not rig.paths.translated_jsonl.exists()
