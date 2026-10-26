"""A stored session written back as a session folder (phase 39), the reverse of
`folder_reader.py`: what `FolderImporter` reads, it can import again.

The folder is laid out as `SessionPaths` (architecture §8) with the mic and system tracks as
WAVs; the mix is left out because the import computes it on read.
"""

from __future__ import annotations

from pathlib import Path

from vozata.audio.pcm import wav_header
from vozata.domain import AudioTrack, Channel
from vozata.labels import SpeakerLabeler
from vozata.ports import AudioTracks, PcmTrack, SessionRepository
from vozata.storage.files.repository import FileSessionRepository
from vozata.storage.session_store import SessionStore

_BLOCK_FRAMES = 1 << 16


def write_folder(
    source: SessionRepository,
    audio: AudioTracks | None,
    session_id: str,
    root: Path,
    labeler: SpeakerLabeler,
) -> Path:
    """Write the session as `root/<id>/` and return that folder; `root/<id>` must not exist.

    `labeler` names the speakers of the readable `transcript.md`. Raises
    `SessionNotFoundError` for an unknown session.
    """
    meta = source.read_meta(session_id)
    files = FileSessionRepository(SessionStore(root))
    paths = files.paths(session_id)
    paths.root.mkdir(parents=True)
    files.write_meta(session_id, meta)
    names = source.speaker_names(session_id)
    sink = files.open_transcript(session_id, labeler.with_names(names))
    try:
        for segment in source.load_source(session_id, "raw"):
            sink.emit(segment)
    finally:
        sink.close()
    if diarized := source.load_source(session_id, "diarized"):
        files.write_diarized(session_id, diarized)
    if edited := source.load_source(session_id, "edited"):
        files.write_edited(session_id, edited)
    if translations := source.load_translations(session_id):
        writer = files.open_translations(session_id)
        for translation in translations.values():
            writer.append(translation)
        writer.close()
    if speakers := source.speaker_ids(session_id):
        files.write_speakers(session_id, speakers)
        files.rename_speakers(session_id, names)
    if (minutes := source.read_minutes(session_id)) is not None:
        files.write_minutes(session_id, minutes)
    if items := source.read_action_items(session_id):
        files.write_action_items(session_id, items)
    if partials := source.read_partial_minutes(session_id):
        files.write_partial_minutes(session_id, partials)
    if requests := source.read_requests(session_id):
        files.write_requests(session_id, requests)
    if audio is not None:
        for channel in Channel:
            pcm = audio.track(session_id, AudioTrack(channel.value))
            if pcm is not None:
                _write_wav(pcm, paths.wav(channel))
    return paths.root


def _write_wav(pcm: PcmTrack, path: Path) -> None:
    with path.open("wb") as wav:
        wav.write(wav_header(pcm.rate, pcm.channels, pcm.frames))
        for start in range(0, pcm.frames, _BLOCK_FRAMES):
            wav.write(pcm.read(start, _BLOCK_FRAMES))
