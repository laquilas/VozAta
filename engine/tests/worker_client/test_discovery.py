from __future__ import annotations

import json

from vozata.worker.discovery import REQUEST
from vozata.worker_client.discovery import BROADCAST, FoundWorker, discover_workers


def _answer(id_: str, name: str = "GPU-PC", port: int = 8766, **extra: object) -> bytes:
    body = {"vozata": "worker", "v": 1, "id": id_, "name": name, "port": port}
    body.update({"version": "0.9.0", "gpu": "RTX 4070", **extra})
    return json.dumps(body).encode()


class _Socket:
    def __init__(self, source: str, answers: list[tuple[bytes, str]]) -> None:
        self.source = source
        self.answers = list(answers)
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.closed = False

    def sendto(self, data: bytes, address: tuple[str, int]) -> int:
        self.sent.append((data, address))
        return len(data)

    def recvfrom(self, size: int) -> tuple[bytes, tuple[str, int]]:
        if not self.answers:
            raise TimeoutError
        data, host = self.answers.pop(0)
        return data, (host, 8767)

    def close(self) -> None:
        self.closed = True


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 0.1
        return self.now


def test_every_network_is_asked_and_each_worker_is_listed_once() -> None:
    sockets = {
        "0.0.0.0": _Socket("0.0.0.0", [(_answer("b", "Zeta"), "192.168.0.20")]),
        "192.168.0.5": _Socket(
            "192.168.0.5",
            [(_answer("b", "Zeta"), "192.168.0.20"), (b"junk", "192.168.0.7")],
        ),
        "10.0.0.5": _Socket(
            "10.0.0.5",
            [
                (_answer("a", "alpha", port=9000, gpu=None), "10.0.0.8"),
                (b'{"vozata":"worker"}', "10.0.0.9"),
            ],
        ),
    }

    found = discover_workers(
        8767,
        ["192.168.0.5", "10.0.0.5", "192.168.0.5"],
        open_socket=lambda source: sockets[source],
        clock=_Clock(),
    )

    assert found == [
        FoundWorker("a", "alpha", "http://10.0.0.8:9000", "0.9.0", None),
        FoundWorker("b", "Zeta", "http://192.168.0.20:8766", "0.9.0", "RTX 4070"),
    ]
    for sock in sockets.values():
        assert sock.sent == [(json.dumps(REQUEST).encode(), (BROADCAST, 8767))]
        assert sock.closed


def test_a_network_that_cannot_send_is_skipped() -> None:
    def open_socket(source: str) -> _Socket:
        if source != "0.0.0.0":
            raise OSError("network is unreachable")
        return _Socket(source, [(_answer("a"), "192.168.0.20")])

    found = discover_workers(8767, ["192.168.0.5"], open_socket=open_socket, clock=_Clock())

    assert [worker.id for worker in found] == ["a"]


def test_nothing_answering_finds_nothing() -> None:
    assert discover_workers(8767, [], open_socket=lambda s: _Socket(s, []), clock=_Clock()) == []
