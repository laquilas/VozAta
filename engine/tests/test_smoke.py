from __future__ import annotations

import runpy
import sys

import pytest

import vozata


def test_package_exposes_version() -> None:
    assert vozata.__version__ == "0.3.1"


def test_running_as_module_prints_the_version(capsys, monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "vozata.__main__", raising=False)
    monkeypatch.setattr(sys, "argv", ["vozata", "--version"])

    with pytest.raises(SystemExit) as exit_:
        runpy.run_module("vozata", run_name="__main__", alter_sys=True)

    assert exit_.value.code == 0
    assert capsys.readouterr().out.strip() == "0.3.1"
