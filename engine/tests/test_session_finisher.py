"""The stop steps after capture, run from stored data (phase 40); the order is in test_session."""

from __future__ import annotations

import dataclasses
import json
import threading
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

import pytest

from tests.fakes import (
    FakeClock,
    FakeDiarizer,
    FakeLanguageModel,
    FakeLocalizer,
    FakeSessionObserver,
    minutes_template,
)
from tests.session_folders import SEGMENTS, make_session_folder
from tests.test_session import ENDED, SETTINGS, _CheckingMixer, _Log
from vozata.config import ConfigError
from vozata.domain import ConversationLanguage, SearchHit, SpeakerTurn, TranscriptSegment
from vozata.labels import SpeakerLabeler
from vozata.minutes.action_items import ActionItemExtractor
from vozata.minutes.generator import MinutesGenerator
from vozata.ports import DiarizationError, LanguageModelError
from vozata.processing.cancel import CancelToken, StepCancelled
from vozata.session import SessionComponents
from vozata.session_finisher import SessionFinisher
from vozata.storage.action_items import read_action_items
from vozata.storage.files.audio import FileAudioStore
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.search_index import SearchIndex
from vozata.storage.session_store import SessionStore
from vozata.transcription.language_lock import LanguageLock

ITEMS = json.dumps(
    {
        "items": [
            {
                "description": "Send the budget",
                "owner": "Me",
                "due": None,
                "source_segment_ids": ["mic-000001"],
            }
        ]
    }
)


class _BlockingDiarizer(FakeDiarizer):
    """`diarize` waits until `cancel()`, then fails like the subprocess diarizer."""

    def __init__(self) -> None:
        super().__init__([SpeakerTurn(0.0, 9.0, 1)])
        self.started = threading.Event()
        self._released = threading.Event()

    def diarize(self, wav: Path, min_speakers: int | None, max_speakers: int | None):
        self.started.set()
        assert self._released.wait(5)
        raise DiarizationError("cancelled")

    def cancel(self) -> None:
        super().cancel()
        self._released.set()


class _BlockingModel(FakeLanguageModel):
    """`generate` waits until `cancel()`, then fails like a call cut short."""

    def __init__(self) -> None:
        super().__init__(["# Minutes"])
        self.started = threading.Event()
        self._released = threading.Event()

    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
        self.started.set()
        assert self._released.wait(5)
        raise LanguageModelError("cancelled")

    def cancel(self) -> None:
        super().cancel()
        self._released.set()


class _BrokenIndex:
    def index_session(self, session_id: str, segments: Sequence[TranscriptSegment]) -> None:
        raise OSError("database is locked")

    def search(self, query: str, limit: int = 50) -> list[SearchHit]:
        return []


class _Rig:
    def __init__(
        self,
        tmp_path: Path,
        *,
        llm: FakeLanguageModel | None = None,
        with_minutes: bool = True,
        diarizer_factory: Callable[[], FakeDiarizer] | None = None,
        action_items_llm: FakeLanguageModel | None = None,
        search_index: SearchIndex | _BrokenIndex | None = None,
        segments: list[TranscriptSegment] = SEGMENTS,
        title: Callable[[], str | None] = lambda: None,
    ) -> None:
        folders = SessionStore(tmp_path / "recordings", now=lambda: ENDED)
        self.store = FileSessionRepository(folders)
        self.audio = FileAudioStore(folders, SETTINGS.sample_rate)
        self.session_id = make_session_folder(self.store, segments=segments)
        self.log = _Log()
        self.llm = llm or FakeLanguageModel(["# Minutes"])
        self.observer = FakeSessionObserver()
        self.mixer = _CheckingMixer(self.log)
        localizer = FakeLocalizer()
        components = SessionComponents(
            sources={},
            device_names={},
            clock=FakeClock(),
            transcriber_factory=lambda: pytest.fail("a finisher never transcribes"),
            mixer=self.mixer,
            minutes=MinutesGenerator(self.llm, localizer, 12000, minutes_template())
            if with_minutes
            else None,
            localizer=localizer,
            labeler=SpeakerLabeler(localizer),
            diarizer_factory=diarizer_factory,
            search_index=search_index,
            action_items=ActionItemExtractor(action_items_llm, localizer, 12000)
            if action_items_llm is not None
            else None,
        )
        self.finisher = SessionFinisher(
            dataclasses.replace(SETTINGS, min_speakers=2, max_speakers=3),
            self.store,
            self.audio,
            components,
            self.observer,
            self.session_id,
            LanguageLock(ConversationLanguage.EN, lambda language: None),
            title,
        )

    @property
    def minutes_file(self) -> Path:
        return self.store.paths(self.session_id).minutes_md


def _run_cancelled(step: Callable[[CancelToken], None], blocked: threading.Event) -> BaseException:
    """Run `step` on a thread, cancel it once it blocks, and return what it raised."""
    token = CancelToken()
    raised: list[BaseException] = []

    def target() -> None:
        try:
            step(token)
        except BaseException as error:
            raised.append(error)

    thread = threading.Thread(target=target)
    thread.start()
    assert blocked.wait(5)
    token.cancel()
    thread.join(5)
    assert not thread.is_alive()
    return raised[0]


def test_identify_speakers_cancelled_raises_and_writes_nothing(tmp_path: Path) -> None:
    diarizer = _BlockingDiarizer()
    rig = _Rig(tmp_path, diarizer_factory=lambda: diarizer)

    error = _run_cancelled(rig.finisher.identify_speakers, diarizer.started)

    assert isinstance(error, StepCancelled)
    assert diarizer.cancels == 1
    assert diarizer.closed
    paths = rig.store.paths(rig.session_id)
    assert not paths.diarized_jsonl.exists() and not paths.speakers_json.exists()
    assert rig.observer.of("error") == []
    assert rig.observer.of("speakers_relabeled") == []


def test_write_minutes_cancelled_sends_no_minutes_ready(tmp_path: Path) -> None:
    llm = _BlockingModel()
    rig = _Rig(tmp_path, llm=llm)

    error = _run_cancelled(rig.finisher.write_minutes, llm.started)

    assert isinstance(error, StepCancelled)
    assert llm.cancels == 1
    assert not rig.minutes_file.exists()
    assert rig.observer.of("error") == []
    assert rig.observer.of("minutes_ready") == []


def test_extract_action_items_cancelled_raises_and_writes_nothing(tmp_path: Path) -> None:
    llm = _BlockingModel()
    rig = _Rig(tmp_path, with_minutes=False, action_items_llm=llm)

    error = _run_cancelled(rig.finisher.extract_action_items, llm.started)

    assert isinstance(error, StepCancelled)
    assert llm.cancels == 1
    assert read_action_items(rig.store.paths(rig.session_id)) == []
    assert rig.observer.of("error") == []
    assert rig.observer.of("action_items_ready") == []


def test_steps_do_nothing_when_the_token_is_already_cancelled(tmp_path: Path) -> None:
    built: list[FakeDiarizer] = []

    def build() -> FakeDiarizer:
        built.append(FakeDiarizer())
        return built[-1]

    llm = FakeLanguageModel(["# Minutes"])
    rig = _Rig(tmp_path, llm=llm, diarizer_factory=build, action_items_llm=FakeLanguageModel())
    token = CancelToken()
    token.cancel()

    for step in (
        rig.finisher.identify_speakers,
        rig.finisher.write_minutes,
        rig.finisher.extract_action_items,
    ):
        with pytest.raises(StepCancelled):
            step(token)

    assert built == [] and llm.prompts == []
    assert rig.observer.events == []


def test_a_finished_step_unregisters_its_cancel_callback(tmp_path: Path) -> None:
    diarizer = FakeDiarizer([SpeakerTurn(0.0, 9.0, 1)])
    llm = FakeLanguageModel(["# Minutes"])
    rig = _Rig(tmp_path, llm=llm, diarizer_factory=lambda: diarizer)
    token = CancelToken()

    rig.finisher.identify_speakers(token)
    rig.finisher.write_minutes(token)
    token.cancel()

    assert diarizer.cancels == 0 and llm.cancels == 0
    assert rig.observer.of("speakers_relabeled") == [(rig.session_id,)]
    assert rig.observer.of("minutes_ready") == [(rig.session_id,)]
    assert rig.minutes_file.read_text(encoding="utf-8") == "# Minutes\n"


def test_the_title_is_read_when_the_minutes_are_written(tmp_path: Path) -> None:
    current: list[str | None] = ["Draft"]
    llm = FakeLanguageModel(["# Minutes"])
    rig = _Rig(tmp_path, llm=llm, title=lambda: current[0])
    current[0] = "Budget review"  # renamed while the meeting waited

    rig.finisher.write_minutes(CancelToken())

    assert "Budget review" in llm.prompts[0][1]
    assert "Draft" not in llm.prompts[0][1]


def test_a_failing_minutes_call_is_reported_with_a_retry_command(tmp_path: Path) -> None:
    class Down(FakeLanguageModel):
        def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
            raise LanguageModelError("connection refused")

    rig = _Rig(tmp_path, llm=Down())

    rig.finisher.write_minutes(CancelToken())

    [(code, message)] = rig.observer.of("error")
    assert code == "minutes_failed"
    assert "connection refused" in message and "python -m vozata minutes" in message
    assert rig.observer.of("minutes_ready") == []


def test_minutes_are_skipped_when_disabled_or_nothing_was_said(tmp_path: Path) -> None:
    off = _Rig(tmp_path / "off", with_minutes=False)
    silent = _Rig(tmp_path / "silent", segments=[])

    off.finisher.write_minutes(CancelToken())
    silent.finisher.write_minutes(CancelToken())

    assert silent.llm.prompts == []
    assert not off.minutes_file.exists() and not silent.minutes_file.exists()
    assert off.observer.events == [] and silent.observer.events == []


def test_a_failing_mixer_is_reported(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    rig.mixer.mix = lambda *args: (_ for _ in ()).throw(OSError("disk full"))  # type: ignore[method-assign]

    rig.finisher.mix()

    [(code, message)] = rig.observer.of("error")
    assert code == "mix_failed" and "disk full" in message


def test_a_failing_diarizer_factory_is_reported_with_the_retry_command(tmp_path: Path) -> None:
    def build() -> FakeDiarizer:
        raise DiarizationError("extra missing")

    rig = _Rig(tmp_path, diarizer_factory=build)

    rig.finisher.identify_speakers(CancelToken())

    [(code, message)] = rig.observer.of("error")
    assert code == "diarization_failed"
    assert "extra missing" in message and "python -m vozata diarize" in message
    assert rig.observer.of("speakers_relabeled") == []


def test_a_configuration_error_is_reported_with_its_localized_message(tmp_path: Path) -> None:
    def build() -> FakeDiarizer:
        raise ConfigError("HF_TOKEN", "", "missing_hf_token")

    rig = _Rig(tmp_path, diarizer_factory=build)

    rig.finisher.identify_speakers(CancelToken())

    [(_, message)] = rig.observer.of("error")
    assert "errors.config.missing_hf_token(key=HF_TOKEN" in message


def test_without_system_speech_no_diarizer_is_loaded(tmp_path: Path) -> None:
    built: list[FakeDiarizer] = []
    rig = _Rig(tmp_path, diarizer_factory=lambda: built.append(FakeDiarizer()) or built[-1])
    rig.store.paths(rig.session_id).transcript_jsonl.write_text("", encoding="utf-8")

    rig.finisher.identify_speakers(CancelToken())

    assert built == []
    assert rig.observer.of("speakers_relabeled") == []


def test_action_items_are_written_and_reported(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, action_items_llm=FakeLanguageModel([ITEMS]))

    rig.finisher.extract_action_items(CancelToken())

    [item] = read_action_items(rig.store.paths(rig.session_id))
    assert (item.id, item.description) == ("a1", "Send the budget")
    assert rig.observer.of("action_items_ready") == [(rig.session_id, 1)]


def test_a_failed_extraction_is_reported(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, action_items_llm=FakeLanguageModel(["nope", "still nope"]))

    rig.finisher.extract_action_items(CancelToken())

    [(code, message)] = rig.observer.of("error")
    assert code == "action_items_failed" and "valid action items" in message
    assert rig.observer.of("action_items_ready") == []


def test_a_silent_session_has_no_action_items_and_no_error(tmp_path: Path) -> None:
    llm = FakeLanguageModel([ITEMS])
    rig = _Rig(tmp_path, segments=[], action_items_llm=llm)

    rig.finisher.extract_action_items(CancelToken())

    assert llm.prompts == []
    assert rig.observer.events == []


def test_index_adds_the_transcript_to_the_search_index(tmp_path: Path) -> None:
    index = SearchIndex(tmp_path / "index.db")
    rig = _Rig(tmp_path, search_index=index)

    rig.finisher.index()

    [hit] = index.search("hello")
    assert (hit.session_id, hit.segment_id) == (rig.session_id, "mic-000001")


def test_a_silent_session_is_indexed_as_empty(tmp_path: Path) -> None:
    index = SearchIndex(tmp_path / "index.db")
    rig = _Rig(tmp_path, segments=[], search_index=index)

    rig.finisher.index()

    assert index.exists()
    assert rig.observer.of("error") == []


def test_an_indexing_failure_is_reported(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, search_index=_BrokenIndex())

    rig.finisher.index()

    [(code, message)] = rig.observer.of("error")
    assert code == "index_failed" and "database is locked" in message


def test_ended_stamps_the_metadata_and_keeps_a_rename_made_meanwhile(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    meta = rig.store.read_meta(rig.session_id)
    rig.store.write_meta(rig.session_id, {**meta, "title": "Renamed"})

    rig.finisher.ended(datetime.fromisoformat("2026-10-15T20:30:00-03:00"))

    stored = rig.store.read_meta(rig.session_id)
    assert (stored["status"], stored["ended_at"], stored["title"]) == (
        "done",
        "2026-10-15T20:30:00-03:00",
        "Renamed",
    )


def test_mix_runs_the_mixer(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)

    rig.finisher.mix()

    assert rig.log.entries == ["mix"] and rig.observer.of("error") == []
