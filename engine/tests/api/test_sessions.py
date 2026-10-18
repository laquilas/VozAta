from __future__ import annotations

import dataclasses
import json
import threading
from pathlib import Path

import pytest

from tests.api.conftest import START_ERROR, Api
from vozata.domain import Channel, ConversationLanguage, StorageInfo, TranscriptSegment
from vozata.storage.sqlite.db import Database
from vozata.storage.sqlite.repository import SqliteSessionRepository

SESSION = "20261015_202358"


def _start(api: Api, **body: object):  # type: ignore[no-untyped-def]
    return api.client.post("/sessions", json=body)


def _finished(api: Api) -> None:
    assert api.manager.wait_until_finished(5)


def test_start_pause_resume_stop_lifecycle(api: Api) -> None:
    started = _start(api, language="pt", mic_device_id=9, system_device_id=10)

    assert started.status_code == 201
    assert started.json()["id"] == SESSION
    assert started.json()["status"] == "recording"
    options = api.factory.sessions[0].options
    assert options.language is ConversationLanguage.PT
    assert (options.mic_device, options.system_device) == (9, 10)

    assert api.client.post("/sessions/current/pause").json()["status"] == "paused"
    assert api.client.post("/sessions/current/resume").json()["status"] == "recording"
    stopped = api.client.post("/sessions/current/stop")
    _finished(api)

    assert stopped.status_code == 202
    assert stopped.json()["status"] == "finalizing"
    assert api.client.get(f"/sessions/{SESSION}").json()["status"] == "done"


def test_second_start_is_409_with_a_localized_message(api: Api) -> None:
    _start(api)

    response = _start(api)

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "session_already_active",
            "message": "A recording is already in progress or still being finalized. "
            "Stop it, or wait until it finishes.",
        }
    }


def test_start_while_finalizing_is_409(api: Api) -> None:
    api.factory.stop_gate = threading.Event()
    _start(api)
    api.client.post("/sessions/current/stop")

    assert _start(api).status_code == 409

    api.factory.stop_gate.set()
    _finished(api)
    assert _start(api).status_code == 201


@pytest.mark.parametrize("action", ["pause", "resume", "stop"])
def test_commands_without_a_session_are_409(api: Api, action: str) -> None:
    response = api.client.post(f"/sessions/current/{action}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_active_session"


def test_device_failure_is_503_with_the_session_message(api: Api) -> None:
    api.factory.start_error = START_ERROR

    response = _start(api)

    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "device_timeout", "message": "The mic did not open"}
    }


def test_unknown_device_is_404(api: Api) -> None:
    api.factory.start_error = LookupError("No audio device with id 42")

    response = _start(api, mic_device_id=42)

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "device_not_found",
        "message": "Audio device not found: No audio device with id 42",
    }


@pytest.mark.parametrize("body", [{"language": "fr"}, {"mic_device_id": "x"}, {"unknown": 1}])
def test_invalid_start_body_is_422_in_the_error_envelope(api: Api, body: dict) -> None:
    response = _start(api, **body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert response.json()["error"]["message"].startswith("Invalid request: ")


def _recorded(api: Api, moment_id: str = SESSION, *, minutes: bool = False) -> Path:
    paths = api.store.paths(moment_id)
    paths.root.mkdir(parents=True)
    api.store.write_meta(
        moment_id,
        {
            "id": moment_id,
            "status": "done",
            "started_at": "2026-10-15T20:23:58-03:00",
            "ended_at": "2026-10-15T20:25:28-03:00",
            "language": "en",
            "devices": {"mic": "Headset Mic"},
        },
    )
    segments = [
        TranscriptSegment("system-000001", Channel.SYSTEM, "system", 3.0, 4.0, "Hi.", ()),
        TranscriptSegment("mic-000001", Channel.MIC, "mic", 1.0, 2.0, "Hello.", ()),
    ]
    paths.transcript_jsonl.write_text(
        "".join(json.dumps(s.to_dict()) + "\n" for s in segments), encoding="utf-8"
    )
    if minutes:
        paths.minutes_md.write_text("# Minutes\n", encoding="utf-8")
    return paths.root


def test_list_sessions_newest_first_with_paging(api: Api) -> None:
    for session_id in ("20261013_090000", "20261014_090000", "20261015_090000"):
        _recorded(api, session_id)

    page = api.client.get("/sessions", params={"limit": 2, "offset": 1}).json()

    assert page["total"] == 3
    assert [item["id"] for item in page["items"]] == ["20261014_090000", "20261013_090000"]
    assert page["items"][0] == {
        "id": "20261014_090000",
        "status": "done",
        "started_at": "2026-10-15T20:23:58-03:00",
        "ended_at": "2026-10-15T20:25:28-03:00",
        "duration_seconds": 90.0,
        "language": "en",
        "has_minutes": False,
        "title": None,
    }


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 501}, {"offset": -1}])
def test_list_sessions_rejects_bad_paging(api: Api, params: dict) -> None:
    assert api.client.get("/sessions", params=params).status_code == 422


def test_detail_adds_metadata_files_and_folder(api: Api) -> None:
    root = _recorded(api, minutes=True)

    body = api.client.get(f"/sessions/{SESSION}").json()

    assert body["has_minutes"] is True
    assert body["devices"] == {"mic": "Headset Mic"}
    assert body["files"] == ["minutes.md", "session.json", "transcript.jsonl"]
    assert body["folder"] == str(root.resolve())
    assert body["storage"] == "files"


def test_detail_of_a_database_session_has_no_folder_or_files(api: Api, tmp_path: Path) -> None:
    database = Database(tmp_path / "vozata.db")
    store = SqliteSessionRepository(database, tmp_path / "db-recordings")
    session_id = store.create()
    store.write_meta(session_id, {"id": session_id, "status": "done", "language": "en"})
    store.write_minutes(session_id, "# Minutes\n")
    container = api.app.state.container
    api.app.state.container = dataclasses.replace(
        container, store=store, storage=StorageInfo("sqlite", database.path)
    )

    body = api.client.get(f"/sessions/{session_id}").json()

    assert (body["storage"], body["has_minutes"]) == ("sqlite", True)
    assert (body["files"], body["folder"], body["audio"]) == (None, None, {})
    database.close()


def test_detail_without_a_session_folder_has_no_files_or_folder(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    _recorded(api, minutes=True)
    monkeypatch.setattr(api.store, "folder", lambda session_id: None)  # e.g. a database backend

    body = api.client.get(f"/sessions/{SESSION}").json()

    assert body["has_minutes"] is True
    assert (body["files"], body["folder"]) == (None, None)


def test_detail_of_the_current_session_uses_the_live_duration(api: Api) -> None:
    _start(api)
    api.factory.sessions[0].duration_seconds = 42.0

    body = api.client.get(f"/sessions/{SESSION}").json()
    listed = api.client.get("/sessions").json()["items"][0]

    assert body["duration_seconds"] == 42.0
    assert listed["duration_seconds"] == 42.0


@pytest.mark.parametrize("session_id", ["20991231_000000", "not-a-session", "2026_1"])
def test_unknown_sessions_are_404(api: Api, session_id: str) -> None:
    for path in ("", "/transcript", "/minutes"):
        response = api.client.get(f"/sessions/{session_id}{path}")
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "session_not_found"


def test_transcript_is_sorted_with_display_labels(api: Api) -> None:
    _recorded(api)

    body = api.client.get(f"/sessions/{SESSION}/transcript").json()

    assert body["source"] == "raw"
    assert [s["segment_id"] for s in body["segments"]] == ["mic-000001", "system-000001"]
    assert body["segments"][0]["label"] == "labels.mic"
    assert body["segments"][0]["edited"] is False
    assert body["segments"][0]["translation"] is None


def test_transcript_segments_carry_their_live_translation(api: Api) -> None:
    root = _recorded(api)
    (root / "transcript.translated.jsonl").write_text(
        '{"segment_id": "system-000001", "language": "pt", "text": "Oi."}\n', encoding="utf-8"
    )

    segments = api.client.get(f"/sessions/{SESSION}/transcript").json()["segments"]

    assert segments[0]["translation"] is None
    assert segments[1]["translation"] == {"language": "pt", "text": "Oi."}


@pytest.mark.parametrize(("value", "expected"), [("pt", "pt"), ("off", "off"), (None, None)])
def test_start_passes_the_translation_choice(
    api: Api, value: str | None, expected: str | None
) -> None:
    response = _start(api, translate_to=value) if value else _start(api)

    assert response.status_code == 201
    chosen = api.factory.sessions[0].options.translate_to
    assert (chosen.value if chosen else None) == expected


def test_start_rejects_an_unknown_translation_language(api: Api) -> None:
    response = _start(api, translate_to="auto")

    assert response.status_code == 422


def test_minutes_markdown_or_404(api: Api) -> None:
    _recorded(api)

    missing = api.client.get(f"/sessions/{SESSION}/minutes")
    api.store.paths(SESSION).minutes_md.write_text("# Minutes\n", encoding="utf-8")
    found = api.client.get(f"/sessions/{SESSION}/minutes")

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "minutes_not_found"
    assert found.json() == {"markdown": "# Minutes\n"}


def test_regenerate_minutes_is_accepted_and_runs_in_the_background(api: Api) -> None:
    _recorded(api)

    response = api.client.post(f"/sessions/{SESSION}/minutes", json={"template": "general"})

    assert response.status_code == 202
    assert api.regenerated == [(SESSION, "general")]


def test_regenerate_minutes_of_the_recording_session_is_409(api: Api) -> None:
    _start(api)

    response = api.client.post(f"/sessions/{SESSION}/minutes")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "session_still_recording"
    assert api.regenerated == []


def test_unexpected_errors_become_a_500_envelope(api: Api) -> None:
    def broken(session_id: str, template: str | None) -> None:
        raise RuntimeError("boom")

    api.app.state.container = api.app.state.container.__class__(
        **{**api.app.state.container.__dict__, "regenerate_minutes": broken}
    )
    _recorded(api)

    response = api.client.post(f"/sessions/{SESSION}/minutes")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "boom" not in response.text


def test_paths_outside_the_api_get_the_error_envelope(api: Api) -> None:
    traversal = api.client.get("/sessions/..%2F..%2Fetc/transcript")
    wrong_method = api.client.delete("/sessions")

    assert traversal.status_code == 404
    assert traversal.json()["error"]["code"] == "not_found"
    assert wrong_method.status_code == 405
    assert wrong_method.json()["error"] == {
        "code": "method_not_allowed",
        "message": "This method is not allowed on this endpoint.",
    }


def test_invalid_configuration_is_a_500_with_the_rendered_message(api: Api) -> None:
    from vozata.config import ConfigError

    api.factory.start_error = ConfigError("STT_PROVIDER", "x", "invalid_choice", allowed="a, b")

    response = _start(api)

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "invalid_configuration",
        "message": 'Invalid value "x" for STT_PROVIDER. Allowed values: a, b.',
    }


def test_a_session_without_an_end_has_no_duration(api: Api) -> None:
    _recorded(api)
    meta = api.store.read_meta(SESSION)
    api.store.write_meta(SESSION, {**meta, "ended_at": None, "status": "interrupted"})

    item = api.client.get("/sessions").json()["items"][0]

    assert (item["status"], item["duration_seconds"]) == ("interrupted", None)


def test_stored_duration_wins_over_the_wall_clock_span(api: Api) -> None:
    _recorded(api)
    meta = api.store.read_meta(SESSION)
    api.store.write_meta(SESSION, {**meta, "duration_seconds": 63.5})

    item = api.client.get("/sessions").json()["items"][0]

    assert item["duration_seconds"] == 63.5


def _diarized(api: Api, names: dict[str, str | None]) -> None:
    paths = api.store.paths(SESSION)
    segments = [
        TranscriptSegment("system-000001", Channel.SYSTEM, "system:1", 3.0, 4.0, "Hi.", ()),
        TranscriptSegment("system-000002", Channel.SYSTEM, "system:2", 5.0, 6.0, "Yo.", ()),
    ]
    paths.diarized_jsonl.write_text(
        "".join(json.dumps(s.to_dict()) + "\n" for s in segments), encoding="utf-8"
    )
    speakers = {speaker_id: {"name": name} for speaker_id, name in names.items()}
    paths.speakers_json.write_text(json.dumps(speakers), encoding="utf-8")


def test_a_diarized_transcript_is_labeled_per_speaker_with_stored_names(api: Api) -> None:
    _recorded(api)
    _diarized(api, {"system:1": None, "system:2": "Ana"})

    body = api.client.get(f"/sessions/{SESSION}/transcript").json()

    assert body["source"] == "diarized"
    labels = [(s["speaker_id"], s["label"]) for s in body["segments"]]
    assert labels == [("system:1", "labels.user(n=1)"), ("system:2", "Ana")]
