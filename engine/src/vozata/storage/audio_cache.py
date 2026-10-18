"""`WavCache`: WAV files built on demand from stored audio (phase 32), `OUTPUT_DIR/cache/`.

Tools that need a file (the diarizer child process) get `cache/<id>/<track>.wav`, written
atomically. The cache is kept under `AUDIO_CACHE_MB`: the least recently used files go first
(each use touches the file), the file just built is always kept.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

from vozata.audio.pcm import wav_size, write_wav
from vozata.ports import PcmTrack

_log = logging.getLogger(__name__)


class WavCache:
    def __init__(self, root: Path, limit_bytes: int) -> None:
        self._root = root
        self._limit = limit_bytes

    @property
    def root(self) -> Path:
        return self._root

    def wav(self, session_id: str, name: str, track: PcmTrack) -> Path:
        """`cache/<session_id>/<name>.wav` holding `track`, reused while its size matches."""
        path = self._root / session_id / f"{name}.wav"
        if path.is_file() and path.stat().st_size == wav_size(track):
            os.utime(path)  # last access, for the LRU order
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=f".{name}-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(handle, "wb") as out:
                write_wav(track, out)
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        self.clean(keep=path)
        return path

    def size(self) -> int:
        """Bytes used by the cache."""
        return sum(path.stat().st_size for path in self._files())

    def drop(self, session_id: str) -> None:
        """Remove every cached file of a session (it was deleted)."""
        shutil.rmtree(self._root / session_id, ignore_errors=True)

    def clean(self, keep: Path | None = None) -> None:
        """Delete the least recently used files until the cache fits its limit; leftovers of
        an interrupted write go too. A file in use (Windows) is skipped."""
        files = []
        for path in self._files():
            if path.suffix == ".tmp":
                _remove(path)
            else:
                files.append((path.stat().st_mtime, path))
        total = sum(path.stat().st_size for _, path in files)
        for _, path in sorted(files):
            if total <= self._limit:
                break
            if path == keep:
                continue
            size = path.stat().st_size
            if _remove(path):
                total -= size
        for folder in self._root.iterdir() if self._root.is_dir() else ():
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()

    def _files(self) -> list[Path]:
        if not self._root.is_dir():
            return []
        return [path for path in self._root.glob("*/*") if path.is_file()]


def _remove(path: Path) -> bool:
    try:
        path.unlink()
    except OSError as error:
        _log.debug("Keeping the cached %s: %s", path, error)
        return False
    return True
