from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest

from tests.fakes import FakeLocalizer
from vozata import __main__ as cli
from vozata import bootstrap
from vozata.audio.devices import DeviceInfo
from vozata.config import ConfigError
from vozata.domain import ConversationLanguage
from vozata.storage.sqlite.search import SqliteSearch

MIC = DeviceInfo(9, "Headset Mic", 2, 48000, False)
LOOPBACK = DeviceInfo(10, "Speakers [Loopback]", 2, 48000, True)


def _main(argv: list[str], env: dict[str, str] | None = None) -> tuple[int, str]:
    out = io.StringIO()
    code = cli.main(argv, stdout=out, stdin=io.StringIO(""), env=env or {})
    return code, out.getvalue()


def test_parser_reads_record_options() -> None:
    args = cli.build_parser(FakeLocalizer()).parse_args(
        ["record", "--language", "auto", "--mic", "9", "--system", "10"]
    )

    assert (args.command, args.language, args.mic, args.system) == ("record", "auto", 9, 10)
    assert args.list_devices is False


def test_parser_rejects_unknown_languages_and_requires_a_command(capsys) -> None:
    parser = cli.build_parser(FakeLocalizer())

    with pytest.raises(SystemExit):
        parser.parse_args(["record", "--language", "fr"])
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_parser_help_is_localized(capsys) -> None:
    with pytest.raises(SystemExit):
        cli.build_parser(FakeLocalizer()).parse_args(["record", "--help"])

    assert "cli.help.language" in capsys.readouterr().out


def test_version_flag_prints_the_version(capsys) -> None:
    with pytest.raises(SystemExit) as exit_:
        cli.main(["--version"], env={})

    assert exit_.value.code == 0
    assert capsys.readouterr().out.strip() == "0.1.0"


def test_record_runs_with_the_parsed_options(monkeypatch: pytest.MonkeyPatch) -> None:
    received: dict[str, Any] = {}

    def fake_run_record(settings, console, localizer, build, **kwargs) -> int:  # type: ignore[no-untyped-def]
        received.update(kwargs, build=build)
        return 0

    monkeypatch.setattr(cli, "run_record", fake_run_record)

    code, _ = _main(["record", "--language", "es", "--system", "10"])

    assert code == 0
    assert received["language"] is ConversationLanguage.ES
    assert (received["mic_device"], received["system_device"]) == (None, 10)
    assert received["build"] is cli.bootstrap.build_session


def test_record_without_language_uses_the_settings_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, Any] = {}
    monkeypatch.setattr(cli, "run_record", lambda *args, **kwargs: received.update(kwargs) or 0)

    _main(["record"])

    assert received["language"] is None


def test_list_devices_prints_the_devices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "list_input_devices", lambda: [MIC])
    monkeypatch.setattr(cli, "list_loopback_devices", lambda: [LOOPBACK])
    monkeypatch.setattr(cli, "default_input", lambda: MIC)
    monkeypatch.setattr(cli, "default_loopback", lambda: LOOPBACK)

    code, out = _main(["record", "--list-devices"], env={"APP_LANGUAGE": "pt-BR"})

    assert code == 0
    assert out.splitlines() == [
        "Microfones:",
        "    9  Headset Mic  (padrão)",
        "Áudio do sistema (loopback):",
        "   10  Speakers [Loopback]  (padrão)",
    ]


def test_minutes_command_runs_on_the_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[Path] = []
    monkeypatch.setattr(cli, "run_minutes", lambda folder, *args: received.append(folder) or 0)

    code, _ = _main(["minutes", "recordings/20261015_202358"])

    assert code == 0
    assert received == [Path("recordings/20261015_202358")]


def test_migrate_command_imports_the_output_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    received: list[tuple[Any, bool]] = []
    monkeypatch.setattr(
        cli, "run_migrate", lambda importer, dry, *args: received.append((importer, dry)) or 0
    )

    code, _ = _main(["migrate", "--dry-run"], env={"OUTPUT_DIR": str(tmp_path)})
    files_code, _ = _main(
        ["migrate"], env={"OUTPUT_DIR": str(tmp_path), "STORAGE_BACKEND": "files"}
    )

    assert (code, files_code) == (0, 0)
    (importer, dry), (no_importer, files_dry) = received
    assert importer is not None and importer.pending() == []
    assert (dry, no_importer, files_dry) == (True, None, False)


def test_reindex_command_rebuilds_the_index_in_the_output_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    received: list[tuple[Any, Any]] = []
    monkeypatch.setattr(
        cli, "run_reindex", lambda store, index, *args: received.append((store, index)) or 0
    )

    code, _ = _main(["reindex"], env={"OUTPUT_DIR": str(tmp_path)})
    files_code, _ = _main(
        ["reindex"], env={"OUTPUT_DIR": str(tmp_path), "STORAGE_BACKEND": "files"}
    )

    assert (code, files_code) == (0, 0)
    (sqlite_store, sqlite_index), (files_store, files_index) = received
    assert isinstance(sqlite_index, SqliteSearch)
    assert sqlite_store.database.path == tmp_path / "vozata.db"
    assert (files_store.store._root, files_index._path) == (tmp_path, tmp_path / "index.db")


@pytest.mark.parametrize(
    ("argv", "expected"),
    [(["recover", "--all"], None), (["recover", "rec/20261015_202358"], "rec/20261015_202358")],
)
def test_recover_command_targets_a_folder_or_every_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, argv: list[str], expected: str | None
) -> None:
    received: list[Any] = []

    def fake_run(session_dir: Path | None, build: Any, *args: Any) -> int:
        recovery = build(None)
        root = recovery.store.database.path.parent  # sqlite: OUTPUT_DIR/vozata.db
        received.append((session_dir, root, recovery._stale_after))
        return 0

    monkeypatch.setattr(cli, "run_recover", fake_run)

    code, _ = _main(argv, env={"OUTPUT_DIR": str(tmp_path), "AUTOSAVE_SECONDS": "5"})

    assert code == 0
    assert received == [(Path(expected) if expected else None, tmp_path, 15.0)]


def test_transcribe_command_passes_the_session_to_the_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[Any] = []

    def fake_run(target: str, settings: Any, *args: Any) -> int:
        received.append(target)
        return 3

    monkeypatch.setattr(cli, "run_transcribe", fake_run)

    code, _ = _main(["transcribe", "20261015_202358"])

    assert (code, received) == (3, ["20261015_202358"])


def test_recover_needs_a_folder_or_all() -> None:
    with pytest.raises(SystemExit):
        _main(["recover"])


def test_invalid_settings_exit_2_with_the_message() -> None:
    code, out = _main(["record"], env={"CHUNK_SECONDS": "abc"})

    assert code == 2
    assert out == 'Invalid value "abc" for CHUNK_SECONDS: expected a number.\n'


def test_unknown_provider_exits_2_with_a_localized_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: Any, **kwargs: Any) -> int:
        raise ConfigError("STT_PROVIDER", "x", "invalid_choice", allowed="faster_whisper")

    monkeypatch.setattr(cli, "run_record", fail)

    code, out = _main(["record"], env={"APP_LANGUAGE": "es"})

    assert code == 2
    assert out.startswith('Valor no válido "x" para STT_PROVIDER')


def test_unknown_device_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> int:
        raise LookupError("No audio device with id 42")

    monkeypatch.setattr(cli, "run_record", fail)

    code, out = _main(["record", "--mic", "42"])

    assert code == 2
    assert out.startswith("Audio device not found: No audio device with id 42.")


def test_ctrl_c_before_recording_exits_130(monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupt(*args: Any, **kwargs: Any) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run_record", interrupt)

    assert _main(["record"])[0] == 130


def test_tolerant_output_replaces_unencodable_characters() -> None:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="ascii")

    assert cli.tolerant_output(stream) is stream
    stream.write("Olá")
    stream.flush()

    assert raw.getvalue() == b"Ol?"


def test_tolerant_output_accepts_streams_without_reconfigure() -> None:
    stream = io.StringIO()

    assert cli.tolerant_output(stream) is stream


def test_serve_command_runs_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[Any] = []
    monkeypatch.setattr(cli, "run_serve", lambda *args: received.append(args) or 0)

    code, _ = _main(["serve"], env={"API_PORT": "9001"})

    assert code == 0
    settings, _console, _localizer, build_app, run = received[0]
    assert settings.api_port == 9001
    assert build_app is cli._build_app
    assert run is cli._uvicorn_run


def test_build_app_wraps_the_real_container(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from tests.api.conftest import Api

    container = Api(tmp_path).app.state.container
    monkeypatch.setattr(cli.bootstrap, "build_api_container", lambda settings: container)

    app = cli._build_app(container.settings)

    assert app.state.container is container


@pytest.mark.parametrize(("argv", "then_minutes"), [([], False), (["--minutes"], True)])
def test_diarize_command_runs_on_the_folder_and_can_chain_the_minutes(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], then_minutes: bool
) -> None:
    received: list[tuple[Path, bool]] = []
    minutes: list[Path] = []

    def diarize(folder, settings, console, localizer, build, then, open_folder):  # type: ignore[no-untyped-def]
        assert open_folder.func is bootstrap.open_session_folder  # the configured storage
        received.append((folder, then is not None))
        return then() if then is not None else 0

    monkeypatch.setattr(cli, "run_diarize", diarize)
    monkeypatch.setattr(cli, "run_minutes", lambda folder, *args: minutes.append(folder) or 5)

    code, _ = _main(["diarize", "recordings/20261015_202358", *argv])

    folder = Path("recordings/20261015_202358")
    assert received == [(folder, then_minutes)]
    assert (code, minutes) == ((5, [folder]) if then_minutes else (0, []))


def test_main_sets_hf_hub_disable_xet_before_importing_the_hub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """huggingface_hub reads `HF_HUB_DISABLE_XET` once, at its first import (phase 42)."""
    import ast
    import importlib

    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    statements = [
        node
        for node in tree.body
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
    ]
    imports = [
        index
        for index, node in enumerate(statements)
        if isinstance(node, ast.Import | ast.ImportFrom)
        and not (isinstance(node, ast.ImportFrom) and node.module == "__future__")
        and not (isinstance(node, ast.Import) and [a.name for a in node.names] == ["os"])
    ]
    setdefault = next(
        index
        for index, node in enumerate(statements)
        if isinstance(node, ast.Expr) and "HF_HUB_DISABLE_XET" in ast.unparse(node)
    )
    assert setdefault < min(imports)

    monkeypatch.delenv("HF_HUB_DISABLE_XET", raising=False)
    importlib.reload(cli)

    assert __import__("os").environ["HF_HUB_DISABLE_XET"] == "1"


def test_worker_check_prints_the_version_and_the_address() -> None:
    code, out = _main(["worker", "--check"], env={"WORKER_PORT": "9001"})

    assert code == 0
    assert "VozAta worker" in out and "http://0.0.0.0:9001" in out
