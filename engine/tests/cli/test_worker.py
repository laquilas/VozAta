from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from tests.fakes import FakeLocalizer
from vozata import __version__
from vozata.cli.console import ConsoleObserver
from vozata.cli.worker import run_worker
from vozata.config import Settings
from vozata.labels import SpeakerLabeler
from vozata.worker.tasks import MISSING_EXTRA, MISSING_HF_TOKEN, WorkerTask

ids: list[str | None] = []


def _worker(
    settings: Settings,
    env_file: Path,
    *,
    check: bool = False,
    json_output: bool = False,
    tasks: list[WorkerTask] | None = None,
) -> tuple[int, str, list[tuple[str | None, dict[str, Any]]]]:
    out = io.StringIO()
    localizer = FakeLocalizer()
    console = ConsoleObserver(localizer, SpeakerLabeler(localizer), out)
    runs: list[tuple[str | None, dict[str, Any]]] = []
    ids.clear()

    def build(settings: Settings, token: str | None, worker_id: str | None) -> object:
        return ("app", token, worker_id)

    def run(application: Any, **options: Any) -> None:
        runs.append((application[1], options))
        ids.append(application[2])

    code = run_worker(
        settings,
        console,
        localizer,
        build,  # type: ignore[arg-type]
        run,
        env_file=env_file,
        check=check,
        json_output=json_output,
        tasks=lambda _: tasks or [WorkerTask("speech", True)],
        new_token=lambda: "generated-token",
        new_id=lambda: "generated-id",
    )
    return code, out.getvalue(), runs


def test_listens_on_the_network_with_the_configured_token_and_id(tmp_path: Path) -> None:
    settings = Settings(
        worker_host="0.0.0.0", worker_port=8766, worker_token="mine", worker_id="4f1c"
    )

    code, out, runs = _worker(settings, tmp_path / ".env")

    assert code == 0
    assert runs == [("mine", {"host": "0.0.0.0", "port": 8766, "log_level": "warning"})]
    assert ids == ["4f1c"]
    assert out == "cli.worker_listening(url=http://0.0.0.0:8766)\n"
    assert not (tmp_path / ".env").exists()


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.68.101", "::", "gpu-box"])
def test_a_network_host_without_a_token_gets_a_new_one_saved_to_the_env_file(
    tmp_path: Path, host: str
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("WHISPER_MODEL=large-v3-turbo", encoding="utf-8")  # no final newline

    code, out, runs = _worker(Settings(worker_host=host), env_file)

    assert code == 0
    assert runs[0][0] == "generated-token"
    assert env_file.read_text(encoding="utf-8") == (
        "WHISPER_MODEL=large-v3-turbo\nWORKER_TOKEN=generated-token\nWORKER_ID=generated-id\n"
    )
    assert ids == ["generated-id"]
    assert f"cli.worker_token_created(file={env_file},token=generated-token)" in out


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_a_loopback_worker_needs_no_token(tmp_path: Path, host: str) -> None:
    code, _, runs = _worker(Settings(worker_host=host), tmp_path / ".env")

    assert code == 0
    assert runs[0][0] is None
    assert ids == [None]  # nobody on the network can find a loopback worker
    assert not (tmp_path / ".env").exists()


def test_check_prints_the_version_and_address_and_starts_nothing(tmp_path: Path) -> None:
    settings = Settings(worker_host="0.0.0.0", worker_port=9001)

    code, out, runs = _worker(settings, tmp_path / ".env", check=True)

    assert code == 0
    assert runs == []
    assert out.splitlines() == [
        f"cli.worker_check(url=http://0.0.0.0:9001,version={__version__})",
        "cli.worker_task.offered(task=cli.worker_task_name.speech)",
    ]
    assert not (tmp_path / ".env").exists()  # a check never writes a token


TASKS = [
    WorkerTask("speech", True),
    WorkerTask("speakers", False, MISSING_HF_TOKEN),
    WorkerTask("translation", False, MISSING_EXTRA),
]


def test_check_says_why_a_task_is_missing(tmp_path: Path) -> None:
    _, out, _ = _worker(Settings(), tmp_path / ".env", check=True, tasks=TASKS)

    assert out.splitlines()[1:] == [
        "cli.worker_task.offered(task=cli.worker_task_name.speech)",
        "cli.worker_task.missing_hf_token(task=cli.worker_task_name.speakers)",
        "cli.worker_task.missing_extra(task=cli.worker_task_name.translation)",
    ]


def test_check_without_a_known_reason(tmp_path: Path) -> None:
    tasks = [WorkerTask("speakers", False)]

    _, out, _ = _worker(Settings(), tmp_path / ".env", check=True, tasks=tasks)

    assert out.splitlines()[1] == "cli.worker_task.missing(task=cli.worker_task_name.speakers)"


def test_check_as_json_for_the_build_smoke_test(tmp_path: Path) -> None:
    settings = Settings(worker_host="0.0.0.0", worker_port=9001)

    code, out, runs = _worker(
        settings, tmp_path / ".env", check=True, json_output=True, tasks=TASKS
    )

    assert (code, runs) == (0, [])
    assert json.loads(out) == {
        "version": __version__,
        "url": "http://0.0.0.0:9001",
        "tasks": [task.to_dict() for task in TASKS],
    }
