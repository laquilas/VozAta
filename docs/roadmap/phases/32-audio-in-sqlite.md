# Phase 32 — Audio in SQLite

## Goal

Record the microphone and system tracks straight into `vozata.db` as small PCM chunks, so a
crash never leaves a broken WAV, and serve the audio to the app over the API.

## Depends on

31

## Read first

- `engine/CLAUDE.md`
- [architecture.md](../architecture.md) §6 (capture, mix, stop order), §8 (data model)
- [phase 30](30-storage-port.md) (`AudioStore`, `AudioReader`), [phase 31](31-sqlite-database.md)
- [phase 17](17-crash-recovery.md) — what recovery guarantees today

## Scope

**Engine**

| File | Content |
|------|---------|
| Schema (migration) | `audio_chunks(session_id FK, channel mic\|system, seq, start_frame, frames, pcm BLOB, PK(session_id, channel, seq))`, 16 kHz mono int16, ~1 s per chunk; `PRAGMA auto_vacuum=INCREMENTAL` |
| `storage/sqlite/audio.py` | `SqliteAudioStore`: the capture callback only appends to an in-memory buffer; a writer thread commits one batch per second (both channels in one transaction); gaps and pauses are written as silence like `AlignedWavWriter`; `finalize` pads both channels to the same length. `SqliteAudioReader`: `frames(...)` reads chunk ranges; `materialize_wav(id, channel)` writes `cache/<id>/<channel>.wav` (atomic) on demand |
| Mix | `mixed` is never stored: `AudioReader` mixes mic + system on the fly with `MIXERS[MIX_MODE]`; `materialize_wav(id, "mixed")` caches it |
| Cache | `OUTPUT_DIR/cache/`, LRU by last access, `AUDIO_CACHE_MB` (default 2048); cleaned at start and after each materialize |
| Diarization | `session_diarization.py` passes `materialize_wav(id, "system")` to the child (unchanged child protocol) |
| Recovery | committed chunks are the recording; no `repair_wav`; pad to equal length; lost audio ≤ 1 s + the in-memory batch (documented) |
| API | `GET /sessions/{id}/audio/{mic\|system\|mixed}` → `audio/wav`, streamed from chunks with a generated header, HTTP `Range` support (206), `404` unknown session/channel; `GET /sessions/{id}` lists `audio: {channel: duration_seconds}` |
| Export / delete | DOCX/PDF/MD export unchanged; `delete` drops chunks and runs `incremental_vacuum` in the background |
| `config.py`, `settings_fields.py`, `.env.example` | `AUDIO_CACHE_MB` |

**UI**: "Play" buttons use the new endpoint (download to a temp file and open the OS player until
phase 37 brings the in-app player); "Open folder" hidden for sqlite sessions.

## Design notes

- Size: 2 channels × 16 kHz × 2 bytes ≈ 230 MB per hour. Show the database size in Config →
  Storage (phase 38) and in `GET /health`.
- The capture callback must never wait on SQLite: if the writer falls behind more than
  `AUDIO_BACKLOG_SECONDS` (fixed 30 s), log and keep buffering; never drop audio silently.
- Large BLOBs are avoided on purpose: 1 s chunks keep commits small and Range reads cheap.
- `STORAGE_BACKEND=files` keeps WAV files (phase 30 implementation) for users who want them.

## Acceptance criteria

- [ ] Tests (temp db, synthetic numpy audio): chunk boundaries, silence for gaps and pauses,
      equal-length finalize, on-the-fly mono/stereo mix equals the old mixer output, Range reads
      (start, middle, open-ended, invalid → 416), WAV materialize + LRU eviction.
- [ ] Crash test (unit): writer subprocess killed mid-batch → recovery returns every committed
      second, both channels equal length.
- [ ] Manual: record 5 minutes from the app; play mic/system/mixed through the API; diarization
      (with `HF_TOKEN`) works from the materialized WAV; hard-kill the engine during a recording
      (phase 17 recipe B) and recover — audio playable to within ~1 s of the kill. Run the crash
      check last and ask for an Audiosrv restart afterwards.
- [ ] Resource parity test passes.

## Tests

`tests/storage/sqlite/test_audio_store.py`, `tests/storage/sqlite/test_audio_reader.py`,
`tests/api/test_audio.py`, recovery tests updated.

## Out of scope

Compression (FLAC/Opus), importing old WAVs (33), the in-app player (37).

## Kickoff prompt

> Execute phase 32 of the roadmap (`docs/roadmap/phases/32-audio-in-sqlite.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/32-audio-in-sqlite`
- **Status:** in progress
- **Updated:** 2026-10-17 23:30
- **Next step:** add migration `003_audio.sql` (`audio_chunks`) and switch new databases to
  `auto_vacuum=INCREMENTAL` in `storage/sqlite/db.py`.

### Steps

- [x] Start the phase (status, Progress)
- [ ] Schema: `audio_chunks` migration, `auto_vacuum=INCREMENTAL`
- [ ] `SqliteAudioStore`: buffered capture, writer thread (1 s batches, both channels per
      transaction), silence for gaps and pauses, equal-length finalize, repair; contract suite
- [ ] Reader: chunk-range `frames`, on-the-fly mix, `materialize_wav` with the LRU cache
      (`AUDIO_CACHE_MB`)
- [ ] API: `GET /sessions/{id}/audio/{track}` (Range), `audio` durations in the detail,
      `folder` / `files` null for sqlite, database and cache sizes in `GET /health`
- [ ] Bootstrap wiring, recovery, delete helper (chunks + background `incremental_vacuum`)
- [ ] Crash test: writer subprocess killed mid-batch
- [ ] UI: "Play" downloads from the endpoint to a temp file and opens the OS player
- [ ] Docs (architecture, api-contract), full suites, manual check recipe

### Decisions and notes

- (none yet)
