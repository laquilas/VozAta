"""Hugging Face `ModelDownloader`: ensures a repo snapshot is cached, reporting byte progress.

huggingface_hub 2.2.0's `snapshot_download(tqdm_class=...)` creates two byte bars (`unit="B"`):
"transfer" (network bytes) and "reconstruct" (bytes written to disk). Over plain HTTP both get
every chunk, so summing them would count each byte twice; the counter reports the furthest of
the byte bars instead. The per-file count bar `hf_thread_map` creates (no unit) is ignored.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vozata.domain import ModelKind
from vozata.models.tracker import DownloadHandle, DownloadTracker

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

    def ensure(
        self,
        kind: ModelKind,
        repo_id: str,
        *,
        allow_patterns: Sequence[str] | None = None,
        token: str | None = None,
        name: str | None = None,
    ) -> Path:
        from huggingface_hub.errors import LocalEntryNotFoundError

        hub = self._hub or _default_hub()
        patterns = list(allow_patterns) if allow_patterns is not None else None
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


def byte_counter(handle: DownloadHandle) -> type:
    """A tqdm-compatible class that forwards the downloaded bytes to `handle`."""
    lock = threading.Lock()
    byte_bars: list[_Bar] = []
    reported = [0]

    class _Bar:
        def __init__(
            self, *args: Any, total: Any = None, initial: Any = 0, unit: str = "it", **kwargs: Any
        ) -> None:
            self.total = total
            self.unit = unit
            self.n = 0
            self.format_dict: dict[str, Any] = {}
            if unit == "B":
                with lock:
                    byte_bars.append(self)
            self.update(initial)

        def update(self, n: float | None = 1) -> None:
            if not n:
                return
            with lock:
                self.n += int(n)
                if self.unit != "B":
                    return
                gain = max(bar.n for bar in byte_bars) - reported[0]
                if gain <= 0:
                    return
                reported[0] += gain
            handle.advance(gain)

        def __enter__(self) -> _Bar:
            return self

        def __exit__(self, *exc: object) -> None:
            self.close()

        def close(self) -> None:
            pass

        def refresh(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_description(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_description_str(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set_postfix_str(self, *args: Any, **kwargs: Any) -> None:
            pass

    return _Bar
