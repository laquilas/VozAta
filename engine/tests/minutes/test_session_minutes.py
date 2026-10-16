from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fakes import FakeLanguageModel, FakeLocalizer
from vozata.domain import Channel, TranscriptSegment
from vozata.labels import SpeakerLabeler
from vozata.minutes.generator import MinutesGenerator
from vozata.minutes.session_minutes import EmptyTranscriptError, write_session_minutes
from vozata.ports import LanguageModelError
from vozata.storage.session_store import SessionNotFoundError, SessionStore


class _Failing(FakeLanguageModel):
    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
        raise LanguageModelError("offline")


def _session(store: SessionStore, meta: dict, *, transcript: bool = True) -> str:
    paths = store.create()
    store.write_meta(paths.id, meta)
    if transcript:
        segment = TranscriptSegment("mic-000001", Channel.MIC, "mic", 1.0, 2.0, "Olá.", ())
        paths.transcript_jsonl.write_text(json.dumps(segment.to_dict()) + "\n", encoding="utf-8")
    return paths.id


def _generator(llm: FakeLanguageModel) -> MinutesGenerator:
    return MinutesGenerator(llm, FakeLocalizer(), 12000)


def test_writes_minutes_in_the_stored_language(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session_id = _session(store, {"language": "pt"})
    llm = FakeLanguageModel(["# Ata"])

    path = write_session_minutes(
        store, session_id, _generator(llm), SpeakerLabeler(FakeLocalizer())
    )

    assert path == store.paths(session_id).minutes_md
    assert path.read_text(encoding="utf-8") == "# Ata\n"
    assert "languages.pt" in llm.prompts[0][1]


def test_without_a_stored_language_auto_is_used(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session_id = _session(store, {})
    llm = FakeLanguageModel(["# Minutes"])

    write_session_minutes(store, session_id, _generator(llm), SpeakerLabeler(FakeLocalizer()))

    assert "languages.auto" in llm.prompts[0][1]


def test_errors_propagate_and_nothing_is_written(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    labeler = SpeakerLabeler(FakeLocalizer())
    empty = _session(store, {}, transcript=False)
    failing = _session(store, {})

    with pytest.raises(EmptyTranscriptError):
        write_session_minutes(store, empty, _generator(FakeLanguageModel()), labeler)
    with pytest.raises(LanguageModelError):
        write_session_minutes(store, failing, _generator(_Failing()), labeler)
    with pytest.raises(SessionNotFoundError):
        write_session_minutes(store, "20991231_000000", _generator(FakeLanguageModel()), labeler)

    assert not store.paths(failing).minutes_md.exists()
