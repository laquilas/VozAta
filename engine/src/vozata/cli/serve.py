"""`python -m vozata serve`: the local HTTP + WebSocket API (loopback only)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from vozata.cli.console import ConsoleObserver
from vozata.config import Settings
from vozata.ports import Localizer

PUBLIC_HOSTS = {"0.0.0.0", "::", "[::]", ""}


def run_serve(
    settings: Settings,
    console: ConsoleObserver,
    localizer: Localizer,
    build_app: Callable[[Settings], FastAPI],
    run: Callable[..., Any],
) -> int:
    """Serve until Ctrl+C. Refuses every-interface addresses: the API has no authentication."""
    host = settings.api_host
    if host in PUBLIC_HOSTS:
        console.say(localizer.t("cli.serve_public_host", host=host or "(empty)"))
        return 2
    app = build_app(settings)
    console.say(localizer.t("cli.serving", url=f"http://{host}:{settings.api_port}"))
    run(app, host=host, port=settings.api_port, log_level="warning")
    return 0
