from __future__ import annotations

import sys
from typing import Any

import pytest

from vozata.frozen import run_module_args

calls: list[tuple[str, dict[str, Any], list[str]]] = []


def _run_module(name: str, **options: Any) -> dict[str, Any]:
    calls.append((name, options, list(sys.argv)))
    return {}


@pytest.fixture(autouse=True)
def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    calls.clear()
    monkeypatch.setattr(sys, "argv", list(sys.argv))  # restored after each test


def test_the_frozen_engine_runs_a_child_module_like_python_does() -> None:
    argv = ["vozata-engine.exe", "-m", "vozata.diarization.child", "--flag"]

    assert run_module_args(argv, frozen=True, run_module=_run_module) is True
    assert calls == [
        (
            "vozata.diarization.child",
            {"run_name": "__main__", "alter_sys": True},
            ["vozata.diarization.child", "--flag"],
        )
    ]


@pytest.mark.parametrize(
    "argv",
    [
        ["vozata-engine.exe", "worker", "--check"],
        ["vozata-engine.exe", "-m"],  # no module: argparse reports it
        ["vozata-engine.exe"],
    ],
)
def test_other_command_lines_go_to_the_cli(argv: list[str]) -> None:
    assert run_module_args(argv, frozen=True, run_module=_run_module) is False
    assert calls == []


def test_python_itself_runs_modules_when_not_frozen() -> None:
    argv = ["python.exe", "-m", "vozata.diarization.child"]

    assert run_module_args(argv, frozen=False, run_module=_run_module) is False
    assert calls == []
