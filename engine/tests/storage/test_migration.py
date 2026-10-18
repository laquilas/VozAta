"""`FolderImporter` (phase 33): session folders into `vozata.db`, idempotent and resumable."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import wave
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

import vozata
from tests.storage.repository_contract import RAW, STARTED, segment
from vozata.audio.mixer import MonoMixer
from vozata.domain import ActionItem, Channel, Translation
from vozata.storage.audio_cache import WavCache
from vozata.storage.files.audio import FileAudioStore
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.migration import FolderImporter, MigrationError, NotEnoughSpaceError
from vozata.storage.session_store import SessionStore
from vozata.storage.sqlite.audio import SqliteAudioStore
from vozata.storage.sqlite.db import Database
from vozata.storage.sqlite.repository import SqliteSessionRepository

RATE = 16000
IMPORTED_AT = datetime(2026, 10, 18, 12, 0, 0)


class Rig:
    def __init__(self, tmp_path: Path, free: int = 1 << 40) -> None:
        self.output = tmp_path / "recordings"
        self.database = Database(tmp_path / "db" / "vozata.db")
        self.files = FileSessionRepository(SessionStore(self.output))
        self.file_audio = FileAudioStore(self.files.store, RATE)
        self.repo = SqliteSessionRepository(self.database, self.output)
        cache = WavCache(tmp_path / "cache", 1 << 30)
        self.audio = SqliteAudioStore(self.database, RATE, MonoMixer(), cache)
        self.free = free
        self.importer = FolderImporter(
            self.output,
            self.files,
            self.file_audio,
            self.repo,
            self.audio,
            RATE,
            free_space=lambda _path: self.free,
            now=lambda: IMPORTED_AT,
        )

    def folder(self, *, status: str = "done", mic: float = 1.0, system: float = 1.0) -> str:
        session_id = self.files.create(STARTED)
        self.files.write_meta(
            session_id,
            {
                "id": session_id,
                "status": status,
                "started_at": STARTED.isoformat(),
                "title": "Weekly sync",
                "template": "general",
            },
        )
        paths = self.files.paths(session_id)
        if mic:
            write_wav(paths.wav(Channel.MIC), mic, step=7)
        if system:
            write_wav(paths.wav(Channel.SYSTEM), system, step=13)
        lines = "".join(json.dumps(s.to_dict()) + "\n" for s in RAW)
        paths.transcript_jsonl.write_text(lines, encoding="utf-8", newline="\n")
        return session_id

    def import_all(self) -> list[MigrationError | None]:
        return [self.importer.import_one(session_id) for session_id in self.importer.pending()]


def write_wav(
    path: Path, seconds: float, step: int = 7, rate: int = RATE, channels: int = 1
) -> None:
    count = round(seconds * rate)
    samples = ((np.arange(count * channels) * step) % 2000 - 1000).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(samples.tobytes())


def wav_samples(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav:
        return np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")


def hashes(root: Path) -> dict[str, str]:
    return {
        str(item.relative_to(root)): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(root.rglob("*"))
        if item.is_file()
    }


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    rig = Rig(tmp_path)
    yield rig
    rig.database.close()


def test_a_full_session_is_imported_with_everything_it_holds(rig: Rig) -> None:
    session_id = rig.folder(mic=2.5, system=2.0)
    diarized = [RAW[0], segment("system-000002", 0.6, "Hi.", "system:1")]
    edited = [replace(segment("mic-000001", 0.1, "Hello there."), edited=True)]
    rig.files.write_diarized(session_id, diarized)
    rig.files.write_edited(session_id, edited)
    writer = rig.files.open_translations(session_id)
    writer.append(Translation("mic-000001", "en", "Hello."))
    writer.close()
    rig.files.write_speakers(session_id, ["system:1", "system:2"])
    rig.files.rename_speakers(session_id, {"system:1": "Ana"})
    rig.files.write_minutes(session_id, "# Minutes\n\n- Decided\n")
    minutes = rig.files.paths(session_id).minutes_md
    os.utime(minutes, (1_700_000_000, 1_700_000_000))
    items = [ActionItem("a1", "Send the deck", "Ana", "2026-10-20", ("mic-000001",))]
    rig.files.write_action_items(session_id, items)

    assert rig.import_all() == [None]

    repo = rig.repo
    assert repo.list_sessions() == [session_id]
    assert repo.read_meta(session_id)["title"] == "Weekly sync"
    assert repo.load_raw_transcript(session_id) == RAW
    assert repo.load_transcript_with_source(session_id) == ("edited", edited)
    rows = rig.database.connection().execute(
        "SELECT source, COUNT(*) FROM segments GROUP BY source ORDER BY source"
    )
    assert rows.fetchall() == [("diarized", 2), ("edited", 1), ("raw", 2)]
    assert repo.load_translations(session_id) == {
        "mic-000001": Translation("mic-000001", "en", "Hello.")
    }
    assert repo.speaker_count(session_id) == 2
    assert repo.speaker_names(session_id) == {"system:1": "Ana"}
    assert repo.read_minutes(session_id) == "# Minutes\n\n- Decided\n"
    generated = rig.database.connection().execute("SELECT generated_at FROM minutes").fetchone()
    expected = datetime.fromtimestamp(1_700_000_000).astimezone().isoformat(timespec="seconds")
    assert generated == (expected,)
    assert repo.read_action_items(session_id) == items
    paths = rig.files.paths(session_id)
    mic = rig.audio.frames(session_id, Channel.MIC, 0, 10 * RATE)
    assert np.array_equal(mic, wav_samples(paths.wav(Channel.MIC)))
    system = rig.audio.frames(session_id, Channel.SYSTEM, 0, 10 * RATE)
    assert np.array_equal(system[: 2 * RATE], wav_samples(paths.wav(Channel.SYSTEM)))
    assert not system[2 * RATE :].any()  # padded with silence to the same length
    assert rig.audio.length(session_id, Channel.SYSTEM) == rig.audio.length(session_id, Channel.MIC)
    row = rig.database.connection().execute(
        "SELECT imported_from, imported_at FROM sessions WHERE id = ?", (session_id,)
    )
    assert row.fetchone() == (str(paths.root), IMPORTED_AT.isoformat(timespec="seconds"))


def test_a_session_without_minutes_audio_or_annotations_is_imported(rig: Rig) -> None:
    session_id = rig.folder(mic=0, system=0)

    assert rig.import_all() == [None]

    assert not rig.repo.has_minutes(session_id)
    assert rig.repo.read_action_items(session_id) == []
    assert rig.audio.track(session_id, vozata.domain.AudioTrack.MIXED) is None


def test_imported_words_are_found_by_search(rig: Rig) -> None:
    rig.folder()

    rig.import_all()

    hits = rig.database.connection().execute(
        "SELECT segment_id FROM segments_fts WHERE segments_fts MATCH 'hello'"
    )
    assert hits.fetchall() == [("mic-000001",)]


def test_the_folders_are_never_changed(rig: Rig) -> None:
    rig.folder()
    rig.folder()
    before = hashes(rig.output)

    rig.import_all()

    assert hashes(rig.output) == before


def test_a_second_run_imports_nothing(rig: Rig) -> None:
    rig.folder()
    rig.import_all()

    assert rig.importer.pending() == []
    assert rig.import_all() == []


def test_folders_are_imported_oldest_first_and_other_items_are_ignored(rig: Rig) -> None:
    first, second = rig.folder(), rig.folder()
    (rig.output / "cache").mkdir()
    (rig.output / "vozata.db").write_bytes(b"")
    (rig.output / "20261015_202358_9").write_bytes(b"")  # a file named like a session

    assert rig.importer.pending() == [first, second]


def test_no_output_folder_means_nothing_to_import(tmp_path: Path) -> None:
    rig = Rig(tmp_path)

    assert rig.importer.pending() == []


def test_an_interrupted_folder_is_repaired_then_imported_as_interrupted(rig: Rig) -> None:
    session_id = rig.folder(status="recording", mic=2.0, system=1.0)
    transcript = rig.files.paths(session_id).transcript_jsonl
    with transcript.open("a", encoding="utf-8") as file:
        file.write('{"segment_id": "mic-0000')  # half-written by the crash

    assert rig.import_all() == [None]

    meta = rig.repo.read_meta(session_id)
    assert meta["status"] == "interrupted"
    assert meta["duration_seconds"] == 2.0
    assert rig.repo.load_raw_transcript(session_id) == RAW
    assert rig.audio.length(session_id, Channel.SYSTEM) == 2 * RATE


def test_an_interrupted_folder_keeps_a_known_duration(rig: Rig) -> None:
    session_id = rig.folder(status="paused")
    meta = rig.files.read_meta(session_id)
    rig.files.write_meta(session_id, {**meta, "duration_seconds": 42.0})

    rig.import_all()

    assert rig.repo.read_meta(session_id)["duration_seconds"] == 42.0


@pytest.mark.parametrize(
    ("damage", "reason"),
    [
        (lambda p: p.meta.write_text("{not json", encoding="utf-8"), "unreadable_json"),
        (lambda p: p.meta.write_text("[1, 2]", encoding="utf-8"), "unreadable_json"),
        (lambda p: p.diarized_jsonl.write_text('{"x": 1}\n', encoding="utf-8"), "unreadable_json"),
        (lambda p: p.action_items_json.write_text("{}", encoding="utf-8"), "unreadable_json"),
        (lambda p: p.wav(Channel.MIC).write_bytes(b"RIFF junk"), "unreadable_wav"),
        (lambda p: write_wav(p.wav(Channel.MIC), 1.0, rate=44100), "unsupported_wav"),
        (lambda p: write_wav(p.wav(Channel.SYSTEM), 1.0, channels=2), "unsupported_wav"),
    ],
)
def test_a_bad_folder_is_recorded_and_the_next_one_still_imported(
    rig: Rig, damage, reason: str
) -> None:
    bad, good = rig.folder(), rig.folder()
    damage(rig.files.paths(bad))

    results = rig.import_all()

    folder = str(rig.files.paths(bad).root)
    assert results[0] is not None and (results[0].folder, results[0].reason) == (folder, reason)
    assert results[1] is None
    assert rig.repo.list_sessions() == [good]  # nothing of the bad one was written
    assert rig.database.connection().execute(
        "SELECT COUNT(*) FROM audio_chunks WHERE session_id = ?", (bad,)
    ).fetchone() == (0,)
    assert [(e.folder, e.reason) for e in rig.importer.errors()] == [(folder, reason)]
    assert rig.importer.pending() == []  # not tried again


def test_an_interrupted_folder_whose_wav_cannot_be_repaired_is_recorded(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vozata.ports import StoreRepairError

    rig.folder(status="finalizing")

    def broken(session_id: str) -> float:
        raise StoreRepairError("mic.wav: unreadable")

    monkeypatch.setattr(rig.file_audio, "repair", broken)

    [error] = rig.import_all()

    assert error is not None and error.reason == "unreadable_wav"


def test_a_folder_whose_id_is_already_used_by_another_session_is_recorded(rig: Rig) -> None:
    session_id = rig.folder()
    rig.database.connection().execute(
        "INSERT INTO sessions (id, meta_json) VALUES (?, '{}')", (session_id,)
    )
    (rig.files.paths(session_id).root / "mic.wav").unlink()
    (rig.files.paths(session_id).root / "system.wav").unlink()

    # The id is known and the folder has a `session.json`: it is not pending.
    assert rig.importer.pending() == []
    assert rig.importer.import_one(session_id).reason == "id_in_use"


def test_the_audio_of_a_phase_31_sqlite_session_is_imported_into_its_row(rig: Rig) -> None:
    session_id = rig.repo.create(STARTED)
    rig.repo.write_meta(session_id, {"id": session_id, "status": "done"})
    root = rig.output / session_id
    root.mkdir(parents=True)
    write_wav(root / "mic.wav", 1.5)

    assert rig.importer.pending() == [session_id]
    assert rig.import_all() == [None]

    assert rig.audio.length(session_id, Channel.MIC) == round(1.5 * RATE)
    assert rig.audio.length(session_id, Channel.SYSTEM) == round(1.5 * RATE)
    assert rig.importer.pending() == []


def test_a_sqlite_session_folder_without_wavs_or_already_with_audio_is_not_pending(
    rig: Rig,
) -> None:
    empty = rig.repo.create(STARTED)
    rig.repo.write_meta(empty, {"id": empty, "status": "done"})
    (rig.output / empty).mkdir(parents=True)
    recorded = rig.repo.create(STARTED)
    rig.repo.write_meta(recorded, {"id": recorded, "status": "done"})
    (rig.output / recorded).mkdir()
    write_wav(rig.output / recorded / "mic.wav", 0.5)
    rig.audio.import_pcm(recorded, Channel.MIC, [bytes(2 * RATE)])
    unknown = rig.output / "20200101_000000"
    unknown.mkdir()
    write_wav(unknown / "mic.wav", 0.5)  # no row and no session.json: nothing to import into

    assert rig.importer.pending() == []


def test_a_short_disk_stops_before_writing_anything(rig: Rig) -> None:
    session_id = rig.folder(mic=1.0, system=1.0)
    size = rig.importer.folder_size(session_id)
    rig.free = round(size * 1.05)

    with pytest.raises(NotEnoughSpaceError) as raised:
        rig.importer.import_one(session_id)

    assert raised.value.needed == round(size * 1.1)
    assert raised.value.free == rig.free
    assert rig.repo.list_sessions() == []
    assert rig.importer.pending() == [session_id]  # left for later
    rig.free = size * 2
    assert rig.importer.import_one(session_id) is None


def test_the_default_free_space_reads_the_disk(tmp_path: Path) -> None:
    from vozata.storage.migration import _free_space

    assert _free_space(tmp_path / "new") > 0
    assert (tmp_path / "new").is_dir()


_IMPORTER = r"""
import sys
import time
from pathlib import Path

from vozata.audio.mixer import MonoMixer
from vozata.storage.audio_cache import WavCache
from vozata.storage.files.audio import FileAudioStore
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.migration import FolderImporter
from vozata.storage.session_store import SessionStore
from vozata.storage.sqlite.audio import SqliteAudioStore
from vozata.storage.sqlite.db import Database
from vozata.storage.sqlite.repository import SqliteSessionRepository

output, database_path = Path(sys.argv[1]), Path(sys.argv[2])
database = Database(database_path)
files = FileSessionRepository(SessionStore(output))
audio = SqliteAudioStore(database, 16000, MonoMixer(), WavCache(output / "cache", 1 << 20))
importer = FolderImporter(
    output, files, FileAudioStore(files.store, 16000),
    SqliteSessionRepository(database, output), audio, 16000,
)
original = importer._blocks


def stalled(path):
    for block in original(path):
        yield block
        print("writing", flush=True)  # inside the open transaction
        time.sleep(3600)


importer._blocks = stalled
for session_id in importer.pending():
    importer.import_one(session_id)
"""


def test_a_crash_mid_import_rolls_that_session_back_and_the_next_run_imports_it(
    rig: Rig, tmp_path: Path
) -> None:
    session_id = rig.folder(mic=3.0, system=3.0)
    env = {**os.environ, "PYTHONPATH": str(Path(vozata.__file__).parents[1])}
    child = subprocess.Popen(
        [sys.executable, "-c", _IMPORTER, str(rig.output), str(rig.database.path)],
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "writing"
    finally:
        child.kill()
        child.wait(10)

    assert rig.repo.list_sessions() == []
    assert rig.importer.pending() == [session_id]
    assert rig.import_all() == [None]
    assert rig.repo.list_sessions() == [session_id]
    assert rig.audio.length(session_id, Channel.MIC) == 3 * RATE


def test_the_default_clock_is_local_and_aware() -> None:
    from vozata.storage.migration import _local_now

    assert _local_now().tzinfo is not None
