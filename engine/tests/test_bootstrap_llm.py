from __future__ import annotations

from vozata import bootstrap
from vozata.config import Settings
from vozata.llm.ollama import OllamaLanguageModel
from vozata.llm.openai_compatible import OpenAICompatibleLanguageModel


def test_the_language_model_registry_offers_every_provider() -> None:
    assert set(bootstrap.LANGUAGE_MODELS) >= {"ollama", "openai_compatible", "anthropic"}


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


def test_the_anthropic_provider_is_built_from_its_keys() -> None:
    from vozata.llm.anthropic import AnthropicLanguageModel

    model = bootstrap.LANGUAGE_MODELS["anthropic"](Settings(anthropic_api_key=None))
    try:
        assert isinstance(model, AnthropicLanguageModel)
        assert model.is_available() is False  # no key: nothing is sent
    finally:
        model.close()
