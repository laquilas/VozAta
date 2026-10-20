"""`GET /sessions/{id}/audio/{track}` and the `audio` field of a session (phase 32)."""

from __future__ import annotations

import dataclasses
import io
import threading
import wave
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from tests.api.conftest import Api, hold_in_queue
from vozata.audio.mixer import StereoMixer
from vozata.audio.wav_writer import to_pcm16
from vozata.domain import Channel
from vozata.storage.audio_cache import WavCache
from vozata.storage.sqlite.audio import SqliteAudioStore
from vozata.storage.sqlite.db import Database
from vozata.storage.sqlite.repository import SqliteSessionRepository

RATE = 1000
MIC = (np.sin(np.arange(2500) / 7) * 0.5).astype(np.float32)
SYSTEM = (np.cos(np.arange(1200) / 3) * 0.25).astype(np.float32)
SIZE = 44 + 2500 * 2


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    database = Database(tmp_path / "vozata.db")
    yield database
    database.close()


@pytest.fixture
def recorded(api: Api, database: Database, tmp_path: Path) -> str:
    """A finished SQLite session (mic 2.5 s, system 1.2 s) served by the API."""
    repo = SqliteSessionRepository(database, tmp_path / "recordings")
    audio = SqliteAudioStore(database, RATE, StereoMixer(), WavCache(tmp_path / "cache", 1 << 20))
    session_id = repo.create(datetime(2026, 10, 15, 20, 23, 58))
    repo.write_meta(session_id, {"id": session_id, "status": "done"})
    for channel, samples in ((Channel.MIC, MIC), (Channel.SYSTEM, SYSTEM)):
        writer = audio.open_writer(session_id, channel)
        writer.write(samples, 0.0)
        writer.finalize(0)
    container = api.app.state.container
    api.app.state.container = dataclasses.replace(
        container, store=repo, audio=audio, storage=dataclasses.replace(container.storage)
    )
    return session_id


def _wav(body: bytes) -> tuple[int, int, np.ndarray]:
    with wave.open(io.BytesIO(body), "rb") as wav:
        frames = np.frombuffer(wav.readframes(wav.getnframes()), "<i2")
        return wav.getnchannels(), wav.getframerate(), frames


def test_a_track_is_served_whole_as_a_wav(api: Api, recorded: str) -> None:
    response = api.client.get(f"/sessions/{recorded}/audio/mic")

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == str(SIZE)
    channels, rate, frames = _wav(response.content)
    assert (channels, rate) == (1, RATE)
    assert frames.tolist() == to_pcm16(MIC).tolist()


def test_the_mixed_track_is_mixed_on_the_fly(api: Api, recorded: str) -> None:
    response = api.client.get(f"/sessions/{recorded}/audio/mixed")

    channels, _, frames = _wav(response.content)
    assert channels == 2  # stereo: mic left, system right
    assert frames[0::2].tolist() == to_pcm16(MIC).tolist()
    assert frames[1::2][:1200].tolist() == to_pcm16(SYSTEM).tolist()
    assert not frames[1::2][1200:].any()  # the shorter channel is padded


@pytest.mark.parametrize(
    ("header", "first", "last"),
    [
        ("bytes=0-99", 0, 99),  # the start, across the header
        ("bytes=1001-2002", 1001, 2002),  # the middle, odd offsets
        ("bytes=5000-", 5000, SIZE - 1),  # open-ended
        ("bytes=-11", SIZE - 11, SIZE - 1),  # the last bytes
        ("bytes=10-999999", 10, SIZE - 1),  # clipped to the end
    ],
)
def test_ranges_give_206_with_exactly_the_bytes_asked(
    api: Api, recorded: str, header: str, first: int, last: int
) -> None:
    whole = api.client.get(f"/sessions/{recorded}/audio/mic").content

    response = api.client.get(f"/sessions/{recorded}/audio/mic", headers={"Range": header})

    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes {first}-{last}/{SIZE}"
    assert response.headers["content-length"] == str(last - first + 1)
    assert response.content == whole[first : last + 1]


@pytest.mark.parametrize(
    "header", ["bytes=2444-", "bytes=20-10", "bytes=-0", "bytes=-", "lines=0-1", "bytes=0-1,4-5"]
)
def test_unsatisfiable_ranges_give_416(api: Api, recorded: str, header: str) -> None:
    response = api.client.get(f"/sessions/{recorded}/audio/system", headers={"Range": header})

    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{44 + 1200 * 2}"


@pytest.mark.parametrize("path", ["20991231_000000/audio/mic", "nope/audio/mic"])
def test_an_unknown_session_is_404(api: Api, recorded: str, path: str) -> None:
    response = api.client.get(f"/sessions/{path}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"


def test_an_unknown_track_is_404(api: Api, recorded: str) -> None:
    response = api.client.get(f"/sessions/{recorded}/audio/speakers")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "audio_not_found"
    assert "speakers" in response.json()["error"]["message"]


def test_a_session_without_audio_is_404(api: Api, recorded: str, database: Database) -> None:
    with database.write() as db:
        db.execute("DELETE FROM audio_chunks")

    response = api.client.get(f"/sessions/{recorded}/audio/mixed")

    assert response.status_code == 404
    assert api.client.get(f"/sessions/{recorded}").json()["audio"] == {}


def test_without_an_audio_store_every_track_is_404(api: Api, store_session: str) -> None:
    response = api.client.get(f"/sessions/{store_session}/audio/mic")

    assert response.status_code == 404


def test_the_detail_lists_the_tracks_with_their_durations_and_no_folder(
    api: Api, recorded: str
) -> None:
    detail = api.client.get(f"/sessions/{recorded}").json()

    assert detail["audio"] == {"mic": 2.5, "system": 1.2, "mixed": 2.5}
    assert detail["folder"] is None
    assert detail["files"] is None


@pytest.fixture
def store_session(api: Api) -> str:
    """A file-backend session in the default API container (which has no audio store)."""
    session_id = api.store.create(datetime(2026, 10, 15, 20, 23, 58))
    api.store.write_meta(session_id, {"id": session_id, "status": "done"})
    return session_id


def test_deleting_a_session_drops_its_audio_and_cached_wavs(
    api: Api, recorded: str, database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = api.app.state.container.audio
    cached = audio.materialize_wav(recorded, Channel.SYSTEM)
    reclaimed = threading.Event()
    monkeypatch.setattr(database, "reclaim", reclaimed.set)
    container = api.app.state.container
    monkeypatch.setattr(container.manager, "_store", container.store)  # the SQLite repository
    api.app.state.container = dataclasses.replace(container, search_index=None)

    response = api.client.delete(f"/sessions/{recorded}")

    assert response.status_code == 204
    assert database.connection().execute("SELECT COUNT(*) FROM audio_chunks").fetchone() == (0,)
    assert not cached.exists()
    assert reclaimed.wait(5)
    assert api.client.get(f"/sessions/{recorded}/audio/mic").status_code == 404


def test_deleting_the_audio_keeps_the_session_and_reclaims_the_space(
    api: Api, recorded: str, database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    cached = api.app.state.container.audio.materialize_wav(recorded, Channel.MIC)
    reclaimed = threading.Event()
    monkeypatch.setattr(database, "reclaim", reclaimed.set)
    monkeypatch.setattr(api.manager, "_store", api.app.state.container.store)

    response = api.client.delete(f"/sessions/{recorded}/audio")

    assert response.status_code == 204
    assert database.connection().execute("SELECT COUNT(*) FROM audio_chunks").fetchone() == (0,)
    assert not cached.exists()
    assert reclaimed.wait(5)
    detail = api.client.get(f"/sessions/{recorded}").json()
    assert (detail["status"], detail["audio"]) == ("done", {})
    assert api.client.get(f"/sessions/{recorded}/audio/mixed").status_code == 404


def test_deleting_the_audio_of_an_unknown_session_is_404(api: Api, recorded: str) -> None:
    response = api.client.delete("/sessions/20991231_000000/audio")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"


def test_deleting_audio_that_is_not_there_is_404(api: Api, store_session: str) -> None:
    response = api.client.delete(f"/sessions/{store_session}/audio")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "no_audio"


def test_deleting_the_audio_of_the_session_being_recorded_is_409(api: Api) -> None:
    session_id = api.client.post("/sessions", json={}).json()["id"]

    response = api.client.delete(f"/sessions/{session_id}/audio")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "session_still_active"


def test_deleting_the_audio_of_a_queued_session_is_409(api: Api, recorded: str) -> None:
    release = hold_in_queue(api.manager, recorded)

    response = api.client.delete(f"/sessions/{recorded}/audio")

    release.set()
    assert api.manager._queue.wait_idle(5)
    assert response.status_code == 409
