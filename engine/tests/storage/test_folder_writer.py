"""`write_folder` (phase 39): a stored session back as a session folder, read by the import."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from tests.fakes import FakeLocalizer
from tests.storage.repository_contract import RAW, segment
from tests.storage.test_migration import RATE, Rig
from vozata.domain import ActionItem, AudioTrack, Channel, PartialMinutes, RequestEntry, Translation
from vozata.labels import SpeakerLabeler
from vozata.storage.folder_writer import write_folder


@pytest.fixture
def source(tmp_path: Path) -> Iterator[Rig]:
    rig = Rig(tmp_path / "source")
    yield rig
    rig.database.close()


@pytest.fixture
def target(tmp_path: Path) -> Iterator[Rig]:
    rig = Rig(tmp_path / "target")
    yield rig
    rig.database.close()


PARTIAL = PartialMinutes(
    "p1", "2026-10-22T10:05:00-03:00", 0.0, 312.5, "button", "# So far\n\n- Ação\n", "general"
)  # phase 48
REQUEST = RequestEntry(
    "r1", "2026-10-22T10:05:00-03:00", 312.5, "minutes_so_far", "voice", "gere a ata", "done", "p1"
)  # phase 59


def _labeler() -> SpeakerLabeler:
    return SpeakerLabeler(FakeLocalizer())


def _full_session(rig: Rig) -> str:
    """A folder with everything a session can hold, imported into the rig's database."""
    session_id = rig.folder(mic=2.5, system=2.0)
    rig.files.write_diarized(session_id, [RAW[0], segment("system-000002", 0.6, "Hi.", "system:1")])
    rig.files.write_edited(session_id, [replace(segment("mic-000001", 0.1, "Hey."), edited=True)])
    writer = rig.files.open_translations(session_id)
    writer.append(Translation("mic-000001", "en", "Hello."))
    writer.close()
    rig.files.write_speakers(session_id, ["system:1", "system:2"])
    rig.files.rename_speakers(session_id, {"system:1": "Ana"})
    rig.files.write_minutes(session_id, "# Minutes\n\n- Decided\n")
    items = [ActionItem("a1", "Send the deck", "Ana", "2026-10-20", ("mic-000001",))]
    rig.files.write_action_items(session_id, items)
    rig.files.write_partial_minutes(session_id, [PARTIAL])
    rig.files.write_requests(session_id, [REQUEST])
    assert rig.import_all() == [None]
    return session_id


def test_a_written_folder_imports_back_into_the_same_session(source: Rig, target: Rig) -> None:
    session_id = _full_session(source)
    repo = source.repo

    folder = write_folder(repo, source.audio, session_id, target.output, _labeler())

    assert folder == target.output / session_id
    assert target.import_all() == [None]
    copy = target.repo
    assert copy.read_meta(session_id) == repo.read_meta(session_id)
    for name in ("raw", "diarized", "edited"):
        assert copy.load_source(session_id, name) == repo.load_source(session_id, name)
    assert copy.load_translations(session_id) == repo.load_translations(session_id)
    assert copy.speaker_ids(session_id) == ["system:1", "system:2"]
    assert copy.speaker_names(session_id) == {"system:1": "Ana"}
    assert copy.read_minutes(session_id) == "# Minutes\n\n- Decided\n"
    assert copy.read_action_items(session_id) == repo.read_action_items(session_id)
    assert copy.read_partial_minutes(session_id) == [PARTIAL]
    assert copy.read_requests(session_id) == [REQUEST]
    for channel in Channel:
        length = source.audio.length(session_id, channel)
        assert length == round(2.5 * RATE)
        assert target.audio.length(session_id, channel) == length
        assert np.array_equal(
            target.audio.frames(session_id, channel, 0, length),
            source.audio.frames(session_id, channel, 0, length),
        )


def test_the_folder_has_the_readable_transcript_and_no_mixed_track(
    source: Rig, tmp_path: Path
) -> None:
    session_id = _full_session(source)

    folder = write_folder(source.repo, source.audio, session_id, tmp_path / "out", _labeler())

    names = sorted(path.name for path in folder.iterdir())
    assert "mixed.wav" not in names
    assert {"session.json", "transcript.jsonl", "transcript.md", "mic.wav", "system.wav"} <= set(
        names
    )
    assert "Hello." in (folder / "transcript.md").read_text(encoding="utf-8")


def test_a_session_without_audio_or_annotations_writes_only_what_it_has(
    source: Rig, tmp_path: Path
) -> None:
    session_id = source.repo.create()
    source.repo.write_meta(session_id, {"id": session_id, "status": "done"})

    folder = write_folder(source.repo, None, session_id, tmp_path / "out", _labeler())

    assert sorted(path.name for path in folder.iterdir()) == [
        "session.json",
        "transcript.jsonl",
        "transcript.md",
    ]
    assert source.audio.track(session_id, AudioTrack.MIC) is None
