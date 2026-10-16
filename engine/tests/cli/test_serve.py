from __future__ import annotations

import io
from typing import Any

import pytest

from tests.fakes import FakeLocalizer
from vozata.cli.console import ConsoleObserver
from vozata.cli.serve import run_serve
from vozata.config import Settings
from vozata.labels import SpeakerLabeler


def _serve(settings: Settings) -> tuple[int, str, list[dict[str, Any]]]:
    out = io.StringIO()
    localizer = FakeLocalizer()
    console = ConsoleObserver(localizer, SpeakerLabeler(localizer), out)
    runs: list[dict[str, Any]] = []
    app = object()

    def run(application: object, **options: Any) -> None:
        assert application is app
        runs.append(options)

    code = run_serve(settings, console, localizer, lambda s: app, run)  # type: ignore[arg-type,return-value]
    return code, out.getvalue(), runs


def test_serves_on_the_configured_loopback_address() -> None:
    code, out, runs = _serve(Settings(api_host="127.0.0.1", api_port=9000))

    assert code == 0
    assert runs == [{"host": "127.0.0.1", "port": 9000, "log_level": "warning"}]
    assert out == "cli.serving(url=http://127.0.0.1:9000)\n"


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "[::]", ""])
def test_refuses_every_interface_addresses(host: str) -> None:
    code, out, runs = _serve(Settings(api_host=host))

    assert code == 2
    assert runs == []
    assert out.startswith("cli.serve_public_host(host=")
