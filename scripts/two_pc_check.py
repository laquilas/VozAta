"""Two-PC end-to-end check of the VozAta worker (phase 52, `docs/two-pc-check.md`).

Run on the client PC (the one that records), from the repository root:

    .venv/Scripts/python scripts/two_pc_check.py --code 123456
    .venv/Scripts/python scripts/two_pc_check.py --worker-url http://192.168.0.20:8766 --token ...

It starts a scratch client engine (its own folder, port, database and `.env`; never the user's),
then checks discovery, pairing, the worker's tasks, a real translation, a diarization job
cancelled on the worker and, with `--record`, a recording that pre-empts the queue's diarize step.
A developer tool: the console output is English, like `packaging/build.ps1`.
"""

from __future__ import annotations

import io
import ipaddress
import random
import struct
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

SAMPLE_RATE = 16000


@dataclass(frozen=True)
class StepResult:
    name: str
    ok: bool | None  # None: the step was skipped
    detail: str


def scratch_env(
    folder: Path,
    *,
    port: int,
    discovery_port: int,
    worker_url: str | None = None,
    worker_token: str | None = None,
    local_speech: bool = False,
) -> str:
    """The client engine's `.env`: everything inside `folder`, every task on the worker (pairing
    adds `WORKER_URL` / `WORKER_TOKEN`, or they are given)."""
    values = {
        "API_PORT": str(port),
        "OUTPUT_DIR": str(folder / "recordings"),
        "DATABASE_PATH": str(folder / "vozata.db"),
        "STT_PROVIDER": "faster_whisper" if local_speech else "vozata_worker",
        "DIARIZATION_PROVIDER": "vozata_worker",
        "TRANSLATION_PROVIDER": "vozata_worker",
        "DIARIZATION_ENABLED": "true",
        "GENERATE_MINUTES": "false",
        "EXTRACT_ACTION_ITEMS": "false",
        "WORKER_DISCOVERY_PORT": str(discovery_port),
    }
    if worker_url:
        values["WORKER_URL"] = worker_url
    if worker_token:
        values["WORKER_TOKEN"] = worker_token
    return "".join(f"{key}={value}\n" for key, value in values.items())


def saved_worker(env_file: Path) -> tuple[str | None, str | None]:
    """`WORKER_URL` and `WORKER_TOKEN` as pairing saved them into the scratch `.env`."""
    if not env_file.exists():
        return None, None
    values = dotenv_values(env_file)
    return values.get("WORKER_URL") or None, values.get("WORKER_TOKEN") or None


def synthetic_wav(seconds: float = 20.0) -> bytes:
    """Mono 16-bit 16 kHz noise bursts: enough for a diarization job to run (not to find voices)."""
    noise = random.Random(52)
    frames = bytearray()
    for index in range(int(seconds * SAMPLE_RATE)):
        loud = (index // (SAMPLE_RATE // 2)) % 2 == 0  # half a second on, half off
        frames += struct.pack("<h", int(noise.uniform(-1, 1) * (8000 if loud else 200)))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(bytes(frames))
    return buffer.getvalue()


def render_table(results: list[StepResult]) -> str:
    width = max([len("Step"), *(len(result.name) for result in results)])
    lines = [f"{'Step':<{width}}  Result  Detail"]
    for result in results:
        verdict = "SKIP" if result.ok is None else "PASS" if result.ok else "FAIL"
        lines.append(f"{result.name:<{width}}  {verdict:<6}  {result.detail}")
    return "\n".join(lines)


def passed(results: list[StepResult]) -> bool:
    return all(result.ok is not False for result in results)


def discover(engine: httpx.Client, name: str | None) -> tuple[StepResult, str | None]:
    """`GET /worker/discover` on the client engine: the worker (by name, else the first)."""
    try:
        response = engine.get("/worker/discover", timeout=10)
    except httpx.HTTPError as error:
        return StepResult("discover", False, f"engine: {error}"), None
    if response.status_code != 200:
        return StepResult("discover", False, f"engine answered {response.status_code}"), None
    workers = response.json().get("workers", [])
    if not workers:
        return StepResult("discover", False, "no worker answered the broadcast"), None
    found = [worker for worker in workers if name is None or worker.get("name") == name]
    if not found:
        names = ", ".join(str(worker.get("name")) for worker in workers)
        return StepResult("discover", False, f"{name} not among: {names}"), None
    worker = found[0]
    if _loopback(worker["url"]):
        return StepResult("discover", False, f"{worker['url']} is a loopback address"), None
    detail = (
        f"{worker.get('name')} at {worker['url']} ({worker.get('version')}, {worker.get('gpu')})"
    )
    return StepResult("discover", True, detail), worker["url"]


def pairing_code(worker_on_this_pc: httpx.Client) -> str:
    """The code VozAta Worker shows, read from `/local/status` (only for a worker on this PC)."""
    response = worker_on_this_pc.get("/local/status", timeout=5)
    response.raise_for_status()
    return str(response.json()["pairing_code"])


def pair(engine: httpx.Client, url: str, code: str) -> StepResult:
    try:
        response = engine.post("/worker/pair", json={"url": url, "code": code}, timeout=15)
    except httpx.HTTPError as error:
        return StepResult("pair", False, f"engine: {error}")
    if response.status_code != 200:
        return StepResult("pair", False, f"{response.status_code} {_error_code(response)}")
    body = response.json()
    return StepResult("pair", True, f"paired with {body.get('name')} ({body.get('id')})")


def worker_health(worker: httpx.Client, *, speakers: bool) -> StepResult:
    """The worker's `/health` with the token: speech and translation, speakers unless told not."""
    try:
        response = worker.get("/health", timeout=10)
    except httpx.HTTPError as error:
        return StepResult("health", False, f"worker: {error}")
    if response.status_code != 200:
        return StepResult("health", False, f"worker answered {response.status_code}")
    capabilities = response.json().get("capabilities", [])
    wanted = {"speech", "translation"} | ({"speakers"} if speakers else set())
    missing = sorted(wanted - set(capabilities))
    detail = f"offers {', '.join(capabilities)}" + (
        f"; missing {', '.join(missing)}" if missing else ""
    )
    return StepResult("health", not missing, detail)


SENTENCE = "Vamos adiar o lançamento da versão beta para a próxima terça-feira."


def translate(worker: httpx.Client) -> StepResult:
    """A real opus-mt translation on the worker, Portuguese to English."""
    body = {"text": SENTENCE, "source": "pt", "target": "en"}
    try:
        response = worker.post("/translate", json=body, timeout=900)  # may download the model
    except httpx.HTTPError as error:
        return StepResult("translate", False, f"worker: {error}")
    if response.status_code != 200:
        return StepResult("translate", False, f"{response.status_code} {_error_code(response)}")
    text = str(response.json().get("text") or "").strip()
    if not text:
        return StepResult("translate", False, "empty translation")
    if text == SENTENCE:
        return StepResult("translate", False, "untranslated: the text came back as it was")
    return StepResult("translate", True, f"pt -> en: {text}")


def diarize_cancel(
    worker: httpx.Client,
    wav: bytes,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    timeout: float = 5.0,
) -> StepResult:
    """Start a diarization job on the worker, cancel it once running: `cancelled` in `timeout`."""
    name = "diarize + cancel"
    try:
        response = worker.post("/diarize", content=wav, timeout=60)
        if response.status_code != 202:
            return StepResult(name, False, f"{response.status_code} {_error_code(response)}")
        job = f"/diarize/{response.json()['job_id']}"
        if _job_state(worker, job) != "running":
            return StepResult(name, False, "the job ended before it could be cancelled")
        worker.delete(job, timeout=10)
        cancelled_at = clock()
        while clock() - cancelled_at <= timeout:
            state = _job_state(worker, job)
            if state != "running":
                ok = state == "cancelled"
                return StepResult(name, ok, f"{state} {clock() - cancelled_at:.1f} s after DELETE")
            sleep(0.2)
    except httpx.HTTPError as error:
        return StepResult(name, False, f"worker: {error}")
    return StepResult(name, False, f"still running {timeout:.0f} s after DELETE")


def _job_state(worker: httpx.Client, job: str) -> str:
    return str(worker.get(job, timeout=10).json().get("state"))


def preempt(
    engine: httpx.Client,
    *,
    expect_pause: bool,
    during: Callable[[], None],
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    timeout: float = 900.0,
) -> StepResult:
    """Record a meeting (`during` plays speech on this PC's output), stop it, and when the queue's
    diarize step runs on the worker start a second recording with live transcription. The step
    pauses (the worker job is cancelled, then redone) only when that recording loads Whisper on
    this PC's GPU (phase 40's gate): `expect_pause` = CUDA here and speech on this PC. With speech
    on the worker the recording uses no GPU here and the step keeps running."""
    name = "pre-emption"
    try:
        first = _record(engine, "two-PC check")
        during()
        engine.post("/sessions/current/stop", timeout=30)
        deadline = clock() + timeout
        if not _wait(engine, first, _diarizing, clock, sleep, deadline):
            meeting = _session(engine, first)
            if meeting.get("status") == "done":
                return StepResult(name, False, "no diarize step: no system speech was recorded?")
            return StepResult(name, False, "timed out waiting for the diarize step")
        second = _record(engine, "two-PC check (pre-empts)", live=True)
        paused = _wait(engine, first, _paused_or_done, clock, sleep, clock() + 20.0)
        engine.post("/sessions/current/stop", timeout=30)
        finished = _wait(engine, second, _done, clock, sleep, deadline)
        if finished:
            engine.delete(f"/sessions/{second}", timeout=30)
        if not _wait(engine, first, _done, clock, sleep, deadline):
            return StepResult(name, False, "timed out waiting for the meeting to finish")
        speakers = _session(engine, first).get("speaker_count")
    except _Refused as error:
        return StepResult(name, False, str(error))
    except httpx.HTTPError as error:
        return StepResult(name, False, f"engine: {error}")
    done = f"then finished: {speakers} speaker(s)"
    if expect_pause and not paused:
        return StepResult(name, False, "diarize step not paused by a recording on this GPU")
    if not expect_pause and paused:
        return StepResult(name, False, "diarize step paused by a recording that uses no GPU here")
    if expect_pause:
        return StepResult(name, True, f"diarize step paused by the recording on this GPU, {done}")
    return StepResult(name, True, f"diarize step kept running on the worker, {done}")


class _Refused(Exception):
    pass


def _record(engine: httpx.Client, title: str, *, live: bool = False) -> str:
    response = engine.post(
        "/sessions", json={"live_transcription": live, "title": title}, timeout=60
    )
    if response.status_code != 201:
        raise _Refused(f"recording refused: {response.status_code} {_error_code(response)}")
    return str(response.json()["id"])


def _session(engine: httpx.Client, session_id: str) -> dict[str, Any]:
    return dict(engine.get(f"/sessions/{session_id}", timeout=30).json())


def _processing(meeting: dict[str, Any]) -> dict[str, Any]:
    return dict(meeting.get("processing") or {})


def _diarizing(meeting: dict[str, Any]) -> bool | None:
    """True while diarize runs, None (stop waiting) once the meeting is done without it."""
    processing = _processing(meeting)
    if processing.get("step") == "diarize" and processing.get("state") == "running":
        return True
    return None if meeting.get("status") == "done" else False


def _paused_or_done(meeting: dict[str, Any]) -> bool | None:
    if _processing(meeting).get("state") == "paused":
        return True
    return None if meeting.get("status") == "done" else False


def _done(meeting: dict[str, Any]) -> bool:
    return meeting.get("status") == "done"


def _wait(
    engine: httpx.Client,
    session_id: str,
    condition: Callable[[dict[str, Any]], bool | None],
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    deadline: float,
) -> bool:
    """Poll the meeting until `condition` is True (True), None or the deadline (False)."""
    while clock() <= deadline:
        verdict = condition(_session(engine, session_id))
        if verdict is not False:
            return bool(verdict)
        sleep(0.5)
    return False


@dataclass(frozen=True)
class Options:
    worker_name: str | None = None
    code: str | None = None  # the pairing code; "auto" reads it from a worker on this PC
    worker_url: str | None = None  # with `token`: skip discovery and pairing
    token: str | None = None
    speakers: bool = True
    record: bool = False
    local_speech: bool = False  # the client transcribes on its own GPU (STT_PROVIDER local)


def run_checks(
    options: Options,
    engine: httpx.Client,
    env_file: Path,
    *,
    worker: Callable[[str, str | None], httpx.Client],
    during: Callable[[], None],
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> list[StepResult]:
    """Every step in order; a failed discover / pair / health stops the steps that need it."""
    results: list[StepResult] = []
    url, token = options.worker_url, options.token
    if url is None:
        found, url = discover(engine, options.worker_name)
        results.append(found)
        if url is None:
            return results
        if options.code is None:
            return [
                *results,
                StepResult("pair", False, "no --code: type the one VozAta Worker shows"),
            ]
        code = options.code
        if code == "auto":
            code = pairing_code(worker(_on_this_pc(url), None))
        paired = pair(engine, url, code)
        results.append(paired)
        if not paired.ok:
            return results
        url, token = saved_worker(env_file)
        if url is None:
            return [
                *results,
                StepResult("health", False, f"pairing saved no WORKER_URL in {env_file}"),
            ]
    else:
        skipped = "--worker-url given"
        results += [StepResult("discover", None, skipped), StepResult("pair", None, skipped)]
    client = worker(url, token)
    health = worker_health(client, speakers=options.speakers)
    results.append(health)
    if not health.ok:
        return results
    results.append(translate(client))
    if options.speakers:
        results.append(diarize_cancel(client, synthetic_wav(), clock=clock, sleep=sleep))
    else:
        results.append(StepResult("diarize + cancel", None, "--no-speakers"))
    if not options.record:
        return [*results, StepResult("pre-emption", None, "not asked (--record)")]
    gpu = engine.get("/health", timeout=10).json().get("gpu") or {}
    expect_pause = bool(gpu.get("available")) and options.local_speech
    return [
        *results,
        preempt(engine, expect_pause=expect_pause, during=during, clock=clock, sleep=sleep),
    ]


def _on_this_pc(url: str) -> str:
    """The worker's URL through loopback: `/local/status` answers this PC only."""
    return f"http://127.0.0.1:{urlsplit(url).port or 8766}"


def _loopback(url: str) -> bool:
    host = urlsplit(url).hostname or ""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def _error_code(response: httpx.Response) -> str:
    try:
        return str(response.json()["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return response.text[:200]


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - starts processes
    import argparse
    import tempfile

    import two_pc_runtime as runtime

    parser = argparse.ArgumentParser(description="Two-PC end-to-end check of the VozAta worker.")
    parser.add_argument("--worker-name", help="the worker to pick when several answer")
    parser.add_argument("--code", help='pairing code shown in VozAta Worker; "auto" on one PC')
    parser.add_argument("--worker-url", help="skip discovery and pairing (needs --token)")
    parser.add_argument("--token", help="the worker token, with --worker-url")
    parser.add_argument("--no-speakers", action="store_true", help="the worker has no speakers")
    parser.add_argument("--record", action="store_true", help="also check the pre-emption")
    parser.add_argument("--play", type=Path, help="WAV played on the output while recording")
    parser.add_argument("--record-seconds", type=float, default=30.0)
    parser.add_argument(
        "--local-speech",
        action="store_true",
        help="this PC transcribes on its own GPU: a recording then pre-empts the diarize step",
    )
    parser.add_argument("--discovery-port", type=int, default=8767)
    parser.add_argument("--folder", type=Path, help="scratch folder (default: a new temp one)")
    args = parser.parse_args(argv)
    if args.token and not args.worker_url:
        parser.error("--token needs --worker-url")
    folder = args.folder or Path(tempfile.mkdtemp(prefix="vozata-two-pc-"))
    folder.mkdir(parents=True, exist_ok=True)
    port = runtime.free_port()
    env_file = folder / ".env"
    env_file.write_text(
        scratch_env(
            folder,
            port=port,
            discovery_port=args.discovery_port,
            worker_url=args.worker_url,
            worker_token=args.token,
            local_speech=args.local_speech,
        ),
        encoding="utf-8",
    )
    options = Options(
        worker_name=args.worker_name,
        code=args.code,
        worker_url=args.worker_url,
        token=args.token,
        speakers=not args.no_speakers,
        record=args.record,
        local_speech=args.local_speech,
    )

    def worker(url: str, token: str | None) -> httpx.Client:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return httpx.Client(base_url=url, headers=headers)

    def during() -> None:
        if args.play:
            runtime.play(args.play.resolve())
        else:
            time.sleep(args.record_seconds)

    print(f"Scratch client engine in {folder} on port {port}")
    with runtime.ScratchEngine(folder, port) as engine_process:
        engine = httpx.Client(base_url=engine_process.url)
        results = run_checks(options, engine, env_file, worker=worker, during=during)
    print(render_table(results))
    return 0 if passed(results) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
