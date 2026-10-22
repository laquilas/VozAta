from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.fakes import (
    FakeDiarizer,
    FakeEmbedder,
    FakeLanguageModel,
    FakeModelDownloader,
    FakeSessionObserver,
    FakeTranscriber,
)
from vozata import bootstrap
from vozata.audio.capture import WasapiSource
from vozata.audio.chunker import FixedWindowChunker
from vozata.audio.devices import DeviceInfo
from vozata.audio.mixer import MonoMixer, StereoMixer
from vozata.audio.vad_chunker import VadChunker
from vozata.config import ConfigError, Settings
from vozata.domain import (
    AppLanguage,
    Channel,
    ChunkMode,
    ConversationLanguage,
    MixMode,
    ModelKind,
    SessionStatus,
    StorageInfo,
)
from vozata.llm.ollama import OllamaLanguageModel
from vozata.minutes.generator import MinutesGenerator
from vozata.minutes.template_repository import UnknownTemplateError
from vozata.session import SessionStartError
from vozata.storage.sqlite.audio import SqliteAudioStore
from vozata.storage.sqlite.repository import SqliteSessionRepository
from vozata.storage.sqlite.search import SqliteSearch
from vozata.transcription.faster_whisper import FasterWhisperTranscriber
from vozata.transcription.shared import SharedTranscriber

MIC = DeviceInfo(9, "Headset Mic", 2, 48000, False)
LOOPBACK = DeviceInfo(10, "Speakers [Loopback]", 2, 48000, True)
OTHER = DeviceInfo(3, "USB Mic", 1, 44100, False)


class _FakeAudioThread:
    instances: list[_FakeAudioThread] = []
    fail: Exception | None = None

    def __init__(self) -> None:
        if _FakeAudioThread.fail is not None:
            raise _FakeAudioThread.fail
        self.pa = object()
        self.calls = 0
        self.closed = False
        _FakeAudioThread.instances.append(self)

    def call(self, function):  # type: ignore[no-untyped-def]
        self.calls += 1
        return function()

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def devices(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    looked_up: list[int] = []

    def find(device_id: int, pa: object) -> DeviceInfo:
        assert pa is _FakeAudioThread.instances[-1].pa
        looked_up.append(device_id)
        if device_id == 404:
            raise LookupError("No audio device with id 404")
        return OTHER

    _FakeAudioThread.instances = []
    _FakeAudioThread.fail = None
    monkeypatch.setattr(bootstrap, "PortAudioThread", _FakeAudioThread)
    monkeypatch.setattr(bootstrap, "default_input", lambda pa: MIC)
    monkeypatch.setattr(bootstrap, "default_loopback", lambda pa: LOOPBACK)
    monkeypatch.setattr(bootstrap, "find_device", find)
    return looked_up


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(output_dir=tmp_path / "recordings", **overrides)  # type: ignore[arg-type]


def test_registries_hold_the_default_providers() -> None:
    assert bootstrap.TRANSCRIBERS["faster_whisper"] is FasterWhisperTranscriber
    assert bootstrap.TRANSCRIBERS["openai_compatible"].__name__ == "from_settings"
    assert bootstrap.MIXERS[MixMode.MONO] is MonoMixer
    assert bootstrap.MIXERS[MixMode.STEREO] is StereoMixer
    settings = Settings(ollama_model="qwen2.5:3b", ollama_keep_alive="10m")
    model = bootstrap.LANGUAGE_MODELS["ollama"](settings)
    assert isinstance(model, OllamaLanguageModel)
    assert model.keep_alive == "10m"
    model.close()


def test_build_session_uses_the_default_devices_and_settings(
    tmp_path: Path, devices: list[int]
) -> None:
    settings = _settings(tmp_path, transcription_language=ConversationLanguage.ES)

    session = bootstrap.build_session(settings, FakeSessionObserver())

    components = session._c
    assert set(components.sources) == {Channel.MIC, Channel.SYSTEM}
    assert all(isinstance(source, WasapiSource) for source in components.sources.values())
    assert components.device_names == {
        Channel.MIC: "Headset Mic",
        Channel.SYSTEM: "Speakers [Loopback]",
    }
    assert isinstance(components.mixer, MonoMixer)
    assert isinstance(components.minutes, MinutesGenerator)
    assert components.chunker_factory is not None
    assert isinstance(components.chunker_factory(Channel.MIC, lambda chunk: None), VadChunker)
    assert components.diarizer_factory is None  # DIARIZATION_ENABLED defaults to false
    assert components.embedder_factory is None  # LIVE_DIARIZATION_ENABLED defaults to false
    assert session._language is ConversationLanguage.ES
    assert isinstance(components.search_index, SqliteSearch)  # STORAGE_BACKEND=sqlite
    assert isinstance(session._store, SqliteSessionRepository)
    assert session._store.database.path == tmp_path / "recordings" / "vozata.db"
    assert devices == []
    assert not (tmp_path / "recordings").exists()  # nothing is created before start()


@pytest.mark.parametrize(
    ("mode", "kind"), [(ChunkMode.VAD, VadChunker), (ChunkMode.FIXED, FixedWindowChunker)]
)
def test_chunkers_registry_builds_the_configured_chunker(mode: ChunkMode, kind: type) -> None:
    chunks: list[object] = []
    chunker = bootstrap.CHUNKERS[mode](Settings(), Channel.SYSTEM, chunks.append)

    assert isinstance(chunker, kind)
    assert set(bootstrap.CHUNKERS) == set(ChunkMode)


def test_build_session_uses_fixed_windows_when_configured(
    tmp_path: Path, devices: list[int]
) -> None:
    settings = _settings(tmp_path, chunk_mode=ChunkMode.FIXED)

    factory = bootstrap.build_session(settings, FakeSessionObserver())._c.chunker_factory

    assert factory is not None
    assert isinstance(factory(Channel.MIC, lambda chunk: None), FixedWindowChunker)


def test_build_session_honours_explicit_devices_language_and_mix_mode(
    tmp_path: Path, devices: list[int]
) -> None:
    settings = _settings(tmp_path, mix_mode=MixMode.STEREO, generate_minutes=False)

    session = bootstrap.build_session(
        settings,
        FakeSessionObserver(),
        language=ConversationLanguage.AUTO,
        mic_device=3,
        system_device=3,
    )

    assert devices == [3, 3]
    assert session._c.device_names == {Channel.MIC: "USB Mic", Channel.SYSTEM: "USB Mic"}
    assert isinstance(session._c.mixer, StereoMixer)
    assert session._c.minutes is None
    assert session._language is ConversationLanguage.AUTO
    assert session._c.minutes_template == "general"  # stored even without minutes


def test_build_session_uses_the_chosen_template(tmp_path: Path, devices: list[int]) -> None:
    settings = _settings(tmp_path, minutes_template="daily")

    default = bootstrap.build_session(settings, FakeSessionObserver())
    chosen = bootstrap.build_session(settings, FakeSessionObserver(), template="client")

    assert default._c.minutes_template == "daily"
    assert default._c.minutes is not None and default._c.minutes.template_id == "daily"
    assert chosen._c.minutes_template == "client"
    assert chosen._c.minutes is not None and chosen._c.minutes.template_id == "client"
    with pytest.raises(UnknownTemplateError):
        bootstrap.build_session(settings, FakeSessionObserver(), template="weekly")
    assert devices == []  # an unknown template fails before any device is opened


def test_transcriber_factory_builds_the_registered_provider_lazily(
    tmp_path: Path, devices: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    built: list[Settings] = []
    fake = FakeTranscriber()

    def factory(settings: Settings, downloader: object) -> FakeTranscriber:
        built.append(settings)
        return fake

    monkeypatch.setitem(bootstrap.TRANSCRIBERS, "fake", factory)
    settings = _settings(tmp_path, stt_provider="fake")
    session = bootstrap.build_session(settings, FakeSessionObserver())

    assert built == []
    assert session._c.transcriber_factory() is fake
    assert built == [settings]


@pytest.mark.parametrize(
    ("overrides", "key"),
    [({"stt_provider": "whisper.cpp"}, "STT_PROVIDER"), ({"llm_provider": "gpt"}, "LLM_PROVIDER")],
)
def test_unknown_providers_fail_fast_naming_the_registered_keys(
    tmp_path: Path, devices: list[int], overrides: dict[str, str], key: str
) -> None:
    with pytest.raises(ConfigError) as error:
        bootstrap.build_session(_settings(tmp_path, **overrides), FakeSessionObserver())

    assert error.value.key == key
    assert error.value.message_key == "invalid_choice"


def test_build_minutes_generator_uses_the_registered_language_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = FakeLanguageModel(["# Minutes"])
    monkeypatch.setitem(bootstrap.LANGUAGE_MODELS, "fake", lambda settings: llm)
    settings = Settings(llm_provider="fake", app_language=AppLanguage.PT_BR, llm_max_chars=5000)

    generator = bootstrap.build_minutes_generator(settings)

    assert generator._llm is llm
    assert generator._max_chars == 5000
    assert generator._localizer.t("labels.mic") == "Eu"
    assert generator.template_id == "general"
    assert generator._template.name == "Reunião geral"


def test_build_minutes_generator_picks_the_template(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(bootstrap.LANGUAGE_MODELS, "fake", lambda settings: FakeLanguageModel())
    settings = Settings(llm_provider="fake", minutes_template="daily")

    assert bootstrap.build_minutes_generator(settings).template_id == "daily"
    assert bootstrap.build_minutes_generator(settings, template="client").template_id == "client"
    with pytest.raises(UnknownTemplateError):
        bootstrap.build_minutes_generator(settings, template="weekly")


def test_build_labeler_applies_the_configured_overrides() -> None:
    settings = Settings(mic_label="Host", app_language=AppLanguage.ES)

    labeler = bootstrap.build_labeler(settings, bootstrap.build_localizer(settings))

    assert labeler.label("mic") == "Host"
    assert labeler.label("system") == "Otros"


def test_sources_share_one_portaudio_thread_released_with_the_session(
    tmp_path: Path, devices: list[int]
) -> None:
    session = bootstrap.build_session(_settings(tmp_path), FakeSessionObserver())

    [audio] = _FakeAudioThread.instances
    assert audio.calls == 2  # both device lookups ran on the PortAudio thread
    for source in session._c.sources.values():
        assert source._pa is audio.pa
        assert source._call_audio == audio.call
    session._c.release()
    assert audio.closed


def test_an_unknown_device_closes_the_portaudio_thread(tmp_path: Path, devices: list[int]) -> None:
    with pytest.raises(LookupError):
        bootstrap.build_session(_settings(tmp_path), FakeSessionObserver(), mic_device=404)

    assert _FakeAudioThread.instances[-1].closed


def test_unresponsive_windows_audio_fails_with_a_localized_start_error(
    tmp_path: Path, devices: list[int]
) -> None:
    _FakeAudioThread.fail = TimeoutError("PortAudio did not answer within 20.0 s")

    with pytest.raises(SessionStartError) as error:
        bootstrap.build_session(_settings(tmp_path), FakeSessionObserver())

    assert error.value.code == "audio_unavailable"
    assert "Windows" in str(error.value)


def test_build_api_container_wires_real_providers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vozata.api.minutes_job import MinutesJob
    from vozata.api.session_manager import StartOptions
    from vozata.audio.catalog import WasapiCatalog

    llm = FakeLanguageModel(available=False)
    monkeypatch.setitem(bootstrap.LANGUAGE_MODELS, "fake", lambda settings: llm)
    built: list[dict[str, Any]] = []
    monkeypatch.setattr(
        bootstrap, "build_session", lambda settings, observer, **kwargs: built.append(kwargs)
    )
    settings = _settings(tmp_path, llm_provider="fake")
    from vozata.api.system_info import GpuInfo
    from vozata.models.download import HubDownloader
    from vozata.processing.gpu_gate import GpuGate, GpuUsage
    from vozata.processing.live_lease import LiveModelTurn
    from vozata.processing.queue import ProcessingQueue

    monkeypatch.setattr(bootstrap, "query_gpu", lambda: GpuInfo(True, "RTX 3050", 6144))

    container = bootstrap.build_api_container(settings)

    assert container.settings is settings
    queue = container.manager._queue
    assert isinstance(queue, ProcessingQueue)  # phase 40: started, shares the live gate
    assert queue._thread is not None and queue._thread.daemon
    assert isinstance(container.devices, WasapiCatalog)
    assert isinstance(container.regenerate_minutes, MinutesJob)
    assert container.llm_reachable() is False
    assert container.store.list_sessions() == []
    assert isinstance(container.search_index, SqliteSearch)
    assert container.storage == StorageInfo("sqlite", tmp_path / "recordings" / "vozata.db")
    assert isinstance(container.audio, SqliteAudioStore)
    assert (
        container.audio_cache is container.audio.cache
    )  # one cache: health, DELETE /storage/cache
    assert container.migration is not None  # phase 33, started by the app's lifespan
    assert container.migration.summary()["state"] == "idle"
    container.manager._factory(FakeSessionObserver(), StartOptions(mic_device=3, template="daily"))
    gate = built[0].pop("gate")
    assert isinstance(gate, GpuGate) and gate is queue._gate
    assert isinstance(built[0].pop("live_models"), LiveModelTurn)  # shared by every session
    downloader = built[0].pop("downloader")  # phase 42: publishes through the container's tracker
    assert isinstance(downloader, HubDownloader) and downloader._tracker is container.downloads
    assert downloader._offline is False
    assert built == [
        {
            "language": None,
            "mic_device": 3,
            "system_device": None,
            "template": "daily",
            "vocabulary": (),
            "env_file": Path(".env"),
            "shared": None,
            "translate_to": None,
            "title": None,
            "live_transcription": None,
            "gpu_usage": GpuUsage(speech=True, speakers=False, llm=False),  # LLM "fake"
        }
    ]
    generator = container.regenerate_minutes._build_generator()
    assert generator._llm is llm


@pytest.mark.parametrize(
    ("setting", "option", "expected"),
    [(True, None, True), (False, None, False), (False, True, True), (True, False, False)],
)
def test_build_session_uses_the_setting_when_the_option_is_none(
    tmp_path: Path,
    devices: list[int],
    setting: bool,
    option: bool | None,
    expected: bool,
) -> None:
    settings = _settings(tmp_path, live_transcription=setting)

    session = bootstrap.build_session(settings, FakeSessionObserver(), live_transcription=option)

    assert session._c.live_transcription is expected


@pytest.mark.parametrize(("generate_minutes", "kept"), [(False, True), (True, False)])
def test_a_shared_transcriber_is_leased_and_kept_only_without_minutes(
    tmp_path: Path,
    devices: list[int],
    monkeypatch: pytest.MonkeyPatch,
    generate_minutes: bool,
    kept: bool,
) -> None:
    fake = FakeTranscriber()
    monkeypatch.setitem(bootstrap.TRANSCRIBERS, "fake", lambda settings, downloader: fake)
    settings = _settings(tmp_path, stt_provider="fake", generate_minutes=generate_minutes)
    shared = SharedTranscriber(lambda: fake)

    session = bootstrap.build_session(settings, FakeSessionObserver(), shared=shared)
    lease = session._c.transcriber_factory()
    lease.close()

    assert shared.loaded is kept
    assert fake.closed is not kept


def test_the_api_container_shares_the_transcriber_when_keep_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vozata.api.session_manager import StartOptions

    fakes: list[FakeTranscriber] = []
    monkeypatch.setitem(
        bootstrap.TRANSCRIBERS,
        "fake",
        lambda settings, downloader: fakes.append(FakeTranscriber()) or fakes[-1],
    )
    monkeypatch.setitem(bootstrap.LANGUAGE_MODELS, "fake", lambda settings: FakeLanguageModel())
    shared_seen: list[object] = []
    monkeypatch.setattr(
        bootstrap,
        "build_session",
        lambda settings, observer, **kwargs: shared_seen.append(kwargs["shared"]),
    )
    settings = _settings(
        tmp_path, stt_provider="fake", llm_provider="fake", whisper_keep_loaded=True
    )

    container = bootstrap.build_api_container(settings)
    container.manager._factory(FakeSessionObserver(), StartOptions())
    [shared] = shared_seen
    assert isinstance(shared, SharedTranscriber)
    shared.lease(keep=True).close()  # an idle, kept Whisper

    container.regenerate_minutes._build_generator()  # POST /minutes frees Whisper first
    assert not shared.loaded and fakes[0].closed
    shared.lease(keep=True).close()
    container.release_models()  # API shutdown
    assert not shared.loaded and fakes[1].closed
    shared.lease(keep=True)  # a live session holds the model
    container.manager._session = SimpleNamespace(status=SessionStatus.RECORDING)
    container.regenerate_minutes._build_generator()  # never unloads the live Whisper
    container.manager._session = None
    assert shared.loaded and not shared._unload


@pytest.mark.parametrize(
    ("url", "unloaded"),
    [("http://localhost:11434", True), ("http://192.168.0.20:11434", False)],
)
def test_whisper_is_freed_for_a_local_ollama_but_kept_for_a_remote_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, url: str, unloaded: bool
) -> None:
    from vozata.api.session_manager import StartOptions

    fakes: list[FakeTranscriber] = []
    monkeypatch.setitem(
        bootstrap.TRANSCRIBERS,
        "fake",
        lambda settings, downloader: fakes.append(FakeTranscriber()) or fakes[-1],
    )
    monkeypatch.setitem(bootstrap.LANGUAGE_MODELS, "ollama", lambda settings: FakeLanguageModel())
    shared_seen: list[object] = []
    monkeypatch.setattr(
        bootstrap,
        "build_session",
        lambda settings, observer, **kwargs: shared_seen.append(kwargs["shared"]),
    )
    settings = _settings(
        tmp_path,
        stt_provider="fake",
        llm_provider="ollama",
        ollama_url=url,
        whisper_keep_loaded=True,
    )

    container = bootstrap.build_api_container(settings)
    container.manager._factory(FakeSessionObserver(), StartOptions())
    [shared] = shared_seen
    assert isinstance(shared, SharedTranscriber)
    shared.lease(keep=True).close()  # an idle, kept Whisper

    container.regenerate_minutes._build_generator()

    assert (not shared.loaded) is unloaded
    assert fakes[0].closed is unloaded


def test_without_keep_loaded_sessions_load_their_own_transcriber(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vozata.api.session_manager import StartOptions

    monkeypatch.setitem(bootstrap.LANGUAGE_MODELS, "fake", lambda settings: FakeLanguageModel())
    shared_seen: list[object] = []
    monkeypatch.setattr(
        bootstrap,
        "build_session",
        lambda settings, observer, **kwargs: shared_seen.append(kwargs["shared"]),
    )

    container = bootstrap.build_api_container(_settings(tmp_path, llm_provider="fake"))
    container.manager._factory(FakeSessionObserver(), StartOptions())
    container.release_models()

    assert shared_seen == [None]


def test_saved_settings_reach_the_next_session_and_the_llm_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vozata.api.session_manager import StartOptions

    class ClosingModel(FakeLanguageModel):
        closed = 0

        def close(self) -> None:
            ClosingModel.closed += 1

    models: list[Settings] = []

    def build_model(settings: Settings) -> ClosingModel:
        models.append(settings)
        return ClosingModel(available=True)

    monkeypatch.setitem(bootstrap.LANGUAGE_MODELS, "fake", build_model)
    sessions: list[Settings] = []
    monkeypatch.setattr(
        bootstrap, "build_session", lambda settings, observer, **kwargs: sessions.append(settings)
    )
    (tmp_path / ".env").write_text("LLM_PROVIDER=fake\n", encoding="utf-8")  # as at start-up
    container = bootstrap.build_api_container(
        _settings(tmp_path, llm_provider="fake"), env_file=tmp_path / ".env"
    )

    container.settings_file.update({"CHUNK_SECONDS": 8, "OLLAMA_MODEL": "qwen2.5:3b"})
    container.manager._factory(FakeSessionObserver(), StartOptions())

    assert sessions[0].chunk_seconds == 8.0
    assert container.llm_reachable() is True
    assert models[-1].ollama_model == "qwen2.5:3b"
    assert ClosingModel.closed == 1
    assert "CHUNK_SECONDS=8" in (tmp_path / ".env").read_text(encoding="utf-8")
    container.settings_file.update({"APP_LANGUAGE": "es"})
    regenerated = container.regenerate_minutes._build_generator("client")
    assert regenerated.template_id == "client"
    assert regenerated._template.name == "Reunión con cliente"
    assert regenerated._localizer.t("minutes.output_language") == "español"  # same language


def test_the_diarizer_registry_holds_pyannote_behind_a_child_process() -> None:
    from vozata.diarization.subprocess_diarizer import SubprocessDiarizer

    downloader = FakeModelDownloader()

    diarizer = bootstrap.DIARIZERS["pyannote"](Settings(hf_token="hf"), downloader)

    assert isinstance(diarizer, SubprocessDiarizer)


def test_an_enabled_diarizer_is_built_lazily_from_its_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[tuple[Settings, object]] = []
    fake = FakeDiarizer()
    monkeypatch.setitem(bootstrap.DIARIZERS, "fake", lambda s, d: built.append((s, d)) or fake)
    settings = Settings(diarization_enabled=True, diarization_provider="fake")
    downloader = FakeModelDownloader()

    factory = bootstrap.build_diarizer_factory(settings, downloader)

    assert factory is not None and built == []
    assert factory() is fake
    assert built == [(settings, downloader)]
    with pytest.raises(ConfigError) as caught:
        bootstrap.build_diarizer_factory(
            Settings(diarization_enabled=True, diarization_provider="nope")
        )
    assert caught.value.key == "DIARIZATION_PROVIDER"


def test_a_shared_transcriber_is_not_kept_when_speakers_are_identified(
    tmp_path: Path, devices: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeTranscriber()
    monkeypatch.setitem(bootstrap.TRANSCRIBERS, "fake", lambda settings, downloader: fake)
    settings = _settings(
        tmp_path,
        stt_provider="fake",
        generate_minutes=False,
        diarization_enabled=True,
        hf_token="hf",
    )
    shared = SharedTranscriber(lambda: fake)

    session = bootstrap.build_session(settings, FakeSessionObserver(), shared=shared)
    session._c.transcriber_factory().close()

    assert session._c.diarizer_factory is not None
    assert shared.loaded is False  # VRAM rule: Whisper never stays next to the diarizer
    assert fake.closed


def test_the_live_embedder_is_built_lazily_from_its_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[tuple[Settings, object]] = []
    fake = FakeEmbedder()
    monkeypatch.setitem(bootstrap.EMBEDDERS, "fake", lambda s, d: built.append((s, d)) or fake)
    settings = Settings(live_diarization_enabled=True, diarization_provider="fake")
    downloader = FakeModelDownloader()

    factory = bootstrap.build_embedder_factory(settings, downloader)

    assert factory is not None and built == []
    assert factory() is fake
    assert built == [(settings, downloader)]
    assert bootstrap.build_embedder_factory(Settings(diarization_provider="fake")) is None
    with pytest.raises(ConfigError) as caught:
        bootstrap.build_embedder_factory(
            Settings(live_diarization_enabled=True, diarization_provider="nope")
        )
    assert caught.value.key == "DIARIZATION_PROVIDER"


def test_the_embedder_registry_holds_pyannote_and_needs_a_token() -> None:
    with pytest.raises(ConfigError) as caught:
        bootstrap.EMBEDDERS["pyannote"](Settings(), FakeModelDownloader())

    assert caught.value.key == "HF_TOKEN"


def test_build_session_wires_the_live_embedder_when_enabled(
    tmp_path: Path, devices: list[int]
) -> None:
    settings = _settings(tmp_path, live_diarization_enabled=True, hf_token="hf")

    session = bootstrap.build_session(settings, FakeSessionObserver())

    assert session._c.embedder_factory is not None


def test_build_diarizer_ignores_the_enabled_flag_for_explicit_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeDiarizer()
    monkeypatch.setitem(bootstrap.DIARIZERS, "fake", lambda settings, downloader: fake)

    assert bootstrap.build_diarizer(Settings(diarization_provider="fake")) is fake


def test_vocabulary_path_defaults_to_a_file_next_to_the_env_file(tmp_path: Path) -> None:
    assert bootstrap.vocabulary_path(Settings()) == Path("vocabulary.txt")
    assert bootstrap.vocabulary_path(Settings(), tmp_path / ".env") == tmp_path / "vocabulary.txt"
    chosen = Settings(vocabulary_file=tmp_path / "glossary.txt")
    assert bootstrap.vocabulary_path(chosen, tmp_path / ".env") == tmp_path / "glossary.txt"


def test_session_vocabulary_puts_session_terms_before_the_glossary(tmp_path: Path) -> None:
    (tmp_path / "vocabulary.txt").write_text("# glossary\nAvalonia\nvozata\n", "utf-8")

    terms = bootstrap.session_vocabulary(Settings(), ["VozAta", "Jéssica"], tmp_path / ".env")

    assert terms == ["VozAta", "Jéssica", "Avalonia"]


def test_an_unreadable_glossary_is_skipped_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "glossary.txt").write_bytes(b"\xff\xfe\xfa bad")
    settings = Settings(vocabulary_file=tmp_path / "glossary.txt")

    assert bootstrap.session_vocabulary(settings, ["Jéssica"]) == ["Jéssica"]
    assert "vocabulary file" in caplog.text


def test_build_session_merges_the_meeting_terms_with_the_glossary(
    tmp_path: Path, devices: list[int]
) -> None:
    (tmp_path / "vocabulary.txt").write_text("Avalonia\n", "utf-8")

    session = bootstrap.build_session(
        _settings(tmp_path),
        FakeSessionObserver(),
        vocabulary=["Jéssica"],
        env_file=tmp_path / ".env",
    )

    assert session._c.vocabulary == ("Jéssica", "Avalonia")


def test_the_api_container_finds_the_glossary_next_to_its_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(bootstrap.LANGUAGE_MODELS, "fake", lambda settings: FakeLanguageModel())
    settings = _settings(tmp_path, llm_provider="fake")

    container = bootstrap.build_api_container(settings, tmp_path / ".env")

    assert container.vocabulary_file() == tmp_path / "vocabulary.txt"


def test_the_translator_registry_holds_opus_mt(monkeypatch: pytest.MonkeyPatch) -> None:
    from vozata.translation import opus_mt

    monkeypatch.setattr(opus_mt, "require_extra", lambda: None)

    translator = bootstrap.TRANSLATORS["opus_mt"](Settings(), FakeModelDownloader())

    assert isinstance(translator, opus_mt.OpusMtTranslator)


def test_download_events_are_published_with_null_session() -> None:
    broadcaster = _Published()
    tracker = bootstrap.build_downloads(broadcaster)

    tracker.start(ModelKind.SPEECH, "large-v3-turbo", 1600).failed("network down")

    assert broadcaster.events == [
        (
            "download_progress",
            None,
            {
                "kind": "speech",
                "model": "large-v3-turbo",
                "downloaded_bytes": 0,
                "total_bytes": 1600,
                "state": "running",
            },
        ),
        (
            "download_progress",
            None,
            {
                "kind": "speech",
                "model": "large-v3-turbo",
                "downloaded_bytes": 0,
                "total_bytes": 1600,
                "state": "failed",
                "reason": "network down",
            },
        ),
    ]


class _Published:
    def __init__(self) -> None:
        self.events: list[tuple[str, str | None, dict[str, object]]] = []

    def publish(self, kind: str, session_id: str | None, data: dict[str, object]) -> None:
        self.events.append((kind, session_id, data))


def test_the_api_container_passes_its_downloader_to_jobs_and_the_kept_whisper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vozata import bootstrap_processing
    from vozata.api.system_info import GpuInfo
    from vozata.models.download import HubDownloader

    monkeypatch.setitem(bootstrap.LANGUAGE_MODELS, "fake", lambda settings: FakeLanguageModel())
    monkeypatch.setattr(bootstrap, "query_gpu", lambda: GpuInfo(False))
    loaded: list[object] = []
    monkeypatch.setitem(
        bootstrap.TRANSCRIBERS,
        "fake",
        lambda settings, downloader: loaded.append(downloader) or FakeTranscriber(),
    )
    jobs: list[dict[str, Any]] = []
    monkeypatch.setattr(
        bootstrap_processing,
        "build_processing_job",
        lambda *args, **kwargs: jobs.append(kwargs) or object(),
    )
    container = bootstrap.build_api_container(
        _settings(tmp_path, llm_provider="fake", stt_provider="fake", whisper_keep_loaded=True)
    )

    container.manager._job_factory("20261015_202358", False, None)
    shared = jobs[0]["shared"]
    shared.lease(keep=False).close()

    downloader = jobs[0]["downloader"]
    assert isinstance(downloader, HubDownloader) and downloader._tracker is container.downloads
    assert loaded == [downloader]  # the kept Whisper downloads through the same tracker


def test_the_api_container_tracks_downloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vozata.api.system_info import GpuInfo

    monkeypatch.setitem(bootstrap.LANGUAGE_MODELS, "fake", lambda settings: FakeLanguageModel())
    monkeypatch.setattr(bootstrap, "query_gpu", lambda: GpuInfo(False))
    container = bootstrap.build_api_container(_settings(tmp_path, llm_provider="fake"))
    published: list[tuple[str, str | None, dict[str, Any]]] = []
    monkeypatch.setattr(
        container.broadcaster,
        "publish",
        lambda kind, sid, data: published.append((kind, sid, data)),
    )

    container.downloads.start(ModelKind.TRANSLATION, "ROMANCE-en", None).done()

    assert [(kind, session) for kind, session, _ in published] == [
        ("download_progress", None),
        ("download_progress", None),
    ]


def test_translation_is_off_by_default_and_the_start_choice_overrides_the_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.fakes import FakeTranslator
    from vozata.domain import TranslationTarget

    fake = FakeTranslator()
    monkeypatch.setitem(bootstrap.TRANSLATORS, "fake", lambda settings, downloader: fake)
    settings = Settings(translate_to=TranslationTarget.ES, translation_provider="fake")

    assert bootstrap.build_translator_factory(Settings()) == (None, None)
    assert bootstrap.build_translator_factory(settings, TranslationTarget.OFF) == (None, None)
    target, factory = bootstrap.build_translator_factory(settings)
    assert target == "es" and factory is not None and factory() is fake
    assert bootstrap.build_translator_factory(settings, TranslationTarget.EN)[0] == "en"
    with pytest.raises(ConfigError) as caught:
        bootstrap.build_translator_factory(
            Settings(translate_to=TranslationTarget.PT, translation_provider="nope")
        )
    assert caught.value.key == "TRANSLATION_PROVIDER"


def test_build_session_passes_the_translation_to_the_session(
    tmp_path: Path, devices: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.fakes import FakeTranslator
    from vozata.domain import TranslationTarget

    monkeypatch.setitem(
        bootstrap.TRANSLATORS, "fake", lambda settings, downloader: FakeTranslator()
    )
    settings = _settings(tmp_path, translation_provider="fake")

    session = bootstrap.build_session(
        settings, FakeSessionObserver(), translate_to=TranslationTarget.PT
    )

    assert session._c.translate_to == "pt"
    assert session._c.translator_factory is not None


def test_the_api_container_queues_stopped_meetings_with_their_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime

    from vozata.api.system_info import GpuInfo
    from vozata.processing.job import StepKind
    from vozata.processing.queue import ProcessingState

    monkeypatch.setitem(bootstrap.LANGUAGE_MODELS, "fake", lambda settings: FakeLanguageModel())
    monkeypatch.setattr(bootstrap, "query_gpu", lambda: GpuInfo(False))
    container = bootstrap.build_api_container(
        _settings(tmp_path, llm_provider="fake", generate_minutes=False)
    )
    published: list[tuple[str, str | None, dict[str, Any]]] = []
    monkeypatch.setattr(
        container.broadcaster,
        "publish",
        lambda kind, sid, data: published.append((kind, sid, data)),
    )
    session_id = container.store.create(datetime(2026, 10, 15, 20, 23, 58).astimezone())
    container.store.write_meta(session_id, {"id": session_id, "status": "finalizing"})

    job = container.manager._job_factory(session_id, False, None)
    container.manager._queue._publish(ProcessingState(session_id, "running", 40, None, None))
    job.on_finished()

    assert [step.kind for step in job.steps] == [StepKind.TRANSCRIBE, StepKind.MIX, StepKind.INDEX]
    assert not any(step.gpu for step in job.steps)  # no CUDA: nothing is gated
    assert published[0] == (
        "processing",
        session_id,
        {"state": "running", "percent": 40, "step": None},
    )
    assert published[1] == ("status", session_id, {"status": "done", "duration_seconds": 0.0})
    assert container.store.read_meta(session_id)["status"] == "done"


def test_ask_and_the_model_test_take_gpu_priority_only_for_a_local_gpu_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vozata.api.system_info import GpuInfo

    monkeypatch.setitem(bootstrap.LANGUAGE_MODELS, "fake", lambda settings: FakeLanguageModel())
    monkeypatch.setattr(bootstrap, "query_gpu", lambda: GpuInfo(True, "RTX 3050", 6144))
    container = bootstrap.build_api_container(
        _settings(tmp_path, llm_provider="ollama"), env_file=tmp_path / ".env"
    )
    gate = container.manager._queue._gate

    assert container.ask._gate is gate and container.ask._uses_gpu() is True
    checks = container.connection_check.__self__
    with checks._priority(container.settings_file.current):
        assert gate.priority_held
    container.settings_file.update({"LLM_PROVIDER": "fake"})
    assert container.ask._uses_gpu() is False
    with checks._priority(container.settings_file.current):
        assert not gate.priority_held
    assert container.regenerate_minutes._uses_gpu() is False
    assert container.extract_action_items._uses_gpu() is False


def test_the_worker_app_needs_its_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from vozata.api.system_info import GpuInfo

    monkeypatch.setattr(bootstrap, "query_gpu", lambda: GpuInfo(False))
    client = TestClient(bootstrap.build_worker_app(Settings(), "t0ken"))

    assert client.get("/health").status_code == 401
    body = client.get("/health", headers={"Authorization": "Bearer t0ken"}).json()
    assert (body["gpu"]["available"], body["models"]) == (False, [])
