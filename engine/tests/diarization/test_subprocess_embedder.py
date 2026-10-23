from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from tests.fakes import FakeModelDownloader
from vozata.config import ConfigError, Settings
from vozata.diarization.models import EMBEDDING_MODEL
from vozata.diarization.runtime import SpeakerRuntime
from vozata.diarization.subprocess_embedder import (
    CHILD_MODULE,
    SubprocessEmbedder,
    pyannote_embedder_from_settings,
)
from vozata.domain import ModelKind, WhisperDevice
from vozata.ports import DiarizationError, SpeakerEmbedder

CHILD = Path(__file__).with_name("fake_embed_child.py")


def _embedder(mode: str, **options: float) -> SubprocessEmbedder:
    command = (sys.executable, str(CHILD), mode)
    return SubprocessEmbedder("hf_x", WhisperDevice.CPU, 16000, command, **options)


def test_clips_round_trip_through_the_child_process() -> None:
    embedder = _embedder("ok")
    try:
        first = embedder.embed(np.full(4, 0.5, dtype=np.float32))
        second = embedder.embed(np.zeros(10, dtype=np.float32))
    finally:
        embedder.close()

    assert first.tolist() == [0.5, 4.0]
    assert second.tolist() == [0.0, 10.0]
    assert isinstance(embedder, SpeakerEmbedder)
    assert embedder._process.poll() == 0
    embedder.close()  # already ended: nothing to do


def test_stray_stdout_lines_are_ignored() -> None:
    embedder = _embedder("noise")
    try:
        assert embedder.embed(np.ones(2, dtype=np.float32)).tolist() == [1.0, 2.0]
    finally:
        embedder.close()


def test_a_failed_load_raises_with_the_child_reason() -> None:
    with pytest.raises(DiarizationError, match="RuntimeError: bad token hf"):
        _embedder("load_error")


def test_a_child_that_dies_raises() -> None:
    embedder = _embedder("crash")
    try:
        with pytest.raises(DiarizationError):
            embedder.embed(np.ones(2, dtype=np.float32))
        embedder._process.wait(5)
        with pytest.raises(DiarizationError, match="gone|exited"):
            embedder.embed(np.ones(2, dtype=np.float32))
    finally:
        embedder.close()


def test_a_slow_reply_times_out() -> None:
    embedder = _embedder("slow", embed_timeout=0.1)
    try:
        with pytest.raises(DiarizationError, match="did not answer within 0.1 s"):
            embedder.embed(np.ones(2, dtype=np.float32))
    finally:
        embedder.close()


def test_a_malformed_reply_raises() -> None:
    embedder = _embedder("bad")
    try:
        with pytest.raises(DiarizationError, match="unreadable embedder reply"):
            embedder.embed(np.ones(2, dtype=np.float32))
    finally:
        embedder.close()


class _HangingProcess:
    """A child that ignores EOF: `wait` times out once, then the kill ends it."""

    def __init__(self) -> None:
        self.stdin = _Pipe()
        self.stdout: list[str] = ['@vozata {"ready": true}\n']
        self.stderr: list[str] = []
        self.killed = False
        self.waits = 0

    def poll(self) -> int | None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        self.waits += 1
        if not self.killed:
            raise subprocess.TimeoutExpired("child", timeout or 0)
        return -9

    def kill(self) -> None:
        self.killed = True


class _Pipe:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, text: str) -> None:
        self.lines.append(text)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_close_kills_a_child_that_does_not_exit() -> None:
    process = _HangingProcess()
    calls: list[tuple] = []

    def popen(*args: object, **kwargs: object) -> _HangingProcess:
        calls.append((args, kwargs))
        return process

    embedder = SubprocessEmbedder("hf_secret", WhisperDevice.CUDA, 16000, popen=popen)
    embedder.close()

    assert process.killed
    [(args, kwargs)] = calls
    assert args == ([sys.executable, "-m", CHILD_MODULE],)
    assert "hf_secret" not in str(args)  # the token goes through stdin only
    assert '"hf_token": "hf_secret"' in process.stdin.lines[0]
    assert '"device": "cuda"' in process.stdin.lines[0]


def test_the_packaged_embedder_starts_with_the_speaker_runtime(tmp_path: Path) -> None:
    root = tmp_path / "speakers"
    (root / "venv" / "Scripts").mkdir(parents=True)
    (root / "venv" / "Scripts" / "python.exe").write_bytes(b"")
    (root / "ready.json").write_text("{}", encoding="utf-8")
    runtime = SpeakerRuntime(root, tmp_path / "bundle")
    calls: list[tuple] = []

    def popen(*args: object, **kwargs: object) -> _HangingProcess:
        calls.append((args, kwargs))
        return _HangingProcess()

    command = runtime.child(CHILD_MODULE)
    embedder = SubprocessEmbedder(
        "hf", WhisperDevice.CPU, 16000, command.argv, popen=popen, env=command.env
    )
    embedder.close()

    [(args, kwargs)] = calls
    assert args == ([str(runtime.python), "-m", CHILD_MODULE],)
    assert kwargs["env"]["PYTHONPATH"] == str(tmp_path / "bundle" / "vozata.zip")


def test_from_settings_without_the_runtime_downloads_nothing(tmp_path: Path) -> None:
    downloader = FakeModelDownloader()

    with pytest.raises(ConfigError) as caught:
        pyannote_embedder_from_settings(
            Settings(hf_token="hf"), downloader, SpeakerRuntime(tmp_path, tmp_path / "b")
        )

    assert caught.value.message_key == "speakers_not_installed"
    assert downloader.calls == []


def test_from_settings_needs_a_token() -> None:
    with pytest.raises(ConfigError) as caught:
        pyannote_embedder_from_settings(Settings(), FakeModelDownloader())

    assert (caught.value.key, caught.value.message_key) == ("HF_TOKEN", "missing_hf_token")


def test_from_settings_passes_the_token_device_and_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[tuple] = []

    class _Recorder:
        def __init__(self, *args: object, **kw: object) -> None:
            built.append(args[:3])

    monkeypatch.setattr("vozata.diarization.subprocess_embedder.SubprocessEmbedder", _Recorder)

    settings = Settings(hf_token="hf_x", diarization_device=WhisperDevice.CPU)
    pyannote_embedder_from_settings(settings, FakeModelDownloader())

    assert built == [("hf_x", WhisperDevice.CPU, 16000)]


def test_embedder_predownloads_its_pyannote_repo_with_the_token_before_spawning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log: list[tuple[str, str]] = []
    downloader = FakeModelDownloader(log=log)

    class _Recorder:
        def __init__(self, token: str, *args: object, **kw: object) -> None:
            log.append(("spawn", token))

    monkeypatch.setattr("vozata.diarization.subprocess_embedder.SubprocessEmbedder", _Recorder)

    pyannote_embedder_from_settings(Settings(hf_token="hf_x"), downloader)

    assert log == [("ensure", EMBEDDING_MODEL), ("spawn", "hf_x")]
    assert downloader.calls == [
        {
            "kind": ModelKind.SPEAKERS,
            "repo_id": "pyannote/wespeaker-voxceleb-resnet34-LM",
            "allow_patterns": None,
            "token": "hf_x",
            "name": "wespeaker-voxceleb-resnet34-LM",
        }
    ]
