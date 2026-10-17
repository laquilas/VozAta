from __future__ import annotations

import io
import json
from pathlib import Path

from tests.fakes import FakeDiarizer, FakeLocalizer
from vozata.cli.console import ConsoleObserver
from vozata.cli.diarize import run_diarize
from vozata.config import ConfigError, Settings
from vozata.domain import Channel, SpeakerTurn, TranscriptSegment
from vozata.labels import SpeakerLabeler
from vozata.ports import DiarizationError, Diarizer
from vozata.storage.session_store import SessionStore


def _session(tmp_path: Path, channel: Channel = Channel.SYSTEM) -> Path:
    store = SessionStore(tmp_path / "recordings")
    paths = store.create()
    store.write_meta(paths.id, {"language": "en"})
    segment = TranscriptSegment(f"{channel}-000001", channel, channel.value, 1.0, 2.0, "Hi.", ())
    paths.transcript_jsonl.write_text(json.dumps(segment.to_dict()) + "\n", encoding="utf-8")
    return paths.root


def _run(
    folder: Path,
    build,  # type: ignore[no-untyped-def]
    then_minutes=None,  # type: ignore[no-untyped-def]
    settings: Settings | None = None,
) -> tuple[int, str]:
    out = io.StringIO()
    localizer = FakeLocalizer()
    console = ConsoleObserver(localizer, SpeakerLabeler(localizer), out)
    code = run_diarize(folder, settings or Settings(), console, localizer, build, then_minutes)
    return code, out.getvalue()


def test_diarizes_a_stored_session_with_the_speaker_hints(tmp_path: Path) -> None:
    folder = _session(tmp_path)
    diarizer = FakeDiarizer([SpeakerTurn(0.0, 5.0, 0)])
    settings = Settings(min_speakers=2, max_speakers=2)

    code, out = _run(folder, lambda s: diarizer, settings=settings)

    assert code == 0
    assert out == f"cli.diarized(count=1,path={folder / 'transcript.diarized.jsonl'})\n"
    assert diarizer.calls == [(folder / "system.wav", 2, 2)]
    assert diarizer.closed


def test_minutes_follow_when_asked(tmp_path: Path) -> None:
    folder = _session(tmp_path)
    calls: list[str] = []

    code, _ = _run(folder, lambda s: FakeDiarizer([]), lambda: calls.append("minutes") or 7)

    assert (code, calls) == (7, ["minutes"])


def test_unknown_folder_exits_1(tmp_path: Path) -> None:
    code, out = _run(tmp_path / "nowhere", lambda s: FakeDiarizer())

    assert code == 1
    assert out.startswith("cli.session_not_found(folder=")


def test_no_system_speech_exits_1_without_building_the_diarizer(tmp_path: Path) -> None:
    folder = _session(tmp_path, Channel.MIC)

    def build(settings: Settings) -> Diarizer:
        raise AssertionError("built")

    code, out = _run(folder, build)

    assert code == 1
    assert out.startswith("cli.no_system_speech(folder=")


def test_failures_exit_1_with_the_reason(tmp_path: Path) -> None:
    folder = _session(tmp_path)

    def missing_token(settings: Settings) -> Diarizer:
        raise ConfigError("HF_TOKEN", "", "missing_hf_token")

    failing = FakeDiarizer(error=DiarizationError("gated model"))

    assert _run(folder, lambda s: failing) == (1, "cli.diarize_failed(reason=gated model)\n")
    code, out = _run(folder, missing_token)
    assert code == 1
    assert out.startswith("cli.diarize_failed(reason=errors.config.missing_hf_token(")
    assert not (folder / "transcript.diarized.jsonl").exists()
