from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.api.conftest import Api
from vozata.domain import Channel, TranscriptSegment
from vozata.storage.search_index import SearchIndex


@pytest.fixture
def searchable(tmp_path: Path) -> Iterator[tuple[Api, SearchIndex]]:
    api = Api(tmp_path)
    index = SearchIndex(tmp_path / "recordings" / "index.db")
    container = api.app.state.container
    api.app.state.container = dataclasses.replace(container, search_index=index)
    with api.client:
        yield api, index


def _segment(segment_id: str, channel: Channel, speaker_id: str, text: str) -> TranscriptSegment:
    return TranscriptSegment(segment_id, channel, speaker_id, 83.12, 87.9, text, ())


def test_search_returns_hits_with_labels_and_marked_snippets(
    searchable: tuple[Api, SearchIndex],
) -> None:
    api, index = searchable
    index.index_session(
        "20261015_202358",
        [
            _segment("mic-000001", Channel.MIC, "mic", "a decisão foi tomada"),
            _segment("system-000002", Channel.SYSTEM, "system", "outro assunto"),
        ],
    )

    response = api.client.get("/search", params={"q": "decisao"})

    assert response.status_code == 200
    assert response.json() == {
        "hits": [
            {
                "session_id": "20261015_202358",
                "segment_id": "mic-000001",
                "start": 83.12,
                "speaker_id": "mic",
                "label": "labels.mic",  # the API tests use FakeLocalizer for labels
                "snippet": "a \u0002decisão\u0003 foi tomada",
            }
        ]
    }


def test_search_honours_the_limit(searchable: tuple[Api, SearchIndex]) -> None:
    api, index = searchable
    segments = [_segment(f"mic-{n:06d}", Channel.MIC, "mic", "budget") for n in range(5)]
    index.index_session("20261015_202358", segments)

    response = api.client.get("/search", params={"q": "budget", "limit": 2})

    assert len(response.json()["hits"]) == 2


@pytest.mark.parametrize("query", ['"', "*", "OR", "NEAR(", "a:b", ""])
def test_fts_syntax_never_fails_the_request(
    searchable: tuple[Api, SearchIndex], query: str
) -> None:
    api, index = searchable
    index.index_session("20261015_202358", [_segment("mic-000001", Channel.MIC, "mic", "x")])

    response = api.client.get("/search", params={"q": query})

    assert response.status_code == 200


@pytest.mark.parametrize("params", [{"q": "x", "limit": 0}, {"q": "x", "limit": 201}])
def test_an_out_of_range_limit_is_rejected(
    searchable: tuple[Api, SearchIndex], params: dict[str, object]
) -> None:
    api, _ = searchable

    assert api.client.get("/search", params=params).status_code == 422


def test_without_an_index_there_are_no_hits(api: Api) -> None:
    response = api.client.get("/search", params={"q": "anything"})

    assert response.json() == {"hits": []}
