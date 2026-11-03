from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from vozata.recorder import __main__ as recorder_main
from vozata.recorder.lock import read_lock, remove_lock, write_lock

SRC = Path(__file__).resolve().parents[2] / "src"
HEAVY = (
    "fastapi",
    "uvicorn",
    "faster_whisper",
    "av",
    "httpx",
    "torch",
    "ctranslate2",
    "onnxruntime",
    "pydantic",
    "vozata.bootstrap",
    "vozata.config",
    "vozata.api",
)


def _python(code: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60
    )


def test_the_recorder_imports_no_heavy_module() -> None:
    result = _python(
        "import sys, time; t = time.perf_counter();"
        "import vozata.recorder.app, vozata.recorder.__main__, vozata.audio.catalog;"
        "print(time.perf_counter() - t);"
        "print(' '.join(sorted(sys.modules)))"
    )

    assert result.returncode == 0, result.stderr
    seconds, modules = result.stdout.splitlines()
    loaded = set(modules.split())
    assert [m for m in loaded if m in HEAVY or m.split(".")[0] in HEAVY] == []
    assert float(seconds) < 1.5


def test_version_runs_without_the_engine() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "vozata.recorder", "--version"],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(SRC)},
        timeout=60,
    )

    assert result.returncode == 0
    assert result.stdout.startswith("vozata-recorder ")


def test_a_port_taken_by_a_running_recorder_means_already_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vozata.recorder import http as http_module

    def taken(*args: object, **kwargs: object) -> None:
        raise OSError("address in use")

    monkeypatch.setattr(http_module.RecorderServer, "__init__", taken)
    monkeypatch.setattr(recorder_main, "answers", lambda port, timeout=1.0: True)

    code = recorder_main.main(["--port", "8799", "--output-dir", str(tmp_path)])

    assert code == recorder_main.ALREADY_RUNNING


def test_a_port_taken_by_something_else_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vozata.recorder import http as http_module

    def taken(*args: object, **kwargs: object) -> None:
        raise OSError("address in use")

    monkeypatch.setattr(http_module.RecorderServer, "__init__", taken)
    monkeypatch.setattr(recorder_main, "answers", lambda port, timeout=1.0: False)

    assert recorder_main.main(["--port", "8799", "--output-dir", str(tmp_path)]) == 1


def test_serve_answers_and_stops_on_shutdown(tmp_path: Path) -> None:
    settings = recorder_main.load_recorder_settings({})
    settings = type(settings)(**{**settings.__dict__, "output_dir": tmp_path, "port": 0})
    result: list[int] = []
    thread = threading.Thread(target=lambda: result.append(recorder_main.serve(settings)))
    thread.start()
    lock = None
    for _ in range(100):
        lock = read_lock(tmp_path / "live")
        if lock is not None:
            break
        time.sleep(0.05)
    assert lock is not None and lock.pid == os.getpid()

    assert recorder_main.answers(lock.port)
    import urllib.request

    urllib.request.urlopen(
        urllib.request.Request(f"http://127.0.0.1:{lock.port}/shutdown", method="POST"), timeout=5
    ).close()
    thread.join(10)

    assert result == [0]
    assert read_lock(tmp_path / "live") is None


def test_answers_is_false_when_nothing_listens() -> None:
    assert recorder_main.answers(1, timeout=0.2) is False


def test_the_lock_file_round_trips_and_only_its_owner_removes_it(tmp_path: Path) -> None:
    write_lock(tmp_path, 8766, "2026-11-03T10:00:00-03:00")
    lock = read_lock(tmp_path)
    assert lock is not None and (lock.port, lock.pid) == (8766, os.getpid())

    (tmp_path / "recorder.lock").write_text('{"pid": 1, "port": 1, "started_at": ""}')
    remove_lock(tmp_path)
    assert read_lock(tmp_path) is not None

    (tmp_path / "recorder.lock").write_text("garbage")
    assert read_lock(tmp_path) is None


def test_stop_asks_a_running_recorder_to_quit_unless_it_records(tmp_path: Path) -> None:
    from tests.recorder.test_app import Rig

    rig = Rig(tmp_path)
    try:
        rig.client.request("POST", "/recordings", {})
        assert recorder_main.main(["--stop", "--port", str(rig.server.port)]) == 3
        rig.client.request("POST", "/recordings/current/stop")
        assert recorder_main.main(["--stop", "--port", str(rig.server.port)]) == 0
        assert rig.app.shutdown_requested.is_set()
    finally:
        rig.close()


def test_stop_without_a_recorder_is_fine() -> None:
    assert recorder_main.stop(1) == 0
