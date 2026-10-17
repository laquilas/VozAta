"""`create_app(container)`: the local HTTP + WebSocket API (api-contract rows tagged 06)."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from vozata import __version__
from vozata.api.container import ApiContainer
from vozata.api.errors import install_error_handlers
from vozata.api.routes import devices, export, health, search, sessions, settings
from vozata.api.schemas import ErrorResponse

ERROR_RESPONSES = {status: {"model": ErrorResponse} for status in (404, 409, 422, 500, 503)}


def create_app(container: ApiContainer) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container.broadcaster.bind(asyncio.get_running_loop())
        yield
        container.release_models()

    app = FastAPI(title="VozAta engine", version=__version__, lifespan=lifespan)
    app.state.container = container
    install_error_handlers(app, container.localizer)
    for module in (health, devices, sessions, export, settings, search):
        app.include_router(module.router, responses=ERROR_RESPONSES)

    @app.websocket("/ws")
    async def events(websocket: WebSocket) -> None:
        await websocket.accept()
        client = container.broadcaster.subscribe()
        try:
            await websocket.send_json(container.manager.status_message())
            receiver = asyncio.create_task(_until_disconnected(websocket))
            while not receiver.done():
                getter = asyncio.create_task(client.get())
                done, _ = await asyncio.wait(
                    {getter, receiver}, return_when=asyncio.FIRST_COMPLETED
                )
                if getter in done:
                    await websocket.send_json(getter.result())
                else:
                    getter.cancel()
        except WebSocketDisconnect:
            pass
        finally:
            container.broadcaster.unsubscribe(client)

    return app


async def _until_disconnected(websocket: WebSocket) -> None:
    """Clients only listen; anything they send is ignored until they disconnect."""
    with contextlib.suppress(WebSocketDisconnect):
        while True:
            await websocket.receive_text()
