# Phase 60 — Import an audio file as a meeting

## Context

Today VozAta only processes meetings it recorded itself (or ZIP bundles it exported, phase 39).
The user wants to bring in an audio file recorded elsewhere (phone, Teams/Zoom recording, etc.) and
get the same pipeline: transcription, speaker identification, minutes, action items, search and
Ask. UX decided with the user: **pick a file → it is processed**, no dialog (title = file name,
language `auto`, default template; everything editable later as usual).

Key facts from exploration:
- The phase 40 job (`processing/session_job.py`: transcribe → mix → diarize → minutes →
  action_items → index) already processes a session purely from stored audio; for a session with
  an empty raw transcript the transcribe step starts at 0 (same as record-only, phase 41).
- No HTTP route enqueues processing for a stored session; `job_factory` lives inside
  `bootstrap.build_api_container` (`bootstrap.py:1174-1191`) and is only given to `SessionManager`.
- `AudioStore.import_pcm` (sqlite `storage/sqlite/audio.py:76`) takes an iterable of int16 mono
  16 kHz bytes; `repair` pads the other channel with silence; `write_mix` makes the mix.
- PyAV (`av` 19, via faster-whisper) is already installed and packaged; no ffmpeg/soundfile needed.
- Speaker identification runs only on the **system** track (`diarization/session_diarization.py`),
  so imported audio goes into `SYSTEM`; `MIC` becomes silence.
- Phase 39 `POST /sessions/import` (`api/routes/bundle.py:64-117`) is the pattern for a raw-body
  upload with a size cap streamed to a temp dir.

## Branch / roadmap

`feature/60-audio-import`. First commit: phase file `docs/roadmap/phases/60-audio-import.md`
(Goal, Depends on 39 / 40 / 41, Read first, Scope, Design notes, Acceptance, Tests, Out of scope,
Kickoff, Progress), README row 60 (in progress) + graph edges. Every commit updates Progress.
Commits stay local; push only when opening the PR (memory rule).

## Engine

| File | Change |
|------|--------|
| `ports.py` | `AudioDecoder` port: `duration(path) -> float | None` and `blocks(path) -> Iterator[bytes]` (int16 LE mono at `SAMPLE_RATE`); raises `AudioDecodeError` |
| `audio/decode.py` (new) | `PyAvDecoder`: `av.open`, first audio stream, `av.AudioResampler(format="s16", layout="mono", rate=16000)`, streams frames (never whole-file in memory), flushes resampler; no audio stream / corrupt → `AudioDecodeError` |
| `storage/audio_import.py` (new) | `AudioFileImporter(repository, audio, decoder, settings, clock)`: `import_file(path, name, recorded_at) -> id`. Creates the session (`started_at` = `recorded_at − duration` when given, else now − duration), `import_pcm(id, SYSTEM, decoder.blocks(path))` in one transaction, `repair`, `write_mix`, then writes meta via `SessionMeta` (title = file stem, `status: finalizing`, `live_transcription: false`, `capture_ended_at` set, `duration_seconds` from the frame count, `language` / `template` / `vocabulary` from settings, `devices: {}`, `source: "imported_audio"`, `imported_file: name`). Meta last, so a crash mid-import leaves no listed session; on any error the half session is deleted. A zero-length decode → `AudioDecodeError("audio_empty")` |
| `api/session_manager.py` | `process_imported(id)`: enqueue `job_factory(id, False, None)` (lock + queue, like `recover`). Restart safety already exists: `resume_pending` re-enqueues `finalizing` sessions with `capture_ended_at` |
| `api/routes/audio_import.py` (new) | `POST /sessions/import-audio?name=<file name>&recorded_at=<ISO, optional>`, raw `application/octet-stream` body streamed to a temp dir with cap `MAX_AUDIO_IMPORT_BYTES` (4 GiB) — reuse/extract the streaming helper from `bundle.py` instead of copying it. Decode + import in `run_in_threadpool`, then `manager.process_imported(id)` → **202** `{id}`. Errors: 413 `audio_too_large`, 422 `audio_invalid` / `audio_empty`, 503 `import_unavailable`, 507 `not_enough_space` |
| `api/container.py`, `bootstrap.py` | `audio_importer` on `ApiContainer`, `PyAvDecoder` wired only in the composition root; `api/app.py` registers the router (phase comment) |
| `locales/{en,pt-BR,es}.toml` | `audio_invalid`, `audio_empty`, `audio_too_large` |

File backend: verify `repair` creates the empty `mic.wav` (agent: `storage/wav_repair.py`); both
backends covered by the same importer tests.

## UI

| File | Change |
|------|--------|
| `VozAta.Client/EngineClient.cs` (+ `IEngineClient`) | `ImportAudioAsync(Stream, string fileName, DateTimeOffset? modifiedAt)` → `SendRawAsync(POST, "sessions/import-audio?...")`, `application/octet-stream`, returns `ImportedAudio(Id)` |
| `Services/FileSaver.cs` | `OpenAsync` overload taking several extensions, returning name + last-modified with the stream (`IStorageFile.Name`, `GetBasicPropertiesAsync().DateModified`) |
| `MeetingsPageViewModel.Actions.cs` | `ImportAudioCommand` beside `ImportCommand` (shares `IsImporting`); flow mirrors `ImportAsync`: pick → upload → `LoadAsync` → message `MeetingAudioImported` → `History.Show`. The row then shows "Queued / Processing n %" through the existing `processing` events (no new event) |
| `Views/MeetingsPage.axaml` | "Import audio" button next to "Import meeting" |
| `Resources/Strings*.resx` | `MeetingImportAudio`, `MeetingImportAudioTitle`, `FileTypeAudio`, `MeetingAudioImported` in en / pt-BR / es |

Extensions in the picker: `wav mp3 m4a aac ogg opus flac wma webm mp4 mkv mov`.

## Docs

`api-contract.md`: the new route, errors, that it emits the usual `processing` / `status` events.
`architecture.md`: `AudioDecoder` port, `source` / `imported_file` meta fields, imported audio goes
to the system track. `__pendent__/README.md`: manual checks below.

## Tests (TDD, fakes only — no real models)

- `PyAvDecoder`: tiny WAV / stereo 44.1 kHz WAV generated in the test (`wave` + numpy) → mono
  16 kHz length within one frame; a text file → `AudioDecodeError`. (PyAV is local, no hardware.)
- `AudioFileImporter` with a fake decoder on both backends: meta fields, system audio + silent mic
  of equal length, started_at from recorded_at, empty decode, cleanup on decoder error.
- Route: 202 + enqueued job (fake manager/queue), 413 by Content-Length and by stream, 422, 503.
- `SessionManager.process_imported` enqueues once.
- UI: client request (method, path, query, content type, error envelope); view model success /
  cancel / engine error; locale parity test covers the new keys.

## Verification

1. Engine: `ruff check`, `ruff format --check`, `pytest` (diff coverage ≥ 80 %).
2. UI: `dotnet build`, `dotnet test`, `dotnet format --verify-no-changes`.
3. Manual (scratch `DATABASE_PATH`): import an mp3 and an m4a/mp4 of a real meeting → row shows
   queued → processing % → done; transcript, speakers, minutes, action items present; player plays
   the audio; Ask answers; search finds it. Invalid file shows the `audio_invalid` message.

## Out of scope

Choosing title/language/template before import, importing several files at once, keeping the
original compressed file, splitting stereo into mic/system.
