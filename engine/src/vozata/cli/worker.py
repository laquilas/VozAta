"""`python -m vozata worker`: serve the heavy models to the engine of another PC (phase 44)."""

from __future__ import annotations

import ipaddress
import json
import secrets
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from vozata import __version__
from vozata.cli.console import ConsoleObserver
from vozata.config import Settings
from vozata.ports import Localizer
from vozata.worker.tasks import WorkerTask


def run_worker(
    settings: Settings,
    console: ConsoleObserver,
    localizer: Localizer,
    build_app: Callable[[Settings, str | None, str | None], FastAPI],
    run: Callable[..., Any],
    *,
    env_file: Path,
    check: bool = False,
    json_output: bool = False,
    tasks: Callable[[Settings], list[WorkerTask]] = lambda _: [],
    new_token: Callable[[], str] = lambda: secrets.token_urlsafe(32),
    new_id: Callable[[], str] = lambda: uuid.uuid4().hex,
) -> int:
    """Serve until Ctrl+C. A worker reachable from the network always has a token and an id
    (phase 47: other PCs find it by id): without `WORKER_TOKEN` / `WORKER_ID` they are made and
    saved to `env_file`, the token printed once. `check` only prints the version, the address and
    the tasks offered (phase 51), as JSON with `json_output` (the packaging smoke test)."""
    host, port = settings.worker_host, settings.worker_port
    url = f"http://{_bracketed(host)}:{port}"
    if check:
        _check(console, localizer, url, tasks(settings), json_output)
        return 0
    token, worker_id = settings.worker_token, settings.worker_id
    if not _loopback(host):
        if token is None:
            token = new_token()
            _save(env_file, "WORKER_TOKEN", token)
            console.say(localizer.t("cli.worker_token_created", token=token, file=env_file))
        if worker_id is None:
            worker_id = new_id()
            _save(env_file, "WORKER_ID", worker_id)
    console.say(localizer.t("cli.worker_listening", url=url))
    run(build_app(settings, token, worker_id), host=host, port=port, log_level="warning")
    return 0


def _check(
    console: ConsoleObserver,
    localizer: Localizer,
    url: str,
    tasks: list[WorkerTask],
    json_output: bool,
) -> None:
    if json_output:
        body = {"version": __version__, "url": url, "tasks": [task.to_dict() for task in tasks]}
        console.say(json.dumps(body))
        return
    console.say(localizer.t("cli.worker_check", version=__version__, url=url))
    for task in tasks:
        state = "offered" if task.available else task.reason or "missing"
        name = localizer.t(f"cli.worker_task_name.{task.name}")
        console.say(localizer.t(f"cli.worker_task.{state}", task=name))


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


def _save(env_file: Path, key: str, value: str) -> None:
    text = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    env_file.write_text(f"{text}{key}={value}\n", encoding="utf-8", newline="\n")
