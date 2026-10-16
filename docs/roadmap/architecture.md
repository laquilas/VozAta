# Architecture

Shared reference for every phase. If a phase changes something described here, it updates this file
in the same branch.

## 1. Environment facts (verified 2026-10-15)

| Item | State |
|------|-------|
| OS | Windows 11 Pro |
| Python | 3.13, virtualenv at repo root `.venv/` (reused by the engine — do not move it). On the reference machine `.venv` is a directory junction to `<local-venv>` (a virtualenv outside OneDrive), because the repo lives in OneDrive |
| Installed in `.venv` | faster-whisper 1.2, ctranslate2, nvidia-cublas-cu12, nvidia-cudnn-cu12 9, PyAudioWPatch, soxr, numpy 2 |
| GPU | NVIDIA RTX 3050 Laptop, **6 GB VRAM** |
| Tools | ffmpeg, git, gh, docker |
| Missing | **.NET SDK** (install .NET 10 LTS in phase 07), Ollama CLI not on PATH (install + `ollama pull` in phase 04) |
| Repo | GitHub `laquilas/VozAta` (public), default branch `main`; CI on pull requests into and pushes to `main` |

### Legacy code (`__legacy__/`, read-only reference)

Working prototypes on this machine, **not published** (git-ignored; copy them from `<prototype-workspace>/__legacy__`). Adapt their logic; never import from them.

| File | Reuse |
|------|-------|
| `__legacy__/gravar_reuniao.py` | `Fonte`: PyAudioWPatch callback → queue, downmix, `soxr.ResampleStream` to 16 kHz, clock-aligned WAV writing with silence fill (loopback delivers no data when nothing plays), `finalizar` pads both WAVs to equal length. `misturar_estereo`: streamed L/R mix in 60 s blocks. Device discovery: `get_default_input_device_info()`, `get_default_wasapi_loopback()`. |
| `__legacy__/transcrever.py` | CUDA DLL path setup (`os.add_dll_directory` for `nvidia/cublas/bin` and `nvidia/cudnn/bin` in site-packages); `carregar_modelo`: GPU load + 1 s warm-up probe, fallback to CPU `small` int8. |
| `__legacy__/transcricao_ao_vivo_v2.py` | Live worker loop and RMS-based speech gating (superseded by the stitcher). |

## 2. Repository layout (target)

```
.venv/                      shared Python virtualenv
__legacy__/                 read-only prototypes
docs/roadmap/               this roadmap
engine/
  pyproject.toml
  .env.example
  src/vozata/
    __main__.py             CLI: record | minutes | recover | reindex | serve
    config.py               Settings (only module reading env vars)
    domain.py               dataclasses / enums (no I/O)
    ports.py                typing.Protocol interfaces
    bootstrap.py            composition root + provider registries
    i18n.py                 TomlLocalizer
    labels.py               SpeakerLabeler (speaker_id → display label)
    formatting.py           timestamps, transcript line rendering
    language.py             conversation-language resolution
    vocabulary.py           glossary store + hint building (19)
    locales/{en,pt-BR,es}.toml
    session.py              RecordingSession
    audio/                  devices.py, capture.py, clock.py, wav_writer.py, chunker.py, mixer.py, levels.py
    transcription/          cuda.py, faster_whisper.py, openai_compatible.py, retry.py,
                            stitcher.py, language_lock.py, worker.py, echo.py
    output/                 sinks.py
    llm/                    ollama.py
    minutes/                generator.py, prompts.py, template_repository.py, templates/, action_items.py
    diarization/            pyannote.py, assign.py, embedder.py, live.py
    storage/                session_store.py, recovery.py, search_index.py
    export/                 markdown.py, docx.py, pdf.py, fonts/, tasks/{azure_devops,github}.py
    qa/                     retriever.py, answerer.py
    api/                    app.py, schemas.py, ws.py, session_manager.py, system_info.py, routes/*.py
  tests/                    mirrors src/
ui/
  VozAta.sln
  src/VozAta.Client/        IEngineClient, DTOs, WebSocket event stream
  src/VozAta.Desktop/       Avalonia app (Views, ViewModels, Services, Resources/Strings*.resx)
  tests/VozAta.Desktop.Tests/
```

## 3. SOLID mapping

- **S** — one responsibility per class: capture, WAV writing, chunking, transcription, stitching,
  mixing, minutes generation, sinks, storage, export are separate units.
- **O** — providers (STT, LLM, diarizer, task exporter, mixer, export format) are registered in
  factory registries in `bootstrap.py`; adding one never edits `RecordingSession` or the API.
- **L** — every implementation honours its port's contract (e.g. all transcribers return
  chunk-relative word timestamps and an empty result on silence; none raise for silence).
- **I** — small Protocols with 1–3 methods each.
- **D** — orchestrators (`RecordingSession`, `MinutesGenerator`, API routes) depend on ports only;
  `bootstrap.py` (engine) and `App.axaml.cs` (UI) are the only places that know concrete classes.

## 4. Domain types (`domain.py`)

```python
class Channel(StrEnum): MIC = "mic"; SYSTEM = "system"
class SessionStatus(StrEnum): RECORDING, PAUSED, FINALIZING, DONE, INTERRUPTED  # lowercase values
class AppLanguage(StrEnum): EN = "en"; PT_BR = "pt-BR"; ES = "es"
class ConversationLanguage(StrEnum): EN = "en"; PT = "pt"; ES = "es"; AUTO = "auto"
class ChunkMode(StrEnum): VAD = "vad"; FIXED = "fixed"

@dataclass(frozen=True) class AudioChunk:      channel, start: float, samples: np.ndarray  # float32 mono, SAMPLE_RATE
                                               complete: bool = False  # ends in a pause (27)
@dataclass(frozen=True) class Word:            text, start, end, probability
@dataclass(frozen=True) class TranscriptionResult: words: tuple[Word, ...], language: str | None
@dataclass(frozen=True) class TranscriptSegment:
    segment_id: str; channel: Channel; speaker_id: str; start: float; end: float
    text: str; words: tuple[Word, ...]
@dataclass(frozen=True) class SpeakerTurn:     start, end, speaker_index: int
@dataclass(frozen=True) class ExportDocument:  title, details, minutes_title, minutes_markdown, minutes_blocks: list[Block],
                                               no_minutes, transcript_title, columns, rows: list[Row]  # localized (11)
@dataclass(frozen=True) class ActionItem:      description, owner: str | None, due: str | None, source_segment_ids
```

All times are **seconds since session start** (float).

Helpers: `default_conversation_language(app_language)` maps `APP_LANGUAGE` to the default spoken
language (`pt-BR` → `pt`). `AudioChunk` uses identity equality (`eq=False`) because of its array field.

## 5. Ports (`ports.py`)

```python
class AudioSource(Protocol):
    def start(self, on_samples: Callable[[np.ndarray, float], None]) -> None: ...  # samples, session time
    def stop(self) -> None: ...
class AudioSink(Protocol):           # AlignedWavWriter
    def write(self, samples: np.ndarray, at: float) -> None: ...
    def finalize(self, total_seconds: float) -> None: ...
class Transcriber(Protocol):
    def transcribe(self, samples: np.ndarray, language: str | None, hints: str | None = None) -> TranscriptionResult: ...
    def close(self) -> None: ...     # releases GPU memory
class TranscriptSink(Protocol):
    def emit(self, segment: TranscriptSegment) -> None: ...
    def close(self) -> None: ...
class AudioMixer(Protocol):
    def mix(self, mic: Path, system: Path, destination: Path) -> None: ...
class Chunker(Protocol):             # FixedWindowChunker (01), VadChunker (27)
    paused: bool
    def feed(self, samples: np.ndarray, at: float) -> None: ...
    def flush(self) -> None: ...
    def buffered(self) -> AudioChunk | None: ...  # copy of the audio not emitted yet (28)
class SpeechDetector(Protocol):      # SileroSpeechDetector (27); unpadded spans in seconds
    def speech_spans(self, samples: np.ndarray) -> list[tuple[float, float]]: ...
class LanguageModel(Protocol):
    def generate(self, system: str, prompt: str, json_schema: dict | None = None) -> str: ...
    def stream(self, system: str, prompt: str) -> Iterator[str]: ...
    def is_available(self) -> bool: ...
    def release(self) -> None: ...   # after a job: unload per OLLAMA_KEEP_ALIVE (25)
class Diarizer(Protocol):
    def diarize(self, wav: Path, min_speakers: int | None, max_speakers: int | None) -> list[SpeakerTurn]: ...
    def close(self) -> None: ...
class SpeakerEmbedder(Protocol):
    def embed(self, samples: np.ndarray) -> np.ndarray: ...
class DocumentExporter(Protocol):     # Markdown, DOCX, PDF (11)
    media_type: str; extension: str
    def export(self, document: ExportDocument) -> bytes: ...  # built once by export.document.build_document
class TaskExporter(Protocol):
    def export(self, items: Sequence[ActionItem], session_title: str) -> list[str]: ...  # created URLs
class Localizer(Protocol):
    def t(self, key: str, /, **params: object) -> str: ...  # key is positional-only
class SessionObserver(Protocol):     # console (05), WebSocket broadcaster (06); called from worker threads
    def on_status(self, status: SessionStatus, duration_seconds: float) -> None: ...
    def on_level(self, channel: Channel, rms_db: float) -> None: ...
    def on_segment(self, segment: TranscriptSegment) -> None: ...
    def on_language_detected(self, language: ConversationLanguage) -> None: ...
    def on_minutes_ready(self, session_id: str) -> None: ...
    def on_model_loading(self, loading: bool) -> None: ...  # speech model loading while recording (26)
    def on_partial(self, channel: Channel, speaker_id: str, start: float, text: str) -> None: ...  # interim (28)
    def on_error(self, code: str, message: str) -> None: ...  # message is localized
```

Ports are added by the phase that first needs them; the list above is the target.

## 6. Data flow

```
WasapiSource(mic) ─┬─> AlignedWavWriter → mic.wav
                   └─> Chunker (vad | fixed) ─┐
WasapiSource(sys) ─┬─> AlignedWavWriter → system.wav
                   └─> Chunker (vad | fixed) ─┴─> Queue[AudioChunk]
                                               └─> TranscriptionWorker (single thread, one GPU)
                                                    └─> CarryOverStitcher (one per channel)
                                                         └─> Transcriber
                                                    └─> [EchoFilter] → [LiveSpeakerTagger]
                                                    └─> CompositeSink → Console | Jsonl | Markdown | WebSocket
```

**Chunkers**: `CHUNKERS[CHUNK_MODE]` in `bootstrap.py` builds one per channel through
`SessionComponents.chunker_factory`. `VadChunker` (27, default) asks a `SpeechDetector`
(`SileroSpeechDetector`, CPU) every 0.25 s and cuts in the middle of pauses ≥ `VAD_MIN_SILENCE_MS`,
marking those chunks `complete`; `FixedWindowChunker` cuts every `CHUNK_SECONDS`.

**Interim text** (phase 28, `LIVE_PARTIALS`): when the chunk queue is empty, the worker previews
each channel's uncommitted audio (stitcher carry + `Chunker.buffered()`, copied under the track
lock) at most once per `PARTIAL_INTERVAL_SECONDS`, only with ≥ 1 s of voiced audio, and sends
changed text through `on_partial` (API `partial`), never to the transcript files. A segment
replaces it; an empty `partial` clears it when the channel's next chunk commits nothing, and at
stop.

**Threads**: one capture callback + one consumer thread per source; one transcription worker;
the API runs in the asyncio loop and receives events through a thread-safe broadcaster. If the
chunk queue backlog exceeds 3 chunks per channel, log a warning (transcription slower than real time).

**Start** (capture first, phase 26): create the session folder, start the clock, then open each
source with a timeout (`SOURCE_OPEN_TIMEOUT`, 20 s): a WASAPI open can hang in
the driver. A source that fails or times out aborts the start (`SessionStartError` with code
`device_timeout` / `device_failed` and a localized message), closes everything and deletes the
empty session folder. Once every source is open the status is `recording` and the transcription
worker loads the transcriber on its own thread (`on_model_loading(True/False)`, API event
`model_loading`); chunks captured meanwhile wait in the queue and are transcribed afterwards
(the backlog warning stays silent while catching up). A failed load reports `error`
`model_failed`; the WAVs keep recording and the queued chunks are dropped.

**PortAudio thread**: WASAPI binds PortAudio's host state to the thread that initialized it (COM);
streams opened from another thread fail with "Unanticipated host error" (-9999). `bootstrap.py`
creates one `PortAudioThread` per session that owns the `PyAudio` instance and runs device lookups,
stream opens and `terminate()`; the session releases it once capture has stopped.

**Stop order** (fixed, enforced by `RecordingSession.stop()`):
1. Stop sources; flush chunkers (last partial window); `status = finalizing`.
2. Drain the queue; `stitcher.flush()` for each channel.
3. Finalize WAVs to the same length (max written samples); run `AudioMixer` → `mixed.wav`.
4. `transcriber.close()` (free VRAM).
5. If enabled: diarize `system.wav` → relabel → `diarizer.close()`.
6. If enabled: `MinutesGenerator` → `minutes.md`, then `llm.release()` (Ollama unloads per
   `OLLAMA_KEEP_ALIVE`, also after a failed job); index the session for search.
7. `status = done`, `ended_at` set in `session.json`.

**VRAM rule (6 GB)**: never keep Whisper, the diarizer and the Ollama model loaded at the same
time; steps 4 → 5 → 6 enforce that. With `WHISPER_KEEP_LOADED` (`serve`, phase 26) a
`SharedTranscriber` keeps Whisper between sessions only when no minutes follow; it is unloaded
before session minutes, before `POST /sessions/{id}/minutes` and when the API stops.

**Pause/resume**: while paused, sources keep running (keeps the clock aligned) but chunkers drop
audio and WAV writers write silence; a `paused` marker is recorded in `session.json`.

## 7. Stitching algorithm (`CarryOverStitcher`)

Problem: fixed `CHUNK_SECONDS` windows (and forced VAD cuts) cut words and sentences. Solution: carry the unfinished
tail audio into the next window and re-transcribe it.

```
state per channel: pending: np.ndarray (may be empty), pending_start: float

on_chunk(chunk):
    audio = concat(pending, chunk.samples); audio_start = pending_start if pending else chunk.start
    if pending is empty and rms(audio) < SILENCE_RMS_THRESHOLD: return []        # no STT call
    result = transcriber.transcribe(audio, language, hints)
    if no words: pending = empty; return []
    if chunk.complete: pending = empty; return [segment(words, offset=audio_start)]  # VAD cut (27)
    duration = len(audio) / SAMPLE_RATE
    safe = [w for w in words if w.end <= duration - TAIL_MARGIN_SECONDS]
    cut_word = last w in safe ending with . ? ! (or … )
            or last w in safe where next_word.start - w.end >= PAUSE_GAP_SECONDS
            or None
    if cut_word is None and duration >= MAX_CARRY_SECONDS: cut_word = words[-1]   # force
    if cut_word is None: pending, pending_start = audio, audio_start; return []
    committed = words up to and including cut_word
    cut_time = midpoint(cut_word.end, next_word.start)
            or voiced_end(cut_word.end) if it is the last word   # see note below
    pending = audio[cut_time * SAMPLE_RATE :]; pending_start = audio_start + cut_time
    return [segment(committed, offset=audio_start)]

flush(): transcribe pending (if any) and commit every word.

partial(tail):  # interim text (28): pending + chunker.buffered(), ≥ 1 s voiced; commits nothing,
                # does not feed the language lock
```

Committed audio is dropped, so no text is duplicated.

Whisper word end timestamps run early. When the cut word is the last word of the window, `voiced_end` extends the
cut through still-voiced 10 ms frames (RMS ≥ `SILENCE_RMS_THRESHOLD`), at most 0.3 s, so the tail of that word is
not carried and re-transcribed as a fragment (found by the phase 03 GPU smoke test: "meeting." + "eating."). Re-transcribing the carried tail costs at most
`MAX_CARRY_SECONDS` of extra audio per window.

## 8. Data model and session folder

`OUTPUT_DIR/YYYYMMDD_HHMMSS/` (the folder name is the session id):

| File | Written by | Notes |
|------|-----------|-------|
| `session.json` | 05 | metadata, updated on every status change |
| `mic.wav`, `system.wav` | 02 / 05 | mono 16-bit, `SAMPLE_RATE`, equal length |
| `mixed.wav` | 02 / 05 | `MIX_MODE=mono` (sum with headroom, clipped) or `stereo` (L = mic, R = system) |
| `transcript.jsonl` | 03 / 05 | raw, append-only, one segment per line |
| `transcript.md` | 03 / 05 | human-readable, `[hh:mm:ss] Label: text` |
| `minutes.md` | 04 / 05 | generated minutes |
| `transcript.diarized.jsonl` | 14 | system segments re-split and tagged `system:<n>` |
| `speakers.json` | 14 / 16 | `{"system:1": {"name": null}}` (display label comes from the localizer unless `name` is set) |
| `transcript.edited.jsonl` | 21 | full copy of the best transcript with user edits |
| `action_items.json` | 23 | extracted items + export results |

`OUTPUT_DIR/index.db` — SQLite FTS5 search index (22).

`session.json` (schema_version 1):

```json
{
  "schema_version": 1,
  "id": "20261015_202358",
  "status": "done",
  "started_at": "2026-10-15T20:23:58-03:00",
  "ended_at": "2026-10-15T21:10:02-03:00",
  "duration_seconds": 2764.2,
  "language": "pt", "language_source": "selected",
  "app_language": "en",
  "template": "general",
  "vocabulary": ["Avalonia", "N5 Sensors"],
  "devices": {"mic": "Headset Microphone", "system": "Headphones [Loopback]"},
  "pauses": [{"start": 120.5, "end": 180.0}],
  "settings": {"CHUNK_MODE": "vad", "CHUNK_SECONDS": 5, "WHISPER_MODEL": "large-v3-turbo", "MIX_MODE": "mono"}
}
```

`transcript.jsonl` line:

```json
{"segment_id": "mic-000042", "channel": "mic", "speaker_id": "mic", "start": 83.12, "end": 87.90,
 "text": "We will ship the beta on Friday.",
 "words": [{"text": "We", "start": 83.12, "end": 83.30, "probability": 0.98}]}
```

Segments in `transcript.edited.jsonl` (21) may also carry `"edited": true` (then `words` is empty).

**Transcript precedence**: every reader (minutes, export, search, Q&A, UI viewer) loads the
transcript through `SessionStore.load_transcript(session_id)`, which returns the first existing file
of `transcript.edited.jsonl` → `transcript.diarized.jsonl` → `transcript.jsonl`. Raw capture data
(`transcript.jsonl`, WAVs) is never rewritten after the session ends.

`duration_seconds` is the recorded length (session time when capture stopped, pauses included),
written at stop; `ended_at` is later, after finalization. `language` / `language_source` are written only when known: at start for a fixed language
(`selected`), or when `auto` locks one (`detected`); a session where `auto` never locked a language
has neither key. `template` (20) and `vocabulary` (19) are added by their phases.

`speaker_id` is `mic` for the microphone and `system` until diarization assigns `system:<n>`.
Display labels are **never** stored in raw data; they are resolved from `speaker_id` +
`speakers.json` + localizer at render time.

## 9. Configuration keys

Only `config.py` reads the environment (`.env` via python-dotenv). Invalid values fail fast with a
clear message. `GET/PUT /settings` (06/10) reads and writes the same keys to `.env`.

| Key | Default | Owner phase | Meaning |
|-----|---------|-------------|---------|
| `CHUNK_SECONDS` | `5` | 01 | transcription window length |
| `TAIL_MARGIN_SECONDS` | `0.6` | 03 | words ending this close to the window end are not committed |
| `PAUSE_GAP_SECONDS` | `0.5` | 03 | gap that counts as a phrase boundary |
| `MAX_CARRY_SECONDS` | `15` | 03 | force commit when carried audio exceeds this |
| `SILENCE_RMS_THRESHOLD` | `0.01` | 03 | below this a window is skipped |
| `SAMPLE_RATE` | `16000` | 01 | internal sample rate |
| `APP_LANGUAGE` | `en` | 01 | `en` / `pt-BR` / `es` |
| `TRANSCRIPTION_LANGUAGE` | *(empty)* | 01 | default conversation language `en`/`pt`/`es`/`auto`; empty = derived from `APP_LANGUAGE` |
| `MIC_LABEL` / `SYSTEM_LABEL` | *(empty)* | 01 | override localized labels |
| `OUTPUT_DIR` | `recordings` | 01 | sessions root |
| `STT_PROVIDER` | `faster_whisper` | 03 | registry key |
| `WHISPER_MODEL` | `large-v3-turbo` | 03 | GPU model |
| `WHISPER_DEVICE` | `auto` | 03 | `auto` / `cuda` / `cpu` |
| `WHISPER_COMPUTE_TYPE` | `int8_float16` | 03 | CTranslate2 compute type on GPU |
| `WHISPER_CPU_MODEL` | `small` | 03 | fallback model on CPU |
| `MIX_MODE` | `mono` | 02 | `mono` / `stereo` |
| `LLM_PROVIDER` | `ollama` | 04 | registry key |
| `OLLAMA_URL` | `http://localhost:11434` | 04 | |
| `OLLAMA_MODEL` | `qwen2.5:7b` | 04 | must fit 6 GB VRAM |
| `LLM_MAX_CHARS` | `12000` | 04 | above this, map-reduce summarization |
| `GENERATE_MINUTES` | `true` | 05 | generate minutes at stop |
| `API_HOST` / `API_PORT` | `127.0.0.1` / `8765` | 06 | never bind to 0.0.0.0 |
| `OPENAI_STT_URL` / `OPENAI_STT_KEY` / `OPENAI_STT_MODEL` | — | 12 | external STT |
| `DIARIZATION_ENABLED` | `false` | 14 | |
| `DIARIZATION_PROVIDER` | `pyannote` | 14 | |
| `DIARIZATION_DEVICE` | `auto` | 14 | `auto` / `cuda` / `cpu` |
| `HF_TOKEN` | *(empty)* | 14 | Hugging Face token for pyannote models |
| `MIN_SPEAKERS` / `MAX_SPEAKERS` | *(empty)* | 14 | hints |
| `LIVE_DIARIZATION_ENABLED` | `false` | 15 | |
| `SPEAKER_SIMILARITY_THRESHOLD` | `0.7` | 15 | cosine similarity for live clustering |
| `AUTOSAVE_SECONDS` | `10` | 17 | `session.json` heartbeat |
| `ECHO_DEDUPE_ENABLED` | `true` | 18 | drop echoed mic segments |
| `ECHO_SIMILARITY` | `0.85` | 18 | text similarity to treat a mic segment as echo |
| `ECHO_HOLD_SECONDS` | `CHUNK_SECONDS + 3` | 18 | how long mic segments wait for a matching system segment |
| `VOCABULARY_FILE` | *(empty)* | 19 | one term per line |
| `MINUTES_TEMPLATE` | `general` | 20 | default template |
| `LOW_CONFIDENCE_THRESHOLD` | `0.5` | 21 | word probability below this is highlighted |
| `EXTRACT_ACTION_ITEMS` | `true` | 23 | extract action items after minutes |
| `AZDO_ORG_URL` / `AZDO_PROJECT` / `AZDO_PAT` | — | 23 | Azure DevOps export |
| `GITHUB_REPO` / `GITHUB_TOKEN` | — | 23 | GitHub Issues export |
| `OLLAMA_KEEP_ALIVE` | `0` | 25 | how long Ollama keeps the model loaded after a minutes job |
| `WHISPER_KEEP_LOADED` | `false` | 26 | keep the transcriber loaded between sessions in `serve` |
| `CHUNK_MODE` | `vad` | 27 | `vad` (cut at pauses) / `fixed` (`CHUNK_SECONDS` windows) |
| `VAD_THRESHOLD` | `0.5` | 27 | Silero speech probability threshold |
| `VAD_MIN_SILENCE_MS` | `600` | 27 | pause that ends a chunk |
| `VAD_MIN_CHUNK_SECONDS` / `VAD_MAX_CHUNK_SECONDS` | `1` / `15` | 27 | chunk length bounds |
| `VAD_SPEECH_PAD_MS` | `200` | 27 | audio kept around detected speech |
| `LIVE_PARTIALS` | `true` | 28 | send interim text while speaking |
| `PARTIAL_INTERVAL_SECONDS` | `1.5` | 28 | minimum time between partials per channel |
| `TRANSLATE_TO` / `TRANSLATION_PROVIDER` | *(empty)* / *(chosen in 29)* | 29 | live translation target (empty = off) and provider |
| `CONTEXT_PROMPT_CHARS` | `200` | 19 | rolling context prompt length (0 = off) |

Secrets (`*_KEY`, `*_TOKEN`, `*_PAT`) are never logged, never returned by `GET /settings`
(masked), and `.env` is git-ignored.

## 10. Internationalization

- Supported app languages: `en` (default), `pt-BR`, `es`. Adding one = new locale files in the
  engine and the UI + enum entry; key-parity tests enforce completeness.
- `APP_LANGUAGE` drives UI strings, speaker labels, minutes headings, LLM prompts and **the
  language the minutes are written in**.
- **Conversation language** (spoken language) is separate and chosen **per session**: UI dropdown
  next to Start (07), `record --language` (05), `language` in `POST /sessions` (06). Values
  `en` / `pt` / `es` / `auto`; default from `TRANSCRIPTION_LANGUAGE`, or derived from
  `APP_LANGUAGE` (`pt-BR` → `pt`). A fixed language makes Whisper faster and prevents it from
  drifting between languages on short windows.
- `auto`: run language detection on the first windows until ≥ 3 s of speech, then **lock** it for
  the session; emit `language_detected`; store `language` + `language_source: "detected"`.
- Localized defaults: labels `Me`/`Others` (en), `Eu`/`Outros` (pt-BR), `Yo`/`Otros` (es);
  diarized speakers `User {n}` / `Usuário {n}` / `Usuario {n}`.
- Engine: `TomlLocalizer` over `locales/<lang>.toml` (flat dotted keys, `{param}` placeholders).
  UI: `.resx` resources, runtime switch from settings.

## 11. Speaker identification

- Only the **system channel** is diarized; the microphone is always the local user (`mic`).
- Post-session (14): `Diarizer` runs on `system.wav` after Whisper is released. Each system segment
  gets the speaker with the largest time overlap; when a segment spans a speaker change it is split
  at word boundaries using word timestamps. Speakers are numbered by first appearance
  (`system:1`, `system:2`, …) and the result is written to `transcript.diarized.jsonl`
  (`transcript.jsonl` stays untouched).
- Live (15): speaker embedding per committed system segment, cosine similarity against running
  centroids; above `SPEAKER_SIMILARITY_THRESHOLD` → existing speaker, else new one. The
  post-session pass is authoritative and emits `speakers_relabeled`.
- Renaming (16): `speakers.json` maps ids to names; raw data untouched.
- Limits: overlapping speech and several people sharing one room microphone reduce accuracy;
  pyannote models require a Hugging Face token and accepting the model terms.

## 12. Minutes

- Input: merged mic + system segments sorted by `start`, rendered as `[hh:mm:ss] Label: text`
  (edited transcript preferred when present).
- Output sections (localized headings): Context, Summary, Topics, Decisions, Action items
  (owner, due date), Open issues. Templates (20) change sections and instructions.
- If the transcript exceeds `LLM_MAX_CHARS`: map (summarize each part into notes) → reduce
  (minutes from notes).
- The prompt states both the conversation language and `APP_LANGUAGE` (minutes language).
- If the LLM is unreachable: keep everything else, log a clear warning; `minutes <dir>` or
  `POST /sessions/{id}/minutes` regenerates later.
