from __future__ import annotations

import logging

import pytest

from tests.fakes import FakeSessionObserver
from vozata.domain import AppLanguage
from vozata.i18n import TomlLocalizer
from vozata.worker_client.notices import LoggedNotices, ObserverNotices


def test_a_fallback_is_an_error_event_with_a_localized_message() -> None:
    observer = FakeSessionObserver()
    localizer = TomlLocalizer(AppLanguage.PT_BR)

    ObserverNotices(observer, localizer).fallback("speech", "192.168.68.101")

    assert observer.of("error") == [
        (
            "worker_fallback",
            "O worker do VozAta em 192.168.68.101 não respondeu: "
            "o reconhecimento de fala roda neste PC.",
        )
    ]


def test_before_runs_ahead_of_the_event() -> None:
    order: list[str] = []
    observer = FakeSessionObserver()
    observer.on_error = lambda code, message: order.append("event")  # type: ignore[method-assign]

    ObserverNotices(
        observer, TomlLocalizer(AppLanguage.EN), before=lambda task: order.append(task)
    ).fallback("speech", "gpu-pc")

    assert order == ["speech", "event"]


@pytest.mark.parametrize("language", list(AppLanguage))
@pytest.mark.parametrize("task", ["speech", "speakers", "translation"])
def test_every_task_has_a_name_in_every_language(language: AppLanguage, task: str) -> None:
    localizer = TomlLocalizer(language)

    assert localizer.t(f"worker.task.{task}") != f"worker.task.{task}"


def test_logged_notices_only_log(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        LoggedNotices().fallback("speech", "gpu-pc")

    assert "gpu-pc" in caplog.text
