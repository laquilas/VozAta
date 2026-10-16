from __future__ import annotations

import io
import json
from pathlib import Path

from tests.fakes import FakeLanguageModel, FakeLocalizer
from vozata.cli.console import ConsoleObserver
from vozata.cli.minutes import run_minutes
from vozata.config import Settings
from vozata.domain import Channel, TranscriptSegment
from vozata.labels import SpeakerLabeler
from vozata.minutes.generator import MinutesGenerator
from vozata.ports import LanguageModelError, Localizer
from vozata.storage.session_store import SessionStore


class _FailingModel(FakeLanguageModel):
    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str:
        raise LanguageModelError("connection refused")


def _session(tmp_path: Path, meta: dict, *, transcript: bool = True) -> Path:
    store = SessionStore(tmp_path / "recordings")
    paths = store.create()
    store.write_meta(paths.id, meta)
    if transcript:
        segment = TranscriptSegment("mic-000001", Channel.MIC, "mic", 1.0, 2.0, "Olá.", ())
        paths.transcript_jsonl.write_text(json.dumps(segment.to_dict()) + "\n", encoding="utf-8")
    return paths.root


def _run(folder: Path, llm: FakeLanguageModel) -> tuple[int, str]:
    out = io.StringIO()
    localizer = FakeLocalizer()
    labeler = SpeakerLabeler(localizer)
    console = ConsoleObserver(localizer, labeler, out)

    def build(settings: Settings, loc: Localizer) -> MinutesGenerator:
        return MinutesGenerator(llm, loc, settings.llm_max_chars)

    code = run_minutes(folder, Settings(), console, localizer, labeler, build)
    return code, out.getvalue()


def test_writes_minutes_in_the_stored_language(tmp_path: Path) -> None:
    folder = _session(tmp_path, {"language": "pt"})
    llm = FakeLanguageModel(["# Ata"])

    code, out = _run(folder, llm)

    assert code == 0
    assert (folder / "minutes.md").read_text(encoding="utf-8") == "# Ata\n"
    assert f"cli.minutes_written(path={folder / 'minutes.md'})" in out
    _, prompt, _ = llm.prompts[0]
    assert "languages.pt" in prompt
    assert "[00:00:01] labels.mic: Olá." in prompt


def test_a_session_without_a_detected_language_uses_auto(tmp_path: Path) -> None:
    folder = _session(tmp_path, {})
    llm = FakeLanguageModel(["# Minutes"])

    _run(folder, llm)

    _, prompt, _ = llm.prompts[0]
    assert "languages.auto" in prompt


def test_unknown_folder_exits_1(tmp_path: Path) -> None:
    code, out = _run(tmp_path / "nowhere", FakeLanguageModel())

    assert code == 1
    assert out.startswith("cli.session_not_found(folder=")


def test_empty_transcript_exits_1_without_calling_the_model(tmp_path: Path) -> None:
    folder = _session(tmp_path, {"language": "en"}, transcript=False)
    llm = FakeLanguageModel()

    code, out = _run(folder, llm)

    assert code == 1
    assert out.startswith("cli.empty_transcript(folder=")
    assert llm.prompts == []


def test_language_model_failure_exits_1_and_writes_nothing(tmp_path: Path) -> None:
    folder = _session(tmp_path, {"language": "en"})

    code, out = _run(folder, _FailingModel())

    assert code == 1
    assert out == "cli.minutes_failed(reason=connection refused)\n"
    assert not (folder / "minutes.md").exists()
