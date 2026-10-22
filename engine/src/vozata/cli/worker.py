"""`python -m vozata worker`: serve the heavy models to the engine of another PC (phase 44)."""

from __future__ import annotations

import ipaddress
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from vozata import __version__
from vozata.cli.console import ConsoleObserver
from vozata.config import Settings
from vozata.ports import Localizer


def run_worker(
    settings: Settings,
    console: ConsoleObserver,
    localizer: Localizer,
    build_app: Callable[[Settings, str | None], FastAPI],
    run: Callable[..., Any],
    *,
    env_file: Path,
    check: bool = False,
    new_token: Callable[[], str] = lambda: secrets.token_urlsafe(32),
) -> int:
    """Serve until Ctrl+C. A worker reachable from the network always has a token: without
    `WORKER_TOKEN` one is made, saved to `env_file` and printed once. `check` only prints the
    version and the address (the packaging smoke test)."""
    host, port = settings.worker_host, settings.worker_port
    url = f"http://{_bracketed(host)}:{port}"
    if check:
        console.say(localizer.t("cli.worker_check", version=__version__, url=url))
        return 0
    token = settings.worker_token
    if token is None and not _loopback(host):
        token = new_token()
        _save_token(env_file, token)
        console.say(localizer.t("cli.worker_token_created", token=token, file=env_file))
    console.say(localizer.t("cli.worker_listening", url=url))
    run(build_app(settings, token), host=host, port=port, log_level="warning")
    return 0


def _loopback(host: str) -> bool:
    """Only this PC can reach the address: `localhost` or a loopback IP (not `0.0.0.0`)."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def _bracketed(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def _save_token(env_file: Path, token: str) -> None:
    text = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    env_file.write_text(f"{text}WORKER_TOKEN={token}\n", encoding="utf-8", newline="\n")
