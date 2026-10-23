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
    alive: set[str] | None = None  # when set, only these URLs answer
    instances: list[_Client] = []

    def __init__(self, url: str, token: str | None) -> None:
        self.url, self.token, self.closed = url, token, False
        _Client.instances.append(self)

    def probe(self) -> None:
        alive = _Client.alive
        if not _Client.reachable if alive is None else self.url not in alive:
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
    _Client.reachable, _Client.alive, _Client.instances = True, None, []
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


MOVED = "http://192.168.0.77:8766"


@pytest.mark.parametrize(
    ("found", "alive", "remote"),
    [
        (MOVED, {MOVED}, True),  # found at its new address: used, no notice
        (MOVED, set(), False),  # found but gone again: fallback
        (None, set(), False),  # not found: fallback
    ],
)
def test_a_moved_worker_is_found_before_the_fallback(
    tmp_path: Path, worker: type[_Client], found: str | None, alive: set[str], remote: bool
) -> None:
    worker.alive = alive
    notices = _Notices()
    asked: list[str | None] = []

    def relocate(settings: Settings) -> str | None:
        asked.append(settings.worker_id)
        return found

    transcriber = bootstrap.build_transcriber(
        _settings(tmp_path, worker_id="4f1c"),
        object(),  # type: ignore[arg-type]
        notices,
        relocate,
    )

    assert asked == ["4f1c"]
    assert isinstance(transcriber, WorkerTranscriber) is remote
    assert notices.calls == ([] if remote else [("speech", "gpu-pc")])
    assert all(client.closed for client in worker.instances[: 1 if remote else None])


@pytest.mark.parametrize(
    ("answers", "worker_id", "moved"),
    [
        ([("4f1c", MOVED)], "4f1c", MOVED),
        ([("4f1c", URL)], "4f1c", None),  # same address: nothing moved
        ([("other", MOVED)], "4f1c", None),
        ([("4f1c", MOVED)], None, None),  # never paired: nothing to look for
    ],
)
def test_the_relocator_looks_for_the_paired_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    answers: list[tuple[str, str]],
    worker_id: str | None,
    moved: str | None,
) -> None:
    from vozata.worker_client.discovery import FoundWorker

    broadcasts: list[tuple[int, list[str]]] = []

    def discover(port: int, sources: list[str]) -> list[FoundWorker]:
        broadcasts.append((port, sources))
        return [FoundWorker(id_, "GPU-PC", url, "0.9.0", None) for id_, url in answers]

    monkeypatch.setattr(bootstrap, "discover_workers", discover)
    monkeypatch.setattr(bootstrap, "lan_addresses", lambda: ["192.168.0.5"])
    saved: list[str] = []

    relocate = bootstrap.worker_relocator(saved.append)
    result = relocate(_settings(tmp_path, worker_id=worker_id))

    assert result == moved
    assert saved == ([moved] if moved else [])
    assert broadcasts == ([] if worker_id is None else [(8767, ["192.168.0.5"])])


# Speakers on the worker (phase 45)


class _LocalSpeakers:
    def __init__(self, settings: Settings, downloader: object) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.fixture
def speakers(monkeypatch: pytest.MonkeyPatch, worker: type[_Client]) -> type[_Client]:
    monkeypatch.setitem(bootstrap.DIARIZERS, "pyannote", _LocalSpeakers)
    monkeypatch.setitem(bootstrap.EMBEDDERS, "pyannote", _LocalSpeakers)
    return worker


def _speaker_settings(tmp_path: Path, **overrides: object) -> Settings:
    values = {"diarization_provider": "vozata_worker", "diarization_enabled": True}
    values.update(overrides)
    return _settings(tmp_path, **values)


def test_speakers_run_on_a_reachable_worker(tmp_path: Path, speakers: type[_Client]) -> None:
    from vozata.worker_client.speakers import WorkerDiarizer, WorkerEmbedder

    settings = _speaker_settings(tmp_path, live_diarization_enabled=True)
    notices = _Notices()

    diarizer = bootstrap.build_diarizer_factory(settings, object(), notices)()  # type: ignore[arg-type,misc]
    embedder = bootstrap.build_embedder_factory(settings, object(), notices)()  # type: ignore[arg-type,misc]

    assert isinstance(diarizer, WorkerDiarizer) and isinstance(embedder, WorkerEmbedder)
    assert notices.calls == []


def test_speakers_fall_back_to_this_pc_with_a_notice(
    tmp_path: Path, speakers: type[_Client]
) -> None:
    speakers.reachable = False
    settings = _speaker_settings(tmp_path, live_diarization_enabled=True)
    notices = _Notices()

    diarizer = bootstrap.build_diarizer(settings, object(), notices)  # type: ignore[arg-type]
    embedder = bootstrap.build_embedder_factory(settings, object(), notices)()  # type: ignore[arg-type,misc]

    assert isinstance(diarizer, _LocalSpeakers) and isinstance(embedder, _LocalSpeakers)
    assert notices.calls == [("speakers", "gpu-pc"), ("speakers", "gpu-pc")]


def test_the_speaker_registries_build_through_the_worker(
    tmp_path: Path, speakers: type[_Client]
) -> None:
    from vozata.worker_client.speakers import WorkerDiarizer, WorkerEmbedder

    settings = _speaker_settings(tmp_path)

    assert isinstance(bootstrap.DIARIZERS["vozata_worker"](settings, object()), WorkerDiarizer)  # type: ignore[arg-type]
    assert isinstance(bootstrap.EMBEDDERS["vozata_worker"](settings, object()), WorkerEmbedder)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("token", "extra", "capabilities", "reason"),
    [
        ("hf_x", True, ["speech", "speakers"], None),
        (None, True, ["speech"], "missing_hf_token"),
        # phase 51: a token without pyannote no longer offers speakers (every job failed)
        ("hf_x", False, ["speech"], "missing_extra"),
    ],
)
def test_the_worker_offers_speakers_with_the_extra_and_a_hugging_face_token(
    monkeypatch: pytest.MonkeyPatch,
    token: str | None,
    extra: bool,
    capabilities: list[str],
    reason: str | None,
) -> None:
    from fastapi.testclient import TestClient

    from vozata.api.system_info import GpuInfo
    from vozata.diarization import models
    from vozata.translation import opus_mt

    monkeypatch.setattr(bootstrap, "query_gpu", lambda: GpuInfo(False))
    monkeypatch.setattr(models, "has_extra", lambda runtime=None: extra)
    monkeypatch.setattr(opus_mt, "has_extra", lambda: False)
    app = bootstrap.build_worker_app(Settings(hf_token=token), None)

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        assert client.get("/health").json()["capabilities"] == capabilities
        speakers = client.get("/local/status").json()["tasks"][1]
    assert (speakers["name"], speakers["reason"]) == ("speakers", reason)


# Translation on the worker (phase 46)


@pytest.mark.parametrize(
    ("reachable", "notified"), [(True, []), (False, [("translation", "gpu-pc")])]
)
def test_translation_runs_on_the_worker_or_falls_back_here(
    monkeypatch: pytest.MonkeyPatch,
    worker: type[_Client],
    tmp_path: Path,
    reachable: bool,
    notified: list[tuple[str, str]],
) -> None:
    from vozata.domain import TranslationTarget
    from vozata.worker_client.translator import WorkerTranslator

    monkeypatch.setitem(bootstrap.TRANSLATORS, "opus_mt", _LocalSpeakers)
    worker.reachable = reachable
    settings = _settings(tmp_path, translation_provider="vozata_worker")
    notices = _Notices()

    target, factory = bootstrap.build_translator_factory(
        settings,
        TranslationTarget("en"),
        object(),
        notices,  # type: ignore[arg-type]
    )
    translator = factory()  # type: ignore[misc]

    assert target == "en"
    assert isinstance(translator, WorkerTranslator if reachable else _LocalSpeakers)
    assert notices.calls == notified
    assert isinstance(
        bootstrap.TRANSLATORS["vozata_worker"](settings, object()),  # type: ignore[arg-type]
        WorkerTranslator if reachable else _LocalSpeakers,
    )


@pytest.mark.parametrize(
    ("extra", "capabilities"), [(True, ["speech", "translation"]), (False, ["speech"])]
)
def test_the_worker_offers_translation_with_the_extra(
    monkeypatch: pytest.MonkeyPatch, extra: bool, capabilities: list[str]
) -> None:
    from fastapi.testclient import TestClient

    from vozata.api.system_info import GpuInfo
    from vozata.translation import opus_mt

    monkeypatch.setattr(bootstrap, "query_gpu", lambda: GpuInfo(False))
    monkeypatch.setattr(opus_mt, "has_extra", lambda: extra)
    app = bootstrap.build_worker_app(Settings(hf_token=None), None)

    with TestClient(app) as client:
        assert client.get("/health").json()["capabilities"] == capabilities
