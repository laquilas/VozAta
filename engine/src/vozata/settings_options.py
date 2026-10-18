"""`GET /settings/options`: the lists the settings page offers for some keys (phase 38).

Each `settings_fields.Field` may name an `options_source`; this module builds every source. The
only network call is Ollama's `/api/tags` on `OLLAMA_URL` (local, short timeout): an unreachable
server gives an empty list and `reachable: false`, never an error.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from vozata.domain import WhisperDevice

_log = logging.getLogger(__name__)

OLLAMA_TIMEOUT = 2.0  # seconds; the page opens without waiting longer for a stopped server

# faster-whisper model names and the Hugging Face repositories they download.
WHISPER_MODELS: dict[str, str] = {
    "tiny": "Systran/faster-whisper-tiny",
    "tiny.en": "Systran/faster-whisper-tiny.en",
    "base": "Systran/faster-whisper-base",
    "base.en": "Systran/faster-whisper-base.en",
    "small": "Systran/faster-whisper-small",
    "small.en": "Systran/faster-whisper-small.en",
    "medium": "Systran/faster-whisper-medium",
    "medium.en": "Systran/faster-whisper-medium.en",
    "large-v1": "Systran/faster-whisper-large-v1",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "distil-large-v2": "Systran/faster-distil-whisper-large-v2",
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
    "distil-medium.en": "Systran/faster-distil-whisper-medium.en",
    "distil-small.en": "Systran/faster-distil-whisper-small.en",
}
COMPUTE_TYPES = (
    "default",
    "auto",
    "int8",
    "int8_float16",
    "int8_float32",
    "int8_bfloat16",
    "int16",
    "float16",
    "bfloat16",
    "float32",
)
OLLAMA_MODELS = "ollama_models"


@dataclass(frozen=True)
class SettingOption:
    """One entry of a list; `available` is false for a model that is not downloaded yet."""

    value: str
    label: str
    available: bool = True


@dataclass(frozen=True)
class OptionLists:
    """Every source's options, and whether each network source answered."""

    options: dict[str, list[SettingOption]]
    reachable: dict[str, bool]


class SettingsOptions:
    """Builds the option lists from the provider registries, the model cache and Ollama."""

    def __init__(
        self,
        providers: Mapping[str, Sequence[str]],
        hf_cache: Path,
        ollama_url: Callable[[], str],
        gpu_available: Callable[[], bool],
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._providers = providers  # source → registry keys, e.g. "stt_providers"
        self._hf_cache = hf_cache
        self._ollama_url = ollama_url
        self._gpu_available = gpu_available
        self._transport = transport

    def collect(self) -> OptionLists:
        options = {
            source: [SettingOption(name, name) for name in sorted(names)]
            for source, names in self._providers.items()
        }
        options["whisper_models"] = self.whisper_models()
        options["compute_types"] = [SettingOption(name, name) for name in COMPUTE_TYPES]
        options["devices"] = self.devices()
        models = self.ollama_models()
        options[OLLAMA_MODELS] = models or []
        return OptionLists(options, {OLLAMA_MODELS: models is not None})

    def whisper_models(self) -> list[SettingOption]:
        """The known names (available when cached) and other Whisper repositories in the cache."""
        cached = self._cached_repositories()
        known = [
            SettingOption(name, name, repository.lower() in cached)
            for name, repository in WHISPER_MODELS.items()
        ]
        listed = {repository.lower() for repository in WHISPER_MODELS.values()}
        extra = [
            SettingOption(repository, repository)
            for repository in sorted(cached.values())
            if repository.lower() not in listed and "whisper" in repository.lower()
        ]
        return known + extra

    def devices(self) -> list[SettingOption]:
        gpu = self._gpu_available()
        return [
            SettingOption(device.value, device.value, gpu or device is not WhisperDevice.CUDA)
            for device in WhisperDevice
        ]

    def ollama_models(self) -> list[SettingOption] | None:
        """The pulled models, or None when Ollama does not answer."""
        url = self._ollama_url().rstrip("/") + "/api/tags"
        try:
            with httpx.Client(timeout=OLLAMA_TIMEOUT, transport=self._transport) as client:
                response = client.get(url)
                response.raise_for_status()
                names = sorted(str(model["name"]) for model in response.json().get("models", []))
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as error:
            _log.info("Ollama model list unavailable: %s", type(error).__name__)
            return None
        return [SettingOption(name, name) for name in names]

    def _cached_repositories(self) -> dict[str, str]:
        """Downloaded Hugging Face model repositories, lower-case id → id."""
        if not self._hf_cache.is_dir():
            return {}
        found: dict[str, str] = {}
        for folder in self._hf_cache.glob("models--*"):
            snapshots = folder / "snapshots"
            if snapshots.is_dir() and any(snapshots.iterdir()):
                repository = folder.name.removeprefix("models--").replace("--", "/", 1)
                found[repository.lower()] = repository
        return found
