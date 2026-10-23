"""Live translation on the worker (phase 46): the service and `POST /translate`."""

from __future__ import annotations

from fastapi.testclient import TestClient

from vozata.api.system_info import GpuInfo
from vozata.ports import TranslationError
from vozata.worker.app import create_worker_app
from vozata.worker.speech import LoadedModel, SpeechService
from vozata.worker.translation import TranslateService

TOKEN = "t0k"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class _Translator:
    built = 0

    def __init__(self) -> None:
        _Translator.built += 1
        self.closed = False

    def translate(self, text: str, source: str, target: str) -> str:
        if source == target:
            raise TranslationError("unsupported language pair")
        return f"[{source}>{target}] {text}"

    def close(self) -> None:
        self.closed = True


def _client(service: TranslateService | None) -> TestClient:
    app = create_worker_app(
        TOKEN,
        gpu_info=lambda: GpuInfo(False),
        speech=SpeechService(lambda: LoadedModel(None, "")),  # type: ignore[arg-type]
        translator=service,
    )
    return TestClient(app)


def test_the_service_loads_the_translator_once_and_closes_it() -> None:
    made: list[_Translator] = []

    def factory() -> _Translator:
        made.append(_Translator())
        return made[-1]

    service = TranslateService(factory)

    assert service.translate("olá", "pt", "en") == "[pt>en] olá"
    assert service.translate("tchau", "pt", "en") == "[pt>en] tchau"
    service.close()
    service.close()

    assert len(made) == 1 and made[0].closed


def test_the_route_translates_and_reports_a_bad_pair() -> None:
    translator = _Translator()
    with _client(TranslateService(lambda: translator)) as client:
        done = client.post(
            "/translate", json={"text": "olá", "source": "pt", "target": "en"}, headers=AUTH
        )
        bad = client.post(
            "/translate", json={"text": "x", "source": "pt", "target": "pt"}, headers=AUTH
        )
        health = client.get("/health", headers=AUTH).json()
        refused = client.post("/translate", json={"text": "x", "source": "pt", "target": "en"})

    assert done.json() == {"text": "[pt>en] olá"}
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "worker_translation_failed"
    assert health["capabilities"] == ["speech", "translation"]
    assert refused.status_code == 401
    assert translator.closed  # released when the worker stops


def test_a_worker_without_the_extra_does_not_translate() -> None:
    with _client(None) as client:
        reply = client.post(
            "/translate", json={"text": "x", "source": "pt", "target": "en"}, headers=AUTH
        )
        capabilities = client.get("/health", headers=AUTH).json()["capabilities"]

    assert reply.status_code == 503
    assert reply.json()["error"]["code"] == "worker_translation_unavailable"
    assert capabilities == ["speech"]
