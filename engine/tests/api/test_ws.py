from __future__ import annotations

import dataclasses

from fastapi.testclient import TestClient

from tests.api.conftest import Api
from vozata.api.app import create_app
from vozata.domain import Channel, TranscriptSegment

SESSION = "20261015_202358"


def test_connect_sends_idle_status_first(api: Api) -> None:
    with api.client.websocket_connect("/ws") as ws:
        assert ws.receive_json() == {
            "type": "status",
            "session_id": None,
            "data": {"status": "idle"},
        }


def test_session_events_arrive_in_order_with_the_envelope(api: Api) -> None:
    with api.client.websocket_connect("/ws") as ws:
        ws.receive_json()  # idle
        api.client.post("/sessions", json={})
        observer = api.factory.sessions[0].observer
        segment = TranscriptSegment("mic-000001", Channel.MIC, "mic", 1.0, 2.0, "Oi.", ())
        observer.on_segment(segment)
        observer.on_level(Channel.MIC, -12.5)
        observer.on_error("minutes_failed", "offline")

        messages = [ws.receive_json() for _ in range(4)]

    assert [m["type"] for m in messages] == ["status", "segment", "level", "error"]
    assert all(m["session_id"] == SESSION for m in messages)
    assert messages[0]["data"] == {"status": "recording", "duration_seconds": 0.0}
    assert messages[1]["data"]["label"] == "labels.mic"
    assert messages[2]["data"] == {"channel": "mic", "rms_db": -12.5}


def test_connect_during_a_session_describes_it(api: Api) -> None:
    api.client.post("/sessions", json={})
    api.factory.sessions[0].duration_seconds = 3.0

    with api.client.websocket_connect("/ws") as ws:
        assert ws.receive_json() == {
            "type": "status",
            "session_id": SESSION,
            "data": {"status": "recording", "duration_seconds": 3.0},
        }


def test_a_disconnect_does_not_break_publishing(api: Api) -> None:
    with api.client.websocket_connect("/ws") as gone:
        gone.receive_json()
    with api.client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_text("ignored")  # clients only listen
        api.broadcaster.publish("minutes_ready", SESSION, {"session_id": SESSION})

        assert ws.receive_json()["type"] == "minutes_ready"


def test_a_client_gone_before_the_first_send_is_cleaned_up(api: Api) -> None:
    import asyncio

    from starlette.websockets import WebSocketDisconnect

    from vozata.api.app import create_app

    class GoneSocket:
        async def accept(self) -> None:
            pass

        async def send_json(self, data: object) -> None:
            raise WebSocketDisconnect(1001)

    app = create_app(api.app.state.container)
    route = next(r for r in app.routes if getattr(r, "path", None) == "/ws")

    asyncio.run(route.endpoint(GoneSocket()))

    assert api.broadcaster._clients == set()


def test_models_are_released_when_the_api_shuts_down(api: Api) -> None:
    released: list[bool] = []
    container = dataclasses.replace(
        api.app.state.container, release_models=lambda: released.append(True)
    )

    with TestClient(create_app(container)):
        assert released == []

    assert released == [True]
