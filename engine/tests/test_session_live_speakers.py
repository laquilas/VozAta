"""Live speaker labels during a recording (phase 15, architecture §6 and §11)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from tests.fakes import FakeEmbedder
from tests.test_session import SETTINGS, _Rig, _voice, _wait_for
from vozata.config import ConfigError
from vozata.domain import Channel, SessionStatus, TranscriptionResult, Word

LIVE = dataclasses.replace(SETTINGS, chunk_seconds=3.0)


def _long_words(*texts: str) -> TranscriptionResult:
    """Words of 0.8 s from 0.2 s: a segment long enough (≥ 1 s) to be embedded."""
    words = tuple(Word(text, 0.2 + i * 0.8, 1.0 + i * 0.8, 0.9) for i, text in enumerate(texts))
    return TranscriptionResult(words=words, language="en")


def _ready(rig: _Rig) -> bool:
    live = rig.session._pipeline._live
    return live is not None and live._tagger is not None


def test_system_lines_get_live_speakers_and_the_embedder_is_released_at_stop(
    tmp_path: Path,
) -> None:
    embedder = FakeEmbedder([[1.0, 0.0]])
    rig = _Rig(
        tmp_path,
        results=[_long_words("Hello", "there.")],
        settings=LIVE,
        embedder_factory=lambda: embedder,
        with_minutes=False,
    )
    rig.session.start()
    _wait_for(lambda: _ready(rig))

    rig.system.push(_voice(3.0), 0.0)
    rig.clock.time = 3.0
    rig.session.stop()

    [(segment,)] = rig.observer.of("segment")
    assert (segment.channel, segment.speaker_id) == (Channel.SYSTEM, "system:1")
    line = json.loads(rig.session.paths.transcript_jsonl.read_text(encoding="utf-8"))
    assert line["speaker_id"] == "system:1"
    [clip] = embedder.calls
    assert len(clip) == round(1.6 * 16000)  # the segment's audio, 0.2 s to 1.8 s
    assert embedder.closed
    assert rig.session.status is SessionStatus.DONE


def test_a_failed_embedder_load_reports_an_error_and_lines_keep_system(tmp_path: Path) -> None:
    def fail() -> FakeEmbedder:
        raise ConfigError("HF_TOKEN", "", "missing_hf_token")

    rig = _Rig(
        tmp_path,
        results=[_long_words("Hello", "there.")],
        settings=LIVE,
        embedder_factory=fail,
        with_minutes=False,
    )
    rig.session.start()
    _wait_for(lambda: bool(rig.observer.of("error")))

    rig.system.push(_voice(3.0), 0.0)
    rig.clock.time = 3.0
    rig.session.stop()

    [(code, message)] = rig.observer.of("error")
    assert code == "live_diarization_failed"
    assert message.startswith("errors.session.live_diarization_failed(reason=errors.config.")
    [(segment,)] = rig.observer.of("segment")
    assert segment.speaker_id == "system"
    assert rig.session.status is SessionStatus.DONE


def test_without_a_system_source_no_live_worker_runs(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, settings=LIVE, embedder_factory=FakeEmbedder, with_minutes=False)
    rig.session._c = dataclasses.replace(rig.session._c, sources={Channel.MIC: rig.mic})

    rig.session.start()
    rig.session.stop()

    assert rig.session._pipeline._live is None
