"""`/sessions/{id}/action-items` routes (phase 23) over the real app with fakes."""

from __future__ import annotations

import dataclasses
import json

from tests.api.conftest import Api
from tests.fakes import FakeTaskExporter
from vozata.domain import ActionItem, Channel, TranscriptSegment
from vozata.ports import TaskExportError
from vozata.storage.action_items import read_action_items, write_action_items

ITEMS = [
    ActionItem("a1", "Send the report", "Ana", "2026-10-20", ("mic-000002",)),
    ActionItem("a2", "Book the room"),
    ActionItem("a3", "Old task", exported_url="https://tasks.test/old"),
]


class _Rig:
    def __init__(self, api: Api) -> None:
        self.api = api
        self.exporter = FakeTaskExporter()
        self.extracted: list[str] = []
        self.targets = ["github"]
        api.app.state.container = dataclasses.replace(
            api.app.state.container,
            extract_action_items=self.extracted.append,
            task_targets=lambda: list(self.targets),
            task_exporter=lambda target: self.exporter if target in self.targets else None,
        )

    def session(self, items: list[ActionItem] = ITEMS) -> str:
        store = self.api.store
        paths = store.create()
        store.write_meta(paths.id, {"id": paths.id, "started_at": "2026-10-15T20:23:58-03:00"})
        segment = TranscriptSegment("mic-000002", Channel.MIC, "mic", 83.5, 85.0, "Report.", ())
        paths.transcript_jsonl.write_text(json.dumps(segment.to_dict()) + "\n", encoding="utf-8")
        write_action_items(paths, items)
        return paths.id

    def stored(self, session_id: str) -> list[ActionItem]:
        return read_action_items(self.api.store.paths(session_id))


def test_get_lists_items_and_configured_targets(api: Api) -> None:
    rig = _Rig(api)
    session_id = rig.session()

    response = api.client.get(f"/sessions/{session_id}/action-items")

    assert response.status_code == 200
    body = response.json()
    assert body["targets"] == ["github"]
    assert body["items"][0] == {
        "id": "a1",
        "description": "Send the report",
        "owner": "Ana",
        "due": "2026-10-20",
        "source_segment_ids": ["mic-000002"],
        "exported_url": None,
    }
    assert body["items"][2]["exported_url"] == "https://tasks.test/old"


def test_get_without_items_or_targets(api: Api) -> None:
    rig = _Rig(api)
    rig.targets = []
    session_id = rig.session([])

    assert api.client.get(f"/sessions/{session_id}/action-items").json() == {
        "items": [],
        "targets": [],
    }


def test_unknown_sessions_are_404(api: Api) -> None:
    _Rig(api)
    for method, path, body in (
        ("get", "/sessions/20990101_000000/action-items", None),
        ("post", "/sessions/20990101_000000/action-items", None),
        ("put", "/sessions/20990101_000000/action-items", {"items": []}),
        (
            "post",
            "/sessions/20990101_000000/action-items/export",
            {"target": "github", "item_ids": ["a1"]},
        ),
    ):
        response = api.client.request(method, path, json=body)
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "session_not_found"


def test_post_starts_an_extraction(api: Api) -> None:
    rig = _Rig(api)
    session_id = rig.session()

    response = api.client.post(f"/sessions/{session_id}/action-items")

    assert response.status_code == 202
    assert rig.extracted == [session_id]


def test_post_is_refused_while_the_session_records(api: Api) -> None:
    rig = _Rig(api)
    session_id = api.client.post("/sessions", json={}).json()["id"]

    response = api.client.post(f"/sessions/{session_id}/action-items")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "action_items_still_recording"
    assert rig.extracted == []


def test_post_without_an_extractor_is_503(api: Api) -> None:
    rig = _Rig(api)
    session_id = rig.session()
    api.app.state.container = dataclasses.replace(
        api.app.state.container, extract_action_items=None
    )

    response = api.client.post(f"/sessions/{session_id}/action-items")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "action_items_unavailable"


def test_put_saves_edits_but_never_changes_exported_items(api: Api) -> None:
    rig = _Rig(api)
    session_id = rig.session()

    response = api.client.put(
        f"/sessions/{session_id}/action-items",
        json={
            "items": [
                {"id": "a1", "description": " Send the final report ", "owner": "", "due": "Mon"},
                {"id": "a3", "description": "Changed", "owner": "Bob", "exported_url": None},
            ]
        },
    )

    assert response.status_code == 200
    items = rig.stored(session_id)
    assert items[0] == ActionItem("a1", "Send the final report", None, "Mon", ("mic-000002",))
    assert items[1] == ITEMS[1]
    assert items[2] == ITEMS[2]
    assert response.json()["items"][0]["description"] == "Send the final report"


def test_put_rejects_unknown_and_empty_items(api: Api) -> None:
    rig = _Rig(api)
    session_id = rig.session()
    url = f"/sessions/{session_id}/action-items"

    unknown = api.client.put(url, json={"items": [{"id": "a9", "description": "x"}]})
    empty = api.client.put(url, json={"items": [{"id": "a1", "description": "  "}]})

    assert (unknown.status_code, unknown.json()["error"]["code"]) == (422, "unknown_action_item")
    assert (empty.status_code, empty.json()["error"]["code"]) == (422, "empty_action_item")
    assert rig.stored(session_id) == ITEMS


def test_export_creates_tasks_and_saves_their_links(api: Api) -> None:
    rig = _Rig(api)
    session_id = rig.session()

    response = api.client.post(
        f"/sessions/{session_id}/action-items/export",
        json={"target": "github", "item_ids": ["a1", "a2", "a1"]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "created": [
            {"item_id": "a1", "url": "https://tasks.test/1"},
            {"item_id": "a2", "url": "https://tasks.test/2"},
        ],
        "failed": [],
    }
    stored = {item.id: item.exported_url for item in rig.stored(session_id)}
    assert stored == {
        "a1": "https://tasks.test/1",
        "a2": "https://tasks.test/2",
        "a3": "https://tasks.test/old",
    }
    first, second = rig.exporter.drafts
    assert (first.title, first.due) == ("Send the report", "2026-10-20")
    folder = api.store.paths(session_id).root.resolve()
    assert first.body.splitlines() == [
        f'Action item from the meeting "Meeting of 2026-10-15 20:23" (session {session_id}).',
        "Mentioned at 00:01:23 into the recording.",
        "Owner: Ana",
        "Due: 2026-10-20",
        f"Session folder: {folder}",
    ]
    assert len(second.body.splitlines()) == 2  # no time, owner or due
    assert rig.exporter.closed


def test_export_never_repeats_an_exported_item(api: Api) -> None:
    rig = _Rig(api)
    session_id = rig.session()
    url = f"/sessions/{session_id}/action-items/export"
    api.client.post(url, json={"target": "github", "item_ids": ["a1"]})

    response = api.client.post(url, json={"target": "github", "item_ids": ["a1", "a3", "a9"]})

    assert response.json() == {
        "created": [],
        "failed": [
            {"item_id": "a1", "error": "Already exported: https://tasks.test/1"},
            {"item_id": "a3", "error": "Already exported: https://tasks.test/old"},
            {"item_id": "a9", "error": 'Action item "a9" is not in this session.'},
        ],
    }
    assert len(rig.exporter.drafts) == 1


def test_a_tracker_error_fails_only_that_item(api: Api) -> None:
    rig = _Rig(api)
    rig.exporter.errors = [TaskExportError("unauthorized", status=401), None]
    session_id = rig.session()

    response = api.client.post(
        f"/sessions/{session_id}/action-items/export",
        json={"target": "github", "item_ids": ["a1", "a2"]},
    )

    assert response.json() == {
        "created": [{"item_id": "a2", "url": "https://tasks.test/2"}],
        "failed": [
            {
                "item_id": "a1",
                "error": "Fake Tracker rejected the credentials (HTTP 401). "
                "Check the token in the settings.",
            }
        ],
    }
    assert rig.stored(session_id)[0].exported_url is None


def test_export_to_an_unconfigured_target_is_422(api: Api) -> None:
    rig = _Rig(api)
    session_id = rig.session()
    url = f"/sessions/{session_id}/action-items/export"

    response = api.client.post(url, json={"target": "azure_devops", "item_ids": ["a1"]})
    rig.targets = []
    none = api.client.post(url, json={"target": "github", "item_ids": ["a1"]})
    empty = api.client.post(url, json={"target": "github", "item_ids": []})

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "unknown_task_target",
        "message": 'Export target "azure_devops" is not configured. Configured targets: github.',
    }
    assert none.json()["error"]["message"].endswith("Configured targets: —.")
    assert empty.json()["error"]["code"] == "invalid_request"


def test_a_session_without_a_start_time_uses_its_id_as_title(api: Api) -> None:
    rig = _Rig(api)
    session_id = rig.session()
    api.store.write_meta(session_id, {"id": session_id, "started_at": None})

    api.client.post(
        f"/sessions/{session_id}/action-items/export",
        json={"target": "github", "item_ids": ["a2"]},
    )

    assert f'"Meeting of {session_id}"' in rig.exporter.drafts[0].body
