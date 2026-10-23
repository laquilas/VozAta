"""`build_transcriber` and its call sites with the VozAta worker (phase 44)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.fakes import FakeSessionObserver
from tests.test_bootstrap import devices  # noqa: F401 - the fixture
from vozata import bootstrap
from vozata.bootstrap_processing import build_offline_transcription
from vozata.config import ConfigError, Settings
from vozata.domain import TranscriptionResult
from vozata.i18n import TomlLocalizer
from vozata.ports import WorkerUnreachableError
from vozata.processing.gpu_gate import GpuGate, GpuUsage
from vozata.transcription.shared import SharedTranscriber
from vozata.worker_client.transcriber import WorkerTranscriber

URL = "http://gpu-pc:8766"


class _Local:
    def __init__(self, settings: Settings, downloader: object) -> None:
        self.closed = False

    def transcribe(self, *args: object) -> TranscriptionResult:
        return TranscriptionResult((), "pt")

    def close(self) -> None:
        self.closed = True


class _Client:
    """A worker client that answers its probe, or not."""

    reachable = True
    instances: list[_Client] = []

    def __init__(self, url: str, token: str | None) -> None:
        self.url, self.token, self.closed = url, token, False
        _Client.instances.append(self)

    def probe(self) -> None:
        if not _Client.reachable:
            raise WorkerUnreachableError("gpu-pc", "refused")

    def close(self) -> None:
        self.closed = True


class _Notices:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def fallback(self, task: str, host: str) -> None:
        self.calls.append((task, host))


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch) -> type[_Client]:
    _Client.reachable, _Client.instances = True, []
    monkeypatch.setattr(bootstrap, "WorkerClient", _Client)
    monkeypatch.setitem(bootstrap.TRANSCRIBERS, "faster_whisper", _Local)
    return _Client


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    values = {"stt_provider": "vozata_worker", "worker_url": URL, "worker_token": "t0k"}
    values.update(overrides)
    return Settings(output_dir=tmp_path / "recordings", **values)  # type: ignore[arg-type]


def test_a_reachable_worker_transcribes(tmp_path: Path, worker: type[_Client]) -> None:
    notices = _Notices()

    transcriber = bootstrap.build_transcriber(_settings(tmp_path), object(), notices)  # type: ignore[arg-type]

    assert isinstance(transcriber, WorkerTranscriber) and transcriber.remote
    assert (worker.instances[0].url, worker.instances[0].token) == (URL, "t0k")
    assert notices.calls == []


def test_an_unreachable_worker_falls_back_to_this_pc_and_says_so(
    tmp_path: Path, worker: type[_Client]
) -> None:
    worker.reachable = False
    notices = _Notices()

    transcriber = bootstrap.build_transcriber(_settings(tmp_path), object(), notices)  # type: ignore[arg-type]

    assert isinstance(transcriber, _Local)
    assert notices.calls == [("speech", "gpu-pc")]
    assert worker.instances[0].closed


def test_a_setup_error_of_the_worker_closes_the_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, worker: type[_Client]
) -> None:
    def refused(self: _Client) -> None:
        raise ConfigError("WORKER_TOKEN", "********", "worker_unauthorized", host="gpu-pc")

    monkeypatch.setattr(_Client, "probe", refused)

    with pytest.raises(ConfigError):
        bootstrap.build_transcriber(_settings(tmp_path), object())  # type: ignore[arg-type]
    assert worker.instances[0].closed


def test_the_worker_needs_its_address(tmp_path: Path, worker: type[_Client]) -> None:
    with pytest.raises(ConfigError) as caught:
        bootstrap.build_transcriber(_settings(tmp_path, worker_url=None), object())  # type: ignore[arg-type]

    assert (caught.value.key, caught.value.message_key) == ("WORKER_URL", "worker_url_missing")


def test_other_providers_are_built_as_before(tmp_path: Path, worker: type[_Client]) -> None:
    transcriber = bootstrap.build_transcriber(
        _settings(tmp_path, stt_provider="faster_whisper"),
        object(),  # type: ignore[arg-type]
    )

    assert isinstance(transcriber, _Local)
    assert worker.instances == []


def test_the_registry_entry_builds_through_the_worker(
    tmp_path: Path, worker: type[_Client]
) -> None:
    transcriber = bootstrap.TRANSCRIBERS["vozata_worker"](_settings(tmp_path), object())  # type: ignore[arg-type]

    assert isinstance(transcriber, WorkerTranscriber)


def test_a_live_fallback_holds_the_gpu_and_sends_the_notice(
    tmp_path: Path,
    devices: list[int],  # noqa: F811
    worker: type[_Client],
) -> None:
    worker.reachable = False
    gate = GpuGate()
    observer = FakeSessionObserver()
    kept = SharedTranscriber(lambda: _Local(Settings(), None))
    session = bootstrap.build_session(
        _settings(tmp_path),
        observer,
        gate=gate,
        gpu_usage=GpuUsage(False, False, False, speech_fallback=True),
        shared=kept,  # ignored: the worker keeps its own Whisper
    )

    transcriber = session._c.transcriber_factory()

    assert isinstance(transcriber, _Local)
    assert gate.priority_held
    [(code, message)] = observer.of("error")
    assert code == "worker_fallback"
    assert message == TomlLocalizer(Settings().app_language).t(
        "errors.worker.fallback",
        task=TomlLocalizer(Settings().app_language).t("worker.task.speech"),
        host="gpu-pc",
    )


class _Store:
    def read_meta(self, session_id: str) -> dict[str, object]:
        return {}


def test_the_queue_transcription_falls_back_with_the_notice(
    tmp_path: Path, worker: type[_Client]
) -> None:
    worker.reachable = False
    notices = _Notices()
    transcription = build_offline_transcription(
        _settings(tmp_path),
        _Store(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        "s1",
        downloader=object(),  # type: ignore[arg-type]
        notices=notices,
    )

    transcriber = transcription._transcriber_factory()

    assert isinstance(transcriber, _Local)
    assert notices.calls == [("speech", "gpu-pc")]
    assert transcriber.transcribe(np.zeros(1, dtype=np.float32), None).language == "pt"
