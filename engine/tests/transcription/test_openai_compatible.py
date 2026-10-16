from __future__ import annotations

import io
import wave

import httpx
import numpy as np
import pytest

from tests.transcription.contract import check_transcriber_contract
from vozata.config import ConfigError
from vozata.transcription.openai_compatible import OpenAICompatibleTranscriber
from vozata.transcription.retry import TranscriptionRequestError

URL = "https://api.example.test/v1"
RATE = 16000
SPEECH = (0.1 * np.sin(np.arange(2 * RATE) / 10)).astype(np.float32)

REPLY = {
    "language": "portuguese",
    "text": "Bom dia, pessoal. Vamos começar?",
    "words": [
        {"word": "Bom", "start": 0.1, "end": 0.3},
        {"word": "dia", "start": 0.3, "end": 0.6},
        {"word": "pessoal", "start": 0.7, "end": 1.1},
        {"word": "Vamos", "start": 1.3, "end": 1.6},
        {"word": "começar", "start": 1.6, "end": 1.9},
    ],
}


class Api:
    """A fake OpenAI-style endpoint that records requests."""

    def __init__(self, *replies: httpx.Response) -> None:
        self.replies = list(replies)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.replies.pop(0) if self.replies else httpx.Response(200, json=REPLY)

    def transcriber(
        self, key: str | None = "sk-test", probe: bool = False
    ) -> OpenAICompatibleTranscriber:
        return OpenAICompatibleTranscriber(
            URL, key, "whisper-1", RATE, transport=httpx.MockTransport(self), probe=probe,
            sleep=lambda seconds: None,
        )  # fmt: skip


def fields(request: httpx.Request) -> dict[str, bytes]:
    """The multipart form fields of a request (name -> raw value)."""
    boundary = request.headers["content-type"].split("boundary=")[1].encode()
    found: dict[str, bytes] = {}
    for part in request.content.split(b"--" + boundary):
        if b"\r\n\r\n" not in part:
            continue
        head, body = part.split(b"\r\n\r\n", 1)
        name = head.split(b'name="')[1].split(b'"')[0].decode()
        found[name] = body.rstrip(b"\r\n")
    return found


def test_honours_the_transcriber_contract() -> None:
    check_transcriber_contract(Api().transcriber(), SPEECH, "pt")


def test_the_request_is_an_openai_style_multipart_with_a_wav_file() -> None:
    api = Api()

    api.transcriber().transcribe(SPEECH, "pt", hints="VozAta, Whisper")

    [request] = api.requests
    assert (request.method, str(request.url)) == ("POST", f"{URL}/audio/transcriptions")
    assert request.headers["authorization"] == "Bearer sk-test"
    form = fields(request)
    assert form["model"] == b"whisper-1"
    assert form["response_format"] == b"verbose_json"
    assert form["timestamp_granularities[]"] == b"word"
    assert form["language"] == b"pt"
    assert form["prompt"] == b"VozAta, Whisper"
    with wave.open(io.BytesIO(form["file"]), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (RATE, 1, 2)
        assert wav.getnframes() == len(SPEECH)


def test_auto_language_and_no_hints_send_no_fields_and_no_key_sends_no_header() -> None:
    api = Api()

    api.transcriber(key=None).transcribe(SPEECH, None)

    form = fields(api.requests[0])
    assert "language" not in form and "prompt" not in form
    assert "authorization" not in api.requests[0].headers


def test_words_get_their_punctuation_back_and_the_language_becomes_a_code() -> None:
    result = Api().transcriber().transcribe(SPEECH, None)

    assert [word.text for word in result.words] == [
        " Bom",
        " dia,",
        " pessoal.",
        " Vamos",
        " começar?",
    ]
    assert (result.words[2].start, result.words[2].end, result.words[2].probability) == (
        0.7,
        1.1,
        1.0,
    )
    assert result.language == "pt"


@pytest.mark.parametrize(
    ("language", "code"),
    [("pt", "pt"), ("English", "en"), ("spanish", "es"), ("klingon", None), (None, None)],
)
def test_language_names_and_codes_are_normalized(language: str | None, code: str | None) -> None:
    api = Api(httpx.Response(200, json={**REPLY, "language": language}))

    assert api.transcriber().transcribe(SPEECH, None).language == code


def test_words_split_inside_a_hyphenated_token_are_merged_with_its_punctuation() -> None:
    reply = {
        "text": "Adiar para sexta-feira. Certo?",
        "words": [
            {"word": "Adiar", "start": 0.0, "end": 0.4},
            {"word": "para", "start": 0.4, "end": 0.6},
            {"word": "sexta", "start": 0.6, "end": 0.9},
            {"word": "-feira", "start": 0.9, "end": 1.3},
            {"word": "Certo", "start": 1.5, "end": 1.8},
        ],
    }

    result = Api(httpx.Response(200, json=reply)).transcriber().transcribe(SPEECH, "pt")

    assert [word.text for word in result.words] == [" Adiar", " para", " sexta-feira.", " Certo?"]
    assert (result.words[2].start, result.words[2].end) == (0.6, 1.3)


def test_a_word_missing_from_the_text_keeps_its_own_spelling() -> None:
    reply = {"text": "Totally different.", "words": [{"word": "hello", "start": 0, "end": 0.5}]}

    result = Api(httpx.Response(200, json=reply)).transcriber().transcribe(SPEECH, "en")

    assert [word.text for word in result.words] == [" hello"]


def test_silence_is_never_sent() -> None:
    api = Api()

    result = api.transcriber().transcribe(np.zeros(RATE, dtype=np.float32), "pt")

    assert (result.words, api.requests) == ((), [])


def test_rate_limits_are_retried() -> None:
    api = Api(httpx.Response(429, headers={"Retry-After": "1"}), httpx.Response(200, json=REPLY))

    assert Api.transcriber(api).transcribe(SPEECH, "pt").words
    assert len(api.requests) == 2


def test_it_gives_up_after_three_failed_attempts() -> None:
    api = Api(*(httpx.Response(503) for _ in range(3)))

    with pytest.raises(TranscriptionRequestError, match="after 3 attempts: HTTP 503"):
        api.transcriber().transcribe(SPEECH, "pt")


def test_a_rejected_request_explains_why_without_the_key() -> None:
    api = Api(httpx.Response(401, json={"error": {"message": "Incorrect API key provided."}}))

    with pytest.raises(TranscriptionRequestError) as caught:
        api.transcriber().transcribe(SPEECH, "pt")

    assert "HTTP 401" in str(caught.value) and "Incorrect API key provided." in str(caught.value)
    assert "sk-test" not in str(caught.value)


def test_an_error_body_that_is_not_json_still_reports_the_status() -> None:
    api = Api(httpx.Response(400, text="<html>bad</html>"))

    with pytest.raises(TranscriptionRequestError, match="HTTP 400"):
        api.transcriber().transcribe(SPEECH, "pt")


def test_the_start_up_probe_accepts_a_provider_with_word_timestamps() -> None:
    api = Api(httpx.Response(200, json={"text": "", "words": []}))

    api.transcriber(probe=True)

    assert len(api.requests) == 1


def test_a_provider_without_word_timestamps_is_rejected_at_start_up() -> None:
    api = Api(httpx.Response(200, json={"text": "", "language": "en"}))

    with pytest.raises(ConfigError) as caught:
        api.transcriber(probe=True)

    assert (caught.value.key, caught.value.message_key) == (
        "OPENAI_STT_MODEL",
        "no_word_timestamps",
    )
    assert "api.example.test" in str(caught.value)


def test_a_reply_without_words_during_a_session_is_an_error() -> None:
    api = Api(httpx.Response(200, json={"text": "Hi."}))

    with pytest.raises(TranscriptionRequestError, match="word timestamps"):
        api.transcriber().transcribe(SPEECH, "en")


def test_close_closes_the_http_client() -> None:
    transcriber = Api().transcriber()

    transcriber.close()

    with pytest.raises(RuntimeError):
        transcriber.transcribe(SPEECH, "en")


def test_the_settings_factory_reads_the_external_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from vozata.config import Settings
    from vozata.transcription import openai_compatible as module

    built: list[tuple] = []
    monkeypatch.setattr(module, "OpenAICompatibleTranscriber", lambda *args: built.append(args))

    module.from_settings(Settings(openai_stt_url=URL, openai_stt_key="k", openai_stt_model="m"))

    assert built == [(URL, "k", "m", 16000)]
