"""`POST /sessions/import-audio` (phase 60): an audio file becomes a meeting in the queue."""

from __future__ import annotations

import dataclasses
import io
import threading
import wave
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from tests.api.conftest import Api
from vozata.api.routes import audio_import as audio_import_routes
from vozata.api.session_manager import session_observer
from vozata.audio.decode import PyAvDecoder
from vozata.audio.mixer import MonoMixer
from vozata.domain import Channel, SessionStatus
from vozata.processing.job import ProcessingJob, Step, StepKind
from vozata.storage.audio_import import AudioFileImporter
from vozata.storage.files.audio import FileAudioStore

RATE = 16000


def _wav(seconds: float, rate: int = 44100) -> bytes:
    frames = round(seconds * rate)
    tone = (np.sin(np.arange(frames) * 2 * np.pi * 300 / rate) * 9000).astype(np.int16)
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(tone.tobytes())
    return out.getvalue()


class _Rig:
    """The real app over a file store; a job marks the imported meeting `done`."""

    def __init__(self, tmp_path: Path) -> None:
        self.gate = threading.Event()
        self.gate.set()
        self.queued: list[tuple[str, bool, threading.Event | None]] = []
        self.api = Api(tmp_path, jobs=self._jobs)
        container = self.api.app.state.container
        self.audio = FileAudioStore(self.api.store.store, RATE)
        importer = AudioFileImporter(
            self.api.store,
            self.audio,
            PyAvDecoder(RATE),
            lambda: self.api.settings,
            MonoMixer(),
        )
        self.api.app.state.container = dataclasses.replace(
            container, audio=self.audio, audio_importer=importer
        )

    def _jobs(self, api: Api):  # type: ignore[no-untyped-def]
        def make(session_id: str, repair: bool, closed: threading.Event | None) -> ProcessingJob:
            self.queued.append((session_id, repair, closed))
            observer = session_observer(api.broadcaster, api.labeler, session_id)

            def step(token: object, progress: object) -> None:
                assert self.gate.wait(5)

            def finished() -> None:
                meta = api.store.read_meta(session_id)
                api.store.write_meta(session_id, {**meta, "status": "done"})
                observer.on_status(SessionStatus.DONE, 1.0)

            return ProcessingJob(session_id, (Step(StepKind.INDEX, 1.0, False, step),), finished)

        return make

    def post(self, body: bytes, **params: str):  # type: ignore[no-untyped-def]
        return self.api.client.post(
            "/sessions/import-audio",
            params={"name": "Weekly sync.wav", **params},
            content=body,
            headers={"content-type": "application/octet-stream"},
        )


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[_Rig]:
    rig = _Rig(tmp_path)
    with rig.api.client:
        yield rig
    rig.gate.set()
    rig.api.manager.wait_until_finished(5)


def test_the_file_becomes_a_meeting_that_is_processed(rig: _Rig) -> None:
    response = rig.post(_wav(1.5), recorded_at="2026-10-20T15:30:00")

    assert response.status_code == 202
    session_id = response.json()["id"]
    assert session_id == "20261020_152958"
    assert rig.queued == [(session_id, False, None)]
    assert rig.api.manager.wait_until_finished(5)
    meta = rig.api.store.read_meta(session_id)
    assert (meta["status"], meta["title"]) == ("done", "Weekly sync")
    assert abs(rig.audio.length(session_id, Channel.SYSTEM) - 1.5 * RATE) <= RATE // 100


def test_the_meeting_is_listed_and_queued_while_it_waits(rig: _Rig) -> None:
    rig.gate.clear()

    session_id = rig.post(_wav(1.0)).json()["id"]

    listed = rig.api.client.get("/sessions").json()
    row = next(item for item in listed["items"] if item["id"] == session_id)
    assert row["status"] == "finalizing"
    assert rig.api.broadcaster.of("processing")


def test_a_file_that_is_not_audio_is_422_and_adds_nothing(rig: _Rig) -> None:
    response = rig.post(b"this is not audio")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "audio_invalid"
    assert rig.api.store.list_sessions() == []
    assert rig.queued == []


def test_a_file_without_samples_is_422_audio_empty(rig: _Rig) -> None:
    response = rig.post(_wav(0))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "audio_empty"
    assert rig.api.store.list_sessions() == []


def test_a_file_larger_than_the_cap_is_413(rig: _Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio_import_routes, "MAX_AUDIO_IMPORT_BYTES", 100)

    response = rig.post(_wav(1.0))

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "audio_too_large"


def test_a_name_is_required(rig: _Rig) -> None:
    response = rig.api.client.post("/sessions/import-audio", content=_wav(1.0))

    assert response.status_code == 422


def test_without_an_importer_it_is_503(api: Api) -> None:
    response = api.client.post("/sessions/import-audio", params={"name": "a.wav"}, content=b"x")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "import_unavailable"


def test_a_meeting_already_queued_is_not_queued_twice(rig: _Rig) -> None:
    rig.gate.clear()
    session_id = rig.post(_wav(1.0)).json()["id"]

    rig.api.manager.process_imported(session_id)

    assert len(rig.queued) == 1
