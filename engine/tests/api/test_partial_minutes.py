"""`/sessions/{id}/partial-minutes` (phase 48) over the real app, a real job and a fake LLM."""

from __future__ import annotations

import dataclasses
import threading

import pytest

from tests.api.conftest import Api
from tests.fakes import FakeLanguageModel, FakeLocalizer, minutes_template
from vozata.api.partial_minutes_job import PartialMinutesJob, PartialRequest
from vozata.domain import Channel, PartialMinutes, TranscriptSegment
from vozata.labels import SpeakerLabeler
from vozata.minutes.generator import MinutesGenerator
from vozata.ports import LanguageModelError, LlmUnreachableError
from vozata.processing.gpu_gate import GpuGate


def _segment(start: float, text: str) -> TranscriptSegment:
    return TranscriptSegment(
        f"mic-{int(start):06d}", Channel.MIC, "mic", start, start + 2, text, ()
    )


class _Rig:
    def __init__(self, api: Api, llm: FakeLanguageModel | None = None) -> None:
        self.api = api
        self.llm = llm or FakeLanguageModel(replies=["# So far"] * 5)
        self.templates: list[str | None] = []
        self.job = PartialMinutesJob(
            self._generator,
            api.store,
            SpeakerLabeler(FakeLocalizer()),
            api.broadcaster,
            api.app.state.container.localizer,
            new_id=lambda: "p1",
        )
        api.app.state.container = dataclasses.replace(
            api.app.state.container, partial_minutes=self.job
        )

    def _generator(self, template: str | None) -> MinutesGenerator:
        self.templates.append(template)
        return MinutesGenerator(self.llm, FakeLocalizer(), 12000, minutes_template())

    def said(self, session_id: str, *segments: TranscriptSegment) -> None:
        sink = self.api.store.open_transcript(session_id, SpeakerLabeler(FakeLocalizer()))
        for segment in segments:
            sink.emit(segment)
        sink.close()

    def finished(self) -> str:
        store = self.api.store
        session_id = store.create()
        store.write_meta(session_id, {"id": session_id, "status": "done"})
        self.said(session_id, _segment(10, "Hello."), _segment(160, "We agreed."))
        return session_id

    def post(self, session_id: str, **body: object):  # type: ignore[no-untyped-def]
        response = self.api.client.post(f"/sessions/{session_id}/partial-minutes", json=body)
        assert self.job.wait(5)
        return response


def test_minutes_so_far_while_recording(api: Api) -> None:
    rig = _Rig(api)
    session_id = api.client.post("/sessions", json={}).json()["id"]
    rig.said(session_id, _segment(5, "Starting."), _segment(70, "Beta on Tuesday."))

    response = rig.post(session_id)

    assert (response.status_code, response.json()) == (202, {"partial_id": "p1"})
    assert api.broadcaster.of("partial_minutes_ready") == [
        (session_id, {"partial_id": "p1", "start": 0.0, "end": 72.0, "origin": "button"})
    ]
    assert (
        "still in progress: these minutes cover what was said up to 00:01:12"
        in rig.llm.prompts[0][1]
    )
    [item] = api.store.read_partial_minutes(session_id)
    assert (item.origin, item.markdown) == ("button", "# So far\n")
    assert (
        api.manager.current is not None and api.manager.current.id == session_id
    )  # still recording


def test_a_recording_without_live_transcription_has_nothing_yet(api: Api) -> None:
    rig = _Rig(api)
    session_id = api.client.post("/sessions", json={}).json()["id"]
    session = api.factory.sessions[-1]
    session.meta["live_transcription"] = False
    api.store.write_meta(session_id, session.meta)

    response = rig.post(session_id)

    assert (response.status_code, response.json()["error"]["code"]) == (
        409,
        "live_transcription_off",
    )


def test_a_range_of_a_finished_meeting(api: Api) -> None:
    rig = _Rig(api)
    session_id = rig.finished()

    response = rig.post(session_id, start=152, end=774, template="daily")

    assert response.status_code == 202
    assert rig.templates == ["daily"]
    assert "only the part of the meeting from 00:02:32 to 00:12:54" in rig.llm.prompts[0][1]
    [(_, data)] = api.broadcaster.of("partial_minutes_ready")
    assert (data["start"], data["end"], data["origin"]) == (152.0, 774.0, "range")


@pytest.mark.parametrize(
    ("start", "end", "status"),
    [(0, 900, 202), (0, 901, 202), (0, 901.5, 422), (901, None, 422), (100, None, 202)],
)
def test_a_range_beyond_the_recorded_length_is_refused(
    api: Api, start: float, end: float | None, status: int
) -> None:
    rig = _Rig(api)
    session_id = rig.finished()
    meta = api.store.read_meta(session_id)
    api.store.write_meta(session_id, {**meta, "duration_seconds": 900.0})

    body = {"start": start} if end is None else {"start": start, "end": end}
    response = rig.post(session_id, **body)

    assert response.status_code == status
    if status == 422:
        error = response.json()["error"]
        assert error["code"] == "range_beyond_end"
        assert "00:15:00" in error["message"]


def test_an_empty_range_is_an_error_event(api: Api) -> None:
    rig = _Rig(api)
    session_id = rig.finished()

    rig.post(session_id, start=20, end=150)

    [(sid, data)] = api.broadcaster.of("error")
    assert (sid, data["code"]) == (session_id, "empty_range")
    assert "Nothing was said" in data["message"]
    assert api.store.read_partial_minutes(session_id) == []


def test_bad_requests(api: Api) -> None:
    rig = _Rig(api)
    session_id = rig.finished()

    assert rig.post(session_id, start=100, end=100).json()["error"]["code"] == "invalid_range"
    assert rig.post(session_id, start=-1).status_code == 422
    assert rig.post(session_id, template="nope").status_code == 422
    assert rig.post("20200101_000000").status_code == 404


def test_one_at_a_time(api: Api) -> None:
    gate = threading.Event()

    class _Slow(FakeLanguageModel):
        def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
            assert gate.wait(5)
            return "# Slow"

    rig = _Rig(api, _Slow())
    session_id = rig.finished()
    first = api.client.post(f"/sessions/{session_id}/partial-minutes", json={})

    second = api.client.post(f"/sessions/{session_id}/partial-minutes", json={})
    gate.set()
    assert rig.job.wait(5)

    assert first.status_code == 202
    assert (second.status_code, second.json()["error"]["code"]) == (
        409,
        "partial_minutes_in_progress",
    )


def test_without_the_job_it_is_unavailable(api: Api) -> None:
    session_id = _Rig(api).finished()
    api.app.state.container = dataclasses.replace(api.app.state.container, partial_minutes=None)

    response = api.client.post(f"/sessions/{session_id}/partial-minutes", json={})

    assert (response.status_code, response.json()["error"]["code"]) == (
        503,
        "partial_minutes_unavailable",
    )


def test_list_read_and_delete(api: Api) -> None:
    rig = _Rig(api)
    session_id = rig.finished()
    items = [
        PartialMinutes("a", "2026-10-22T10:00:00-03:00", 0, 60, "button", "# A\n", "general"),
        PartialMinutes("b", "2026-10-22T10:05:00-03:00", 60, 120, "range", "# B\n"),
    ]
    api.store.write_partial_minutes(session_id, items)
    base = f"/sessions/{session_id}/partial-minutes"

    listed = api.client.get(base).json()
    one = api.client.get(f"{base}/b").json()
    deleted = api.client.delete(f"{base}/a")

    assert listed == {
        "items": [
            {
                "id": "a",
                "created_at": "2026-10-22T10:00:00-03:00",
                "start": 0.0,
                "end": 60.0,
                "origin": "button",
                "template": "general",
            },
            {
                "id": "b",
                "created_at": "2026-10-22T10:05:00-03:00",
                "start": 60.0,
                "end": 120.0,
                "origin": "range",
                "template": None,
            },
        ]
    }
    assert one["markdown"] == "# B\n"
    assert deleted.status_code == 204
    assert [item.id for item in api.store.read_partial_minutes(session_id)] == ["b"]
    assert api.client.get(f"{base}/a").json()["error"]["code"] == "partial_minutes_not_found"
    assert api.client.delete(f"{base}/a").status_code == 404


class _Failing(FakeLanguageModel):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
        raise self.error


def _failure(api: Api, error: Exception) -> dict[str, object]:
    rig = _Rig(api, _Failing(error))
    session_id = rig.finished()
    rig.post(session_id)
    [(_, data)] = api.broadcaster.of("error")
    return data


def test_an_unreachable_model_names_its_host(api: Api) -> None:
    data = _failure(api, LlmUnreachableError("192.168.0.20", "refused"))

    assert data["code"] == "llm_unreachable" and "192.168.0.20" in str(data["message"])


def test_a_failing_model_is_reported(api: Api) -> None:
    assert _failure(api, LanguageModelError("boom"))["code"] == "partial_minutes_failed"


def test_an_unexpected_error_is_reported(api: Api) -> None:
    assert _failure(api, RuntimeError("bug"))["code"] == "partial_minutes_failed"


def test_with_the_llm_on_this_gpu_it_takes_the_ask_priority(api: Api) -> None:
    gate = GpuGate()
    held: list[bool] = []

    class _Watching(FakeLanguageModel):
        def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
            held.append(gate.priority_held)
            return "# x"

    rig = _Rig(api, _Watching())
    job = PartialMinutesJob(
        rig._generator,
        api.store,
        SpeakerLabeler(FakeLocalizer()),
        api.broadcaster,
        FakeLocalizer(),
        gate=gate,
        uses_gpu=lambda: True,
    )
    session_id = rig.finished()

    partial_id = job.start(PartialRequest(session_id, 0, None, "range", False))
    assert job.wait(5)

    assert held == [True] and not gate.priority_held
    assert partial_id is not None and not job.busy
