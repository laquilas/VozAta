from __future__ import annotations

import io
import json
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.fakes import FakeDiarizer
from vozata.config import ConfigError, Settings
from vozata.diarization import child
from vozata.diarization.pyannote import PyannoteDiarizer, read_wav, turns_from_tracks
from vozata.diarization.subprocess_diarizer import SubprocessDiarizer, pyannote_from_settings
from vozata.domain import SpeakerTurn, WhisperDevice
from vozata.ports import DiarizationError, Diarizer


class _Child:
    """Stands in for `subprocess.run`: runs `child.main` in-process with a fake diarizer."""

    def __init__(self, diarizer: FakeDiarizer) -> None:
        self.diarizer = diarizer
        self.built: list[tuple[str, WhisperDevice]] = []
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def build(self, token: str, device: WhisperDevice) -> FakeDiarizer:
        self.built.append((token, device))
        return self.diarizer

    def __call__(self, command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((command, options))
        stderr = io.StringIO()
        code = child.main(io.StringIO(options["input"]), stderr, self.build)
        return subprocess.CompletedProcess(command, code, "", stderr.getvalue())


def test_turns_come_back_from_the_child_and_the_token_is_not_in_the_command(
    tmp_path: Path,
) -> None:
    fake = _Child(FakeDiarizer([SpeakerTurn(0.0, 1.5, 0), SpeakerTurn(1.5, 3.0, 1)]))
    diarizer = SubprocessDiarizer(
        "hf_secret", WhisperDevice.CPU, command=["py", "-m", "x"], run=fake
    )

    turns = diarizer.diarize(tmp_path / "system.wav", 2, None)
    diarizer.close()

    assert turns == [SpeakerTurn(0.0, 1.5, 0), SpeakerTurn(1.5, 3.0, 1)]
    assert fake.built == [("hf_secret", WhisperDevice.CPU)]
    assert fake.diarizer.calls == [(tmp_path / "system.wav", 2, None)]
    assert fake.diarizer.closed
    [(command, options)] = fake.calls
    assert command == ["py", "-m", "x"]
    assert "hf_secret" not in " ".join(command)
    assert options["check"] is False and options["capture_output"] is True


def test_a_failing_child_raises_with_its_last_stderr_line(tmp_path: Path) -> None:
    fake = _Child(FakeDiarizer(error=RuntimeError("401 gated model")))
    diarizer = SubprocessDiarizer("hf", WhisperDevice.AUTO, run=fake)

    with pytest.raises(DiarizationError, match="RuntimeError: 401 gated model"):
        diarizer.diarize(tmp_path / "system.wav", None, None)

    assert fake.diarizer.closed


def test_a_child_that_dies_silently_reports_its_exit_code(tmp_path: Path) -> None:
    def run(command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 3, "", "\n")

    with pytest.raises(DiarizationError, match="exit 3"):
        SubprocessDiarizer("hf", WhisperDevice.AUTO, run=run).diarize(tmp_path / "a.wav", 1, 2)


@pytest.mark.parametrize("output", [None, "not json", '{"rows": []}', '{"turns": [[1, 2]]}'])
def test_missing_or_malformed_output_is_a_diarization_error(
    tmp_path: Path, output: str | None
) -> None:
    def run(command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        if output is not None:
            Path(json.loads(options["input"])["output"]).write_text(output, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    with pytest.raises(DiarizationError, match="unreadable"):
        SubprocessDiarizer("hf", WhisperDevice.AUTO, run=run).diarize(tmp_path / "a.wav", 1, 2)


def test_a_bad_request_makes_the_child_fail() -> None:
    stderr = io.StringIO()

    assert child.main(io.StringIO("{}"), stderr, lambda token, device: FakeDiarizer()) == 1
    assert "KeyError" in stderr.getvalue()


def test_the_real_child_process_runs_without_the_extra(tmp_path: Path) -> None:
    """A real `python -m vozata.diarization.child` fails cleanly on a missing WAV (no download)."""
    diarizer = SubprocessDiarizer("hf", WhisperDevice.CPU)

    with pytest.raises(DiarizationError, match="missing.wav"):
        diarizer.diarize(tmp_path / "missing.wav", None, None)


def test_the_pyannote_provider_needs_a_token() -> None:
    with pytest.raises(ConfigError) as caught:
        pyannote_from_settings(Settings())

    assert (caught.value.key, caught.value.message_key) == ("HF_TOKEN", "missing_hf_token")
    diarizer = pyannote_from_settings(Settings(hf_token="hf", diarization_device=WhisperDevice.CPU))
    assert isinstance(diarizer, Diarizer)


def test_tracks_become_turns_in_time_order_numbered_by_first_turn() -> None:
    tracks = [
        (5.0, 6.0, "SPEAKER_00"),
        (0.5, 2.0, "SPEAKER_03"),
        (2.0, 2.0, "X"),
        (3.0, 4.12345, "SPEAKER_00"),
    ]

    assert turns_from_tracks(tracks) == [
        SpeakerTurn(0.5, 2.0, 0),
        SpeakerTurn(3.0, 4.123, 1),
        SpeakerTurn(5.0, 6.0, 1),
    ]


def test_read_wav_returns_float_samples_and_rejects_other_formats(tmp_path: Path) -> None:
    path = tmp_path / "system.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(np.array([0, 16384, -32768], dtype=np.int16).tobytes())
    stereo = tmp_path / "stereo.wav"
    with wave.open(str(stereo), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0\0\0")

    samples, rate = read_wav(path)

    assert rate == 16000
    assert samples.tolist() == [0.0, 0.5, -1.0]
    with pytest.raises(DiarizationError):
        read_wav(stereo)


def test_the_pyannote_diarizer_imports_nothing_heavy_until_it_runs() -> None:
    diarizer = PyannoteDiarizer("hf", WhisperDevice.CPU)

    diarizer.close()  # nothing loaded: nothing to free

    assert isinstance(diarizer, Diarizer)
    assert "pyannote.audio" not in sys.modules
