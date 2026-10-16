from __future__ import annotations

import runpy
import sys

import vozata
from vozata.__main__ import main


def test_package_exposes_version() -> None:
    assert vozata.__version__ == "0.1.0"


def test_main_prints_version(capsys) -> None:
    main()

    assert capsys.readouterr().out.strip() == "0.1.0"


def test_running_as_module_prints_version(capsys, monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "vozata.__main__", raising=False)

    runpy.run_module("vozata", run_name="__main__", alter_sys=True)

    assert capsys.readouterr().out.strip() == "0.1.0"
