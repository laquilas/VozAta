"""Kept sources of a meeting (phase 66) and the remix of a new choice."""

from __future__ import annotations

import wave
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from vozata.domain import Channel
from vozata.processing.source_remix import UnknownSourceError, remix
from vozata.recorder.manifest import Manifest, Segment
from vozata.storage.source_archive import SourceArchive

RATE = 1000
ZONE = timezone(timedelta(hours=-3))
SESSION = "20261112_140724"


def _wav(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(RATE)
        file.writeframes(samples.astype(np.int16).tobytes())


def _recording(tmp_path: Path) -> tuple[Path, Manifest, dict[str, np.ndarray]]:
    folder = tmp_path / "live" / SESSION
    (folder / "sources").mkdir(parents=True)
    data = {
        "in-jbl": np.full(1000, 1000, np.int16),
        "in-room": np.full(800, -2000, np.int16),
        "out-headset": np.arange(1000, dtype=np.int16),
    }
    manifest = Manifest(id=SESSION, started_at="2026-11-12T14:07:24-03:00", sample_rate=RATE)
    for source_id, samples in data.items():
        _wav(folder / "sources" / f"{source_id}.wav", samples)
        kind = "system" if source_id.startswith("out-") else "mic"
        manifest.sources[source_id] = {
            "kind": kind,
            "name": source_id.upper(),
            "selected": source_id != "in-room",
            "preferred": source_id == "in-jbl",
            "state": "open",
            "segments": [Segment(f"{source_id}.wav", 0, len(samples), closed=True)],
        }
    manifest.selection_log.append({"at": 1.0, "source": "in-jbl", "selected": True, "by": "auto"})
    return folder, manifest, data


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 12, 15, 0, tzinfo=ZONE)

    def __call__(self) -> datetime:
        return self.now


class Pcm:
    def __init__(self) -> None:
        self.channels: dict[Channel, np.ndarray] = {}

    def import_pcm(self, session_id: str, channel: Channel, blocks: Iterable[bytes]) -> int:
        self.channels[channel] = np.frombuffer(b"".join(blocks), np.int16)
        return len(self.channels[channel])


def test_keep_moves_the_sources_and_lists_them(tmp_path: Path) -> None:
    folder, manifest, data = _recording(tmp_path)
    archive = SourceArchive(tmp_path, Clock())

    assert archive.keep(SESSION, folder, manifest)

    assert not (folder / "sources").exists()
    listed = {s.source_id: s for s in archive.list(SESSION)}
    assert sorted(listed) == ["in-jbl", "in-room", "out-headset"]
    assert (listed["in-room"].kind, listed["in-room"].frames) == (Channel.MIC, 800)
    assert listed["in-jbl"].preferred and listed["in-jbl"].selected
    assert listed["out-headset"].name == "OUT-HEADSET"
    assert archive.has(SESSION)
    assert archive.kept_at(SESSION) == Clock()()
    assert np.array_equal(archive.frames(SESSION, "in-room", 0, 900), data["in-room"])
    with pytest.raises(KeyError):
        archive.frames(SESSION, "in-nope", 0, 10)


def test_keep_without_sources_does_nothing(tmp_path: Path) -> None:
    folder, manifest, _ = _recording(tmp_path)
    archive = SourceArchive(tmp_path, Clock())
    manifest.sources.clear()

    assert not archive.keep(SESSION, folder, manifest)
    assert archive.list(SESSION) == []
    assert archive.kept_at(SESSION) is None


def test_keep_replaces_an_older_copy(tmp_path: Path) -> None:
    folder, manifest, _ = _recording(tmp_path)
    archive = SourceArchive(tmp_path, Clock())
    (archive.folder(SESSION)).mkdir(parents=True)
    (archive.folder(SESSION) / "stale.wav").write_bytes(b"x")

    archive.keep(SESSION, folder, manifest)

    assert not (archive.folder(SESSION) / "stale.wav").exists()


def test_keep_only_selected_deletes_the_other_files(tmp_path: Path) -> None:
    folder, manifest, _ = _recording(tmp_path)
    archive = SourceArchive(tmp_path, Clock())
    archive.keep(SESSION, folder, manifest)

    assert archive.keep_only_selected(SESSION) == ["in-room"]

    assert not (archive.folder(SESSION) / "in-room.wav").exists()
    assert [s.source_id for s in archive.list(SESSION)] == ["in-jbl", "out-headset"]


def test_prune_removes_old_sources_only(tmp_path: Path) -> None:
    folder, manifest, _ = _recording(tmp_path)
    clock = Clock()
    archive = SourceArchive(tmp_path, clock)
    archive.keep(SESSION, folder, manifest)
    (archive.root / "broken").mkdir()

    assert archive.prune(0) == []
    clock.now += timedelta(days=6)
    assert archive.prune(7) == []
    clock.now += timedelta(days=2)
    assert archive.prune(7) == [SESSION]
    assert not archive.has(SESSION)
    assert (archive.root / "broken").exists()  # not a kept meeting: left alone
    archive.remove(SESSION)  # nothing left: no error
    assert SourceArchive(tmp_path / "empty", clock).prune(7) == []


def test_an_invalid_session_id_is_refused(tmp_path: Path) -> None:
    archive = SourceArchive(tmp_path, Clock())
    for bad in ("", "../x", "a/b"):
        with pytest.raises(ValueError):
            archive.folder(bad)


def test_remix_writes_the_chosen_sources_into_both_channels(tmp_path: Path) -> None:
    folder, manifest, data = _recording(tmp_path)
    archive = SourceArchive(tmp_path, Clock())
    archive.keep(SESSION, folder, manifest)
    pcm = Pcm()

    written = remix(archive, pcm, SESSION, {"in-room", "out-headset"}, RATE)

    assert written == {Channel.MIC: 1000, Channel.SYSTEM: 1000}
    mic = pcm.channels[Channel.MIC]
    assert np.array_equal(mic[:800], data["in-room"]) and not mic[800:].any()
    assert np.allclose(pcm.channels[Channel.SYSTEM], data["out-headset"], atol=1)
    selected = {s.source_id for s in archive.list(SESSION) if s.selected}
    assert selected == {"in-room", "out-headset"}


def test_remix_of_no_source_of_a_kind_is_silence(tmp_path: Path) -> None:
    folder, manifest, _ = _recording(tmp_path)
    archive = SourceArchive(tmp_path, Clock())
    archive.keep(SESSION, folder, manifest)
    pcm = Pcm()

    remix(archive, pcm, SESSION, {"out-headset"}, RATE)

    assert len(pcm.channels[Channel.MIC]) == 1000 and not pcm.channels[Channel.MIC].any()


def test_remix_refuses_an_unknown_source(tmp_path: Path) -> None:
    folder, manifest, _ = _recording(tmp_path)
    archive = SourceArchive(tmp_path, Clock())
    archive.keep(SESSION, folder, manifest)

    with pytest.raises(UnknownSourceError):
        remix(archive, Pcm(), SESSION, {"in-gone"}, RATE)
