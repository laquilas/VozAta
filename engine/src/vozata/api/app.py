"""`create_app(container)`: the local HTTP + WebSocket API (api-contract rows tagged 06)."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from vozata import __version__
from vozata.api.container import ApiContainer
from vozata.api.errors import install_error_handlers
from vozata.api.routes import (
    action_items,
    audio,
    branding,
    devices,
    export,
    health,
    recover,
    search,
    sessions,
    settings,
    settings_tools,
    speakers,
    templates,
    transcript_edit,
    vocabulary,
)
from vozata.api.routes import ask as ask_routes
from vozata.api.routes import audio_import as audio_import_routes
from vozata.api.routes import bundle as bundle_routes
from vozata.api.routes import migration as migration_routes
from vozata.api.routes import partial_minutes as partial_minutes_routes
from vozata.api.routes import requests as requests_routes
from vozata.api.routes import voice_commands as voice_commands_routes
from vozata.api.routes import worker as worker_routes
from vozata.api.schemas import ErrorResponse

ERROR_RESPONSES = {status: {"model": ErrorResponse} for status in (404, 409, 422, 500, 503)}


def create_app(container: ApiContainer) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container.broadcaster.bind(asyncio.get_running_loop())
        container.manager.resume_pending()  # phase 40: unfinished meetings, before the import
        if container.migration is not None:
            container.migration.start()  # phase 33: after `bind`, so its events reach clients
        if container.meeting_detector is not None:
            container.meeting_detector.start()  # phase 54
        yield
        if container.meeting_detector is not None:
            await asyncio.to_thread(container.meeting_detector.stop)
        await asyncio.to_thread(container.stop_processing)  # 40: e.g. ends a diarizer child
        container.release_models()

    # /docs and /redoc come from the branding router so they show the VozAta favicon
    app = FastAPI(
        title="VozAta engine", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None
    )
    app.state.container = container
    install_error_handlers(app, container.localizer)
    for module in (
        health,
        devices,
        sessions,
        audio,
        speakers,
        transcript_edit,
        export,
        settings,
        search,
        templates,
        vocabulary,
    ):
        app.include_router(module.router, responses=ERROR_RESPONSES)
    app.include_router(ask_routes.router, responses=ERROR_RESPONSES)  # phase 24
    app.include_router(action_items.router, responses=ERROR_RESPONSES)  # phase 23
    app.include_router(recover.router, responses=ERROR_RESPONSES)  # phase 17
    app.include_router(settings_tools.router, responses=ERROR_RESPONSES)  # phase 38
    app.include_router(migration_routes.router, responses=ERROR_RESPONSES)  # phase 33
    app.include_router(bundle_routes.router, responses=ERROR_RESPONSES)  # phase 39
    app.include_router(audio_import_routes.router, responses=ERROR_RESPONSES)  # phase 60
    app.include_router(worker_routes.router, responses=ERROR_RESPONSES)  # phase 47
    app.include_router(partial_minutes_routes.router, responses=ERROR_RESPONSES)  # phase 48
    app.include_router(requests_routes.router, responses=ERROR_RESPONSES)  # phase 59
    app.include_router(voice_commands_routes.router, responses=ERROR_RESPONSES)  # phase 50
    app.include_router(branding.router)

    @app.websocket("/ws")
    async def events(websocket: WebSocket) -> None:
        await websocket.accept()
        client = container.broadcaster.subscribe()
        try:
            await websocket.send_json(container.manager.status_message())
            for message in container.manager.processing_messages():  # phase 40
                await websocket.send_json(message)
            if container.migration is not None and container.migration.is_running():
                await websocket.send_json(container.migration.progress_message())  # phase 33
            for download in container.downloads.running():  # phase 42
                data = download.to_payload()
                await websocket.send_json(
                    {"type": "download_progress", "session_id": None, "data": data}
                )
            interrupted = await asyncio.to_thread(container.manager.interrupted_sessions)
            if interrupted:  # phase 17: offer to recover sessions a crash cut short
                data = {"session_ids": interrupted}
                await websocket.send_json(
                    {"type": "recovery_available", "session_id": None, "data": data}
                )
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
