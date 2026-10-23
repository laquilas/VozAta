from __future__ import annotations

import io
import json
import sys
import wave
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import two_pc_check as check  # noqa: E402

Handler = Callable[[httpx.Request], httpx.Response]


def _client(handler: Handler, base: str = "http://engine") -> httpx.Client:
    return httpx.Client(base_url=base, transport=httpx.MockTransport(handler))


def _json(status: int, body: object) -> httpx.Response:
    return httpx.Response(status, json=body)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


# Scratch environment, WAV, table


def test_the_scratch_env_never_points_at_the_user_files(tmp_path: Path) -> None:
    text = check.scratch_env(tmp_path, port=8799, discovery_port=8767)
    values = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)

    assert values["API_PORT"] == "8799"
    assert Path(values["OUTPUT_DIR"]).parent == tmp_path
    assert Path(values["DATABASE_PATH"]).parent == tmp_path
    assert values["STT_PROVIDER"] == values["DIARIZATION_PROVIDER"] == "vozata_worker"
    assert values["TRANSLATION_PROVIDER"] == "vozata_worker"
    assert (values["DIARIZATION_ENABLED"], values["GENERATE_MINUTES"]) == ("true", "false")
    assert values["WORKER_DISCOVERY_PORT"] == "8767"
    assert "WORKER_TOKEN" not in values  # pairing writes it


def test_the_synthetic_wav_is_mono_16_bit_16_khz() -> None:
    data = check.synthetic_wav(seconds=2.0)

    with wave.open(io.BytesIO(data)) as wav:
        params = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes())
    assert params == (1, 2, 16000, 32000)
    assert data == check.synthetic_wav(seconds=2.0)  # deterministic


def test_the_table_shows_every_step_and_the_verdict() -> None:
    results = [
        check.StepResult("discover", True, "GPU-PC at http://192.168.0.20:8766"),
        check.StepResult("pair", False, "409 worker_pairing_refused"),
        check.StepResult("pre-emption", None, "not asked (--record)"),
    ]

    table = check.render_table(results)

    assert table.splitlines()[0].startswith("Step")
    assert "discover" in table and "PASS" in table and "FAIL" in table and "SKIP" in table
    assert check.passed(results) is False
    assert check.passed([results[0], results[2]]) is True


# Discover and pair


def test_discover_picks_the_named_worker_on_the_network() -> None:
    workers = [
        {"id": "a", "name": "Other", "url": "http://192.168.0.9:8766", "version": "0.1.0"},
        {"id": "b", "name": "GPU-PC", "url": "http://192.168.0.20:8766", "version": "0.1.0"},
    ]
    engine = _client(lambda _: _json(200, {"workers": workers}))

    result, url = check.discover(engine, "GPU-PC")

    assert (result.ok, url) == (True, "http://192.168.0.20:8766")
    assert "GPU-PC" in result.detail


@pytest.mark.parametrize(
    ("workers", "name", "detail"),
    [
        ([], None, "no worker answered"),
        ([{"id": "a", "name": "X", "url": "http://192.168.0.9:8766"}], "GPU-PC", "GPU-PC"),
        ([{"id": "a", "name": "X", "url": "http://127.0.0.1:8766"}], None, "loopback"),
    ],
)
def test_discover_fails_without_a_usable_worker(
    workers: list[dict[str, str]], name: str | None, detail: str
) -> None:
    engine = _client(lambda _: _json(200, {"workers": workers}))

    result, url = check.discover(engine, name)

    assert (result.ok, url) == (False, None)
    assert detail in result.detail


def test_discover_reports_an_engine_error() -> None:
    result, _ = check.discover(_client(lambda _: _json(500, {})), None)

    assert result.ok is False and "500" in result.detail


def test_pair_sends_the_code_and_passes_on_success() -> None:
    sent: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return _json(200, {"id": "b", "name": "GPU-PC", "url": "http://192.168.0.20:8766"})

    result = check.pair(_client(handler), "http://192.168.0.20:8766", "123456")

    assert result.ok is True
    assert sent == [{"url": "http://192.168.0.20:8766", "code": "123456"}]


def test_pair_shows_the_refusal_code() -> None:
    engine = _client(lambda _: _json(409, {"error": {"code": "worker_pairing_refused"}}))

    result = check.pair(engine, "http://192.168.0.20:8766", "000000")

    assert result.ok is False and "worker_pairing_refused" in result.detail


def test_the_pairing_code_of_a_worker_on_this_pc() -> None:
    worker = _client(lambda _: _json(200, {"pairing_code": "654321"}), "http://127.0.0.1:8766")

    assert check.pairing_code(worker) == "654321"


def test_the_token_saved_by_pairing_is_read_from_the_scratch_env(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("API_PORT=8799\nWORKER_URL='http://x:8766'\nWORKER_TOKEN='t0k'\n", "utf-8")

    assert check.saved_worker(env) == ("http://x:8766", "t0k")
    assert check.saved_worker(tmp_path / "missing.env") == (None, None)


# Worker health


@pytest.mark.parametrize(
    ("capabilities", "speakers", "ok"),
    [
        (["speech", "speakers", "translation"], True, True),
        (["speech", "translation"], False, True),
        (["speech", "translation"], True, False),
        (["speech"], False, False),
    ],
)
def test_the_worker_offers_the_tasks_this_check_needs(
    capabilities: list[str], speakers: bool, ok: bool
) -> None:
    worker = _client(lambda _: _json(200, {"capabilities": capabilities, "version": "0.1.0"}))

    result = check.worker_health(worker, speakers=speakers)

    assert result.ok is ok
    assert ", ".join(capabilities) in result.detail


def test_a_refused_token_fails_the_health_step() -> None:
    result = check.worker_health(_client(lambda _: _json(401, {})), speakers=True)

    assert result.ok is False and "401" in result.detail


def test_a_worker_that_does_not_answer_fails_the_step() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    result = check.worker_health(_client(handler), speakers=True)

    assert result.ok is False and "refused" in result.detail
