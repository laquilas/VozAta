from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from tests.fakes import FakeTranscriptSink
from vozata.domain import AppLanguage, Channel, TranscriptSegment, Word
from vozata.i18n import TomlLocalizer
from vozata.labels import SpeakerLabeler
from vozata.output.sinks import CompositeSink, ConsoleSink, JsonlSink, MarkdownSink
from vozata.ports import TranscriptSink


def segment(
    segment_id: str = "mic-000001", start: float = 83.1, text: str = "Olá, ação!"
) -> TranscriptSegment:
    return TranscriptSegment(
        segment_id,
        Channel.MIC,
        "mic",
        start,
        start + 2,
        text,
        (Word("Olá,", start, start + 0.4, 0.9),),
    )


@pytest.fixture
def labeler() -> SpeakerLabeler:
    return SpeakerLabeler(TomlLocalizer(AppLanguage.PT_BR))


def test_sinks_satisfy_the_port(tmp_path: Path, labeler: SpeakerLabeler) -> None:
    sinks = [
        ConsoleSink(labeler, io.StringIO()),
        JsonlSink(tmp_path / "t.jsonl"),
        MarkdownSink(tmp_path / "t.md", labeler),
        CompositeSink([]),
    ]

    assert all(isinstance(sink, TranscriptSink) for sink in sinks)
    for sink in sinks:
        sink.close()


def test_console_sink_writes_one_rendered_line(labeler: SpeakerLabeler) -> None:
    stream = io.StringIO()
    sink = ConsoleSink(labeler, stream)

    sink.emit(segment())
    sink.close()

    assert stream.getvalue() == "[00:01:23] Eu: Olá, ação!\n"
    assert not stream.closed


def test_jsonl_sink_appends_one_flushed_line_per_segment(tmp_path: Path) -> None:
    path = tmp_path / "transcript.jsonl"
    sink = JsonlSink(path)

    sink.emit(segment("mic-000001"))
    flushed = path.read_text(encoding="utf-8")  # readable before close
    sink.emit(segment("mic-000002"))
    sink.close()
    JsonlSink(path).close()  # reopening appends, never truncates

    lines = path.read_text(encoding="utf-8").splitlines()
    assert flushed.count("\n") == 1
    assert [json.loads(line)["segment_id"] for line in lines] == ["mic-000001", "mic-000002"]
    assert "Olá, ação!" in lines[0]  # UTF-8, not escaped
    assert TranscriptSegment.from_dict(json.loads(lines[0])) == segment("mic-000001")


def test_jsonl_sink_fsyncs_every_segment_and_markdown_does_not(
    tmp_path: Path, labeler: SpeakerLabeler, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced: list[int] = []
    monkeypatch.setattr("vozata.output.sinks.os.fsync", synced.append)
    jsonl = JsonlSink(tmp_path / "transcript.jsonl")
    markdown = MarkdownSink(tmp_path / "transcript.md", labeler)

    for sink in (jsonl, markdown):
        sink.emit(segment("mic-000001"))
        sink.emit(segment("mic-000002"))
        sink.close()

    assert len(synced) == 2  # phase 17: a machine crash keeps every committed line


def test_markdown_sink_appends_rendered_lines(tmp_path: Path, labeler: SpeakerLabeler) -> None:
    path = tmp_path / "transcript.md"
    sink = MarkdownSink(path, labeler)

    sink.emit(segment(start=3700))
    sink.close()

    assert path.read_text(encoding="utf-8") == "[01:01:40] Eu: Olá, ação!\n"


class BrokenSink:
    def emit(self, segment: TranscriptSegment) -> None:
        raise OSError("disk full")

    def close(self) -> None:
        raise OSError("disk full")


def test_composite_isolates_a_failing_sink(caplog: pytest.LogCaptureFixture) -> None:
    healthy = FakeTranscriptSink()
    sink = CompositeSink([BrokenSink(), healthy])

    sink.emit(segment())
    sink.close()

    assert healthy.segments == [segment()]
    assert healthy.closed
    assert caplog.text.count("BrokenSink") == 2
