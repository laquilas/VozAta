"""Composition root: the only module that knows concrete providers (architecture §3).

New providers are added to a registry here; orchestrators never change.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from vozata.audio.capture import WasapiSource
from vozata.audio.clock import SessionClock
from vozata.audio.devices import DeviceInfo, default_input, default_loopback, find_device
from vozata.audio.mixer import MonoMixer, StereoMixer
from vozata.audio.portaudio import PortAudioThread
from vozata.config import ConfigError, Settings
from vozata.domain import Channel, ConversationLanguage, MixMode
from vozata.i18n import TomlLocalizer
from vozata.labels import SpeakerLabeler
from vozata.llm.ollama import OllamaLanguageModel
from vozata.minutes.generator import MinutesGenerator
from vozata.ports import AudioMixer, LanguageModel, Localizer, SessionObserver, Transcriber
from vozata.session import RecordingSession, SessionComponents, SessionStartError
from vozata.storage.session_store import SessionStore
from vozata.transcription.faster_whisper import FasterWhisperTranscriber

TRANSCRIBERS: dict[str, Callable[[Settings], Transcriber]] = {
    "faster_whisper": FasterWhisperTranscriber,
}
LANGUAGE_MODELS: dict[str, Callable[[Settings], LanguageModel]] = {
    "ollama": lambda settings: OllamaLanguageModel(settings.ollama_url, settings.ollama_model),
}
MIXERS: dict[MixMode, Callable[[], AudioMixer]] = {
    MixMode.MONO: MonoMixer,
    MixMode.STEREO: StereoMixer,
}


def _provider[T](registry: Mapping[str, T], key: str, value: str) -> T:
    if value not in registry:
        raise ConfigError(key, value, "invalid_choice", allowed=", ".join(sorted(registry)))
    return registry[value]


def build_localizer(settings: Settings) -> Localizer:
    return TomlLocalizer(settings.app_language)


def build_labeler(settings: Settings, localizer: Localizer) -> SpeakerLabeler:
    return SpeakerLabeler(localizer, settings.mic_label, settings.system_label)


def build_store(settings: Settings) -> SessionStore:
    return SessionStore(settings.output_dir)


def build_minutes_generator(
    settings: Settings, localizer: Localizer | None = None
) -> MinutesGenerator:
    factory = _provider(LANGUAGE_MODELS, "LLM_PROVIDER", settings.llm_provider)
    return MinutesGenerator(
        factory(settings), localizer or build_localizer(settings), settings.llm_max_chars
    )


def build_session(
    settings: Settings,
    observer: SessionObserver,
    *,
    language: ConversationLanguage | None = None,
    mic_device: int | None = None,
    system_device: int | None = None,
) -> RecordingSession:
    """A ready-to-start session; no stream is opened and no folder created until `start()`.

    Devices default to the WASAPI default microphone and the default output's loopback. Every
    PortAudio call runs on one `PortAudioThread`, closed by the session when capture ends.
    """
    transcriber = _provider(TRANSCRIBERS, "STT_PROVIDER", settings.stt_provider)
    localizer = build_localizer(settings)
    minutes = build_minutes_generator(settings, localizer) if settings.generate_minutes else None
    try:
        audio = PortAudioThread()
    except TimeoutError:
        message = localizer.t("errors.session.audio_unavailable")
        raise SessionStartError("audio_unavailable", message) from None
    try:
        devices = _devices(audio, mic_device, system_device)
    except BaseException:
        audio.close()
        raise
    clock = SessionClock()
    components = SessionComponents(
        sources={
            channel: WasapiSource(
                device, clock, settings.sample_rate, pa=audio.pa, call_audio=audio.call
            )
            for channel, device in devices.items()
        },
        device_names={channel: device.name for channel, device in devices.items()},
        clock=clock,
        transcriber_factory=lambda: transcriber(settings),
        mixer=MIXERS[settings.mix_mode](),
        minutes=minutes,
        localizer=localizer,
        labeler=build_labeler(settings, localizer),
        release=audio.close,
    )
    return RecordingSession(
        settings,
        build_store(settings),
        components,
        observer,
        language or settings.transcription_language,
    )


def _devices(
    audio: PortAudioThread, mic_device: int | None, system_device: int | None
) -> dict[Channel, DeviceInfo]:
    pa = audio.pa
    mic = audio.call(
        lambda: default_input(pa) if mic_device is None else find_device(mic_device, pa)
    )
    system = audio.call(
        lambda: default_loopback(pa) if system_device is None else find_device(system_device, pa)
    )
    return {Channel.MIC: mic, Channel.SYSTEM: system}
