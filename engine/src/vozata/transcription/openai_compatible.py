"""`Transcriber` for OpenAI-style `/audio/transcriptions` APIs: OpenAI, Groq, self-hosted servers.

Audio leaves the machine (the CLI and the health panel name the host). One request per window;
the transcription worker stays single-threaded, so segments keep their order.
"""

from __future__ import annotations

import io
import re
import wave
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import urlparse

import httpx
import numpy as np

from vozata.config import ConfigError, Settings
from vozata.domain import TranscriptionResult, Word
from vozata.transcription.retry import TranscriptionRequestError, send_with_retry

PROBE_SECONDS = 0.5
# providers report either an ISO code or the English name of the language
_LANGUAGE_NAMES = {"english": "en", "portuguese": "pt", "spanish": "es"}
_NOT_WORD = re.compile(r"[^\w']+")


class OpenAICompatibleTranscriber:
    """Word timestamps come from `timestamp_granularities[]=word`; providers give no word
    probability, so every word gets `1.0`. Punctuation, missing from the word list, is taken back
    from the response text so the stitcher can still cut at sentence ends."""

    def __init__(
        self,
        url: str,
        api_key: str | None,
        model: str,
        sample_rate: int,
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
        probe: bool = True,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._model = model
        self._rate = sample_rate
        self._sleep = sleep
        self._host = urlparse(url).hostname or url
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(
            base_url=url, headers=headers, timeout=timeout, transport=transport
        )
        if probe:
            self._check_word_timestamps()

    def transcribe(
        self, samples: np.ndarray, language: str | None, hints: str | None = None
    ) -> TranscriptionResult:
        if not np.any(samples):
            return TranscriptionResult(words=(), language=language)  # silence costs nothing
        reply = self._request(samples, language, hints)
        if not isinstance(reply.get("words"), list):
            raise TranscriptionRequestError(
                f"The speech API at {self._host} returned no word timestamps"
            )
        words = _with_punctuation(reply["words"], str(reply.get("text", "")))
        return TranscriptionResult(words=words, language=_language_code(reply.get("language")))

    def close(self) -> None:
        self._client.close()

    def _check_word_timestamps(self) -> None:
        quiet = np.full(round(PROBE_SECONDS * self._rate), 1e-4, dtype=np.float32)
        if not isinstance(self._request(quiet, None, None).get("words"), list):
            raise ConfigError(
                "OPENAI_STT_MODEL", self._model, "no_word_timestamps", host=self._host
            )

    def _request(
        self, samples: np.ndarray, language: str | None, hints: str | None
    ) -> dict[str, Any]:
        data = {
            "model": self._model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "word",
        }
        if language:
            data["language"] = language
        if hints:
            data["prompt"] = hints
        files = {"file": ("audio.wav", _wav(samples, self._rate), "audio/wav")}
        response = send_with_retry(
            lambda: self._client.post("/audio/transcriptions", data=data, files=files),
            sleep=self._sleep,
        )
        if response.status_code >= 400:
            raise TranscriptionRequestError(
                f"The speech API at {self._host} answered HTTP {response.status_code}: "
                f"{_error_message(response)}"
            )
        return response.json()


def remote_host(settings: Settings) -> str | None:
    """The host audio is sent to, or None when transcription runs on this machine."""
    if settings.stt_provider != "openai_compatible":
        return None
    return urlparse(settings.openai_stt_url).hostname or settings.openai_stt_url


def from_settings(settings: Settings) -> OpenAICompatibleTranscriber:
    """`TRANSCRIBERS["openai_compatible"]`."""
    return OpenAICompatibleTranscriber(
        settings.openai_stt_url,
        settings.openai_stt_key,
        settings.openai_stt_model,
        settings.sample_rate,
    )


def _wav(samples: np.ndarray, rate: int) -> bytes:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm.tobytes())
    return buffer.getvalue()


def _with_punctuation(words: Sequence[dict[str, Any]], text: str) -> tuple[Word, ...]:
    tokens = text.split()
    position = 0
    result = []
    for item in words:
        spelled = str(item["word"]).strip()
        core = _NOT_WORD.sub("", spelled.lower())
        for ahead in range(position, min(position + 3, len(tokens))):  # tolerate small drifts
            if _NOT_WORD.sub("", tokens[ahead].lower()) == core:
                spelled, position = tokens[ahead], ahead + 1
                break
        result.append(Word(f" {spelled}", float(item["start"]), float(item["end"]), 1.0))
    return tuple(result)


def _language_code(language: object) -> str | None:
    if not isinstance(language, str):
        return None
    lowered = language.lower()
    return _LANGUAGE_NAMES.get(lowered, lowered if len(lowered) == 2 else None)


def _error_message(response: httpx.Response) -> str:
    try:
        return str(response.json()["error"]["message"])
    except (ValueError, KeyError, TypeError):
        return response.reason_phrase or "error"
