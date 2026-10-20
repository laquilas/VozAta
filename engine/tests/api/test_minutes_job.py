from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.api.conftest import RecordingBroadcaster
from tests.fakes import FakeLanguageModel, FakeLocalizer, minutes_template
from vozata.api.minutes_job import MinutesJob
from vozata.domain import Channel, TranscriptSegment
from vozata.labels import SpeakerLabeler
from vozata.minutes.generator import MinutesGenerator
from vozata.ports import LanguageModelError
from vozata.processing.gpu_gate import GpuGate, GpuUser
from vozata.processing.job import ProcessingJob, Step, StepKind
from vozata.processing.queue import ProcessingQueue
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.session_store import SessionStore


class _Failing(FakeLanguageModel):
    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
        raise LanguageModelError("connection refused")


class _Blocking(FakeLanguageModel):
    """Blocks in `generate` until `cancel()` (then fails like a closed HTTP request)."""

    def __init__(self, replies: list[str] | None = None) -> None:
        super().__init__(replies)
        self.started = threading.Event()
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        super().cancel()
        self._cancelled.set()

    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
        self.started.set()
        assert self._cancelled.wait(5)
        raise LanguageModelError("request closed")


class _Rig:
    def __init__(self, tmp_path: Path, llms: list[FakeLanguageModel], uses_gpu: bool) -> None:
        store = SessionStore(tmp_path)
        self.paths = store.create()
        store.write_meta(self.paths.id, {"language": "en"})
        self.repo = FileSessionRepository(store)
        self.broadcaster = RecordingBroadcaster()
        self.gate = GpuGate()
        self.queue = ProcessingQueue(self.gate, lambda state: self.states.append(state))
        self.states: list = []
        self.indexed: list[str] = []
        self.gpu = uses_gpu  # read by the job when the step runs
        self.index_error: Exception | None = None
        self.built: list[str | None] = []
        localizer = FakeLocalizer()
        llms = list(llms)

        def build(template: str | None) -> MinutesGenerator:
            self.built.append(template)
            llm = llms.pop(0) if len(llms) > 1 else llms[0]
            return MinutesGenerator(
                llm, localizer, 12000, minutes_template(template_id=template or "general")
            )

        self.job = MinutesJob(
            self.repo,
            build,
            SpeakerLabeler(localizer),
            self.broadcaster,
            localizer,
            queue=self.queue,
            uses_gpu=lambda: self.gpu,
            index=self._index,
        )
        self.queue.start()

    def _index(self, session_id: str) -> None:
        if self.index_error is not None:
            raise self.index_error
        self.indexed.append(session_id)

    def transcript(self) -> None:
        segment = TranscriptSegment("mic-000001", Channel.MIC, "mic", 1.0, 2.0, "Hi.", ())
        self.paths.transcript_jsonl.write_text(
            json.dumps(segment.to_dict()) + "\n", encoding="utf-8"
        )

    def run(self, template: str | None = None) -> None:
        assert self.job(self.paths.id, template)
        assert self.queue.wait_idle(5)


@pytest.fixture
def rigs(tmp_path: Path) -> Iterator[list[_Rig]]:
    made: list[_Rig] = []
    yield made
    for rig in made:
        rig.queue.stop()


def _rig(
    rigs: list[_Rig],
    tmp_path: Path,
    *llms: FakeLanguageModel,
    transcript: bool = True,
    uses_gpu: bool = False,
) -> _Rig:
    rig = _Rig(tmp_path, list(llms), uses_gpu)
    if transcript:
        rig.transcript()
    rigs.append(rig)
    return rig


def test_writes_the_minutes_in_the_queue_announces_them_and_indexes(
    tmp_path: Path, rigs: list[_Rig]
) -> None:
    llm = FakeLanguageModel(["# Minutes"])
    rig = _rig(rigs, tmp_path, llm)

    rig.run()

    assert llm.closes == 1  # the attempt's client is closed once it is over
    assert rig.paths.minutes_md.read_text(encoding="utf-8") == "# Minutes\n"
    assert rig.broadcaster.of("minutes_ready") == [(rig.paths.id, {"session_id": rig.paths.id})]
    assert rig.indexed == [rig.paths.id]
    steps = [state.step for state in rig.states if state.state == "running"]
    assert StepKind.MINUTES in steps and StepKind.INDEX in steps
    assert rig.states[-1].state == "done"


def test_a_language_model_failure_is_published_as_a_localized_error(
    tmp_path: Path, rigs: list[_Rig]
) -> None:
    rig = _rig(rigs, tmp_path, _Failing())

    rig.run()

    assert rig.broadcaster.of("error") == [
        (
            rig.paths.id,
            {
                "code": "minutes_failed",
                "message": "errors.api.minutes_failed(reason=connection refused)",
            },
        )
    ]
    assert not rig.paths.minutes_md.exists()


def test_an_empty_transcript_is_published_as_an_error(tmp_path: Path, rigs: list[_Rig]) -> None:
    rig = _rig(rigs, tmp_path, FakeLanguageModel(), transcript=False)

    rig.run()

    [(_, data)] = rig.broadcaster.of("error")
    assert data["code"] == "empty_transcript"


def test_the_requested_template_is_used_and_stored(tmp_path: Path, rigs: list[_Rig]) -> None:
    llm = FakeLanguageModel(["# Client"])
    rig = _rig(rigs, tmp_path, llm)

    rig.run("client")

    assert "## Client needs" in llm.prompts[0][1]
    assert json.loads(rig.paths.meta.read_text(encoding="utf-8"))["template"] == "client"


def test_regenerate_minutes_is_queued_behind_running_job(tmp_path: Path, rigs: list[_Rig]) -> None:
    rig = _rig(rigs, tmp_path, FakeLanguageModel(["# Minutes"]))
    running, release = threading.Event(), threading.Event()

    def held(token: object, progress: object) -> None:
        running.set()
        assert release.wait(5)

    hold = Step(StepKind.INDEX, 1.0, False, held)
    assert rig.queue.enqueue(ProcessingJob("20261014_090000", (hold,), on_finished=lambda: None))
    assert running.wait(5)

    assert rig.job(rig.paths.id, None)
    queued = rig.queue.state(rig.paths.id)
    written_early = rig.paths.minutes_md.exists()
    release.set()
    assert rig.queue.wait_idle(5)

    assert queued is not None and (queued.state, queued.position) == ("queued", 1)
    assert not written_early
    assert rig.paths.minutes_md.read_text(encoding="utf-8") == "# Minutes\n"


def test_a_meeting_already_in_the_queue_is_not_queued_twice(
    tmp_path: Path, rigs: list[_Rig]
) -> None:
    rig = _rig(rigs, tmp_path, FakeLanguageModel(["# Minutes"]))
    release = threading.Event()
    hold = Step(StepKind.INDEX, 1.0, False, lambda token, progress: release.wait(5))
    assert rig.queue.enqueue(ProcessingJob(rig.paths.id, (hold,), on_finished=lambda: None))

    accepted = rig.job(rig.paths.id, None)
    release.set()
    assert rig.queue.wait_idle(5)

    assert accepted is False
    assert not rig.paths.minutes_md.exists()


def test_a_live_recording_cancels_the_step_and_a_fresh_generator_redoes_it(
    tmp_path: Path, rigs: list[_Rig]
) -> None:
    blocking = _Blocking()
    rig = _rig(rigs, tmp_path, blocking, FakeLanguageModel(["# Minutes"]), uses_gpu=True)

    assert rig.job(rig.paths.id, None)
    assert blocking.started.wait(5)
    with rig.gate.priority(GpuUser.LIVE):
        assert blocking.cancels == 1
    assert rig.queue.wait_idle(5)

    assert rig.built == [None, None]  # one generator per attempt
    assert blocking.closes == 1  # the cancelled attempt's client is closed too
    assert rig.paths.minutes_md.read_text(encoding="utf-8") == "# Minutes\n"
    assert rig.broadcaster.of("error") == []
    assert len(rig.broadcaster.of("minutes_ready")) == 1
    assert "paused" in [state.state for state in rig.states]


def test_without_the_gpu_the_step_is_not_gated(tmp_path: Path, rigs: list[_Rig]) -> None:
    rig = _rig(rigs, tmp_path, FakeLanguageModel(["# Minutes"]))

    with rig.gate.priority(GpuUser.LIVE):  # a live recording does not block a CPU/remote LLM
        rig.run()

    assert rig.paths.minutes_md.exists()


def test_rename_while_queued_survives_the_job(tmp_path: Path, rigs: list[_Rig]) -> None:
    llm = _Renaming(["# Minutes"])
    rig = _rig(rigs, tmp_path, llm)
    llm.rename = lambda: rig.repo.write_meta(
        rig.paths.id, {**rig.repo.read_meta(rig.paths.id), "title": "Renamed"}
    )

    rig.run("client")  # the template differs from the stored one, so the metadata is rewritten

    meta = json.loads(rig.paths.meta.read_text(encoding="utf-8"))
    assert (meta["title"], meta["template"]) == ("Renamed", "client")


class _Renaming(FakeLanguageModel):
    """Renames the meeting (through `rename`) while the minutes are being generated."""

    rename = staticmethod(lambda: None)

    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
        self.rename()
        return super().generate(system, prompt, json_schema)


def test_an_unexpected_failure_is_published_as_an_internal_error(
    tmp_path: Path, rigs: list[_Rig]
) -> None:
    rig = _rig(rigs, tmp_path, _Broken())

    rig.run()

    assert rig.broadcaster.of("error") == [
        (rig.paths.id, {"code": "minutes_failed", "message": "errors.api.internal_error"})
    ]
    assert rig.indexed == []
    assert rig.states[-1].state == "done"


@pytest.mark.parametrize("transcript", [True, False])
def test_a_failed_model_step_skips_the_index(
    tmp_path: Path, rigs: list[_Rig], transcript: bool
) -> None:
    rig = _rig(rigs, tmp_path, _Failing(), transcript=transcript)

    rig.run()

    assert len(rig.broadcaster.of("error")) == 1
    assert rig.indexed == []


def test_an_index_failure_is_reported_and_the_job_still_ends_done(
    tmp_path: Path, rigs: list[_Rig]
) -> None:
    rig = _rig(rigs, tmp_path, FakeLanguageModel(["# Minutes"]))
    rig.index_error = OSError("disk full")

    rig.run()

    assert len(rig.broadcaster.of("minutes_ready")) == 1
    assert rig.broadcaster.of("error") == [
        (
            rig.paths.id,
            {"code": "index_failed", "message": "errors.session.index_failed(reason=disk full)"},
        )
    ]
    assert rig.states[-1].state == "done"


def test_the_gpu_setting_is_read_when_the_step_runs(tmp_path: Path, rigs: list[_Rig]) -> None:
    rig = _rig(rigs, tmp_path, FakeLanguageModel(["# Minutes"]), uses_gpu=False)
    running, release = threading.Event(), threading.Event()

    def held(token: object, progress: object) -> None:
        running.set()
        assert release.wait(5)

    hold = Step(StepKind.INDEX, 1.0, False, held)
    assert rig.queue.enqueue(ProcessingJob("20261014_090000", (hold,), on_finished=lambda: None))
    assert running.wait(5)
    assert rig.job(rig.paths.id, None)  # queued while the language model is not on the GPU
    rig.gpu = True  # the settings changed before the step runs

    with rig.gate.priority(GpuUser.LIVE):
        release.set()
        paused = _wait_for(lambda: (rig.queue.state(rig.paths.id) or _NONE).state == "paused")
        written_while_live = rig.paths.minutes_md.exists()
    assert rig.queue.wait_idle(5)

    assert paused and not written_while_live
    assert rig.paths.minutes_md.exists()


class _Broken(FakeLanguageModel):
    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
        raise RuntimeError("bug")


class _NoState:
    state = None


_NONE = _NoState()


def _wait_for(condition, timeout: float = 5.0) -> bool:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False
