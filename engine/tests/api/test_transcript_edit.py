from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from tests.api.conftest import Api
from vozata.domain import Channel, SearchHit, TranscriptSegment, Word
from vozata.storage.session_store import SessionPaths

SESSION = "20261015_202358"
WORD = Word("Hello", 1.0, 1.4, 0.3)


class FakeSearch:
    def __init__(self, fail: bool = False) -> None:
        self.indexed: list[tuple[str, list[TranscriptSegment]]] = []
        self.fail = fail

    def index_session(self, session_id: str, segments: Sequence[TranscriptSegment]) -> None:
        if self.fail:
            raise RuntimeError("index locked")
        self.indexed.append((session_id, list(segments)))

    def search(self, query: str, limit: int = 50) -> list[SearchHit]:
        return []


@pytest.fixture
def search() -> FakeSearch:
    return FakeSearch()


@pytest.fixture
def edit_api(tmp_path: Path, search: FakeSearch) -> Iterator[Api]:
    api = Api(tmp_path)
    container = api.app.state.container
    api.app.state.container = dataclasses.replace(container, search_index=search)
    with api.client:
        yield api


def _recorded(api: Api) -> SessionPaths:
    paths = api.store.paths(SESSION)
    paths.root.mkdir(parents=True)
    api.store.write_meta(SESSION, {"id": SESSION, "status": "done", "language": "en"})
    segments = [
        TranscriptSegment("mic-000001", Channel.MIC, "mic", 1.0, 2.0, "Hello wold.", (WORD,)),
        TranscriptSegment("system-000001", Channel.SYSTEM, "system", 3.0, 4.0, "Hi.", ()),
    ]
    paths.transcript_jsonl.write_text(
        "".join(json.dumps(s.to_dict()) + "\n" for s in segments), encoding="utf-8"
    )
    return paths


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _put(api: Api, *segments: dict[str, object]):  # type: ignore[no-untyped-def]
    return api.client.put(f"/sessions/{SESSION}/transcript", json={"segments": list(segments)})


def test_put_writes_the_edited_copy_and_get_returns_it(edit_api: Api) -> None:
    paths = _recorded(edit_api)
    raw_before = _digest(paths.transcript_jsonl)

    response = _put(edit_api, {"segment_id": "mic-000001", "text": "Hello world."})

    assert response.status_code == 200
    assert response.json() == {"source": "edited"}
    body = edit_api.client.get(f"/sessions/{SESSION}/transcript").json()
    assert body["source"] == "edited"
    first, second = body["segments"]
    assert (first["text"], first["edited"], first["words"]) == ("Hello world.", True, [])
    assert (second["text"], second["edited"]) == ("Hi.", False)
    assert _digest(paths.transcript_jsonl) == raw_before


def test_put_accepts_full_segment_payloads(edit_api: Api) -> None:
    _recorded(edit_api)
    segment = edit_api.client.get(f"/sessions/{SESSION}/transcript").json()["segments"][1]

    response = _put(edit_api, {**segment, "text": "Hi there."})

    assert response.status_code == 200
    assert edit_api.store.load_transcript(SESSION)[1].text == "Hi there."


def test_unchanged_segments_keep_their_words(edit_api: Api) -> None:
    _recorded(edit_api)

    _put(edit_api, {"segment_id": "mic-000001", "text": "Hello wold."})

    first = edit_api.store.load_transcript(SESSION)[0]
    assert (first.edited, first.words) == (False, (WORD,))


def test_an_unknown_segment_id_is_422_and_writes_nothing(edit_api: Api) -> None:
    paths = _recorded(edit_api)

    response = _put(edit_api, {"segment_id": "mic-999999", "text": "x"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_segment"
    assert "mic-999999" in response.json()["error"]["message"]
    assert not paths.edited_jsonl.exists()


@pytest.mark.parametrize("text", ["", "   "])
def test_empty_text_is_422(edit_api: Api, text: str) -> None:
    paths = _recorded(edit_api)

    response = _put(edit_api, {"segment_id": "mic-000001", "text": text})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "empty_segment_text"
    assert not paths.edited_jsonl.exists()


def test_a_malformed_body_is_422(edit_api: Api) -> None:
    _recorded(edit_api)

    response = edit_api.client.put(
        f"/sessions/{SESSION}/transcript", json={"segments": [{"text": "x"}]}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_edits_build_on_the_diarized_transcript(edit_api: Api) -> None:
    _recorded(edit_api)
    diarized = TranscriptSegment("system-000001", Channel.SYSTEM, "system:1", 3.0, 4.0, "Hi.", ())
    edit_api.store.write_diarized(SESSION, [diarized])

    _put(edit_api, {"segment_id": "system-000001", "text": "Hi, all."})

    assert [s.speaker_id for s in edit_api.store.load_transcript(SESSION)] == ["system:1"]
    rejected = _put(edit_api, {"segment_id": "mic-000001", "text": "x"})
    assert rejected.json()["error"]["code"] == "unknown_segment"  # not in the best transcript


def test_put_and_delete_reindex_the_session(edit_api: Api, search: FakeSearch) -> None:
    _recorded(edit_api)

    _put(edit_api, {"segment_id": "mic-000001", "text": "Hello world."})
    edit_api.client.delete(f"/sessions/{SESSION}/transcript/edits")

    assert [(sid, [s.text for s in segments]) for sid, segments in search.indexed] == [
        (SESSION, ["Hello world.", "Hi."]),
        (SESSION, ["Hello wold.", "Hi."]),
    ]


def test_delete_reverts_to_the_previous_source(edit_api: Api) -> None:
    paths = _recorded(edit_api)
    raw_before = _digest(paths.transcript_jsonl)
    _put(edit_api, {"segment_id": "mic-000001", "text": "Hello world."})

    response = edit_api.client.delete(f"/sessions/{SESSION}/transcript/edits")

    assert response.status_code == 204
    assert not paths.edited_jsonl.exists()
    body = edit_api.client.get(f"/sessions/{SESSION}/transcript").json()
    assert body["source"] == "raw"
    assert body["segments"][0]["text"] == "Hello wold."
    assert _digest(paths.transcript_jsonl) == raw_before


def test_delete_without_edits_is_204_and_does_not_reindex(
    edit_api: Api, search: FakeSearch
) -> None:
    _recorded(edit_api)

    response = edit_api.client.delete(f"/sessions/{SESSION}/transcript/edits")

    assert response.status_code == 204
    assert search.indexed == []


def test_a_failing_index_does_not_fail_the_edit(tmp_path: Path) -> None:
    api = Api(tmp_path)
    container = api.app.state.container
    api.app.state.container = dataclasses.replace(container, search_index=FakeSearch(fail=True))
    with api.client:
        _recorded(api)

        response = _put(api, {"segment_id": "mic-000001", "text": "Hello world."})

    assert response.status_code == 200
    assert api.store.load_transcript_with_source(SESSION)[0] == "edited"


def test_edits_work_without_a_search_index(api: Api) -> None:
    _recorded(api)

    assert _put(api, {"segment_id": "mic-000001", "text": "Hello world."}).status_code == 200
    assert api.client.delete(f"/sessions/{SESSION}/transcript/edits").status_code == 204


@pytest.mark.parametrize("method", ["put", "delete"])
def test_unknown_sessions_are_404(edit_api: Api, method: str) -> None:
    if method == "put":
        response = edit_api.client.put(
            "/sessions/20991231_000000/transcript", json={"segments": []}
        )
    else:
        response = edit_api.client.delete("/sessions/20991231_000000/transcript/edits")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"


def test_the_recording_session_cannot_be_edited(api: Api) -> None:
    api.client.post("/sessions", json={})

    put = _put(api, {"segment_id": "mic-000001", "text": "x"})
    delete = api.client.delete(f"/sessions/{SESSION}/transcript/edits")

    assert (put.status_code, delete.status_code) == (409, 409)
    assert put.json()["error"]["code"] == "transcript_still_recording"
