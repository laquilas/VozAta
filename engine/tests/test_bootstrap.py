from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.fakes import (
    FakeDiarizer,
    FakeEmbedder,
    FakeLanguageModel,
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
from vozata.domain import AppLanguage, Channel, ChunkMode, ConversationLanguage, MixMode
from vozata.llm.ollama import OllamaLanguageModel
from vozata.minutes.generator import MinutesGenerator
from vozata.minutes.template_repository import UnknownTemplateError
from vozata.session import SessionStartError
from vozata.storage.search_index import SearchIndex
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
    assert isinstance(components.search_index, SearchIndex)
    assert components.search_index._path == tmp_path / "recordings" / "index.db"
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

    def factory(settings: Settings) -> FakeTranscriber:
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

    container = bootstrap.build_api_container(settings)

    assert container.settings is settings
    assert isinstance(container.devices, WasapiCatalog)
    assert isinstance(container.regenerate_minutes, MinutesJob)
    assert container.llm_reachable() is False
    assert container.store.list_sessions() == []
    assert isinstance(container.search_index, SearchIndex)
    assert container.search_index._path == tmp_path / "recordings" / "index.db"
    container.manager._factory(FakeSessionObserver(), StartOptions(mic_device=3, template="daily"))
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
        }
    ]
    generator = container.regenerate_minutes._build_generator()
    assert generator._llm is llm


@pytest.mark.parametrize(("generate_minutes", "kept"), [(False, True), (True, False)])
def test_a_shared_transcriber_is_leased_and_kept_only_without_minutes(
    tmp_path: Path,
    devices: list[int],
    monkeypatch: pytest.MonkeyPatch,
    generate_minutes: bool,
    kept: bool,
) -> None:
    fake = FakeTranscriber()
    monkeypatch.setitem(bootstrap.TRANSCRIBERS, "fake", lambda settings: fake)
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
        lambda settings: fakes.append(FakeTranscriber()) or fakes[-1],
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
    shared.lease(keep=True)

    container.regenerate_minutes._build_generator()  # POST /minutes frees Whisper first
    assert not shared.loaded and fakes[0].closed
    shared.lease(keep=True)
    container.release_models()  # API shutdown
    assert not shared.loaded and fakes[1].closed


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

    diarizer = bootstrap.DIARIZERS["pyannote"](Settings(hf_token="hf"))

    assert isinstance(diarizer, SubprocessDiarizer)


def test_an_enabled_diarizer_is_built_lazily_from_its_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[Settings] = []
    fake = FakeDiarizer()
    monkeypatch.setitem(bootstrap.DIARIZERS, "fake", lambda s: built.append(s) or fake)
    settings = Settings(diarization_enabled=True, diarization_provider="fake")

    factory = bootstrap.build_diarizer_factory(settings)

    assert factory is not None and built == []
    assert factory() is fake
    assert built == [settings]
    with pytest.raises(ConfigError) as caught:
        bootstrap.build_diarizer_factory(
            Settings(diarization_enabled=True, diarization_provider="nope")
        )
    assert caught.value.key == "DIARIZATION_PROVIDER"


def test_a_shared_transcriber_is_not_kept_when_speakers_are_identified(
    tmp_path: Path, devices: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeTranscriber()
    monkeypatch.setitem(bootstrap.TRANSCRIBERS, "fake", lambda settings: fake)
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
    built: list[Settings] = []
    fake = FakeEmbedder()
    monkeypatch.setitem(bootstrap.EMBEDDERS, "fake", lambda s: built.append(s) or fake)
    settings = Settings(live_diarization_enabled=True, diarization_provider="fake")

    factory = bootstrap.build_embedder_factory(settings)

    assert factory is not None and built == []
    assert factory() is fake
    assert built == [settings]
    assert bootstrap.build_embedder_factory(Settings(diarization_provider="fake")) is None
    with pytest.raises(ConfigError) as caught:
        bootstrap.build_embedder_factory(
            Settings(live_diarization_enabled=True, diarization_provider="nope")
        )
    assert caught.value.key == "DIARIZATION_PROVIDER"


def test_the_embedder_registry_holds_pyannote_and_needs_a_token() -> None:
    with pytest.raises(ConfigError) as caught:
        bootstrap.EMBEDDERS["pyannote"](Settings())

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
    monkeypatch.setitem(bootstrap.DIARIZERS, "fake", lambda settings: fake)

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

    assert isinstance(bootstrap.TRANSLATORS["opus_mt"](Settings()), opus_mt.OpusMtTranslator)


def test_translation_is_off_by_default_and_the_start_choice_overrides_the_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.fakes import FakeTranslator
    from vozata.domain import TranslationTarget

    fake = FakeTranslator()
    monkeypatch.setitem(bootstrap.TRANSLATORS, "fake", lambda settings: fake)
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

    monkeypatch.setitem(bootstrap.TRANSLATORS, "fake", lambda settings: FakeTranslator())
    settings = _settings(tmp_path, translation_provider="fake")

    session = bootstrap.build_session(
        settings, FakeSessionObserver(), translate_to=TranslationTarget.PT
    )

    assert session._c.translate_to == "pt"
    assert session._c.translator_factory is not None
