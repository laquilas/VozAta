"""Ports: the interfaces orchestrators depend on (architecture §5).

Concrete implementations are wired only in `bootstrap.py`. Ports are added by the phase that first
needs them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import numpy as np

from vozata.domain import (
    ActionItem,
    AudioChunk,
    AudioTrack,
    Channel,
    ConversationLanguage,
    ExportDocument,
    ImportedSession,
    ModelKind,
    PartialMinutes,
    RequestEntry,
    SearchHit,
    SessionStatus,
    SpeakerTurn,
    TaskDraft,
    TranscriptionResult,
    TranscriptSegment,
    Translation,
)

if TYPE_CHECKING:
    from vozata.labels import SpeakerLabeler


@runtime_checkable
class AudioSource(Protocol):
    def start(self, on_samples: Callable[[np.ndarray, float], None]) -> None:
        """Begin delivering float32 mono samples with their session time."""
        ...

    def stop(self) -> None: ...


@runtime_checkable
class AudioSink(Protocol):
    def write(self, samples: np.ndarray, at: float) -> None: ...

    def finalize(self, total_seconds: float) -> None: ...


@runtime_checkable
class Transcriber(Protocol):
    def transcribe(
        self,
        samples: np.ndarray,
        language: str | None,
        hints: str | None = None,
        prompt: str | None = None,
    ) -> TranscriptionResult:
        """Return chunk-relative words; an empty result on silence (never raise for silence).

        `hints` are vocabulary terms (phase 19); `prompt` is the channel's recent text, the
        rolling context of the chunk (O4). Both may be ignored by a provider.
        """
        ...

    def close(self) -> None:
        """Release model memory (GPU)."""
        ...


@runtime_checkable
class Cancellable(Protocol):
    def cancel(self) -> None:
        """Stop the current call from another thread; the call raises."""
        ...


@runtime_checkable
class TranscriptSink(Protocol):
    def emit(self, segment: TranscriptSegment) -> None: ...

    def close(self) -> None: ...


@runtime_checkable
class Chunker(Protocol):
    """Cuts one channel's captured audio into `AudioChunk`s (fixed windows or pauses)."""

    paused: bool  # pausing emits the buffered audio and drops audio until resumed

    def feed(self, samples: np.ndarray, at: float) -> None: ...

    def flush(self) -> None: ...

    def buffered(self) -> AudioChunk | None:
        """A copy of the audio not emitted yet (interim text, phase 28)."""
        ...


@runtime_checkable
class SpeechDetector(Protocol):
    def speech_spans(self, samples: np.ndarray) -> list[tuple[float, float]]:
        """Unpadded (start, end) seconds of speech in `samples`, in order."""
        ...


@runtime_checkable
class AudioMixer(Protocol):
    channels: int  # of the mixed track: 1 (mono sum) or 2 (mic left, system right)

    def mix(self, reader: AudioReader, session_id: str, destination: Path) -> None:
        """Write the mic and system tracks of `session_id`, read through `reader`, as one WAV."""
        ...

    def combine(self, mic: np.ndarray, system: np.ndarray) -> np.ndarray:
        """Mix equal-length int16 blocks into interleaved int16 samples (phase 32)."""
        ...


class LanguageModelError(RuntimeError):
    """A language model could not produce a reply (unreachable, failed or malformed)."""


class LlmUnreachableError(LanguageModelError):
    """The model's server did not answer at all: off, wrong address or blocked (phase 43).

    Callers report it with the localized `llm_unreachable` message instead of a generic failure.
    """

    def __init__(self, host: str, detail: str) -> None:
        super().__init__(f"Could not reach the language model at {host}: {detail}")
        self.host = host


class WorkerUnreachableError(RuntimeError):
    """The VozAta worker did not answer at all: off, wrong address or blocked (phase 44).

    Callers fall back to this PC and tell the user through `FallbackNotices`.
    """

    def __init__(self, host: str, detail: str) -> None:
        super().__init__(f"Could not reach the VozAta worker at {host}: {detail}")
        self.host = host


class FallbackNotices(Protocol):
    def fallback(self, task: str, host: str) -> None:
        """`task` (`speech`, …) runs on this PC because the worker at `host` did not answer."""
        ...


@runtime_checkable
class LanguageModel(Protocol):
    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str: ...

    def stream(self, system: str, prompt: str) -> Iterator[str]: ...

    def is_available(self) -> bool: ...

    def release(self) -> None:
        """Free the model's memory (VRAM) after a job; raises `LanguageModelError` on failure."""
        ...

    def close(self) -> None:
        """Free the client's resources (HTTP connections); idempotent."""
        ...


class DiarizationError(RuntimeError):
    """Speaker identification failed (missing extra or token, model error, bad output)."""


@runtime_checkable
class Diarizer(Protocol):
    """Finds who speaks when in a recording (phase 14); only `system.wav` is diarized."""

    def diarize(
        self, wav: Path, min_speakers: int | None, max_speakers: int | None
    ) -> list[SpeakerTurn]:
        """Speaker turns in time order; raises `DiarizationError` on failure."""
        ...

    def close(self) -> None:
        """Release model memory (GPU)."""
        ...


@runtime_checkable
class SpeakerEmbedder(Protocol):
    """Turns a voice clip into a speaker embedding (phase 15, live speaker labels)."""

    def embed(self, samples: np.ndarray) -> np.ndarray:
        """A 1-D vector for float32 mono samples at the session rate; raises on failure."""
        ...

    def close(self) -> None:
        """Release the model (and its process or GPU memory)."""
        ...


@runtime_checkable
class DocumentExporter(Protocol):
    """Renders an `ExportDocument` (minutes + transcript) as one file format (phase 11)."""

    media_type: str
    extension: str

    def export(self, document: ExportDocument) -> bytes: ...


class TaskExportError(RuntimeError):
    """A task could not be created; `code` is an `errors.tasks.<code>` key, `params` its values.

    Codes: `unauthorized`, `not_found`, `http_error` (status, detail), `unreachable` (reason),
    `invalid_reply`. Messages never contain credentials.
    """

    def __init__(self, code: str, **params: object) -> None:
        super().__init__(code, params)
        self.code = code
        self.params = params


@runtime_checkable
class TaskExporter(Protocol):
    """Creates one work item / issue per action item in an external tracker (phase 23)."""

    name: str  # display name, e.g. "Azure DevOps"

    def create(self, task: TaskDraft) -> str:
        """The URL of the created item; raises `TaskExportError`."""
        ...


@runtime_checkable
class Localizer(Protocol):
    def t(self, key: str, /, **params: object) -> str: ...


@runtime_checkable
class SessionObserver(Protocol):
    """Receives recording-session events (console in phase 05, WebSocket in phase 06).

    Calls arrive from capture and transcription threads; implementations must be thread-safe and
    return quickly.
    """

    def on_status(self, status: SessionStatus, duration_seconds: float) -> None: ...

    def on_level(self, channel: Channel, rms_db: float) -> None: ...

    def on_segment(self, segment: TranscriptSegment) -> None: ...

    def on_language_detected(self, language: ConversationLanguage) -> None: ...

    def on_minutes_ready(self, session_id: str) -> None: ...

    def on_action_items_ready(self, session_id: str, count: int) -> None:
        """Action items were extracted and saved (phase 23)."""
        ...

    def on_speakers_relabeled(self, session_id: str) -> None:
        """The post-session speaker pass rewrote the speakers (phase 15); reload the transcript."""
        ...

    def on_partial(self, channel: Channel, speaker_id: str, start: float, text: str) -> None:
        """Interim text of a channel (phase 28); empty `text` clears it. Never written to files."""
        ...

    def on_model_loading(self, loading: bool) -> None:
        """The speech model started (True) or finished (False) loading; capture already runs."""
        ...

    def on_translation(self, segment_id: str, language: str, text: str) -> None:
        """A committed segment translated into `language` (phase 29)."""
        ...

    def on_error(self, code: str, message: str) -> None:
        """A non-fatal error; `message` is localized."""
        ...


class TranslationError(RuntimeError):
    """A translator could not translate (missing extra or model, unsupported pair, model error)."""


@runtime_checkable
class Translator(Protocol):
    """Translates committed transcript text (phase 29); runs on CPU during recording."""

    def translate(self, text: str, source: str, target: str) -> str:
        """`text` from `source` into `target` (`en`, `pt`, `es`); raises `TranslationError`."""
        ...

    def close(self) -> None:
        """Release the model memory."""
        ...


@runtime_checkable
class ModelDownloader(Protocol):
    """Makes sure a model repo is in the local cache, reporting progress while it downloads
    (phase 42)."""

    def ensure(
        self,
        kind: ModelKind,
        repo_id: str,
        *,
        allow_patterns: Sequence[str] | None = None,
        token: str | None = None,
        name: str | None = None,
    ) -> Path:
        """The local snapshot folder of `repo_id` (only the files matching `allow_patterns`),
        downloading what is missing; raises the hub's exception when it cannot. `name` is the
        model as the user knows it (the progress events' `model`; default: `repo_id`)."""
        ...


@runtime_checkable
class TranscriptSearch(Protocol):
    """Full-text search over every session's transcript (phase 22; reused by 21 and 24)."""

    def index_session(self, session_id: str, segments: Sequence[TranscriptSegment]) -> None:
        """Replace everything indexed for `session_id` with `segments`."""
        ...

    def search(self, query: str, limit: int = 50) -> list[SearchHit]:
        """Best matches first for free user text; FTS syntax in `query` is never interpreted."""
        ...


# --- Storage (phase 30): every read and write of session data goes through these ports. ---


class SessionNotFoundError(LookupError):
    """No session with this id (or the id is not a session id)."""


@runtime_checkable
class TranslationWriter(Protocol):
    """A recording's live translations (phase 29), appended one by one."""

    def append(self, translation: Translation) -> None: ...

    def close(self) -> None: ...


@runtime_checkable
class SessionRepository(Protocol):
    """Sessions: metadata, transcripts, speakers, translations, minutes and action items.

    Session ids are `YYYYMMDD_HHMMSS[_n]`; any other id raises `SessionNotFoundError`.
    """

    def now(self) -> datetime:
        """The local time with its offset (start and end stamps, heartbeats)."""
        ...

    def create(self, started_at: datetime | None = None) -> str:
        """A new, empty session named after `started_at` (default: now); returns its id."""
        ...

    def discard(self, session_id: str) -> None:
        """Delete everything of a session (a recording that failed to start)."""
        ...

    def read_meta(self, session_id: str) -> dict[str, Any]:
        """The metadata (architecture §8); `SessionNotFoundError` when the session has none."""
        ...

    def write_meta(self, session_id: str, meta: dict[str, Any]) -> None:
        """Replace the metadata atomically (a crash leaves the old or the new one)."""
        ...

    def list_sessions(self) -> list[str]:
        """Ids of the sessions that have metadata, newest first."""
        ...

    def open_transcript(self, session_id: str, labeler: SpeakerLabeler) -> TranscriptSink:
        """The live, append-only raw transcript of a recording; each segment is durable once
        `emit` returns (crash safety, phase 17)."""
        ...

    def load_transcript(self, session_id: str) -> list[TranscriptSegment]:
        """The best transcript: edited, then diarized, then raw (empty when there is none)."""
        ...

    def load_transcript_with_source(self, session_id: str) -> tuple[str, list[TranscriptSegment]]:
        """The best transcript and its source: `edited`, `diarized` or `raw`."""
        ...

    def load_raw_transcript(self, session_id: str) -> list[TranscriptSegment]:
        """The transcript as captured (empty when there is none)."""
        ...

    def load_source(self, session_id: str, source: str) -> list[TranscriptSegment]:
        """One transcript: `raw`, `diarized` or `edited` (empty when there is none; phase 39)."""
        ...

    def write_diarized(self, session_id: str, segments: Sequence[TranscriptSegment]) -> None:
        """Replace the speaker-labelled transcript (phase 14)."""
        ...

    def write_edited(self, session_id: str, segments: Sequence[TranscriptSegment]) -> None:
        """Replace the edited transcript with this full copy (phase 21)."""
        ...

    def delete_edited(self, session_id: str) -> bool:
        """Drop the edited transcript; False when there was none (phase 21)."""
        ...

    def open_translations(self, session_id: str) -> TranslationWriter:
        """Where a recording's live translations go; nothing is stored until the first one."""
        ...

    def load_translations(self, session_id: str) -> dict[str, Translation]:
        """Translations by segment id (the last one wins); empty when there is none."""
        ...

    def speaker_names(self, session_id: str) -> dict[str, str]:
        """Names given to speakers (empty when none or unreadable)."""
        ...

    def write_speakers(self, session_id: str, speaker_ids: Sequence[str]) -> None:
        """Replace the speakers with these ids, without names (phase 14)."""
        ...

    def speaker_ids(self, session_id: str) -> list[str]:
        """Every speaker id, named or not, in the order they were added (phase 39)."""
        ...

    def rename_speakers(self, session_id: str, names: Mapping[str, str | None]) -> None:
        """Merge trimmed names; an empty or None name clears it (phase 16)."""
        ...

    def read_minutes(self, session_id: str) -> str | None:
        """The minutes Markdown exactly as written; None when there are none."""
        ...

    def write_minutes(self, session_id: str, markdown: str) -> None: ...

    def has_minutes(self, session_id: str) -> bool: ...

    def read_action_items(self, session_id: str) -> list[ActionItem]:
        """The stored items in order; empty when none or unreadable (phase 23)."""
        ...

    def write_action_items(self, session_id: str, items: Sequence[ActionItem]) -> None:
        """Replace the action items atomically."""
        ...

    def action_items_lock(self) -> AbstractContextManager[object]:
        """Held around every read-modify-write of action items (extraction, edits, export)."""
        ...

    def read_partial_minutes(self, session_id: str) -> list[PartialMinutes]:
        """Minutes of parts of the meeting, oldest first; empty when none (phase 48)."""
        ...

    def write_partial_minutes(self, session_id: str, items: Sequence[PartialMinutes]) -> None:
        """Replace the partial minutes atomically."""
        ...

    def read_requests(self, session_id: str) -> list[RequestEntry]:
        """The meeting's request history, oldest first; empty when none (phase 59)."""
        ...

    def write_requests(self, session_id: str, items: Sequence[RequestEntry]) -> None:
        """Replace the request history atomically."""
        ...

    def folder(self, session_id: str) -> Path | None:
        """The session folder (file backend); None for a backend without one."""
        ...

    def files(self, session_id: str) -> list[str] | None:
        """Names of the files in the session folder, sorted; None without a folder."""
        ...

    # Meetings page (phase 36)

    def list_range(self, start: datetime, end: datetime) -> list[str]:
        """Ids of the sessions with metadata that started in `[start, end)` (aware datetimes),
        newest first; a session without `started_at` starts at the local time of its id."""
        ...

    def speaker_count(self, session_id: str) -> int:
        """How many speakers diarization found (0 before diarization or without speakers)."""
        ...

    def delete(self, session_id: str) -> None:
        """Delete a session and everything of it (phase 36): permanently in the database; the
        file backend moves the session folder to the Recycle Bin. `SessionNotFoundError` when
        there is no such session."""
        ...


@runtime_checkable
class Recycler(Protocol):
    """Moves a file or folder to the Recycle Bin (phase 36); never deletes it permanently."""

    def recycle(self, path: Path) -> None: ...


@runtime_checkable
class AudioTrackWriter(AudioSink, Protocol):
    """One channel of a recording, aligned to the session clock (`AlignedWavWriter`)."""

    paused: bool  # blocks are written as silence while paused
    samples_written: int


@runtime_checkable
class AudioStore(Protocol):
    """Where a recording's audio goes."""

    def open_writer(self, session_id: str, channel: Channel) -> AudioTrackWriter:
        """A writer for one channel; `finalize` completes the track and closes it."""
        ...

    def write_mix(self, session_id: str, mixer: AudioMixer) -> None:
        """Mix the finished tracks with `mixer` and keep the result (stop step 3)."""
        ...

    def delete(self, session_id: str) -> None:
        """Drop what this store keeps of a deleted session beyond the repository (phase 32)."""
        ...

    def discard(self, session_id: str) -> None:
        """Remove the audio of a session that is kept: its transcript and minutes stay (39)."""
        ...


class AudioDecodeError(RuntimeError):
    """A file holds no audio that can be decoded (phase 60); the message says why."""


@runtime_checkable
class AudioDecoder(Protocol):
    """Reads an audio (or video) file recorded elsewhere (phase 60)."""

    def blocks(self, path: Path) -> Iterator[bytes]:
        """The file's first audio stream as mono little-endian 16-bit PCM at the engine's sample
        rate, a block at a time; raises `AudioDecodeError`."""
        ...


@runtime_checkable
class PcmImport(Protocol):
    """A store that takes a whole channel at once (phase 33 folders, phase 60 audio files)."""

    def import_pcm(self, session_id: str, channel: Channel, blocks: Iterable[bytes]) -> int:
        """Replace the channel's audio with `blocks` of mono 16-bit PCM; returns the samples."""
        ...


class BundleImporter(Protocol):
    """Reads an unpacked meeting ZIP into the storage backend (phase 39)."""

    def import_folder(self, folder: Path) -> ImportedSession:
        """Import the session folder `<dir>/<id>/`: a new session, or only its audio into a kept
        session that has none. Raises `storage.bundle_import.BundleError` for a folder that
        cannot be read and `SessionExistsError` when the session is there with its audio;
        nothing is changed then."""
        ...


@runtime_checkable
class AudioReader(Protocol):
    """Reads a session's recorded tracks (mono 16-bit PCM)."""

    def frames(self, session_id: str, channel: Channel, start: int, count: int) -> np.ndarray:
        """Up to `count` int16 samples from sample `start` (fewer at the end of the track)."""
        ...

    def length(self, session_id: str, channel: Channel) -> int:
        """The track length in samples."""
        ...

    def sample_rate(self, session_id: str, channel: Channel) -> int: ...

    def materialize_wav(self, session_id: str, channel: Channel | AudioTrack) -> Path:
        """A WAV file of the track, for tools that need a file (the diarizer child process)."""
        ...


@runtime_checkable
class PcmTrack(Protocol):
    """A playable track as 16-bit PCM (phase 32): `frames` frames of `channels` samples."""

    rate: int
    channels: int
    frames: int

    def read(self, start: int, count: int) -> bytes:
        """Up to `count` frames from frame `start`, interleaved little-endian int16."""
        ...


@runtime_checkable
class AudioTracks(Protocol):
    """The playable tracks of a session (`GET /sessions/{id}/audio/{track}`, phase 32)."""

    def track(self, session_id: str, track: AudioTrack) -> PcmTrack | None:
        """The track, or None when the session has no such audio."""
        ...


@runtime_checkable
class AudioCache(Protocol):
    """Files built from stored audio (phase 32): measured and cleared from Config → Storage."""

    def size(self) -> int: ...

    def clear(self) -> int:
        """Delete what is not in use; returns the bytes freed."""
        ...


@runtime_checkable
class SessionAudio(AudioStore, AudioReader, AudioTracks, Protocol):
    """Both sides of a storage backend's audio: what a recording session needs."""


class StoreRepairError(RuntimeError):
    """A store could not repair an interrupted session; the message says why."""


@runtime_checkable
class RecoverableStore(Protocol):
    """A store that can make an interrupted session's data readable again (phase 17)."""

    def repair(self, session_id: str) -> float | None:
        """Repair what a crash left half-written. Returns the recorded length in seconds when
        this store holds the audio, else None; raises `StoreRepairError` when it cannot."""
        ...


@runtime_checkable
class AudioSessionMonitor(Protocol):
    """Which apps play or capture audio right now (phase 54): the executable names (e.g.
    `ms-teams.exe`) of the active Windows audio sessions."""

    def active_apps(self) -> set[str]: ...
