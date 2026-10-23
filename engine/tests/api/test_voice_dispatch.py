"""The voice command dispatcher (phase 50) with the real jobs and a fake LLM."""

from __future__ import annotations

from pathlib import Path

from tests.api.conftest import RecordingBroadcaster
from tests.fakes import FakeLanguageModel, FakeLocalizer, minutes_template
from vozata.api.ask_job import AskJob
from vozata.api.partial_minutes_job import PartialMinutesJob
from vozata.api.voice_dispatch import VoiceCommandDispatcher
from vozata.domain import Channel, TranscriptSegment, VoiceCommand
from vozata.labels import SpeakerLabeler
from vozata.minutes.generator import MinutesGenerator
from vozata.qa.meeting_so_far import MeetingSoFarAnswerer
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.session_store import SessionStore

MINUTES = VoiceCommand("gere a ata", "minutes")
DECIDED = VoiceCommand("o que foi decidido", "ask", "O que foi decidido?")


class _Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.store = FileSessionRepository(SessionStore(tmp_path))
        self.session_id = self.store.create()
        self.store.write_meta(self.session_id, {"id": self.session_id, "status": "recording"})
        sink = self.store.open_transcript(self.session_id, SpeakerLabeler(FakeLocalizer()))
        sink.emit(
            TranscriptSegment("mic-000001", Channel.MIC, "mic", 5, 7, "A beta sai na terça.", ())
        )
        sink.close()
        self.broadcaster = RecordingBroadcaster()
        self.llm = FakeLanguageModel(replies=["# Ata", "Beta na terça."])
        labeler = SpeakerLabeler(FakeLocalizer())
        self.minutes = PartialMinutesJob(
            lambda template: MinutesGenerator(self.llm, FakeLocalizer(), 12000, minutes_template()),
            self.store,
            labeler,
            self.broadcaster,
            FakeLocalizer(),
        )
        self.questions = AskJob(
            lambda: MeetingSoFarAnswerer(self.llm, self.store, labeler, FakeLocalizer(), 12000),
            self.broadcaster,
            FakeLocalizer(),
            origin="voice",
        )
        self.dispatch = VoiceCommandDispatcher(
            self.broadcaster, FakeLocalizer(), self.minutes, self.questions, new_id=lambda: "1"
        )


def test_minutes_by_voice_are_partial_minutes_so_far(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)

    rig.dispatch(rig.session_id, MINUTES)
    assert rig.minutes.wait(5)

    assert rig.broadcaster.of("voice_command") == [
        (
            rig.session_id,
            {"phrase": "gere a ata", "action": "minutes", "question": None, "answer_id": None},
        )
    ]
    [(_, ready)] = rig.broadcaster.of("partial_minutes_ready")
    assert ready["origin"] == "voice"
    [item] = rig.store.read_partial_minutes(rig.session_id)
    assert item.origin == "voice"


def test_a_question_by_voice_streams_its_answer_with_the_origin(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)

    rig.llm.replies = ["Beta na terça."]
    rig.dispatch(rig.session_id, DECIDED)
    assert rig.questions.wait(5)

    [(_, command)] = rig.broadcaster.of("voice_command")
    assert command["answer_id"] == "voice-1"
    chunks = [data["text"] for _, data in rig.broadcaster.of("answer_chunk")]
    assert chunks == ["Beta", "na", "terça."]
    [(sid, done)] = rig.broadcaster.of("answer_done")
    assert (sid, done["answer_id"], done["origin"], done["error"]) == (
        rig.session_id,
        "voice-1",
        "voice",
        None,
    )
    _, user, _ = rig.llm.prompts[0]
    assert "qa.so_far_instructions" in user and "O que foi decidido?" in user


def test_a_busy_job_answers_busy(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)

    class _Busy:
        def start(self, answer_id: str, question: str, session_id: str | None) -> bool:
            return False

    VoiceCommandDispatcher(rig.broadcaster, FakeLocalizer(), None, _Busy())(rig.session_id, DECIDED)

    [(_, error)] = rig.broadcaster.of("error")
    assert error == {"code": "voice_command_busy", "message": "errors.api.voice_command_busy"}


def test_a_command_with_nothing_to_run_is_only_announced(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)

    VoiceCommandDispatcher(rig.broadcaster, FakeLocalizer(), None, None)(rig.session_id, MINUTES)

    assert len(rig.broadcaster.of("voice_command")) == 1
    assert rig.broadcaster.of("error") == []
