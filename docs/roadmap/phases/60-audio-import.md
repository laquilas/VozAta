# Phase 60 — Import an audio file as a meeting

## Goal

Bring an audio file recorded elsewhere (a phone, a Teams / Zoom recording, a video) into VozAta
and run on it what a recorded meeting gets: transcription, speaker identification, minutes,
action items, search and Ask. The user picks a file on the Meetings page and the meeting goes
straight into the processing queue: named after the file, language `auto`, the default minutes
template (all editable afterwards, as for any meeting).

## Depends on

39, 40, 41

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- [phase 39](39-audio-export-delete.md) (`POST /sessions/import`: raw body, size cap)
- [phase 40](40-background-processing.md) (`ProcessingQueue`, `session_job`, `job_factory`)
- [phase 41](41-record-only.md) (a session with audio and no transcript is transcribed from 0)
- `plans/60-audio-import.md` (the approved plan)

## Scope

**Engine**

| File | Content |
|------|---------|
| `ports.py` | `AudioDecoder` (`blocks(path)`: int16 mono PCM at `SAMPLE_RATE`), `AudioDecodeError`, `PcmImport` (`import_pcm`) |
| `audio/decode.py` | `PyAvDecoder`: any format PyAV reads (wav, mp3, m4a, ogg, opus, flac, wma, the audio of mp4 / mkv / webm / mov), resampled to mono 16 kHz, streamed |
| `storage/files/audio.py` | `FileAudioStore.import_pcm` (the SQLite store has it since phase 33) |
| `storage/audio_import.py` | `AudioFileImporter`: a new session from a file, ready for the queue |
| `api/session_manager.py` | `process_imported(id)`: queue the job of an imported meeting |
| `api/routes/audio_import.py` | `POST /sessions/import-audio?name=&recorded_at=` → 202 `{id}` |
| `locales/*.toml` | `audio_invalid`, `audio_empty`, `audio_too_large` |

**UI**

| File | Content |
|------|---------|
| `VozAta.Client/EngineClient.cs` | `ImportAudioAsync` |
| `Services/FileSaver.cs` | an open picker for several extensions, with the file name and date |
| `MeetingsPage` | "Import audio" button |
| Resources | strings in en / pt-BR / es |

## Design notes

- The imported audio goes into the **system** track: speaker identification runs on that track
  only. The mic track is silence of the same length, so mix, player and echo dedupe need nothing
  new.
- `session.json` is written last, with `status: finalizing` and `capture_ended_at`: a crash
  during the import leaves no listed meeting, and a restart after it re-queues the meeting
  (`resume_pending`). A failed import deletes the half-made session.
- The meeting starts at `recorded_at − duration` (the UI sends the file's modified time), else
  at the import time minus the duration.
- Extra metadata: `source: "imported_audio"`, `imported_file: <name>`.

## Acceptance criteria

- [ ] "Import audio" on the Meetings page opens a picker for audio and video files.
- [ ] An mp3 / m4a / wav / mp4 file becomes a meeting named after the file that is queued and
      processed: transcript, speakers, minutes and action items, and Ask and search work.
- [ ] The meeting's player plays the imported audio for its full length.
- [ ] A file without audio, or an empty one, shows a clear error and adds no meeting.
- [ ] A meeting imported just before the engine stops is processed after the restart.

## Tests

Engine: decoder on generated WAVs (stereo 44.1 kHz → mono 16 kHz) and a non-audio file; the
importer on both backends with a fake decoder (meta, track lengths, start time, cleanup); the
route (202 + job, 413, 422, 503); `process_imported`. UI: client request and errors, view model
success / cancel / error, locale parity.

## Out of scope

Setting title, language or template before the import; several files at once; keeping the
original compressed file; splitting a stereo file into mic and system.

## Kickoff prompt

> Start phase 60 (`docs/roadmap/phases/60-audio-import.md`): read its *Read first* files and
> `plans/60-audio-import.md`, then implement it task by task.

## Progress

- **Branch:** `feature/60-audio-import`
- **Status:** in progress
- **Updated:** 2026-10-29 10:00
- **Next step:** UI client: `IEngineClient.ImportAudioAsync(stream, fileName, modifiedAt)` → `POST sessions/import-audio`, `ImportedAudio(Id)`, tests in `EngineClientTests`.

### Steps

- [x] Phase start (phase file, plan, README)
- [x] Engine: `AudioDecoder` port + `PyAvDecoder`
- [x] Engine: `import_pcm` on the file store + `AudioFileImporter` (both backends)
- [x] Engine: `process_imported` + `POST /sessions/import-audio` + wiring + locales
- [x] Docs (api-contract, architecture)
- [ ] UI client: `ImportAudioAsync`
- [ ] UI: picker + Meetings page "Import audio" + strings
- [ ] Full suites, manual check

### Decisions and notes

- The importer uses the language of `TRANSCRIPTION_LANGUAGE` like a recording (`auto` is
  detected), not always `auto`; the vocabulary is the glossary of a new recording.
- `AudioDecoder.duration` (the container's estimate) only names the session id; the stored
  length is the decoded frame count.
- `api/uploads.save_body` is the raw-body-with-cap helper shared with phase 39's import.
- Requested by the user on 2026-10-29; they chose "pick the file, then process" (no dialog).
