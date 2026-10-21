from __future__ import annotations

from pathlib import Path

import pytest

from vozata.config import ConfigError, load_settings
from vozata.domain import ChunkMode
from vozata.settings_file import SettingsFile
from vozata.settings_view import SECRET_MASK

ENV = """# VozAta engine configuration.
# --- Core ---
CHUNK_SECONDS=5
APP_LANGUAGE=en

# --- Minutes ---
OLLAMA_MODEL=qwen2.5:7b
"""


def settings_file(
    tmp_path: Path, text: str = ENV, environ: dict[str, str] | None = None
) -> SettingsFile:
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    current = load_settings(env={**_file_values(text), **(environ or {})})
    return SettingsFile(path, current, environ=environ or {})


def _file_values(text: str) -> dict[str, str]:
    lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    return dict(line.split("=", 1) for line in lines)


def test_an_update_is_validated_persisted_and_keeps_comments_and_order(tmp_path: Path) -> None:
    file = settings_file(tmp_path)

    restart = file.update({"CHUNK_SECONDS": 8, "CHUNK_MODE": "fixed", "GENERATE_MINUTES": False})

    assert restart == []
    assert file.current.chunk_seconds == 8.0
    assert file.current.chunk_mode is ChunkMode.FIXED
    assert file.current.generate_minutes is False
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert text.startswith("# VozAta engine configuration.\n# --- Core ---\nCHUNK_SECONDS=8\n")
    assert "# --- Minutes ---\nOLLAMA_MODEL=qwen2.5:7b\n" in text
    assert "CHUNK_MODE=fixed\n" in text and "GENERATE_MINUTES=false\n" in text
    assert load_settings(env={}, env_file=tmp_path / ".env").chunk_seconds == 8.0


def test_unchanged_values_are_not_rewritten(tmp_path: Path) -> None:
    file = settings_file(tmp_path)

    file.update({"CHUNK_SECONDS": 5.0, "APP_LANGUAGE": "en", "MIX_MODE": "mono"})

    assert (tmp_path / ".env").read_text(encoding="utf-8") == ENV


def test_an_invalid_value_names_its_key_and_changes_nothing(tmp_path: Path) -> None:
    file = settings_file(tmp_path)
    before = file.current

    with pytest.raises(ConfigError) as caught:
        file.update({"CHUNK_SECONDS": 8, "VAD_MIN_SILENCE_MS": 10})

    assert caught.value.key == "VAD_MIN_SILENCE_MS"
    assert file.current is before
    assert (tmp_path / ".env").read_text(encoding="utf-8") == ENV


def test_an_unknown_key_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as caught:
        settings_file(tmp_path).update({"NOT_A_KEY": "x"})

    assert (caught.value.key, caught.value.message_key) == ("NOT_A_KEY", "unknown_key")


def test_keys_read_at_start_up_report_a_restart(tmp_path: Path) -> None:
    file = settings_file(tmp_path)

    restart = file.update({"WHISPER_MODEL": "medium", "API_PORT": 8770, "MIX_MODE": "stereo"})

    assert restart == ["WHISPER_MODEL", "API_PORT"]


def test_the_secret_mask_means_unchanged_and_an_empty_value_clears(tmp_path: Path) -> None:
    file = settings_file(tmp_path, ENV + "MIC_LABEL=Host\n")

    file.update({"MIC_LABEL": SECRET_MASK})
    assert file.current.mic_label == SECRET_MASK  # MIC_LABEL is not secret: the text is kept
    file.update({"MIC_LABEL": None})

    assert file.current.mic_label is None
    assert "MIC_LABEL=\n" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_secret_fields_ignore_the_mask(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from vozata import settings_file as module
    from vozata.settings_fields import FIELDS

    secret = {"OLLAMA_MODEL"}
    monkeypatch.setattr(
        module, "SECRET_KEYS", frozenset(field.key for field in FIELDS if field.key in secret)
    )
    file = settings_file(tmp_path)

    file.update({"OLLAMA_MODEL": SECRET_MASK})

    assert file.current.ollama_model == "qwen2.5:7b"
    assert (tmp_path / ".env").read_text(encoding="utf-8") == ENV


def test_a_missing_env_file_is_created(tmp_path: Path) -> None:
    path = tmp_path / "config" / ".env"
    file = SettingsFile(path, load_settings(env={}), environ={})

    file.update({"CHUNK_SECONDS": 6})

    assert path.read_text(encoding="utf-8") == "CHUNK_SECONDS=6\n"


def test_process_environment_values_keep_winning(tmp_path: Path) -> None:
    file = settings_file(tmp_path, environ={"CHUNK_SECONDS": "3"})

    file.update({"CHUNK_SECONDS": 8})

    assert file.current.chunk_seconds == 3.0  # documented: the process environment overrides .env
    assert "CHUNK_SECONDS=8\n" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_hf_hub_offline_survives_an_update(tmp_path: Path) -> None:
    file = settings_file(tmp_path, environ={"HF_HUB_OFFLINE": "1"})
    assert file.current.hf_hub_offline is True

    file.update({"CHUNK_SECONDS": 8})

    assert file.current.hf_hub_offline is True  # a process value, never on the saved-settings path
    assert "HF_HUB_OFFLINE" not in (tmp_path / ".env").read_text(encoding="utf-8")


def test_a_briefly_locked_env_file_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vozata import settings_file as module

    real_set_key = module.set_key
    failures = [PermissionError("locked by OneDrive"), PermissionError("still locked")]

    def flaky(*args: object, **kwargs: object) -> object:
        if failures:
            raise failures.pop(0)
        return real_set_key(*args, **kwargs)

    monkeypatch.setattr(module, "set_key", flaky)
    monkeypatch.setattr(module, "WRITE_RETRY_SECONDS", 0)
    file = settings_file(tmp_path)

    file.update({"CHUNK_SECONDS": 8})

    assert file.current.chunk_seconds == 8.0
    assert "CHUNK_SECONDS=8\n" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_a_file_that_stays_locked_reports_a_write_error_and_keeps_the_current_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vozata import settings_file as module

    def locked(*args: object, **kwargs: object) -> object:
        raise PermissionError("locked by OneDrive")

    monkeypatch.setattr(module, "set_key", locked)
    monkeypatch.setattr(module, "WRITE_RETRY_SECONDS", 0)
    file = settings_file(tmp_path)
    before = file.current

    with pytest.raises(module.SettingsWriteError) as caught:
        file.update({"CHUNK_SECONDS": 8})

    assert "locked by OneDrive" in str(caught.value)
    assert file.current is before
