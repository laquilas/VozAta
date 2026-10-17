from __future__ import annotations

import json
from pathlib import Path

from tests.api.conftest import RecordingBroadcaster
from tests.fakes import FakeLanguageModel, FakeLocalizer, minutes_template
from vozata.api.minutes_job import MinutesJob
from vozata.domain import Channel, TranscriptSegment
from vozata.labels import SpeakerLabeler
from vozata.minutes.generator import MinutesGenerator
from vozata.ports import LanguageModelError
from vozata.storage.session_store import SessionStore


class _Failing(FakeLanguageModel):
    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
        raise LanguageModelError("connection refused")


def _job(tmp_path: Path, llm: FakeLanguageModel, *, transcript: bool = True):  # type: ignore[no-untyped-def]
    store = SessionStore(tmp_path)
    paths = store.create()
    store.write_meta(paths.id, {"language": "en"})
    if transcript:
        segment = TranscriptSegment("mic-000001", Channel.MIC, "mic", 1.0, 2.0, "Hi.", ())
        paths.transcript_jsonl.write_text(json.dumps(segment.to_dict()) + "\n", encoding="utf-8")
    broadcaster = RecordingBroadcaster()
    localizer = FakeLocalizer()
    job = MinutesJob(
        store,
        lambda: MinutesGenerator(llm, localizer, 12000, minutes_template()),
        SpeakerLabeler(localizer),
        broadcaster,
        localizer,
    )
    return job, broadcaster, paths


def test_writes_the_minutes_in_the_background_and_announces_them(tmp_path: Path) -> None:
    job, broadcaster, paths = _job(tmp_path, FakeLanguageModel(["# Minutes"]))

    job(paths.id)
    assert job.wait(5)

    assert paths.minutes_md.read_text(encoding="utf-8") == "# Minutes\n"
    assert broadcaster.of("minutes_ready") == [(paths.id, {"session_id": paths.id})]


def test_a_language_model_failure_is_published_as_a_localized_error(tmp_path: Path) -> None:
    job, broadcaster, paths = _job(tmp_path, _Failing())

    job(paths.id)
    assert job.wait(5)

    assert broadcaster.of("error") == [
        (
            paths.id,
            {
                "code": "minutes_failed",
                "message": "errors.api.minutes_failed(reason=connection refused)",
            },
        )
    ]
    assert not paths.minutes_md.exists()


def test_an_empty_transcript_is_published_as_an_error(tmp_path: Path) -> None:
    job, broadcaster, paths = _job(tmp_path, FakeLanguageModel(), transcript=False)

    job(paths.id)
    assert job.wait(5)

    [(_, data)] = broadcaster.of("error")
    assert data["code"] == "empty_transcript"


def test_wait_without_a_job_returns_at_once(tmp_path: Path) -> None:
    job, _, _ = _job(tmp_path, FakeLanguageModel())

    assert job.wait(0.01)
