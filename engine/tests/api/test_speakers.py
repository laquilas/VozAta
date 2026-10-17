from __future__ import annotations

import dataclasses
import json

from tests.api.conftest import Api
from tests.api.test_sessions import SESSION, _recorded
from vozata.domain import Channel, SearchHit, TranscriptSegment


def _diarized(api: Api) -> None:
    """The session of `_recorded` plus a diarized transcript and a fresh `speakers.json`."""
    _recorded(api, minutes=True)
    segments = [
        TranscriptSegment("mic-000001", Channel.MIC, "mic", 1.0, 2.0, "Hello.", ()),
        TranscriptSegment("system-000002", Channel.SYSTEM, "system:2", 5.0, 6.0, "Yo.", ()),
        TranscriptSegment("system-000001", Channel.SYSTEM, "system:1", 3.0, 4.0, "Hi.", ()),
    ]
    api.store.write_diarized(SESSION, segments)
    api.store.write_speakers(SESSION, ["system:1", "system:2"])


def _put(api: Api, speakers: dict[str, object]):  # type: ignore[no-untyped-def]
    return api.client.put(f"/sessions/{SESSION}/speakers", json={"speakers": speakers})


def test_get_lists_transcript_speakers_in_order_with_default_labels(api: Api) -> None:
    _diarized(api)

    response = api.client.get(f"/sessions/{SESSION}/speakers")

    assert response.status_code == 200
    speakers = response.json()["speakers"]
    assert list(speakers) == ["mic", "system:1", "system:2"]  # first appearance in time
    assert speakers["system:1"] == {"name": None, "default_label": "labels.user(n=1)"}
    assert speakers["mic"] == {"name": None, "default_label": "labels.mic"}


def test_put_round_trip_trims_names_and_an_empty_name_restores_the_default(api: Api) -> None:
    _diarized(api)

    saved = _put(api, {"system:1": {"name": "  Alice "}, "mic": {"name": "Me & co"}})
    cleared = _put(api, {"mic": {"name": ""}})

    assert saved.status_code == 200
    assert saved.json()["speakers"]["system:1"] == {
        "name": "Alice",
        "default_label": "labels.user(n=1)",
    }
    assert cleared.json()["speakers"]["mic"]["name"] is None
    assert cleared.json()["speakers"]["system:1"]["name"] == "Alice"  # untouched by the 2nd PUT
    assert api.client.get(f"/sessions/{SESSION}/speakers").json() == cleared.json()
    stored = json.loads(api.store.paths(SESSION).speakers_json.read_text(encoding="utf-8"))
    assert stored["system:1"] == {"name": "Alice"}


def test_an_unknown_speaker_id_is_a_422_and_nothing_is_saved(api: Api) -> None:
    _diarized(api)

    response = _put(api, {"system:1": {"name": "Alice"}, "system:9": {"name": "Ghost"}})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "unknown_speaker"
    assert "system:9" in error["message"]
    assert "mic, system:1, system:2" in error["message"]
    assert api.store.speaker_names(SESSION) == {}


def test_the_undiarized_system_speaker_can_be_renamed(api: Api) -> None:
    _recorded(api)

    response = _put(api, {"system": {"name": "Room"}})

    assert response.status_code == 200
    labels = {
        s["speaker_id"]: s["label"]
        for s in api.client.get(f"/sessions/{SESSION}/transcript").json()["segments"]
    }
    assert labels == {"system": "Room", "mic": "labels.mic"}


def test_names_label_the_transcript_and_the_export(api: Api) -> None:
    _diarized(api)
    _put(api, {"system:2": {"name": "Bruno"}, "mic": {"name": "Ana"}})

    segments = api.client.get(f"/sessions/{SESSION}/transcript").json()["segments"]
    exported = api.client.get(f"/sessions/{SESSION}/export", params={"format": "md"}).text

    assert [s["label"] for s in segments] == ["Ana", "labels.user(n=1)", "Bruno"]
    assert "Bruno" in exported
    assert "Ana" in exported
    assert api.store.load_transcript(SESSION)[1].speaker_id == "system:2"  # raw ids kept


def test_names_label_search_hits(api: Api) -> None:
    class OneHitIndex:
        def search(self, query: str, limit: int) -> list[SearchHit]:
            return [SearchHit(SESSION, "system-000002", 5.0, "system:2", "\u0002Yo\u0003.")]

    _diarized(api)
    _put(api, {"system:2": {"name": "Bruno"}})
    container = api.app.state.container
    api.app.state.container = dataclasses.replace(container, search_index=OneHitIndex())

    hits = api.client.get("/search", params={"q": "yo"}).json()["hits"]

    assert [hit["label"] for hit in hits] == ["Bruno"]


def test_invalid_bodies_and_unknown_sessions_are_rejected(api: Api) -> None:
    _diarized(api)

    too_long = _put(api, {"mic": {"name": "x" * 201}})
    extra = api.client.put(f"/sessions/{SESSION}/speakers", json={"speakers": {}, "x": 1})
    missing = api.client.put("/sessions/20991231_000000/speakers", json={"speakers": {}})
    missing_get = api.client.get("/sessions/20991231_000000/speakers")

    assert too_long.status_code == 422
    assert extra.status_code == 422
    assert missing.status_code == 404
    assert missing_get.status_code == 404
