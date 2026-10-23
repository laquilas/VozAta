from __future__ import annotations

import json
import queue
import threading

from fastapi.testclient import TestClient

from vozata.api.system_info import GpuInfo
from vozata.worker.app import create_worker_app
from vozata.worker.discovery import REQUEST, DiscoveryResponder, is_request
from vozata.worker.speech import LoadedModel, SpeechService

REPLY = {"id": "4f1c", "name": "GPU-PC", "port": 8766, "version": "0.9.0", "gpu": "RTX 4070"}


class _Socket:
    """Datagrams queued by the test; `recvfrom` times out when there is none."""

    def __init__(self) -> None:
        self.incoming: queue.Queue[tuple[bytes, tuple[str, int]]] = queue.Queue()
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.answered = threading.Event()
        self.closed = False

    def recvfrom(self, size: int) -> tuple[bytes, tuple[str, int]]:
        try:
            return self.incoming.get(timeout=0.01)
        except queue.Empty:
            raise TimeoutError from None

    def sendto(self, data: bytes, address: tuple[str, int]) -> int:
        self.sent.append((data, address))
        self.answered.set()
        return len(data)

    def close(self) -> None:
        self.closed = True


def test_only_the_discovery_request_is_recognized() -> None:
    assert is_request(json.dumps(REQUEST).encode())
    assert not is_request(b'{"vozata":"discover","v":2}')
    assert not is_request(b"\xff\xfe not json")


def test_the_responder_answers_the_sender_and_ignores_the_rest() -> None:
    sock = _Socket()
    opened: list[int] = []
    responder = DiscoveryResponder(8767, lambda: REPLY, lambda port: opened.append(port) or sock)

    responder.start()
    sock.incoming.put((b"hello", ("192.168.0.9", 5000)))
    sock.incoming.put((json.dumps(REQUEST).encode(), ("192.168.0.10", 50123)))
    assert sock.answered.wait(5)
    responder.stop()

    assert opened == [8767]
    [(data, address)] = sock.sent
    assert address == ("192.168.0.10", 50123)
    assert json.loads(data) == {"vozata": "worker", "v": 1, **REPLY}
    assert sock.closed


def test_a_busy_port_leaves_discovery_off_and_the_worker_running(caplog) -> None:  # type: ignore[no-untyped-def]
    def busy(port: int) -> _Socket:
        raise OSError("address in use")

    responder = DiscoveryResponder(8767, lambda: REPLY, busy)

    responder.start()
    responder.stop()

    assert "Worker discovery is off" in caplog.text


def test_the_worker_app_runs_its_background_parts_while_it_serves() -> None:
    events: list[str] = []

    class _Part:
        def start(self) -> None:
            events.append("start")

        def stop(self) -> None:
            events.append("stop")

    app = create_worker_app(
        None,
        gpu_info=lambda: GpuInfo(False),
        speech=SpeechService(lambda: LoadedModel(None, "")),  # type: ignore[arg-type]
        background=[_Part()],
    )

    with TestClient(app):
        assert events == ["start"]
    assert events == ["start", "stop"]
