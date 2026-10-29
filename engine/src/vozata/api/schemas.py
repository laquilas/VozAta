"""Pydantic models for every request and response shape tagged 06 in the API contract."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ConversationLanguageValue = Literal["en", "pt", "es", "auto"]
TranslationTargetValue = Literal["off", "en", "pt", "es"]


class GpuStatus(BaseModel):
    available: bool
    name: str | None
    vram_total_mb: int | None


class SttStatus(BaseModel):
    provider: str
    model: str
    device: str


class LlmStatus(BaseModel):
    """Phase 43: `remote` is true for an Ollama on another PC, `host` names it (null when local)."""

    provider: str
    model: str
    reachable: bool
    remote: bool = False
    host: str | None = None


class StorageStatus(BaseModel):
    """Phase 31: `warning` is a localized message when the database is in a OneDrive folder.

    Phase 32: `size_bytes` is the database file (with its WAL), `audio_cache_bytes` the WAVs
    built from it; both null for the file backend.
    """

    backend: Literal["sqlite", "files"]
    database: str | None  # absolute path of the SQLite database
    warning: str | None
    size_bytes: int | None = None  # the database with its WAL files (phase 38)
    audio_cache_bytes: int = 0  # `OUTPUT_DIR/cache/` (phase 38)


class WorkerHealth(BaseModel):
    """Phase 44: the VozAta worker of `WORKER_URL` (null in `Health` when it is empty)."""

    url: str
    reachable: bool
    version: str | None = None
    # phase 46: where `speech`, `speakers` and `translation` run now: `worker`, `local` (another
    # provider is chosen) or `fallback` (the worker is chosen but does not answer: this PC runs it)
    tasks: dict[str, Literal["worker", "local", "fallback"]] = {}


class FoundWorkerOut(BaseModel):
    """Phase 47: a worker that answered the discovery broadcast (no secret)."""

    id: str
    name: str
    url: str
    version: str
    gpu: str | None = None


class WorkersFound(BaseModel):
    workers: list[FoundWorkerOut]


class PairWorkerRequest(BaseModel):
    url: str = Field(pattern=r"^https?://")
    code: str = Field(min_length=1, max_length=32)


class PairedWorkerOut(BaseModel):
    id: str | None
    name: str
    url: str


class Health(BaseModel):
    engine: Literal["ok"] = "ok"
    version: str
    gpu: GpuStatus
    stt: SttStatus
    llm: LlmStatus
    storage: StorageStatus
    worker: WorkerHealth | None = None


class Device(BaseModel):
    id: int
    name: str
    sample_rate: int
    channels: int


class Devices(BaseModel):
    inputs: list[Device]
    loopbacks: list[Device]
    default_input_id: int | None
    default_loopback_id: int | None


class StartSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mic_device_id: int | None = None
    system_device_id: int | None = None
    language: ConversationLanguageValue | None = None
    template: str | None = None  # phase 20
    vocabulary: list[str] | None = None  # phase 19
    translate_to: TranslationTargetValue | None = None  # phase 29; None = TRANSLATE_TO
    title: str | None = None  # phase 35; trimmed, at most 200 characters; blank = untitled
    live_transcription: bool | None = None  # phase 41; None = LIVE_TRANSCRIPTION


class SessionSummary(BaseModel):
    id: str
    status: str
    started_at: str | None
    ended_at: str | None
    duration_seconds: float | None
    language: str | None
    has_minutes: bool
    title: str | None = None  # phase 35; None = untitled
    # phase 36 (meetings list): speakers found by diarization, any action item, minutes template
    speaker_count: int = 0
    has_action_items: bool = False
    template: str | None = None
    # phase 40: {state, percent, step, position?} while queued or processed; None otherwise
    processing: dict[str, Any] | None = None


class SessionDetail(SessionSummary):
    """`SessionSummary` + every `session.json` field + files + absolute folder + audio.

    `files` and `folder` come from the file backend; a backend without folders leaves them null.
    `audio` maps each playable track (`mic`, `system`, `mixed`) to its duration in seconds; play
    it from `GET /sessions/{id}/audio/{track}` (phase 32).
    """

    model_config = ConfigDict(extra="allow")

    files: list[str] | None = None
    folder: str | None = None
    storage: Literal["sqlite", "files"] = "files"  # phase 31
    audio: dict[Literal["mic", "system", "mixed"], float] = {}  # phase 32


class SessionList(BaseModel):
    items: list[SessionSummary]
    total: int


class SessionDay(BaseModel):
    """One local day of `GET /sessions?from=&to=` (phase 36)."""

    date: str  # YYYY-MM-DD, local time zone
    total_seconds: float
    items: list[SessionSummary]


class SessionDays(BaseModel):
    """Meetings of a date range grouped by local start day, newest first (phase 36)."""

    days: list[SessionDay]
    total_seconds: float
    has_earlier: bool  # sessions started before `from` exist
    storage: Literal["sqlite", "files"] = "files"  # what `DELETE /sessions/{id}` does


class WordModel(BaseModel):
    text: str
    start: float
    end: float
    probability: float


class TranslationModel(BaseModel):
    language: str
    text: str


class Segment(BaseModel):
    segment_id: str
    channel: Literal["mic", "system"]
    speaker_id: str
    label: str
    start: float
    end: float
    text: str
    edited: bool
    words: list[WordModel]
    translation: TranslationModel | None = None  # phase 29


class Transcript(BaseModel):
    source: Literal["raw", "diarized", "edited"]
    segments: list[Segment]


class SegmentText(BaseModel):
    """A corrected segment of `PUT /sessions/{id}/transcript`; other `Segment` keys are ignored."""

    model_config = ConfigDict(extra="ignore")

    segment_id: str
    text: str


class EditTranscript(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segments: list[SegmentText]


class TranscriptEdited(BaseModel):
    source: Literal["edited"] = "edited"


class Minutes(BaseModel):
    markdown: str


class SearchHitModel(BaseModel):
    session_id: str
    segment_id: str
    start: float
    speaker_id: str
    label: str
    snippet: str  # matches wrapped in \u0002 ... \u0003


class SearchResults(BaseModel):
    hits: list[SearchHitModel]


class VoiceCommandOut(BaseModel):
    """Phase 50: `action` is `minutes` or `ask` (`question` then required)."""

    phrase: str
    action: str
    question: str | None = None


class VoiceCommandsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commands: list[VoiceCommandOut]


class VoiceCommandsView(BaseModel):
    commands: list[VoiceCommandOut]
    defaults: list[VoiceCommandOut]


class PartialMinutesRequest(BaseModel):
    """Phase 48: seconds since the meeting start; `end` None is up to the transcript's end."""

    model_config = ConfigDict(extra="forbid")

    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, gt=0)
    template: str | None = None


class PartialMinutesStarted(BaseModel):
    partial_id: str


class PartialMinutesSummary(BaseModel):
    id: str
    created_at: str
    start: float
    end: float
    origin: str
    template: str | None = None


class PartialMinutesList(BaseModel):
    items: list[PartialMinutesSummary]


class PartialMinutesDetail(PartialMinutesSummary):
    markdown: str


class RequestEntryOut(BaseModel):
    """Phase 59: one request of a meeting's history (`RequestEntry`)."""

    id: str
    created_at: str
    at: float | None
    kind: str
    source: str
    text: str
    status: str
    result_id: str | None = None
    message: str | None = None
    finished_at: str | None = None


class RequestList(BaseModel):
    items: list[RequestEntryOut]


class RegenerateMinutes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: str | None = None  # phase 20


class UpdateSession(BaseModel):
    """`PATCH /sessions/{id}` (phase 35): the meeting title; null or blank clears it."""

    model_config = ConfigDict(extra="forbid")

    title: str | None


class ActionItemModel(BaseModel):
    """An action item (phase 23); `exported_url` is set once it was exported."""

    id: str
    description: str
    owner: str | None
    due: str | None
    source_segment_ids: list[str]
    exported_url: str | None


class ActionItems(BaseModel):
    """`GET|PUT /sessions/{id}/action-items`; `targets` are the configured export targets."""

    items: list[ActionItemModel]
    targets: list[str]


class ActionItemEdit(BaseModel):
    """One edited item of `PUT /sessions/{id}/action-items`; other `ActionItem` keys are ignored."""

    model_config = ConfigDict(extra="ignore")

    id: str
    description: str = Field(max_length=1000)
    owner: str | None = Field(default=None, max_length=200)
    due: str | None = Field(default=None, max_length=100)


class EditActionItems(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ActionItemEdit]


class ExportActionItems(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str
    item_ids: list[str] = Field(min_length=1)


class CreatedTask(BaseModel):
    item_id: str
    url: str


class FailedTask(BaseModel):
    item_id: str
    error: str


class ExportedActionItems(BaseModel):
    created: list[CreatedTask]
    failed: list[FailedTask]


class Vocabulary(BaseModel):
    """`GET|PUT /vocabulary` (phase 19)."""

    model_config = ConfigDict(extra="forbid")

    terms: list[str]


class SpeakerNameUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=200)  # empty or null: the default label


class SpeakersUpdate(BaseModel):
    """`PUT /sessions/{id}/speakers` (phase 16)."""

    model_config = ConfigDict(extra="forbid")

    speakers: dict[str, SpeakerNameUpdate]


class SpeakerInfo(BaseModel):
    name: str | None
    default_label: str


class Speakers(BaseModel):
    """Every speaker of the transcript, in order of first appearance (phase 16)."""

    speakers: dict[str, SpeakerInfo]


class TemplateInfo(BaseModel):
    id: str
    name: str


class SettingSchema(BaseModel):
    key: str
    type: str
    default: Any
    choices: list[str] | None
    secret: bool
    group: str
    applies: str  # "next_session" | "restart"
    options_source: str | None = None  # a `GET /settings/options` list (phase 38)


class SettingsUpdate(BaseModel):
    values: dict[str, Any]


class SettingsUpdated(BaseModel):
    values: dict[str, Any]
    restart_required: list[str]


class SettingsView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    values: dict[str, Any]
    schema_: list[SettingSchema] = Field(alias="schema")


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class AskQuestion(BaseModel):
    """`POST /ask` (phase 24); no `session_id` asks about every session."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    session_id: str | None = None


class AskAccepted(BaseModel):
    answer_id: str


class SettingOptionItem(BaseModel):
    """Phase 38: one entry of a `GET /settings/options` list."""

    value: str
    label: str
    available: bool


class SettingOptionsView(BaseModel):
    """Phase 38: lists by `options_source`; `reachable` false: the service did not answer."""

    options: dict[str, list[SettingOptionItem]]
    reachable: dict[str, bool]


class ConnectionTestResult(BaseModel):
    """Phase 38: `POST /settings/test/{target}`; `message` is localized and never holds a secret."""

    ok: bool
    message: str


class CacheCleared(BaseModel):
    """Phase 38: `DELETE /storage/cache`."""

    freed_bytes: int


class AudioImported(BaseModel):
    """Phase 60: `POST /sessions/import-audio`; the meeting is queued for processing."""

    id: str


class BundleImported(BaseModel):
    """Phase 39: `POST /sessions/import` (`mode`: imported | audio_restored)."""

    id: str
    mode: str


class MigrationErrorModel(BaseModel):
    folder: str
    reason: str  # unreadable_json | unreadable_wav | unsupported_wav | id_in_use
    message: str  # localized
    detail: str


class Migration(BaseModel):
    """The folder import of phase 33 (`state`: disabled | idle | running | done | no_space |
    failed)."""

    state: str
    done: int
    total: int
    current: str | None
    paused: bool
    imported: int
    skipped: int
    needed_bytes: int | None
    free_bytes: int | None
    message: str | None  # localized, when it stopped for lack of disk space
    errors: list[MigrationErrorModel]
