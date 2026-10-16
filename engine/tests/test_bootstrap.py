from __future__ import annotations

from pathlib import Path

import pytest

from tests.fakes import FakeLanguageModel, FakeSessionObserver, FakeTranscriber
from vozata import bootstrap
from vozata.audio.capture import WasapiSource
from vozata.audio.devices import DeviceInfo
from vozata.audio.mixer import MonoMixer, StereoMixer
from vozata.config import ConfigError, Settings
from vozata.domain import AppLanguage, Channel, ConversationLanguage, MixMode
from vozata.llm.ollama import OllamaLanguageModel
from vozata.minutes.generator import MinutesGenerator
from vozata.transcription.faster_whisper import FasterWhisperTranscriber

MIC = DeviceInfo(9, "Headset Mic", 2, 48000, False)
LOOPBACK = DeviceInfo(10, "Speakers [Loopback]", 2, 48000, True)
OTHER = DeviceInfo(3, "USB Mic", 1, 44100, False)


@pytest.fixture
def devices(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    looked_up: list[int] = []

    def find(device_id: int) -> DeviceInfo:
        looked_up.append(device_id)
        return OTHER

    monkeypatch.setattr(bootstrap, "default_input", lambda: MIC)
    monkeypatch.setattr(bootstrap, "default_loopback", lambda: LOOPBACK)
    monkeypatch.setattr(bootstrap, "find_device", find)
    return looked_up


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(output_dir=tmp_path / "recordings", **overrides)  # type: ignore[arg-type]


def test_registries_hold_the_default_providers() -> None:
    assert bootstrap.TRANSCRIBERS["faster_whisper"] is FasterWhisperTranscriber
    assert bootstrap.MIXERS[MixMode.MONO] is MonoMixer
    assert bootstrap.MIXERS[MixMode.STEREO] is StereoMixer
    model = bootstrap.LANGUAGE_MODELS["ollama"](Settings(ollama_model="qwen2.5:3b"))
    assert isinstance(model, OllamaLanguageModel)
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
    assert session._language is ConversationLanguage.ES
    assert devices == []
    assert not (tmp_path / "recordings").exists()  # nothing is created before start()


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


def test_build_labeler_applies_the_configured_overrides() -> None:
    settings = Settings(mic_label="Host", app_language=AppLanguage.ES)

    labeler = bootstrap.build_labeler(settings, bootstrap.build_localizer(settings))

    assert labeler.label("mic") == "Host"
    assert labeler.label("system") == "Otros"
