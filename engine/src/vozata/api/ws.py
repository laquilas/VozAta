"""WebSocket event stream: thread-safe publishing to every connected client (api-contract)."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable
from typing import Any

_log = logging.getLogger(__name__)

Message = dict[str, Any]
CLIENT_QUEUE_SIZE = 256


class ClientQueue:
    """A bounded per-client queue (used only on the event loop).

    When full, the oldest `level` event is dropped first (meters lose nothing important);
    without one, the oldest event is dropped.
    """

    def __init__(self, maxsize: int = CLIENT_QUEUE_SIZE) -> None:
        if maxsize < 1:
            raise ValueError("A client queue needs room for one event")
        self._items: deque[Message] = deque()
        self._maxsize = maxsize
        self._ready = asyncio.Event()
        self.dropped = 0

    def put(self, message: Message) -> None:
        if len(self._items) >= self._maxsize:
            self._drop_one()
        self._items.append(message)
        self._ready.set()

    async def get(self) -> Message:
        while not self._items:
            self._ready.clear()
            await self._ready.wait()
        return self._items.popleft()

    def drain(self) -> list[Message]:
        items, self._items = list(self._items), deque()
        return items

    def _drop_one(self) -> None:
        self.dropped += 1
        for index, item in enumerate(self._items):
            if item["type"] == "level":
                del self._items[index]
                return
        self._items.popleft()


class EventBroadcaster:
    """Publish `{type, session_id, data}` envelopes from any thread to every subscribed client.

    `publish` hops onto the bound event loop with `call_soon_threadsafe`; before `bind` (or after
    the loop closed) events are dropped, since nobody can be listening.
    """

    def __init__(self, queue_size: int = CLIENT_QUEUE_SIZE) -> None:
        self._queue_size = queue_size
        self._clients: set[ClientQueue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> ClientQueue:
        client = ClientQueue(self._queue_size)
        self._clients.add(client)
        return client

    def unsubscribe(self, client: ClientQueue) -> None:
        self._clients.discard(client)

    def publish(self, kind: str, session_id: str | None, data: dict[str, Any]) -> None:
        message = {"type": kind, "session_id": session_id, "data": data}
        loop = self._loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(self._fan_out, message)
        except RuntimeError:  # the loop is closed: the server is shutting down
            _log.debug("Event %s dropped: the event loop is closed", kind)

    def _fan_out(self, message: Message) -> None:
        for client in list(self._clients):
            client.put(message)


StatusProvider = Callable[[], Message]
