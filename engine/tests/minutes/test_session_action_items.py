from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from tests.fakes import FakeLocalizer
from vozata.domain import ActionItem, Channel, ConversationLanguage, TranscriptSegment
from vozata.labels import SpeakerLabeler
from vozata.minutes.session_action_items import write_session_action_items
from vozata.minutes.session_minutes import EmptyTranscriptError
from vozata.storage.action_items import read_action_items, write_action_items
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.session_store import SessionStore


class _Extractor:
    def __init__(self, items: list[ActionItem]) -> None:
        self.items = items
        self.calls: list[tuple] = []

    def extract(
        self,
        segments: Sequence[TranscriptSegment],
        labeler: SpeakerLabeler,
        conversation_language: ConversationLanguage,
        vocabulary: Sequence[str] = (),
        meeting_date: str | None = None,
    ) -> list[ActionItem]:
        self.calls.append(
            (len(segments), labeler.label("mic"), conversation_language, vocabulary, meeting_date)
        )
        return self.items


def _session(store: SessionStore, meta: dict, *, transcript: bool = True) -> str:
    paths = store.create()
    store.write_meta(paths.id, meta)
    if transcript:
        segment = TranscriptSegment("mic-000001", Channel.MIC, "mic", 1.0, 2.0, "Olá.", ())
        paths.transcript_jsonl.write_text(json.dumps(segment.to_dict()) + "\n", encoding="utf-8")
    return paths.id


def test_items_are_extracted_with_the_stored_context_and_saved(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session_id = _session(
        store,
        {"language": "pt", "vocabulary": ["Avalonia", 3], "started_at": "2026-10-15T20:23:58"},
    )
    store.rename_speakers(session_id, {"mic": "Ana"})
    extractor = _Extractor([ActionItem("a1", "Send")])

    items = write_session_action_items(
        FileSessionRepository(store), session_id, extractor, SpeakerLabeler(FakeLocalizer())
    )

    assert items == [ActionItem("a1", "Send")]
    assert read_action_items(store.paths(session_id)) == items
    assert extractor.calls == [(1, "Ana", ConversationLanguage.PT, ["Avalonia"], "2026-10-15")]


def test_exported_items_are_kept_and_new_ids_do_not_collide(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session_id = _session(store, {})
    exported = ActionItem("a1", "Old", exported_url="https://example.test/1")
    write_action_items(store.paths(session_id), [exported, ActionItem("a2", "Not exported")])
    extractor = _Extractor([ActionItem("a1", "New one"), ActionItem("a2", "New two")])

    items = write_session_action_items(
        FileSessionRepository(store), session_id, extractor, SpeakerLabeler(FakeLocalizer())
    )

    assert [(item.id, item.description) for item in items] == [
        ("a1", "Old"),
        ("a2", "New one"),
        ("a3", "New two"),
    ]
    assert extractor.calls[0][2] is ConversationLanguage.AUTO
    assert extractor.calls[0][4] is None  # no started_at


def test_an_empty_transcript_raises_and_writes_nothing(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session_id = _session(store, {}, transcript=False)

    with pytest.raises(EmptyTranscriptError):
        write_session_action_items(
            FileSessionRepository(store),
            session_id,
            _Extractor([]),
            SpeakerLabeler(FakeLocalizer()),
        )
    assert not store.paths(session_id).action_items_json.exists()
