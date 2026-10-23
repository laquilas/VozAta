"""Phase 42: faster-whisper models come from the `ModelDownloader`, then load from its folder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.fakes import FakeModelDownloader
from vozata.config import Settings
from vozata.domain import ModelKind, WhisperDevice
from vozata.transcription.faster_whisper import (
    WHISPER_FILES,
    FasterWhisperTranscriber,
    whisper_repo,
)


class _Model:
    def transcribe(self, audio: np.ndarray, **kwargs: Any) -> tuple[Any, None]:
        return iter(()), None


class _Factory:
    def __init__(self, cuda_fails: bool = False) -> None:
        self.cuda_fails = cuda_fails
        self.loaded: list[tuple[str, str]] = []

    def __call__(self, path: str, device: str, compute_type: str) -> _Model:
        self.loaded.append((path, device))
        if device == "cuda" and self.cuda_fails:
            raise RuntimeError("Library cublas64_12.dll is not found")
        return _Model()


@pytest.mark.parametrize(
    ("name", "repo"),
    [
        ("large-v3-turbo", "mobiuslabsgmbh/faster-whisper-large-v3-turbo"),
        ("small", "Systran/faster-whisper-small"),
        ("large-v3", "Systran/faster-whisper-large-v3"),
        ("org/custom-ct2", "org/custom-ct2"),  # a name with "/" is a repo id
    ],
)
def test_whisper_repo_follows_faster_whispers_mapping(name: str, repo: str) -> None:
    assert whisper_repo(name) == repo


def test_an_unknown_whisper_size_is_rejected() -> None:
    with pytest.raises(ValueError, match="Invalid model size 'huge'"):
        whisper_repo("huge")


def test_whisper_files_match_faster_whisper_1_2_1() -> None:
    assert WHISPER_FILES == (
        "config.json",
        "preprocessor_config.json",
        "model.bin",
        "tokenizer.json",
        "vocabulary.*",
    )


def test_whisper_loads_from_the_downloaded_folder() -> None:
    downloader = FakeModelDownloader(Path("hub"))
    factory = _Factory()

    transcriber = FasterWhisperTranscriber(
        Settings(whisper_device=WhisperDevice.CUDA), downloader, model_factory=factory
    )

    assert transcriber.device == "cuda"
    assert downloader.calls == [
        {
            "kind": ModelKind.SPEECH,
            "repo_id": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
            "allow_patterns": WHISPER_FILES,
            "token": None,
            "name": "large-v3-turbo",
        }
    ]
    expected = str(Path("hub") / "mobiuslabsgmbh/faster-whisper-large-v3-turbo")
    assert factory.loaded == [(expected, "cuda")]


def test_whisper_cpu_fallback_downloads_its_own_repo() -> None:
    downloader = FakeModelDownloader(Path("hub"))
    factory = _Factory(cuda_fails=True)

    transcriber = FasterWhisperTranscriber(
        Settings(whisper_device=WhisperDevice.AUTO), downloader, model_factory=factory
    )

    assert transcriber.device == "cpu"
    assert [(call["repo_id"], call["name"]) for call in downloader.calls] == [
        ("mobiuslabsgmbh/faster-whisper-large-v3-turbo", "large-v3-turbo"),
        ("Systran/faster-whisper-small", "small"),
    ]
    assert factory.loaded[-1] == (str(Path("hub") / "Systran/faster-whisper-small"), "cpu")


def test_cpu_device_downloads_only_the_cpu_model() -> None:
    downloader = FakeModelDownloader(Path("hub"))

    FasterWhisperTranscriber(
        Settings(whisper_device=WhisperDevice.CPU), downloader, model_factory=_Factory()
    )

    assert [call["repo_id"] for call in downloader.calls] == ["Systran/faster-whisper-small"]


def test_existing_model_folder_skips_the_downloader(tmp_path: Path) -> None:
    downloader = FakeModelDownloader()
    factory = _Factory()

    FasterWhisperTranscriber(
        Settings(whisper_device=WhisperDevice.CUDA, whisper_model=str(tmp_path)),
        downloader,
        model_factory=factory,
    )

    assert downloader.calls == []
    assert factory.loaded == [(str(tmp_path), "cuda")]


def test_a_failed_download_on_cuda_propagates() -> None:
    downloader = FakeModelDownloader(error=OSError("network down"))

    with pytest.raises(OSError, match="network down"):
        FasterWhisperTranscriber(
            Settings(whisper_device=WhisperDevice.CUDA), downloader, model_factory=_Factory()
        )


def test_auto_without_cuda_libraries_goes_to_the_cpu_without_the_gpu_model() -> None:
    downloader = FakeModelDownloader(Path("hub"))
    factory = _Factory()

    transcriber = FasterWhisperTranscriber(
        Settings(whisper_device=WhisperDevice.AUTO),
        downloader,
        model_factory=factory,
        cuda_libraries=lambda: False,
    )

    assert transcriber.device == "cpu"
    assert [call["name"] for call in downloader.calls] == ["small"]
    assert [device for _, device in factory.loaded] == ["cpu"]


def test_cuda_asked_for_explicitly_is_still_tried_without_the_libraries() -> None:
    factory = _Factory()

    transcriber = FasterWhisperTranscriber(
        Settings(whisper_device=WhisperDevice.CUDA),
        FakeModelDownloader(Path("hub")),
        model_factory=factory,
        cuda_libraries=lambda: False,
    )

    assert transcriber.device == "cuda"


@pytest.mark.parametrize(
    ("found", "packaged", "expected"),
    [(True, True, True), (False, True, False), (False, False, True)],
)
def test_only_the_packaged_engine_without_cuda_folders_skips_the_gpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, found: bool, packaged: bool, expected: bool
) -> None:
    from vozata.transcription import faster_whisper

    seen: list[list[Path]] = []

    def register(site_dirs: object = None, extra: list[Path] = ()) -> bool:  # type: ignore[assignment]
        seen.append(list(extra))
        return found

    monkeypatch.setattr(faster_whisper, "register_cuda_dlls", register)
    monkeypatch.setattr(faster_whisper, "packaged", lambda: packaged)

    assert faster_whisper._cuda_libraries(Settings(cuda_runtime_dir=tmp_path)) is expected
    assert seen == [[tmp_path]]
