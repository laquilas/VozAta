"""Hugging Face `ModelDownloader`: ensures a repo snapshot is cached, reporting byte progress.

The bytes are counted by `byte_counter` (`models/byte_counter.py`). Concurrent `ensure()` calls for
the same repo and file patterns share one download (one tracker handle): the later callers wait
for the first and get its folder or its error.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vozata.domain import ModelKind
from vozata.models.byte_counter import byte_counter
from vozata.models.tracker import DownloadTracker

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class HubFunctions:
    """The huggingface_hub calls the downloader makes (injectable: tests never hit the network)."""

    snapshot_download: Callable[..., str]
    model_info: Callable[..., Any]
    cached_file: Callable[..., Any]  # `try_to_load_from_cache`: a path when cached (no network)


def _default_hub() -> HubFunctions:  # pragma: no cover - the real hub
    from huggingface_hub import model_info, snapshot_download, try_to_load_from_cache

    return HubFunctions(
        snapshot_download=snapshot_download,
        model_info=model_info,
        cached_file=try_to_load_from_cache,
    )


@dataclass
class _Flight:
    """One `ensure()` in progress; the callers that join it wait for its outcome."""

    finished: threading.Event = field(default_factory=threading.Event)
    folder: Path | None = None
    error: BaseException | None = None

    def outcome(self) -> Path:
        self.finished.wait()
        if self.error is not None:
            raise self.error
        assert self.folder is not None
        return self.folder


class HubDownloader:
    """Returns cached snapshots untouched; otherwise downloads them with progress events.

    `offline` (`HF_HUB_OFFLINE=1`) never downloads: the cache check's error propagates.
    """

    def __init__(
        self, tracker: DownloadTracker, offline: bool, hub: HubFunctions | None = None
    ) -> None:
        self._tracker = tracker
        self._offline = offline
        self._hub = hub
        self._lock = threading.Lock()
        self._flights: dict[tuple[str, tuple[str, ...] | None], _Flight] = {}

    def ensure(
        self,
        kind: ModelKind,
        repo_id: str,
        *,
        allow_patterns: Sequence[str] | None = None,
        token: str | None = None,
        name: str | None = None,
    ) -> Path:
        patterns = list(allow_patterns) if allow_patterns is not None else None
        key = (repo_id, tuple(patterns) if patterns is not None else None)
        with self._lock:
            flight = self._flights.get(key)
            if flight is not None:
                joined = True
            else:
                joined = False
                flight = self._flights[key] = _Flight()
        if joined:
            return flight.outcome()
        try:
            flight.folder = self._ensure(kind, repo_id, patterns, token, name)
            return flight.folder
        except BaseException as error:
            flight.error = error
            raise
        finally:
            with self._lock:
                del self._flights[key]
            flight.finished.set()

    def _ensure(
        self,
        kind: ModelKind,
        repo_id: str,
        patterns: list[str] | None,
        token: str | None,
        name: str | None,
    ) -> Path:
        from huggingface_hub.errors import LocalEntryNotFoundError

        hub = self._hub or _default_hub()
        try:
            return Path(
                hub.snapshot_download(
                    repo_id, allow_patterns=patterns, local_files_only=True, token=token
                )
            )
        except LocalEntryNotFoundError:  # includes IncompleteSnapshotError
            if self._offline:
                raise
        total = _total_bytes(hub, repo_id, patterns, token)
        handle = self._tracker.start(kind, name or repo_id, total)
        try:
            folder = hub.snapshot_download(
                repo_id,
                allow_patterns=patterns,
                local_files_only=False,
                token=token,
                tqdm_class=byte_counter(handle),
            )
        except BaseException as error:
            handle.failed(str(error) or type(error).__name__)
            raise
        handle.done()
        return Path(folder)


def _total_bytes(
    hub: HubFunctions, repo_id: str, patterns: list[str] | None, token: str | None
) -> int | None:
    """The size of the files still to download, or None when any of them is unknown.

    Files of a partly cached snapshot are left out, so the bar reaches 100 %.
    """
    from huggingface_hub.utils import filter_repo_objects

    try:
        info = hub.model_info(repo_id, files_metadata=True, token=token)
    except Exception as error:  # the download itself reports a real failure
        _log.info("Size of %s unknown: %s", repo_id, error)
        return None
    siblings = info.siblings or []
    wanted = filter_repo_objects(siblings, allow_patterns=patterns, key=lambda s: s.rfilename)
    sizes = [
        sibling.size
        for sibling in wanted
        if not isinstance(hub.cached_file(repo_id, sibling.rfilename, revision=info.sha), str)
    ]
    return None if any(size is None for size in sizes) else sum(sizes)
