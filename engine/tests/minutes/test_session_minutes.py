from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.fakes import FakeLanguageModel, FakeLocalizer, minutes_template
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


def _generator(llm: FakeLanguageModel) -> Callable[[str | None], MinutesGenerator]:
    def build(template: str | None) -> MinutesGenerator:
        built.append(template)
        return MinutesGenerator(
            llm, FakeLocalizer(), 12000, minutes_template(template_id=template or "general")
        )

    built: list[str | None] = []
    build.built = built  # type: ignore[attr-defined]
    return build


def test_the_requested_template_wins_and_is_stored(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session_id = _session(store, {"template": "daily", "status": "done"})
    llm = FakeLanguageModel(["# Client"])

    write_session_minutes(
        store, session_id, _generator(llm), SpeakerLabeler(FakeLocalizer()), "client"
    )

    assert "## Client needs" in llm.prompts[0][1]
    assert store.read_meta(session_id) == {"template": "client", "status": "done"}


def test_the_stored_template_is_used_when_none_is_requested(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session_id = _session(store, {"template": "daily"})
    build = _generator(FakeLanguageModel(["# Daily"]))

    write_session_minutes(store, session_id, build, SpeakerLabeler(FakeLocalizer()))

    assert build.built == ["daily"]  # type: ignore[attr-defined]
    assert store.read_meta(session_id) == {"template": "daily"}


def test_a_stored_template_that_is_no_longer_bundled_falls_back_to_the_default(
    tmp_path: Path,
) -> None:
    store = SessionStore(tmp_path)
    removed = _session(store, {"template": "weekly"})
    missing = _session(store, {})
    build = _generator(FakeLanguageModel(["# A", "# B"]))

    write_session_minutes(store, removed, build, SpeakerLabeler(FakeLocalizer()))
    write_session_minutes(store, missing, build, SpeakerLabeler(FakeLocalizer()))

    assert build.built == [None, None]  # type: ignore[attr-defined]
    assert store.read_meta(removed)["template"] == "general"
    assert store.read_meta(missing)["template"] == "general"


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


def test_diarized_speakers_appear_with_their_stored_names(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session_id = _session(store, {"language": "en"}, transcript=False)
    paths = store.paths(session_id)
    segment = TranscriptSegment("system-000001", Channel.SYSTEM, "system:1", 1.0, 2.0, "Hi.", ())
    paths.diarized_jsonl.write_text(json.dumps(segment.to_dict()) + "\n", encoding="utf-8")
    paths.speakers_json.write_text(json.dumps({"system:1": {"name": "Ana"}}), encoding="utf-8")
    llm = FakeLanguageModel(["# Minutes"])

    write_session_minutes(store, session_id, _generator(llm), SpeakerLabeler(FakeLocalizer()))

    assert "Ana: Hi." in llm.prompts[0][1]
