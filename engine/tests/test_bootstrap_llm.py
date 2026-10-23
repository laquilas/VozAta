from __future__ import annotations

from vozata import bootstrap
from vozata.config import Settings
from vozata.llm.ollama import OllamaLanguageModel
from vozata.llm.openai_compatible import OpenAICompatibleLanguageModel


def test_the_language_model_registry_offers_every_provider() -> None:
    assert set(bootstrap.LANGUAGE_MODELS) >= {"ollama", "openai_compatible"}


def test_the_ollama_and_openai_compatible_providers_are_built_from_their_keys() -> None:
    settings = Settings(
        openai_llm_url="http://localhost:1234/v1", openai_llm_key="k", openai_llm_model="m"
    )

    ollama = bootstrap.LANGUAGE_MODELS["ollama"](settings)
    openai = bootstrap.LANGUAGE_MODELS["openai_compatible"](settings)
    try:
        assert isinstance(ollama, OllamaLanguageModel)
        assert isinstance(openai, OpenAICompatibleLanguageModel)
    finally:
        ollama.close()
        openai.close()
