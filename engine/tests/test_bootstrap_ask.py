from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.fakes import FakeLanguageModel, FakeSessionObserver, FakeTranscriber
from vozata import bootstrap
from vozata.api.ask_job import AskJob
from vozata.api.session_manager import StartOptions
from vozata.config import Settings
from vozata.domain import AppLanguage, SessionStatus
from vozata.qa.answerer import MeetingAnswerer
from vozata.storage.search_index import SearchIndex
from vozata.storage.session_store import SessionStore
from vozata.transcription.shared import SharedTranscriber


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(output_dir=tmp_path / "recordings", **overrides)  # type: ignore[arg-type]


def test_build_answerer_follows_the_app_language_and_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = FakeLanguageModel()
    monkeypatch.setitem(bootstrap.LANGUAGE_MODELS, "fake", lambda settings: llm)
    settings = _settings(
        tmp_path, llm_provider="fake", app_language=AppLanguage.PT_BR, llm_max_chars=4000
    )
    store = SessionStore(settings.output_dir)
    index = SearchIndex(tmp_path / "index.db")

    answerer = bootstrap.build_answerer(settings, store, index)

    assert isinstance(answerer, MeetingAnswerer)
    assert answerer._llm is llm
    assert answerer._t("qa.not_found") == "Não encontrei isso nas reuniões."
    assert answerer._retriever._max_chars == 4000
    assert answerer._retriever._search is index


def test_the_api_container_answers_questions_and_frees_an_idle_whisper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes: list[FakeTranscriber] = []
    monkeypatch.setitem(
        bootstrap.TRANSCRIBERS,
        "fake",
        lambda settings: fakes.append(FakeTranscriber()) or fakes[-1],
    )
    monkeypatch.setitem(bootstrap.LANGUAGE_MODELS, "fake", lambda settings: FakeLanguageModel())
    shared_seen: list[SharedTranscriber] = []
    monkeypatch.setattr(
        bootstrap,
        "build_session",
        lambda settings, observer, **kwargs: (
            shared_seen.append(kwargs["shared"]) or SimpleNamespace(status=SessionStatus.RECORDING)
        ),
    )
    settings = _settings(
        tmp_path, stt_provider="fake", llm_provider="fake", whisper_keep_loaded=True
    )

    container = bootstrap.build_api_container(settings)
    assert isinstance(container.ask, AskJob)
    container.manager._factory(FakeSessionObserver(), StartOptions())
    [shared] = shared_seen
    shared.lease(keep=True).close()  # an idle, kept Whisper

    answerer = container.ask._build()  # idle: Whisper is freed before the LLM loads
    assert isinstance(answerer, MeetingAnswerer)
    assert not shared.loaded

    shared.lease(keep=True)
    container.manager._session = SimpleNamespace(status=SessionStatus.RECORDING)
    container.ask._build()  # a recording uses Whisper right now: keep it
    assert shared.loaded
