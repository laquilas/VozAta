from __future__ import annotations

from pathlib import Path

import pytest

from vozata.recorder.settings import RecorderSettings, load_recorder_settings


def test_defaults_without_any_value() -> None:
    assert load_recorder_settings({}) == RecorderSettings()


def test_values_come_from_the_env_file_and_the_environment_wins(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OUTPUT_DIR=C:/VozAta/recordings\nRECORDER_PORT=9000\nAUTOSAVE_SECONDS=5\nWHISPER_MODEL=x\n",
        encoding="utf-8",
    )

    settings = load_recorder_settings({"RECORDER_PORT": "9100", "SAMPLE_RATE": " "}, env_file)

    assert settings.output_dir == Path("C:/VozAta/recordings")
    assert settings.port == 9100
    assert settings.autosave_seconds == 5
    assert settings.sample_rate == 16000  # blank = not set


@pytest.mark.parametrize("value", ["abc", "70000", "-1"])
def test_a_bad_value_falls_back_to_the_default(value: str) -> None:
    assert load_recorder_settings({"RECORDER_PORT": value}).port == 8766


def test_the_size_guard_is_in_bytes() -> None:
    assert load_recorder_settings({"RECORDER_MAX_SEGMENT_MB": "100"}).max_segment_bytes == 100 << 20


def test_the_process_environment_and_dot_env_are_read_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("RECORDER_FSYNC_SECONDS=4\n", encoding="utf-8")
    monkeypatch.setenv("RECORDER_BUFFER_WARN_SECONDS", "60")

    settings = load_recorder_settings()

    assert (settings.fsync_seconds, settings.buffer_warn_seconds) == (4, 60)
