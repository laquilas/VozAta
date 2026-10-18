"""Crash safety of the SQLite backend (phase 31): a recording process killed mid-session.

A child process records into `vozata.db` (metadata heartbeats and one committed segment after
another) and is hard-killed while it writes. Every segment it reported as committed must be
readable, and the session must be found as interrupted.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import vozata
from tests.storage.repository_contract import STARTED
from vozata.storage.recovery import find_interrupted
from vozata.storage.sqlite.db import Database
from vozata.storage.sqlite.repository import SqliteSessionRepository

_WRITER = r"""
import sys
from datetime import datetime
from pathlib import Path

from vozata.domain import Channel, TranscriptSegment, Word
from vozata.storage.sqlite.db import Database
from vozata.storage.sqlite.repository import SqliteSessionRepository

database, output, started = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
repository = SqliteSessionRepository(Database(database), output)
session_id = repository.create(datetime.fromisoformat(started))
meta = {"id": session_id, "status": "recording", "started_at": started}
repository.write_meta(session_id, meta)
sink = repository.open_transcript(session_id, labeler=None)
number = 0
while True:  # until killed
    number += 1
    start = number * 0.5
    text = f"segment {number} " + "word " * 50
    words = (Word("segment", start, start + 0.2, 0.9),)
    sink.emit(
        TranscriptSegment(f"mic-{number:06d}", Channel.MIC, "mic", start, start + 0.4, text, words)
    )
    repository.write_meta(session_id, {**meta, "duration_seconds": start})
    print(session_id, number, flush=True)
"""


def test_a_killed_writer_leaves_every_committed_segment_and_an_interrupted_session(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "vozata.db"
    src = Path(vozata.__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(src)}
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _WRITER,
            str(database_path),
            str(tmp_path / "rec"),
            STARTED.isoformat(),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        reported = 0
        session_id = ""
        assert child.stdout is not None
        while reported < 25:
            line = child.stdout.readline()
            assert line, child.stderr.read() if child.stderr else "the writer stopped"
            session_id, number = line.split()
            reported = int(number)
    finally:
        child.kill()  # hard kill (TerminateProcess on Windows), most likely mid-write
        child.wait(10)

    database = Database(database_path)
    try:
        repository = SqliteSessionRepository(database, tmp_path / "rec")
        segments = repository.load_raw_transcript(session_id)
        assert len(segments) >= reported
        assert [s.segment_id for s in segments] == [
            f"mic-{n:06d}" for n in range(1, len(segments) + 1)
        ]
        assert all(s.text.startswith(f"segment {n} ") for n, s in enumerate(segments, 1))
        assert all(len(s.words) == 1 for s in segments)
        assert repository.read_meta(session_id)["status"] == "recording"

        assert find_interrupted(repository) == [session_id]
        assert repository.read_meta(session_id)["status"] == "interrupted"
        assert database.connection().execute("PRAGMA integrity_check").fetchone() == ("ok",)
        hits = database.connection().execute(
            "SELECT COUNT(*) FROM segments_fts WHERE segments_fts MATCH 'segment'"
        )
        assert hits.fetchone()[0] == len(segments)  # the index is consistent too
    finally:
        database.close()
