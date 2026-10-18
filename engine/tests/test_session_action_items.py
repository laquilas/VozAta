"""Stop step 6 (phase 23): action items are extracted after the minutes."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from tests.fakes import FakeLanguageModel, FakeLocalizer
from tests.test_session import _Rig, _voice, _words
from vozata.domain import SessionStatus
from vozata.minutes.action_items import ActionItemExtractor
from vozata.ports import LanguageModelError
from vozata.storage.action_items import read_action_items

REPLY = json.dumps(
    {
        "items": [
            {
                "description": "Send the budget",
                "owner": "Me",
                "due": None,
                "source_segment_ids": ["mic-000001"],
            }
        ]
    }
)


def _rig(tmp_path: Path, llm: FakeLanguageModel, **kwargs: object) -> _Rig:
    rig = _Rig(tmp_path, **kwargs)  # type: ignore[arg-type]
    extractor = ActionItemExtractor(llm, FakeLocalizer(), 12000)
    rig.session._c = dataclasses.replace(rig.session._c, action_items=extractor)
    return rig


def test_stop_extracts_action_items_after_the_minutes(tmp_path: Path) -> None:
    llm = FakeLanguageModel([REPLY])
    rig = _rig(tmp_path, llm, results=[_words("Send", " the", " budget.")])
    rig.session.start()
    rig.mic.push(_voice(1.0), 0.0)

    rig.session.stop()

    [item] = read_action_items(rig.store.paths(rig.session.id))
    assert (item.id, item.description, item.source_segment_ids) == (
        "a1",
        "Send the budget",
        ("mic-000001",),
    )
    names = [event[0] for event in rig.observer.events]
    assert names.index("minutes_ready") < names.index("action_items_ready")
    assert rig.observer.of("action_items_ready") == [(rig.session.id, 1)]
    assert "action_items.meeting_date(date=2026-10-15)" in llm.prompts[0][1]
    assert llm.releases == 1


def test_a_failed_extraction_is_reported_and_the_session_still_finishes(tmp_path: Path) -> None:
    llm = FakeLanguageModel(["nope", "still nope"])
    rig = _rig(tmp_path, llm, results=[_words("Hi.")])
    rig.session.start()
    rig.mic.push(_voice(1.0), 0.0)

    rig.session.stop()

    [(code, message)] = rig.observer.of("error")
    assert code == "action_items_failed"
    assert "valid action items" in message
    assert rig.observer.of("action_items_ready") == []
    assert rig.paths.minutes_md.is_file()
    assert rig.session.status is SessionStatus.DONE


def test_an_unreachable_model_is_reported(tmp_path: Path) -> None:
    class Down(FakeLanguageModel):
        def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
            raise LanguageModelError("connection refused")

    rig = _rig(tmp_path, Down(), results=[_words("Hi.")], with_minutes=False)
    rig.session.start()
    rig.mic.push(_voice(1.0), 0.0)

    rig.session.stop()

    [(code, message)] = rig.observer.of("error")
    assert code == "action_items_failed"
    assert "connection refused" in message


def test_a_silent_session_has_no_action_items_and_no_error(tmp_path: Path) -> None:
    llm = FakeLanguageModel([REPLY])
    rig = _rig(tmp_path, llm)
    rig.session.start()

    rig.session.stop()

    assert llm.prompts == []
    assert rig.observer.of("error") == []
    assert rig.observer.of("action_items_ready") == []
