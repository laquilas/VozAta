from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from huggingface_hub.errors import LocalEntryNotFoundError

from vozata.domain import ModelKind
from vozata.models import download as download_module
from vozata.models.download import HubDownloader, HubFunctions
from vozata.models.tracker import DownloadState, DownloadTracker
from vozata.ports import ModelDownloader

SNAPSHOT = "C:/cache/models--org--repo/snapshots/abc"


@dataclass
class Sibling:
    rfilename: str
    size: int | None


@dataclass
class Info:
    siblings: list[Sibling]
    sha: str = "abc"


class FakeHub:
    """Mimics huggingface_hub 2.2.0's `snapshot_download` progress calls (`_snapshot_download.py`):
    two byte bars (transfer + reconstruct) whose totals grow per file, a per-file count bar from
    `hf_thread_map`, every chunk reported to BOTH byte bars, then the transfer bar snapped."""

    def __init__(
        self,
        files: Mapping[str, Sequence[int]],
        *,
        cached: bool = False,
        sizes: Mapping[str, int | None] | None = None,
        error: Exception | None = None,
        in_cache: Sequence[str] = (),
    ) -> None:
        self.files = files
        self.in_cache = set(in_cache)  # files of a partly cached snapshot
        self.cache_calls: list[tuple[str, str, str | None]] = []
        self.cached = cached
        self.sizes = sizes
        self.error = error
        self.calls: list[dict[str, Any]] = []
        self.info_calls: list[dict[str, Any]] = []

    def hub(self) -> HubFunctions:
        return HubFunctions(
            snapshot_download=self.snapshot_download,
            model_info=self.model_info,
            cached_file=self.cached_file,
        )

    def cached_file(self, repo_id: str, filename: str, revision: str | None = None) -> Any:
        self.cache_calls.append((repo_id, filename, revision))
        return f"{SNAPSHOT}/{filename}" if filename in self.in_cache else None

    def model_info(self, repo_id: str, **kwargs: Any) -> Info:
        self.info_calls.append({"repo_id": repo_id, **kwargs})
        sizes = self.sizes or {name: sum(chunks) for name, chunks in self.files.items()}
        return Info([Sibling(name, size) for name, size in sizes.items()])

    def snapshot_download(self, repo_id: str, **kwargs: Any) -> str:
        self.calls.append({"repo_id": repo_id, **kwargs})
        if kwargs.get("local_files_only"):
            if self.cached:
                return SNAPSHOT
            raise LocalEntryNotFoundError("not cached")
        bar = kwargs["tqdm_class"]
        transfer = bar(desc="Downloading bytes", total=0, initial=0, unit="B", unit_scale=True)
        reconstruct = bar(desc="Reconstructing", total=0, initial=0, unit="B", unit_scale=True)
        with bar(desc=f"Fetching {len(self.files)} files", total=len(self.files)) as count:
            for chunks in self.files.values():
                reconstruct.total = (reconstruct.total or 0) + sum(chunks)
                transfer.total = (transfer.total or 0) + sum(chunks)
                reconstruct.refresh()
                for chunk in chunks:
                    if self.error is not None:
                        raise self.error
                    reconstruct.update(chunk)
                    if transfer.total < transfer.n + chunk:  # `_update_transfer_bar`
                        transfer.total = int((transfer.n + chunk) * 1.25) + 1
                    transfer.update(chunk)
                count.update(1)
        transfer.total = transfer.n  # `_finish_transfer_bar`
        transfer.refresh()
        transfer.set_description_str("Download complete")
        reconstruct.set_description("Reconstruction complete")
        return SNAPSHOT


def _downloader(
    fake: FakeHub, *, offline: bool = False
) -> tuple[HubDownloader, list[DownloadState]]:
    events: list[DownloadState] = []
    tracker = DownloadTracker(events.append, clock=lambda: 0.0, interval=0.0)
    return HubDownloader(tracker, offline, hub=fake.hub()), events


def test_hub_downloader_is_a_model_downloader() -> None:
    downloader, _ = _downloader(FakeHub({}))

    assert isinstance(downloader, ModelDownloader)


def test_cached_repo_returns_its_path_without_network_or_events() -> None:
    fake = FakeHub({"model.bin": [10]}, cached=True)
    downloader, events = _downloader(fake)

    folder = downloader.ensure(
        ModelKind.SPEECH, "org/repo", allow_patterns=["*.bin"], token="secret"
    )

    assert folder == Path(SNAPSHOT)
    assert fake.calls == [
        {
            "repo_id": "org/repo",
            "allow_patterns": ["*.bin"],
            "local_files_only": True,
            "token": "secret",
        }
    ]
    assert fake.info_calls == []
    assert events == []


def test_offline_does_not_download_and_propagates_the_hub_error() -> None:
    fake = FakeHub({"model.bin": [10]})
    downloader, events = _downloader(fake, offline=True)

    with pytest.raises(LocalEntryNotFoundError):
        downloader.ensure(ModelKind.SPEECH, "org/repo")

    assert [call["local_files_only"] for call in fake.calls] == [True]
    assert fake.info_calls == []
    assert events == []


def test_download_reports_running_then_done_with_bytes_and_total() -> None:
    fake = FakeHub({"config.json": [100], "model.bin": [1000, 1000]})
    downloader, events = _downloader(fake)

    folder = downloader.ensure(ModelKind.SPEECH, "org/repo", token="secret")

    assert folder == Path(SNAPSHOT)
    online = fake.calls[1]
    assert (online["local_files_only"], online["token"]) == (False, "secret")
    assert fake.info_calls == [{"repo_id": "org/repo", "files_metadata": True, "token": "secret"}]
    assert [(e.state, e.downloaded_bytes) for e in events] == [
        ("running", 0),
        ("running", 100),
        ("running", 1100),
        ("running", 2100),
        ("done", 2100),  # bytes from one stream only: the transfer bar is not counted twice
    ]
    assert {(e.kind, e.model, e.total_bytes) for e in events} == {
        (ModelKind.SPEECH, "org/repo", 2100)
    }


def test_total_counts_only_files_matching_allow_patterns() -> None:
    fake = FakeHub(
        {"model.bin": [500]},
        sizes={"model.bin": 500, "README.md": 7, "sub/vocab.json": 30, "pytorch.pt": 9000},
    )
    downloader, events = _downloader(fake)

    downloader.ensure(ModelKind.TRANSLATION, "org/repo", allow_patterns=("*.bin", "*.json"))

    assert events[0].total_bytes == 530
    assert fake.calls[1]["allow_patterns"] == ["*.bin", "*.json"]


def test_total_excludes_files_already_in_the_cache() -> None:
    fake = FakeHub(
        {"model.bin": [500]},
        sizes={"config.json": 20, "model.bin": 500, "vocabulary.json": 30},
        in_cache=("config.json", "vocabulary.json"),
    )
    downloader, events = _downloader(fake)

    downloader.ensure(ModelKind.SPEECH, "org/repo")

    assert {e.total_bytes for e in events} == {500}
    assert (events[-1].state, events[-1].downloaded_bytes) == ("done", 500)  # reaches 100 %
    assert ("org/repo", "model.bin", "abc") in fake.cache_calls  # the snapshot's revision


def test_name_is_the_model_shown_in_the_events() -> None:
    fake = FakeHub({"model.bin": [10]})
    downloader, events = _downloader(fake)

    downloader.ensure(ModelKind.SPEECH, "org/faster-whisper-small", name="small")

    assert {e.model for e in events} == {"small"}


def test_unknown_total_is_reported_as_none() -> None:
    fake = FakeHub({"a.bin": [5], "b.bin": [5]}, sizes={"a.bin": 5, "b.bin": None})
    downloader, events = _downloader(fake)

    downloader.ensure(ModelKind.SPEAKERS, "org/repo")

    assert {e.total_bytes for e in events} == {None}
    assert events[-1].downloaded_bytes == 10


def test_model_info_failure_leaves_the_total_unknown() -> None:
    fake = FakeHub({"a.bin": [5]})

    def broken_info(repo_id: str, **kwargs: Any) -> Info:
        raise OSError("no metadata")

    events: list[DownloadState] = []
    tracker = DownloadTracker(events.append, clock=lambda: 0.0, interval=0.0)
    hub = HubFunctions(
        snapshot_download=fake.snapshot_download,
        model_info=broken_info,
        cached_file=fake.cached_file,
    )

    HubDownloader(tracker, False, hub=hub).ensure(ModelKind.SPEECH, "org/repo")

    assert [(e.state, e.total_bytes) for e in events][-1] == ("done", None)


def test_failure_reports_failed_with_the_reason_and_reraises() -> None:
    fake = FakeHub({"model.bin": [10]}, error=ConnectionError("network down"))
    downloader, events = _downloader(fake)

    with pytest.raises(ConnectionError, match="network down"):
        downloader.ensure(ModelKind.SPEECH, "org/repo")

    assert events[-1].state == "failed"
    assert events[-1].to_payload()["reason"] == "network down"
    assert downloader._tracker.running() == []


def test_failure_without_a_message_reports_the_error_type() -> None:
    fake = FakeHub({"model.bin": [10]}, error=TimeoutError())
    downloader, events = _downloader(fake)

    with pytest.raises(TimeoutError):
        downloader.ensure(ModelKind.SPEECH, "org/repo")

    assert events[-1].reason == "TimeoutError"


def test_byte_counter_handles_initial_bytes_and_empty_updates() -> None:
    events: list[DownloadState] = []
    tracker = DownloadTracker(events.append, clock=lambda: 0.0, interval=0.0)
    seen: dict[str, Any] = {}

    def snapshot_download(repo_id: str, **kwargs: Any) -> str:
        if kwargs["local_files_only"]:
            raise LocalEntryNotFoundError("not cached")
        bar = kwargs["tqdm_class"]("ignored positional", unit="B", total=10, initial=4)
        bar.update(None)
        bar.update(0)
        bar.update(2.0)
        bar.set_postfix_str("1 MB/s", refresh=False)
        seen["rate"] = bar.format_dict.get("rate")
        bar.close()
        return SNAPSHOT

    empty = FakeHub({})
    hub = HubFunctions(
        snapshot_download=snapshot_download,
        model_info=empty.model_info,
        cached_file=empty.cached_file,
    )
    HubDownloader(tracker, False, hub=hub).ensure(ModelKind.SPEECH, "org/repo")

    assert [e.downloaded_bytes for e in events] == [0, 4, 6, 6]
    assert seen["rate"] is None


class GatedHub(FakeHub):
    """A FakeHub whose real download waits for `release` (to overlap two `ensure()` calls)."""

    def __init__(self, files: Mapping[str, Sequence[int]], **kwargs: Any) -> None:
        super().__init__(files, **kwargs)
        self.downloading = threading.Event()
        self.release = threading.Event()

    def snapshot_download(self, repo_id: str, **kwargs: Any) -> str:
        if not kwargs.get("local_files_only") and kwargs["allow_patterns"] == ["*.bin"]:
            self.downloading.set()
            assert self.release.wait(5)
        return super().snapshot_download(repo_id, **kwargs)


def _overlap(
    fake: GatedHub, monkeypatch: pytest.MonkeyPatch, second_patterns: list[str]
) -> tuple[list[DownloadState], list[object]]:
    """Runs two `ensure()` calls, the second starting while the first downloads."""
    downloader, events = _downloader(fake)
    joined = threading.Event()
    outcome = download_module._Flight.outcome

    def joining(flight: Any) -> Path:
        joined.set()
        return outcome(flight)

    monkeypatch.setattr(download_module._Flight, "outcome", joining)
    results: list[object] = [None, None]

    def call(index: int, patterns: list[str]) -> None:
        try:
            results[index] = downloader.ensure(
                ModelKind.SPEECH, "org/repo", allow_patterns=patterns
            )
        except Exception as error:
            results[index] = error

    first = threading.Thread(target=call, args=(0, ["*.bin"]), daemon=True)
    first.start()
    assert fake.downloading.wait(5)
    second = threading.Thread(target=call, args=(1, second_patterns), daemon=True)
    second.start()
    if second_patterns == ["*.bin"]:
        assert joined.wait(5)
    else:  # a different download runs on its own while the first one still waits
        second.join(5)
        assert not second.is_alive() and not fake.release.is_set()
    fake.release.set()
    first.join(5)
    second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert downloader._flights == {}
    return events, results


def test_concurrent_ensures_of_the_same_repo_share_one_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = GatedHub({"model.bin": [10]})

    events, results = _overlap(fake, monkeypatch, ["*.bin"])

    assert results == [Path(SNAPSHOT), Path(SNAPSHOT)]
    assert len([call for call in fake.calls if not call["local_files_only"]]) == 1
    assert [e.state for e in events if e.state != "running"] == ["done"]
    assert len([e for e in events if e.downloaded_bytes == 0]) == 1  # one bar, never back to 0


def test_a_joined_ensure_gets_the_first_ones_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = GatedHub({"model.bin": [10]}, error=ConnectionError("network down"))

    events, results = _overlap(fake, monkeypatch, ["*.bin"])

    assert [type(result) for result in results] == [ConnectionError, ConnectionError]
    assert results[0] is results[1]
    assert [e.state for e in events].count("failed") == 1


def test_other_file_patterns_download_on_their_own(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = GatedHub({"model.bin": [10]})

    events, results = _overlap(fake, monkeypatch, ["*.json"])

    assert results == [Path(SNAPSHOT), Path(SNAPSHOT)]
    assert [e.state for e in events].count("done") == 2
