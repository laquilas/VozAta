"""Pydantic models for every request and response shape tagged 06 in the API contract."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ConversationLanguageValue = Literal["en", "pt", "es", "auto"]


class GpuStatus(BaseModel):
    available: bool
    name: str | None
    vram_total_mb: int | None


class SttStatus(BaseModel):
    provider: str
    model: str
    device: str


class LlmStatus(BaseModel):
    provider: str
    model: str
    reachable: bool


class Health(BaseModel):
    engine: Literal["ok"] = "ok"
    version: str
    gpu: GpuStatus
    stt: SttStatus
    llm: LlmStatus


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


class SessionSummary(BaseModel):
    id: str
    status: str
    started_at: str | None
    ended_at: str | None
    duration_seconds: float | None
    language: str | None
    has_minutes: bool


class SessionDetail(SessionSummary):
    """`SessionSummary` + every `session.json` field + files + absolute folder."""

    model_config = ConfigDict(extra="allow")

    files: list[str]
    folder: str


class SessionList(BaseModel):
    items: list[SessionSummary]
    total: int


class WordModel(BaseModel):
    text: str
    start: float
    end: float
    probability: float


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


class RegenerateMinutes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: str | None = None  # phase 20


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
