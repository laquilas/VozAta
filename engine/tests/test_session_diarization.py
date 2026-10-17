"""Stop step 5: speaker identification between Whisper and the minutes (architecture §6)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from tests.fakes import FakeDiarizer
from tests.test_session import SETTINGS, _Log, _Rig, _voice, _words
from vozata.config import ConfigError
from vozata.domain import Channel, SessionStatus, SpeakerTurn
from vozata.ports import DiarizationError


class _LoggingDiarizer(FakeDiarizer):
    def __init__(self, log: _Log, turns: list[SpeakerTurn], error: Exception | None = None):
        super().__init__(turns, error)
        self._log = log

    def diarize(self, wav: Path, min_speakers: int | None, max_speakers: int | None):
        self._log.entries.append("diarizer.diarize")
        return super().diarize(wav, min_speakers, max_speakers)

    def close(self) -> None:
        super().close()
        self._log.entries.append("diarizer.close")


def _rig(tmp_path: Path, error: Exception | None = None) -> tuple[_Rig, list[_LoggingDiarizer]]:
    built: list[_LoggingDiarizer] = []
    holder: dict[str, _Rig] = {}

    def build() -> _LoggingDiarizer:
        turns = [SpeakerTurn(0.0, 0.5, 3), SpeakerTurn(0.5, 9.0, 1)]
        built.append(_LoggingDiarizer(holder["rig"].log, turns, error))
        holder["rig"].log.entries.append("diarizer.load")
        return built[-1]

    settings = dataclasses.replace(SETTINGS, min_speakers=2, max_speakers=3)
    rig = _Rig(
        tmp_path,
        results=[_words("Hello", " there.")],
        diarizer_factory=build,
        settings=settings,
    )
    holder["rig"] = rig
    return rig, built


def test_whisper_is_released_before_diarizing_and_the_diarizer_before_the_minutes(
    tmp_path: Path,
) -> None:
    rig, built = _rig(tmp_path)
    rig.session.start()
    rig.system.push(_voice(1.0), 0.0)

    rig.session.stop()

    steps = [entry for entry in rig.log.entries if entry not in ("transcriber.load", "release")]
    assert steps == [
        "mix",
        "transcriber.close",
        "diarizer.load",
        "diarizer.diarize",
        "diarizer.close",
        "llm.generate",
    ]
    [diarizer] = built
    paths = rig.paths
    assert diarizer.calls == [(paths.wav(Channel.SYSTEM), 2, 3)]
    assert [s.speaker_id for s in rig.store.load_transcript(rig.session.id)] == ["system:1"]
    assert paths.speakers_json.is_file()
    assert "labels.user(n=1): Hello there." in rig.llm.prompts[0][1]
    assert rig.observer.of("error") == []
    assert rig.observer.of("speakers_relabeled") == [(rig.session.id,)]
    names = [event[0] for event in rig.observer.events]
    assert names.index("speakers_relabeled") < names.index("minutes_ready")


def test_a_failing_diarizer_keeps_system_labels_reports_and_still_writes_minutes(
    tmp_path: Path,
) -> None:
    rig, built = _rig(tmp_path, error=DiarizationError("no token"))
    rig.session.start()
    rig.system.push(_voice(1.0), 0.0)

    rig.session.stop()

    assert built[0].closed
    assert rig.log.entries.index("diarizer.close") < rig.log.entries.index("llm.generate")
    [(code, message)] = rig.observer.of("error")
    assert code == "diarization_failed"
    assert "no token" in message and "python -m vozata diarize" in message
    assert not rig.paths.diarized_jsonl.exists()
    assert rig.observer.of("speakers_relabeled") == []
    assert "labels.system: Hello there." in rig.llm.prompts[0][1]
    assert rig.session.status is SessionStatus.DONE


def test_a_failing_diarizer_factory_is_reported_too(tmp_path: Path) -> None:
    def build() -> FakeDiarizer:
        raise DiarizationError("extra missing")

    rig = _Rig(tmp_path, results=[_words("Hi.")], diarizer_factory=build)
    rig.session.start()
    rig.system.push(_voice(1.0), 0.0)

    rig.session.stop()

    assert [code for code, _ in rig.observer.of("error")] == ["diarization_failed"]
    assert rig.paths.minutes_md.exists()


def test_without_system_speech_no_diarizer_is_loaded(tmp_path: Path) -> None:
    rig, built = _rig(tmp_path)
    rig.session.start()
    rig.mic.push(_voice(1.0), 0.0)

    rig.session.stop()

    assert built == []
    assert not rig.paths.diarized_jsonl.exists()
    assert rig.observer.of("speakers_relabeled") == []


def test_a_configuration_error_is_reported_with_its_localized_message(tmp_path: Path) -> None:
    def build() -> FakeDiarizer:
        raise ConfigError("HF_TOKEN", "", "missing_hf_token")

    rig = _Rig(tmp_path, results=[_words("Hi.")], diarizer_factory=build)
    rig.session.start()
    rig.system.push(_voice(1.0), 0.0)

    rig.session.stop()

    [(_, message)] = rig.observer.of("error")
    assert "errors.config.missing_hf_token(key=HF_TOKEN" in message
