"""Reading a meeting ZIP (phase 39) back into a session folder, strictly.

The ZIP must hold one top-level folder named like a session id with only the file names of a
session folder (`SessionPaths`), so an entry can never land outside the extraction folder. The
uncompressed size is checked before anything is written.
"""

from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from vozata.storage.files.layout import SESSION_ID

MAX_BUNDLE_BYTES = 8 << 30  # 8 GiB, ~35 h of mic + system audio
FOLDER_FILES = frozenset(
    {
        "session.json",
        "transcript.jsonl",
        "transcript.md",
        "transcript.diarized.jsonl",
        "transcript.edited.jsonl",
        "transcript.translated.jsonl",
        "speakers.json",
        "minutes.md",
        "action_items.json",
        "partial_minutes.json",
        "mic.wav",
        "system.wav",
        "mixed.wav",
    }
)


class BundleError(Exception):
    """The file is not a meeting ZIP that can be imported (`422 bundle_invalid`)."""


class BundleTooLargeError(BundleError):
    """The ZIP, or what it unpacks to, is larger than `MAX_BUNDLE_BYTES` (`413`)."""


class SessionExistsError(Exception):
    """The meeting is already there with its audio (`409 session_exists`); nothing changed."""


def extract_bundle(archive: Path, destination: Path, max_bytes: int = MAX_BUNDLE_BYTES) -> Path:
    """Unpack `archive` into `destination/<id>/` and return that folder.

    Raises `BundleError` for anything but a session folder, `BundleTooLargeError` when it
    unpacks to more than `max_bytes`.
    """
    try:
        with ZipFile(archive) as bundle:
            entries = [info for info in bundle.infolist() if not info.is_dir()]
            session_id = _session_id([info.filename for info in entries])
            if sum(info.file_size for info in entries) > max_bytes:
                raise BundleTooLargeError(f"unpacks to more than {max_bytes} bytes")
            folder = destination / session_id
            folder.mkdir(parents=True)
            for info in entries:
                with (
                    bundle.open(info) as source,
                    (folder / info.filename.split("/")[1]).open("wb") as target,
                ):
                    shutil.copyfileobj(source, target)
    except (BadZipFile, EOFError) as error:
        raise BundleError(f"not a readable ZIP file: {error}") from error
    return folder


def _session_id(names: list[str]) -> str:
    folders = set()
    for name in names:
        parts = PurePosixPath(name).parts
        if len(parts) != 2 or not SESSION_ID.match(parts[0]) or parts[1] not in FOLDER_FILES:
            raise BundleError(f"unexpected entry {name!r}")
        folders.add(parts[0])
    if len(folders) != 1:
        raise BundleError("the ZIP must hold exactly one session folder")
    session_id = folders.pop()
    if f"{session_id}/session.json" not in names:
        raise BundleError("the session folder has no session.json")
    return session_id
