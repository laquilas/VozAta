from __future__ import annotations

import asyncio
import threading

import pytest

from vozata.api.ws import ClientQueue, EventBroadcaster


def _event(kind: str, n: int = 0) -> dict:
    return {"type": kind, "session_id": "s", "data": {"n": n}}


def test_client_queue_drops_the_oldest_level_event_when_full() -> None:
    queue = ClientQueue(maxsize=3)

    for message in (
        _event("level", 1),
        _event("segment", 2),
        _event("level", 3),
        _event("status", 4),
    ):
        queue.put(message)

    assert [item["data"]["n"] for item in queue.drain()] == [2, 3, 4]
    assert queue.dropped == 1


def test_client_queue_drops_the_oldest_event_when_no_level_is_queued() -> None:
    queue = ClientQueue(maxsize=2)

    for n in range(3):
        queue.put(_event("segment", n))

    assert [item["data"]["n"] for item in queue.drain()] == [1, 2]


def test_events_published_from_other_threads_reach_every_client_in_order() -> None:
    async def scenario() -> tuple[list[dict], list[dict]]:
        broadcaster = EventBroadcaster()
        broadcaster.bind(asyncio.get_running_loop())
        first, second = broadcaster.subscribe(), broadcaster.subscribe()

        def publish() -> None:
            for n in range(5):
                broadcaster.publish("segment", "s", {"n": n})

        thread = threading.Thread(target=publish)
        thread.start()
        thread.join()
        received = ([await first.get() for _ in range(5)], [await second.get() for _ in range(5)])
        broadcaster.unsubscribe(first)
        broadcaster.unsubscribe(second)
        return received

    first, second = asyncio.run(scenario())

    assert [message["data"]["n"] for message in first] == [0, 1, 2, 3, 4]
    assert second == first
    assert first[0] == {"type": "segment", "session_id": "s", "data": {"n": 0}}


def test_unsubscribed_clients_stop_receiving_and_publishing_continues() -> None:
    async def scenario() -> list[dict]:
        broadcaster = EventBroadcaster()
        broadcaster.bind(asyncio.get_running_loop())
        gone, staying = broadcaster.subscribe(), broadcaster.subscribe()
        broadcaster.unsubscribe(gone)
        broadcaster.unsubscribe(gone)  # harmless twice

        broadcaster.publish("status", None, {"status": "idle"})
        message = await staying.get()
        return [message, *gone.drain()]

    assert asyncio.run(scenario()) == [
        {"type": "status", "session_id": None, "data": {"status": "idle"}}
    ]


def test_publishing_before_the_loop_is_bound_is_ignored() -> None:
    broadcaster = EventBroadcaster()
    client = broadcaster.subscribe()

    broadcaster.publish("level", "s", {"rms_db": -20.0})

    assert client.drain() == []


def test_publishing_after_the_loop_closed_is_ignored() -> None:
    broadcaster = EventBroadcaster()
    loop = asyncio.new_event_loop()
    broadcaster.bind(loop)
    loop.close()

    broadcaster.publish("level", "s", {"rms_db": -20.0})  # no exception


def test_get_waits_for_the_next_event() -> None:
    async def scenario() -> dict:
        queue = ClientQueue(maxsize=4)
        waiter = asyncio.create_task(queue.get())
        await asyncio.sleep(0)
        assert not waiter.done()
        queue.put(_event("status"))
        return await asyncio.wait_for(waiter, 1)

    assert asyncio.run(scenario())["type"] == "status"


@pytest.mark.parametrize("maxsize", [0, -1])
def test_client_queue_needs_room_for_one_event(maxsize: int) -> None:
    with pytest.raises(ValueError):
        ClientQueue(maxsize=maxsize)
