"""`vozata-engine data paths | erase --yes` (phase 67): where this user's VozAta data lives.

The uninstaller runs `data erase --yes` (in `%APPDATA%\\VozAta`, where the engine reads its
`.env`) when the user asks to delete the data, so it never guesses the paths: the database
(`DATABASE_PATH` may be outside `OUTPUT_DIR`), `OUTPUT_DIR` (recordings, live recordings, the audio
cache, exports) and the downloaded runtimes (`%LOCALAPPDATA%\\VozAta`: CUDA, speakers). A folder
that is not VozAta's alone (a drive root, the home folder, Documents, Desktop) is never deleted.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from vozata.cli.console import ConsoleObserver
from vozata.config import Settings
from vozata.ports import Localizer

ACTIONS = ("paths", "erase")
DATABASE_SUFFIXES = ("", "-wal", "-shm", "-journal")
_SHARED_NAMES = {
    "documents",
    "documentos",
    "desktop",
    "área de trabalho",
    "escritorio",
    "downloads",
}


@dataclass(frozen=True)
class DataPaths:
    database: tuple[Path, ...]  # the database file and its SQLite companions
    folders: tuple[Path, ...]  # OUTPUT_DIR, the downloaded runtimes

    def to_json(self) -> dict[str, list[str]]:
        return {
            "database": [str(path) for path in self.database],
            "folders": [str(path) for path in self.folders],
        }


def data_paths(settings: Settings) -> DataPaths:
    database = settings.database_file
    files = tuple(database.with_name(database.name + suffix) for suffix in DATABASE_SUFFIXES)
    folders = (settings.output_dir, settings.cuda_runtime_dir.parent)
    return DataPaths(files, tuple(dict.fromkeys(path.absolute() for path in folders)))


def shared_folder(path: Path, home: Path) -> bool:
    """True for a folder that holds more than VozAta's data: never deleted as a whole."""
    resolved = path.absolute()
    if resolved == Path(resolved.anchor) or len(resolved.parts) <= 2:
        return True
    if resolved in (home.absolute(), home.absolute().parent):
        return True
    return resolved.name.lower() in _SHARED_NAMES


def run_data(
    action: str,
    settings: Settings,
    console: ConsoleObserver,
    localizer: Localizer,
    *,
    yes: bool = False,
    json_output: bool = False,
    keep_runtimes: bool = False,
    home: Path | None = None,
    remove_tree: Callable[[Path], None] = shutil.rmtree,
    remove_file: Callable[[Path], None] = lambda path: path.unlink(missing_ok=True),
) -> int:
    """`paths` lists the data; `erase --yes` deletes it (exit 1 when something stayed).

    `keep_runtimes` keeps the downloaded runtimes (the other product still uses them).
    """
    t = localizer.t
    paths = data_paths(settings)
    if keep_runtimes:
        runtimes = settings.cuda_runtime_dir.parent.absolute()
        paths = DataPaths(paths.database, tuple(p for p in paths.folders if p != runtimes))
    if action == "paths":
        if json_output:
            console.say(json.dumps(paths.to_json()))
        else:
            for path in (*paths.database[:1], *paths.folders):
                console.say(t("cli.data.path", path=path))
        return 0
    if not yes:
        console.say(t("cli.data.confirm"))
        return 2
    failed = _erase(paths, home or Path.home(), console, localizer, remove_tree, remove_file)
    return 1 if failed else 0


def _erase(
    paths: DataPaths,
    home: Path,
    console: ConsoleObserver,
    localizer: Localizer,
    remove_tree: Callable[[Path], None],
    remove_file: Callable[[Path], None],
) -> Sequence[Path]:
    t = localizer.t
    failed: list[Path] = []
    for file in paths.database:
        if not file.exists():
            continue
        try:
            remove_file(file)
            console.say(t("cli.data.removed", path=file))
        except OSError as error:
            failed.append(file)
            console.say(t("cli.data.failed", path=file, reason=error))
    for folder in paths.folders:
        if not folder.exists():
            continue
        if shared_folder(folder, home):
            console.say(t("cli.data.skipped", path=folder))
            continue
        try:
            remove_tree(folder)
            console.say(t("cli.data.removed", path=folder))
        except OSError as error:
            failed.append(folder)
            console.say(t("cli.data.failed", path=folder, reason=error))
    return failed
