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

- [x] Tests (temp db, synthetic numpy audio): chunk boundaries, silence for gaps and pauses,
      equal-length finalize, on-the-fly mono/stereo mix equals the old mixer output, Range reads
      (start, middle, open-ended, invalid → 416), WAV materialize + LRU eviction.
- [x] Crash test (unit): writer subprocess killed mid-batch → recovery returns every committed
      second, both channels equal length.
- [ ] Manual: record 5 minutes from the app; play mic/system/mixed through the API; diarization
      (with `HF_TOKEN`) works from the materialized WAV; hard-kill the engine during a recording
      (phase 17 recipe B) and recover — audio playable to within ~1 s of the kill. Run the crash
      check last and ask for an Audiosrv restart afterwards. *(Offline part A done 2026-10-17;
      parts B and C — real audio — are left to the user, recipe below.)*
- [x] Resource parity test passes.

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
- **Status:** ready for PR
- **Updated:** 2026-10-18 00:30
- **Next step:** open the PR; before merge the user runs parts B and C of the manual check
  recipe below on the reference machine (C last, then restart Windows Audio).

### Steps

- [x] Start the phase (status, Progress)
- [x] Schema: `audio_chunks` migration, `auto_vacuum=INCREMENTAL`
- [x] Playable tracks: `AudioTrack`, `PcmTrack` / `AudioTracks` ports, `audio/pcm.py`
      (WAV header, channel and mixed tracks), file backend tracks
- [x] `SqliteAudioStore`: buffered capture, writer thread (1 s batches, both channels per
      transaction), silence for gaps and pauses, equal-length finalize, repair; contract suite
- [x] Reader: chunk-range `frames`, on-the-fly mix, `materialize_wav` with the LRU cache
- [x] Config `AUDIO_CACHE_MB` (`config.py`, `settings_fields.py`, `.env.example`, UI labels)
- [x] Bootstrap wiring (`AUDIO_STORES`, cache trimmed at engine start), recovery through
      `SqliteAudioStore.repair`, no session folder for sqlite (`folder` / `files` None)
- [x] API: `GET /sessions/{id}/audio/{track}` (Range), `audio` durations in the detail,
      `folder` / `files` null for sqlite, database and cache sizes in `GET /health`
- [x] Crash test: writer subprocess killed mid-batch (`tests/storage/sqlite/test_audio_crash.py`)
- [x] UI: "Play" downloads from the endpoint to a temp file and opens the OS player
- [x] Docs (architecture §2/§4/§5/§6/§8/§9, api-contract), full suites, manual check recipe

### Decisions and notes

- Schema `003_audio.sql`: `audio_chunks` with an extra index on `(session_id, channel,
  start_frame)` for range reads. `auto_vacuum=INCREMENTAL` is set on every new connection (it
  only takes effect on a new file); a file created by phase 31 is converted once on open with
  one `VACUUM` (it holds no audio yet, so it is quick). `Database.reclaim()` runs
  `PRAGMA incremental_vacuum`.
- Ports: `domain.AudioTrack` (`mic`, `system`, `mixed`); `PcmTrack` (`rate`, `channels`,
  `frames`, `read(start, count) -> bytes`) and `AudioTracks.track(id, track) -> PcmTrack | None`,
  part of `SessionAudio`. `AudioMixer` gained `channels` and a public `combine(mic, system)` so
  the mix can be computed per range. `materialize_wav` also takes `AudioTrack.MIXED`.
- `SqliteAudioStore.write_mix` does nothing (the mix is never stored); the shared contract test
  that checked the mixer call moved to the file backend tests, and the contract now checks that
  the mixed track reads as the mono sum. The mix uses the current `MIX_MODE` mixer (an old
  session recorded in stereo plays as mono after switching to mono).
- Writer: `ChunkBatcher` per recording (one thread, `audio-chunks`) commits whole 1 s chunks of
  every channel in one transaction per second; a finished channel's shorter last chunk goes in
  with its `finalize`, and the last `finalize` stops the thread and commits the rest in the
  caller (raises if that fails). A failed commit puts the audio back in the buffer (logged,
  retried next second). More than 30 s buffered logs one warning; nothing is dropped. No chunk
  is longer than `CHUNK_SECONDS` x rate, which bounds the range query on `start_frame`.
- Cache: `WavCache` (`OUTPUT_DIR/cache/<id>/<track>.wav`), written to a temp file and
  `os.replace`d; reused while its size matches the track (a growing or repaired track rebuilds
  it); LRU by mtime (touched on use); a file in use is skipped; `.tmp` leftovers removed.
- `SqliteAudioStore.delete(id)` drops the chunks and cached files, then runs
  `Database.reclaim()` on a background thread. Phase 36 (`DELETE /sessions/{id}`) calls it.
- `AUDIO_CACHE_MB` (integer, 0 to 1048576, default 2048) applies on restart; 0 keeps only the
  file just built.
- `SqliteSessionRepository` no longer creates `OUTPUT_DIR/<id>/`; `create` still skips ids
  whose folder exists (file-backend sessions). `folder` / `files` are None, so
  `GET /sessions/{id}` has `folder: null`, `files: null` for sqlite. Phase 31 sessions recorded
  with the SQLite backend keep their WAVs in their folders, which the API no longer serves;
  phase 33 imports them (only manual-check sessions exist: phase 31 merged the same day).
- With no folder, the retry commands in error messages name `OUTPUT_DIR/<id>` (the CLI
  `minutes` / `diarize` open the storage of the parent folder, so that path works); `record`
  prints the session id instead of a folder.
- API: `GET /sessions/{id}/audio/{mic|system|mixed}` serves any backend through
  `ApiContainer.audio` (`AudioTracks`): a generated 44-byte header plus PCM read a second at a
  time (`api/wav_stream.py`). One range per request (`bytes=a-b`, `a-`, `-n`); malformed,
  multiple or out-of-file ranges give `416` with `Content-Range: bytes */size`. `404
  session_not_found` for an unknown session, `404 audio_not_found` for an unknown track or one
  with no audio. The detail has `audio: {track: seconds}`; the file backend lists the WAVs it
  has. `GET /health` → `storage.size_bytes` (database + WAL) and `storage.audio_cache_bytes`
  (null for files), as phase 38 expects.
- Crash test: a child process records both channels (synthetic samples, 5x real time, commit
  every 0.05 s) and is killed once 3 s are committed; every committed sample reads back
  unchanged, only whole chunks exist, and `repair` evens the channels without losing any. Run
  8 times with the phase 31 crash test: stable.
- UI: "Play mixed / mic / system" download the track through
  `IEngineClient.DownloadAudioAsync` (streamed, `ResponseHeadersRead`) into
  `%TEMP%\VozAta\audio\<id>-<track>.wav` and open it with the shell, for both backends (the
  file backend serves its WAVs through the same endpoint). The buttons are enabled from the
  detail's `audio` field. A file the player still holds open is opened again without a new
  download; a failed download shows the error and deletes the partial file. The folder is a
  constructor parameter of `SessionDetailViewModel` (default under `%TEMP%`), so
  `HistoryViewModel` (which phase 36 rewrites) is unchanged. "Open folder" stays hidden when
  `folder` is null (phase 31). `SessionDetail.Files` / `Folder` are nullable.
- Merge of `origin/main` with phases 36 and 38 (after PR #49 was opened):
  - Phase 38 had also added `storage.size_bytes` / `audio_cache_bytes` to `GET /health` and
    `DELETE /storage/cache`. One implementation each is kept: `size_bytes` = phase 38's
    `storage/usage.database_size` (database + `-wal` + `-shm`); the cache is the `WavCache` of
    the SQLite audio store, exposed as `ApiContainer.audio_cache` (new `AudioCache` port:
    `size()`, `clear()`), the same instance the store writes to. `audio_cache_bytes` is `0`
    (not null) for the file backend, as phase 38 defined it. `DELETE /storage/cache` calls
    `WavCache.clear()`: every cached WAV is deleted except files in use (skipped, logged, not
    counted); `freed_bytes` counts only what was deleted; the file backend frees 0.
    `usage.clear_directory` and `usage.AUDIO_CACHE_DIR` were removed, as was the phase 32
    `StorageInfo.audio_cache` field.
  - Phase 36's `DELETE /sessions/{id}`: the SQLite repository's `delete` no longer removes a
    folder (there is none); the chunks cascade with the row. The route then calls the new
    `AudioStore.delete(id)` port method: `SqliteAudioStore` drops the cached WAVs and reclaims
    the space in the background; `FileAudioStore.delete` does nothing (the repository sends the
    folder, WAVs included, to the Recycle Bin).
  - Phase 36's Meetings row "Play" read `folder` / `files`; it now uses the same download as
    the detail view (`Services/AudioPlayback.cs`, shared): enabled by `audio.mixed`, downloads
    `GET /sessions/{id}/audio/mixed` to `%TEMP%\VozAta\audio` and opens it. The detail view
    (now `Views/SessionDetailView.axaml`) keeps its Play buttons and hides "Open folder" when
    `folder` is null.
  - After the merge: engine 1642 passed (3 deselected), coverage 99.88 %, ruff clean; UI 634
    passed, `dotnet format --verify-no-changes` clean.
- Checks run in the phase session: full engine suite 1499 passed (3 deselected), coverage
  99.87 % (new modules 100 % of lines), `ruff check` / `ruff format --check` clean; UI suite
  526 passed (resource parity included), `dotnet format --verify-no-changes` clean.

### Manual check recipe

Status: **A done 2026-10-17 (offline, no audio hardware); B and C pending** — run on the
reference machine, one phase at a time (audio is shared). Engine commands from `engine/` in
PowerShell; the app with `dotnet run --project ui/src/VozAta.Desktop`.

**A. Simulated crash with the SQLite audio, no microphone (done).** A script (scratch folder)
started a child process that recorded both channels through `bootstrap.build_audio_store`
(synthetic sine blocks, `OUTPUT_DIR=<scratch>`, a 10-minute-old start so the CLI sees it as
stale) and killed it once 5 s were committed. Then, with `OUTPUT_DIR=<scratch>`,
`GENERATE_MINUTES=false`, `DIARIZATION_ENABLED=false`:

```powershell
..\.venv\Scripts\python -m vozata recover <scratch>\<id>   # exit 0, "Recovered: <id>"
..\.venv\Scripts\python -m vozata recover <scratch>\<id>   # exit 1, "... was not interrupted ..."
```

Seen: the row is `done` with `duration_seconds: 5.0`; `audio_chunks` has 5 chunks of 16000
samples per channel; `integrity_check` ok, `auto_vacuum` 2, `user_version` 3; `OUTPUT_DIR`
holds only `vozata.db` (+ `-wal` / `-shm`), no session folder. Through the API routes (TestClient
over the same stores): the detail has `audio: {mic: 5.0, system: 5.0, mixed: 5.0}`,
`folder: null`, `files: null`; each track is `200 audio/wav`, 160044 bytes, `RIFF`; `Range:
bytes=1000-1999` gives `206` with 1000 bytes; an out-of-file range `416`; `GET /health` has
`size_bytes` and `audio_cache_bytes: 0`; `materialize_wav(system)` wrote
`cache\<id>\system.wav` (80000 frames, 16 kHz).

**B. Real recording from the desktop app (pending, needs the microphone and speakers).**

1. In `engine/.env` keep `STORAGE_BACKEND` empty or `sqlite`, `DATABASE_PATH` outside OneDrive
   (e.g. `C:\VozAta\vozata.db`), `DIARIZATION_ENABLED=true` with `HF_TOKEN` set, and
   `AUDIO_CACHE_MB` empty (2048). The database from phase 31 is converted to incremental
   auto-vacuum on the first start (log line "Converting the database to
   auto_vacuum=INCREMENTAL").
2. Start the app. Record **5 minutes** while speaking and playing a video (both channels); pause
   once for ~10 s in the middle. Watch the engine log: no "is waiting for the database" warning.
   Stop and wait for *idle*.
3. `OUTPUT_DIR` has no new `<id>` folder. `curl http://127.0.0.1:8765/sessions/<id>` shows
   `folder: null`, `files: null`, `storage: "sqlite"` and `audio` with `mic`, `system` and
   `mixed` all ≈ 300 s (equal).
4. Play through the API:
   `curl -o mic.wav http://127.0.0.1:8765/sessions/<id>/audio/mic` (same for `system` and
   `mixed`); each opens in a player, lasts the whole recording, the pause is silence on both
   channels, and `mixed` has both voices (stereo if `MIX_MODE=stereo`). A ranged request:
   `curl -s -D - -o NUL -H "Range: bytes=0-99" http://127.0.0.1:8765/sessions/<id>/audio/mixed`
   → `206`, `Content-Range: bytes 0-99/<size>`.
5. History → the session: "Play mixed / mic / system" download to
   `%TEMP%\VozAta\audio\<id>-<track>.wav` and open the default player; "Open folder" is hidden.
   Play again while the player still has the file open: it opens again (no error).
6. Diarization ran from the materialized WAV: the transcript shows `User 1` / `User 2` labels for
   the system side, the log has no `diarization_failed`, and `OUTPUT_DIR\cache\<id>\system.wav`
   exists. `curl http://127.0.0.1:8765/health` shows `storage.size_bytes` grown by ≈ 115 MB
   (5 min × 2 channels) and `storage.audio_cache_bytes` ≈ the size of that WAV.
7. Export DOCX / MD / PDF: unchanged (minutes and transcript).
8. Optional: `STORAGE_BACKEND=files` + restart; record 30 s: the folder has `mic.wav`,
   `system.wav`, `mixed.wav`, and the Play buttons still work (same endpoint). Set it back.

**C. Crash during a real recording (pending; run last — it hard-kills a recording engine, which
can wedge WASAPI: restart Windows Audio afterwards).**

1. Start a recording from the app, speak and play audio for ~60 s; note the clock time.
2. Kill the engine process (Task Manager → `python.exe` running `vozata serve` → End task).
3. Restart the app: the start screen offers to recover the interrupted session; recover it.
   The transcript lines seen before the kill are there; `GET /sessions/<id>` has `audio` with
   `mic` and `system` equal; play `mixed`: it ends within ~1–2 s of the kill.
4. Restart the Windows Audio service (`Restart-Service Audiosrv` in an elevated PowerShell).
