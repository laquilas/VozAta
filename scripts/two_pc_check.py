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
import wave
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

SAMPLE_RATE = 16000


@dataclass(frozen=True)
class StepResult:
    name: str
    ok: bool | None  # None: the step was skipped
    detail: str


def scratch_env(folder: Path, *, port: int, discovery_port: int) -> str:
    """The client engine's `.env`: everything inside `folder`, every task on the worker."""
    values = {
        "API_PORT": str(port),
        "OUTPUT_DIR": str(folder / "recordings"),
        "DATABASE_PATH": str(folder / "vozata.db"),
        "STT_PROVIDER": "vozata_worker",
        "DIARIZATION_PROVIDER": "vozata_worker",
        "TRANSLATION_PROVIDER": "vozata_worker",
        "DIARIZATION_ENABLED": "true",
        "GENERATE_MINUTES": "false",
        "EXTRACT_ACTION_ITEMS": "false",
        "WORKER_DISCOVERY_PORT": str(discovery_port),
    }
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
