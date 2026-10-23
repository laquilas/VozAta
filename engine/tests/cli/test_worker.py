from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest

from tests.fakes import FakeLocalizer
from vozata import __version__
from vozata.cli.console import ConsoleObserver
from vozata.cli.worker import run_worker
from vozata.config import Settings
from vozata.labels import SpeakerLabeler


def _worker(
    settings: Settings, env_file: Path, *, check: bool = False
) -> tuple[int, str, list[tuple[str | None, dict[str, Any]]]]:
    out = io.StringIO()
    localizer = FakeLocalizer()
    console = ConsoleObserver(localizer, SpeakerLabeler(localizer), out)
    runs: list[tuple[str | None, dict[str, Any]]] = []

    def build(settings: Settings, token: str | None) -> object:
        return ("app", token)

    def run(application: Any, **options: Any) -> None:
        runs.append((application[1], options))

    code = run_worker(
        settings,
        console,
        localizer,
        build,  # type: ignore[arg-type]
        run,
        env_file=env_file,
        check=check,
        new_token=lambda: "generated-token",
    )
    return code, out.getvalue(), runs


def test_listens_on_the_network_with_the_configured_token(tmp_path: Path) -> None:
    settings = Settings(worker_host="0.0.0.0", worker_port=8766, worker_token="mine")

    code, out, runs = _worker(settings, tmp_path / ".env")

    assert code == 0
    assert runs == [("mine", {"host": "0.0.0.0", "port": 8766, "log_level": "warning"})]
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
        "WHISPER_MODEL=large-v3-turbo\nWORKER_TOKEN=generated-token\n"
    )
    assert f"cli.worker_token_created(file={env_file},token=generated-token)" in out


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_a_loopback_worker_needs_no_token(tmp_path: Path, host: str) -> None:
    code, _, runs = _worker(Settings(worker_host=host), tmp_path / ".env")

    assert code == 0
    assert runs[0][0] is None
    assert not (tmp_path / ".env").exists()


def test_check_prints_the_version_and_address_and_starts_nothing(tmp_path: Path) -> None:
    settings = Settings(worker_host="0.0.0.0", worker_port=9001)

    code, out, runs = _worker(settings, tmp_path / ".env", check=True)

    assert code == 0
    assert runs == []
    assert out == f"cli.worker_check(url=http://0.0.0.0:9001,version={__version__})\n"
    assert not (tmp_path / ".env").exists()  # a check never writes a token
