"""`/sessions/{id}/sources` (phase 66): a meeting's kept sources, a new choice, trimming."""

from __future__ import annotations

import dataclasses
import io
import threading
import wave
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from tests.api.conftest import Api, hold_in_queue
from tests.storage.test_source_archive import Clock, _recording
from vozata.api.session_sources import SessionSources
from vozata.domain import Channel
from vozata.processing.job import ProcessingJob, Step, StepKind
from vozata.storage.files.audio import FileAudioStore
from vozata.storage.source_archive import SourceArchive

RATE = 1000
ZONE = timezone(timedelta(hours=-3))


class _Rig:
    def __init__(self, tmp_path: Path, keep_days: int = 7) -> None:
        self.queued: list[str] = []
        self.api = Api(tmp_path, jobs=self._jobs)
        self.audio = FileAudioStore(self.api.store.store, RATE)
        self.archive = SourceArchive(self.api.settings.output_dir, Clock())
        self.sources = SessionSources(
            self.archive, self.api.store, self.audio, self.api.manager, RATE, keep_days
        )
        container = self.api.app.state.container
        self.api.app.state.container = dataclasses.replace(
            container, audio=self.audio, sources=self.sources
        )
        self.session_id = self.api.store.create(datetime(2026, 11, 12, 14, 7, 24, tzinfo=ZONE))
        self.api.store.write_meta(
            self.session_id,
            {
                "id": self.session_id,
                "status": "done",
                "started_at": "2026-11-12T14:07:24-03:00",
                "capture_ended_at": "2026-11-12T14:10:00-03:00",
            },
        )
        folder, manifest, self.data = _recording(tmp_path / "rec")
        self.archive.keep(self.session_id, folder, manifest)

    def _jobs(self, api: Api):  # type: ignore[no-untyped-def]
        def make(session_id: str, repair: bool, closed: threading.Event | None) -> ProcessingJob:
            self.queued.append(session_id)

            def finished() -> None:
                meta = api.store.read_meta(session_id)
                api.store.write_meta(session_id, {**meta, "status": "done"})

            return ProcessingJob(
                session_id, (Step(StepKind.INDEX, 1.0, False, lambda t, p: None),), finished
            )

        return make

    def url(self, suffix: str = "") -> str:
        return f"/sessions/{self.session_id}/sources{suffix}"


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[_Rig]:
    rig = _Rig(tmp_path)
    with rig.api.client:
        yield rig
    rig.api.manager.wait_until_finished(5)


def test_the_sources_are_listed_with_the_day_they_go(rig: _Rig) -> None:
    body = rig.api.client.get(rig.url()).json()

    assert [item["id"] for item in body["items"]] == ["in-jbl", "in-room", "out-headset"]
    room = body["items"][1]
    assert (room["kind"], room["selected"], room["duration_seconds"]) == ("mic", False, 0.8)
    assert body["kept_until"] == "2026-11-19T15:00:00-03:00"


def test_a_new_choice_rewrites_the_tracks_and_queues_the_meeting(rig: _Rig) -> None:
    sink = rig.api.store.open_transcript(rig.session_id, rig.api.labeler)
    sink.close()

    response = rig.api.client.post(rig.url(), json={"selected": ["in-room", "out-headset"]})

    assert response.status_code == 202
    assert rig.queued == [rig.session_id]
    assert rig.api.manager.wait_until_finished(5)
    mic = rig.audio.frames(rig.session_id, Channel.MIC, 0, 1000)
    assert np.array_equal(mic[:800], rig.data["in-room"])
    assert rig.api.store.read_meta(rig.session_id)["status"] == "done"
    listed = rig.api.client.get(rig.url()).json()["items"]
    assert [item["id"] for item in listed if item["selected"]] == ["in-room", "out-headset"]


def test_a_bad_choice_is_refused(rig: _Rig) -> None:
    empty = rig.api.client.post(rig.url(), json={"selected": []})
    unknown = rig.api.client.post(rig.url(), json={"selected": ["in-gone"]})

    assert (empty.status_code, empty.json()["error"]["code"]) == (422, "no_source_selected")
    assert (unknown.status_code, unknown.json()["error"]["code"]) == (422, "unknown_source")
    assert rig.queued == []


def test_a_meeting_in_the_queue_is_refused(rig: _Rig) -> None:
    release = hold_in_queue(rig.api.manager, rig.session_id)
    try:
        response = rig.api.client.post(rig.url(), json={"selected": ["in-jbl"]})
    finally:
        release.set()

    assert (response.status_code, response.json()["error"]["code"]) == (409, "session_still_active")


def test_keep_selected_deletes_the_others(rig: _Rig) -> None:
    response = rig.api.client.post(rig.url("/keep-selected"))

    assert response.json() == {"removed": ["in-room"]}
    assert [i["id"] for i in rig.api.client.get(rig.url()).json()["items"]] == [
        "in-jbl",
        "out-headset",
    ]


def test_a_source_is_played_as_wav(rig: _Rig) -> None:
    response = rig.api.client.get(rig.url("/in-room/audio"))

    assert response.headers["content-type"] == "audio/wav"
    with wave.open(io.BytesIO(response.content), "rb") as file:
        assert (file.getframerate(), file.getnframes()) == (RATE, 800)
    missing = rig.api.client.get(rig.url("/in-nope/audio"))
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "source_not_found")


def test_a_meeting_without_kept_sources(rig: _Rig) -> None:
    other = rig.api.store.create(datetime(2026, 11, 12, 9, 0, tzinfo=ZONE))
    rig.api.store.write_meta(other, {"id": other, "status": "done"})

    listed = rig.api.client.get(f"/sessions/{other}/sources").json()
    chosen = rig.api.client.post(f"/sessions/{other}/sources", json={"selected": ["in-jbl"]})
    trimmed = rig.api.client.post(f"/sessions/{other}/sources/keep-selected")

    assert listed == {"items": [], "kept_until": None}
    assert (chosen.status_code, chosen.json()["error"]["code"]) == (404, "sources_not_kept")
    assert trimmed.status_code == 404
    assert rig.api.client.get("/sessions/20991231_000000/sources").status_code == 404


def test_deleting_the_meeting_removes_its_sources(rig: _Rig) -> None:
    assert rig.api.client.delete(f"/sessions/{rig.session_id}").status_code == 204

    assert not rig.archive.has(rig.session_id)


def test_prune_at_start_and_kept_forever_with_zero(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, keep_days=0)
    assert rig.sources.describe(rig.session_id)["kept_until"] is None
    assert rig.sources.prune() == []


def test_without_sources_the_routes_are_503(api: Api) -> None:
    response = api.client.get("/sessions/20261112_140724/sources")

    assert (response.status_code, response.json()["error"]["code"]) == (503, "sources_unavailable")
