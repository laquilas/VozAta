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


# Translate


def test_a_real_translation_comes_back_in_english() -> None:
    sent: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return _json(200, {"text": "Let's postpone the beta release until next Tuesday."})

    result = check.translate(_client(handler, "http://worker"))

    assert result.ok is True and "postpone" in result.detail
    assert sent == [{"text": check.SENTENCE, "source": "pt", "target": "en"}]


@pytest.mark.parametrize(
    ("response", "detail"),
    [
        (_json(503, {"error": {"code": "worker_translation_unavailable"}}), "unavailable"),
        (_json(200, {"text": ""}), "empty"),
        (_json(200, {"text": check.SENTENCE}), "untranslated"),
    ],
)
def test_a_translation_that_did_not_happen_fails(response: httpx.Response, detail: str) -> None:
    result = check.translate(_client(lambda _: response, "http://worker"))

    assert result.ok is False and detail in result.detail


# Diarize + cancel


class _Jobs:
    """A worker's /diarize: running until DELETE, then `after_delete` (cancelled by default)."""

    def __init__(self, after_delete: str = "cancelled", accept: int = 202) -> None:
        self.after_delete = after_delete
        self.accept = accept
        self.state = "running"
        self.calls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(f"{request.method} {request.url.path}")
        if request.method == "POST":
            return _json(self.accept, {"job_id": "j1"} if self.accept == 202 else {})
        if request.method == "DELETE":
            self.state = self.after_delete
            return httpx.Response(204)
        return _json(200, {"state": self.state, "turns": [], "message": None})


def test_a_running_diarization_job_is_cancelled_on_the_worker() -> None:
    jobs, clock = _Jobs(), _Clock()

    result = check.diarize_cancel(
        _client(jobs, "http://worker"), b"RIFF", clock=clock, sleep=clock.sleep
    )

    assert result.ok is True and "cancelled" in result.detail
    assert jobs.calls[0] == "POST /diarize"
    assert "DELETE /diarize/j1" in jobs.calls


def test_a_job_that_keeps_running_after_the_cancel_fails() -> None:
    jobs, clock = _Jobs(after_delete="running"), _Clock()

    result = check.diarize_cancel(
        _client(jobs, "http://worker"), b"RIFF", clock=clock, sleep=clock.sleep
    )

    assert result.ok is False and "still running" in result.detail


def test_a_refused_job_fails_the_step() -> None:
    clock = _Clock()

    result = check.diarize_cancel(
        _client(_Jobs(accept=503), "http://worker"), b"RIFF", clock=clock, sleep=clock.sleep
    )

    assert result.ok is False and "503" in result.detail


# Pre-emption


class _Engine:
    """The client engine during the pre-emption step: two recordings and the first meeting's
    processing, which moves through `script` one GET at a time."""

    def __init__(self, script: list[dict[str, object] | None], speaker_count: int = 2) -> None:
        self.script = script
        self.speaker_count = speaker_count
        self.calls: list[str] = []
        self.sessions = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        call = f"{request.method} {request.url.path}"
        self.calls.append(call)
        if call == "POST /sessions":
            self.sessions += 1
            return _json(201, {"id": f"s{self.sessions}", "status": "recording"})
        if call == "POST /sessions/current/stop":
            return _json(202, {})
        if call == "DELETE /sessions/s2":
            return httpx.Response(204)
        if call == "GET /sessions/s2":
            return _json(200, {"id": "s2", "status": "done", "processing": None})
        processing = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        status = "done" if processing is None else "finalizing"
        body = {"id": "s1", "status": status, "processing": processing}
        return _json(200, {**body, "speaker_count": self.speaker_count})


def _step(state: str, step: str) -> dict[str, object]:
    return {"state": state, "percent": 50, "step": step}


def _preempt(engine: _Engine, cuda: bool) -> check.StepResult:
    clock, played = _Clock(), []
    result = check.preempt(
        _client(engine),
        cuda=cuda,
        during=lambda: played.append(True),
        clock=clock,
        sleep=clock.sleep,
    )
    assert played == [True]
    return result


def test_with_cuda_a_recording_pauses_the_diarize_step_on_the_worker() -> None:
    engine = _Engine(
        [
            _step("running", "transcribe"),
            _step("running", "diarize"),
            _step("paused", "diarize"),
            _step("running", "diarize"),
            None,
        ]
    )

    result = _preempt(engine, cuda=True)

    assert result.ok is True
    assert "paused" in result.detail and "2 speaker" in result.detail
    assert engine.calls.count("POST /sessions") == 2
    assert engine.calls.count("POST /sessions/current/stop") == 2
    assert engine.calls[-1] != "DELETE /sessions/s1"
    assert "DELETE /sessions/s2" in engine.calls


def test_with_cuda_a_step_that_is_not_paused_fails() -> None:
    engine = _Engine([_step("running", "diarize")] * 3 + [None])

    result = _preempt(engine, cuda=True)

    assert result.ok is False and "not paused" in result.detail


def test_without_cuda_the_worker_step_keeps_running() -> None:
    engine = _Engine([_step("running", "diarize"), _step("running", "diarize"), None])

    result = _preempt(engine, cuda=False)

    assert result.ok is True and "kept running" in result.detail


def test_without_cuda_a_paused_step_fails() -> None:
    engine = _Engine([_step("running", "diarize"), _step("paused", "diarize"), None])

    result = _preempt(engine, cuda=False)

    assert result.ok is False and "paused" in result.detail


def test_a_meeting_without_a_diarize_step_fails() -> None:
    engine = _Engine([_step("running", "transcribe"), None])

    result = _preempt(engine, cuda=True)

    assert result.ok is False and "no diarize step" in result.detail
    assert engine.calls.count("POST /sessions") == 1


def test_a_meeting_that_never_finishes_fails() -> None:
    engine = _Engine([_step("running", "transcribe")])

    result = _preempt(engine, cuda=True)

    assert result.ok is False and "timed out" in result.detail


def test_a_recording_that_cannot_start_fails() -> None:
    clock = _Clock()
    engine = _client(lambda _: _json(503, {"error": {"code": "device_timeout"}}))

    result = check.preempt(engine, cuda=True, during=lambda: None, clock=clock, sleep=clock.sleep)

    assert result.ok is False and "device_timeout" in result.detail


# The whole run


class _Worker:
    """A worker that offers every task, translates and cancels jobs; records the clients made."""

    def __init__(self, capabilities: list[str] | None = None) -> None:
        self.capabilities = capabilities or ["speech", "speakers", "translation"]
        self.jobs = _Jobs()
        self.made: list[tuple[str, str | None]] = []

    def __call__(self, url: str, token: str | None) -> httpx.Client:
        self.made.append((url, token))
        return _client(self._handle, url)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/local/status":
            return _json(200, {"pairing_code": "654321"})
        if path == "/health":
            return _json(200, {"capabilities": self.capabilities})
        if path == "/translate":
            return _json(200, {"text": "Let's postpone the beta release."})
        return self.jobs(request)


def _paired_engine(env_file: Path, workers: list[dict[str, str]]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/worker/discover":
            return _json(200, {"workers": workers})
        if request.url.path == "/worker/pair":
            body = json.loads(request.content)
            env_file.write_text(f"WORKER_URL={body['url']}\nWORKER_TOKEN=t0k\n", "utf-8")
            return _json(200, {"id": "b", "name": "GPU-PC"})
        return _json(404, {})

    return _client(handler)


GPU_PC = {"id": "b", "name": "GPU-PC", "url": "http://192.168.0.20:8766", "version": "0.1.0"}


def _run(options: check.Options, engine: httpx.Client, env: Path, worker: _Worker) -> list[str]:
    clock = _Clock()
    results = check.run_checks(
        options, engine, env, worker=worker, during=lambda: None, clock=clock, sleep=clock.sleep
    )
    return [f"{result.name}:{result.ok}" for result in results]


def test_a_run_discovers_pairs_with_the_code_on_this_pc_and_checks_the_worker(
    tmp_path: Path,
) -> None:
    env, worker = tmp_path / ".env", _Worker()

    steps = _run(check.Options(code="auto"), _paired_engine(env, [GPU_PC]), env, worker)

    assert steps == [
        "discover:True",
        "pair:True",
        "health:True",
        "translate:True",
        "diarize + cancel:True",
        "pre-emption:None",
    ]
    # the code from /local/status through loopback, then the saved URL and token
    assert worker.made == [("http://127.0.0.1:8766", None), ("http://192.168.0.20:8766", "t0k")]


def test_without_a_code_the_run_stops_after_discovery(tmp_path: Path) -> None:
    env = tmp_path / ".env"

    steps = _run(check.Options(), _paired_engine(env, [GPU_PC]), env, _Worker())

    assert steps == ["discover:True", "pair:False"]


def test_nothing_discovered_stops_the_run(tmp_path: Path) -> None:
    env = tmp_path / ".env"

    steps = _run(check.Options(code="1"), _paired_engine(env, []), env, _Worker())

    assert steps == ["discover:False"]


def test_a_given_worker_url_skips_discovery_and_pairing(tmp_path: Path) -> None:
    worker = _Worker(["speech", "translation"])
    options = check.Options(worker_url="http://10.0.0.5:8766", token="t", speakers=False)

    steps = _run(options, _client(lambda _: _json(404, {})), tmp_path / ".env", worker)

    assert steps == [
        "discover:None",
        "pair:None",
        "health:True",
        "translate:True",
        "diarize + cancel:None",
        "pre-emption:None",
    ]
    assert worker.made == [("http://10.0.0.5:8766", "t")]


def test_a_worker_missing_a_task_stops_after_health(tmp_path: Path) -> None:
    options = check.Options(worker_url="http://10.0.0.5:8766", token="t")

    steps = _run(options, _client(lambda _: _json(404, {})), tmp_path / ".env", _Worker(["speech"]))

    assert steps[-1] == "health:False"


def test_a_pairing_that_saved_nothing_fails(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/worker/discover":
            return _json(200, {"workers": [GPU_PC]})
        return _json(200, {"id": "b", "name": "GPU-PC"})  # but no .env written

    steps = _run(check.Options(code="1"), _client(handler), tmp_path / ".env", _Worker())

    assert steps == ["discover:True", "pair:True", "health:False"]


def test_record_runs_the_pre_emption_with_the_engine_gpu(tmp_path: Path) -> None:
    engine = _Engine([_step("running", "diarize"), _step("paused", "diarize"), None])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return _json(200, {"gpu": {"available": True}})
        return engine(request)

    options = check.Options(worker_url="http://10.0.0.5:8766", token="t", record=True)

    steps = _run(options, _client(handler), tmp_path / ".env", _Worker())

    assert steps[-1] == "pre-emption:True"


def test_a_scratch_env_with_a_given_worker(tmp_path: Path) -> None:
    text = check.scratch_env(
        tmp_path, port=1, discovery_port=2, worker_url="http://10.0.0.5:8766", worker_token="t"
    )

    assert "WORKER_URL=http://10.0.0.5:8766\n" in text and "WORKER_TOKEN=t\n" in text
