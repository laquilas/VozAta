from __future__ import annotations

import threading

from vozata.domain import ModelKind
from vozata.models.tracker import DownloadState, DownloadTracker


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _tracker(interval: float = 0.5) -> tuple[DownloadTracker, list[DownloadState], FakeClock]:
    events: list[DownloadState] = []
    clock = FakeClock()
    return DownloadTracker(events.append, clock=clock, interval=interval), events, clock


def test_state_payload_matches_the_event_contract() -> None:
    running = DownloadState(ModelKind.SPEECH, "large-v3-turbo", 10, None, "running")
    failed = DownloadState(ModelKind.SPEAKERS, "repo", 5, 9, "failed", reason="offline")

    assert running.to_payload() == {
        "kind": "speech",
        "model": "large-v3-turbo",
        "downloaded_bytes": 10,
        "total_bytes": None,
        "state": "running",
    }
    assert failed.to_payload()["reason"] == "offline"
    assert failed.to_payload()["kind"] == "speakers"


def test_tracker_throttles_running_events_per_download() -> None:
    tracker, events, clock = _tracker()

    handle = tracker.start(ModelKind.SPEECH, "m", 100)
    for when in (0.1, 0.3):
        clock.now = when
        handle.advance(10)
    clock.now = 0.5
    handle.advance(10)  # interval reached: one event with everything so far
    clock.now = 0.7
    handle.advance(10)
    clock.now = 0.8
    handle.done()

    assert [(e.state, e.downloaded_bytes) for e in events] == [
        ("running", 0),
        ("running", 30),
        ("done", 40),
    ]
    assert all(e.total_bytes == 100 for e in events)


def test_tracker_keeps_two_downloads_apart_and_lists_running() -> None:
    tracker, events, clock = _tracker()
    speech = tracker.start(ModelKind.SPEECH, "whisper", 100)
    clock.now = 0.2
    speakers = tracker.start(ModelKind.SPEAKERS, "pyannote", None)

    clock.now = 0.6
    speech.advance(40)  # speech's interval is over, not speakers' (started at 0.2)
    speakers.advance(7)

    assert sorted((s.model, s.downloaded_bytes, s.state) for s in tracker.running()) == [
        ("pyannote", 7, "running"),
        ("whisper", 40, "running"),
    ]
    assert [(e.model, e.downloaded_bytes) for e in events] == [
        ("whisper", 0),
        ("pyannote", 0),
        ("whisper", 40),
    ]

    speech.done()

    assert [s.model for s in tracker.running()] == ["pyannote"]
    assert events[-1] == DownloadState(ModelKind.SPEECH, "whisper", 40, 100, "done")


def test_failed_download_carries_its_reason_and_leaves_the_running_list() -> None:
    tracker, events, _ = _tracker()
    handle = tracker.start(ModelKind.TRANSLATION, "opus", 50)
    handle.advance(5)

    handle.failed("network down")

    assert events[-1] == DownloadState(
        ModelKind.TRANSLATION, "opus", 5, 50, "failed", reason="network down"
    )
    assert tracker.running() == []


def test_a_finished_handle_ignores_later_calls() -> None:
    tracker, events, clock = _tracker(interval=0.0)
    handle = tracker.start(ModelKind.SPEECH, "m", None)
    handle.done()
    published = len(events)

    clock.now = 5.0
    handle.advance(10)
    handle.done()
    handle.failed("late")

    assert len(events) == published
    assert tracker.running() == []


def test_zero_interval_publishes_every_advance() -> None:
    tracker, events, _ = _tracker(interval=0.0)
    handle = tracker.start(ModelKind.SPEECH, "m", 3)

    for _ in range(3):
        handle.advance(1)

    assert [e.downloaded_bytes for e in events] == [0, 1, 2, 3]


def test_concurrent_advances_are_all_counted() -> None:
    tracker, _, _ = _tracker()
    handle = tracker.start(ModelKind.SPEECH, "m", None)

    def work() -> None:
        for _ in range(1000):
            handle.advance(1)

    threads = [threading.Thread(target=work, daemon=True) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert tracker.running()[0].downloaded_bytes == 4000
