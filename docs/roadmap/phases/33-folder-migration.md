# Phase 33 — Folder to database migration

## Goal

Bring every meeting recorded before phase 31 into `vozata.db` automatically, so history, search,
ask and playback show old and new meetings together. The original folders are never deleted.

## Depends on

31, 32

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- [architecture.md](../architecture.md) §8 (folder layout and the sqlite schema)
- [phase 31](31-sqlite-database.md), [phase 32](32-audio-in-sqlite.md), [phase 17](17-crash-recovery.md)

## Scope

**Engine**

| File | Content |
|------|---------|
| `storage/migration.py` | `FolderImporter(file_repo, file_audio, sqlite_repo, sqlite_audio)`: for each folder in `OUTPUT_DIR` with a `session.json` and no row whose `imported_from` matches → one transaction per session: meta, raw/diarized/edited segments, translations, speakers, minutes, action items, then audio chunks streamed from the WAVs; sets `imported_from` (folder path) and `imported_at` |
| Interrupted folders | run phase 17 file recovery first (repair, pad), then import |
| Bad folders | unreadable JSON/WAV → skip, record in `migration_errors(folder, reason)`, continue |
| `serve` | at start (after `ensure` of the schema), a background job imports pending folders one at a time; recording stays available (the import pauses while a session is active, VRAM/IO rule) |
| API / events | `migration_progress {done, total, current}` on the WebSocket (and in the first `status`), `migration_done {imported, skipped, errors}`; `GET /migration` returns the same summary |
| CLI | `python -m vozata migrate [--dry-run]`: prints what would be imported / imports with a progress line |

**UI**: banner "Importing old meetings… N of M" with a progress bar; when done, a notification
with counts and a "Show errors" link if any; history refreshes.

## Design notes

- Idempotent and resumable: a crash mid-import rolls back that session only; the next start
  continues.
- Never deletes or modifies the folders (except phase 17 repair of an interrupted one, which is
  what recovery already does). Docs: tell users to keep a backup until they've checked.
- Disk space: the audio is copied, so check free space first (≥ folder size × 1.1); if short,
  stop with a localized error and leave the rest for later.
- `STORAGE_BACKEND=files` disables the migration.

## Acceptance criteria

- [x] Tests (tmp_path folders built by fixtures): full session, session without minutes, with
      edits/diarization/translations/action items, interrupted folder, corrupt JSON, corrupt WAV,
      second run imports nothing, crash mid-import resumes, pause while recording, free-space
      check.
- [ ] Manual: copy the reference machine's `engine/recordings` to a scratch `OUTPUT_DIR`, start
      the app: banner progress, every meeting appears in history with minutes, search finds old
      words, audio plays; the folders are unchanged (compare hashes). *(Offline part A done
      2026-10-18 through the CLI, the API and the serve-time import; part B — the banner in the
      running app — is left to the user, recipe below.)*
- [x] Resource parity test passes.

## Tests

`tests/storage/test_migration.py`, `tests/api/test_migration.py`, `MigrationViewModelTests.cs`.

## Out of scope

Exporting the database back to folders (backlog), deleting the folders.

## Kickoff prompt

> Execute phase 33 of the roadmap (`docs/roadmap/phases/33-folder-migration.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/33-folder-migration` (stacked on `feature/32-audio-in-sqlite`, PR #49)
- **Status:** ready for PR
- **Updated:** 2026-10-18 19:46
- **Next step:** open the PR (base `feature/32-audio-in-sqlite`); before merge the user runs
  part B of the manual check recipe below.

### Steps

- [x] Start the phase (status, Progress)
- [x] Schema `004_migration.sql`: `imported_at`, index on `imported_from`, `migration_errors`
- [x] `import_track` bulk audio helper; `write_minutes(generated_at=...)`
- [x] `storage/migration.py` `FolderImporter`: full import in one transaction, interrupted
      folders (repairs only), bad folders → `migration_errors`, free-space check
- [x] `SessionManager.busy`; background migration job in `serve` (pauses while recording)
- [ ] API: `GET /migration`, `migration_progress` / `migration_done` events, first WS messages
- [x] CLI `python -m vozata migrate [--dry-run]`
- [x] UI: client DTOs, `MigrationViewModel`, banner + done toast + errors dialog, strings
- [x] Docs (architecture §8, api-contract), full suites, manual check recipe

### Decisions and notes

- Stacked on phase 32 (user's choice): the PR targets `feature/32-audio-in-sqlite`; GitHub
  retargets it to `main` once #49 merges.
- Schema `004_migration.sql`: `sessions.imported_at`, index `sessions_imported_from`, and `migration_errors(folder PK, reason, detail, at)` (`reason` is a `[migration]` locale key, `detail` the error text). A folder listed there is not tried again.
- `SqliteAudioStore.import_pcm(id, channel, blocks)` replaces a channel's chunks from PCM blocks in one transaction (joins the caller's); `audio_writer.INSERT_CHUNK` is the shared insert. `write_minutes(..., generated_at=None)` keeps the original minutes time on import.
- `FolderImporter(output_dir, files, file_audio, repository, audio, sample_rate, free_space, now)`: `pending()` (folders with `session.json` and no row of that id, plus phase 31 SQLite session folders holding WAVs whose row has no audio; minus `migration_errors`), oldest first; `import_one(id)` → None or the recorded `MigrationError`; raises `NotEnoughSpaceError` before writing. The folder id stays the session id. `storage/folder_reader.py` reads a folder strictly (an unreadable transcript line or `action_items.json` is an error, unlike the file backend). Reasons: `unreadable_json`, `unreadable_wav`, `unsupported_wav` (not mono 16-bit at `SAMPLE_RATE`; no resampling), `id_in_use`. Minutes keep the mtime of `minutes.md` as `generated_at`. Interrupted folders get the phase 17 repairs only (WAV headers + pad, half-written transcript line); no LLM; the row is `interrupted` so the recovery prompt offers it. `SqliteSessionRepository.replace_segments` is public (used for `raw`).
- `SessionManager.busy`: a session is active (until finalization ends) or being recovered. `api/migration_job.py` `MigrationJob`: states `idle` / `running` / `done` / `no_space` / `failed`; waits (1 s polls) while `busy` before each folder; publishes `migration_progress {done, total, current, paused}` before each folder and on pause, and `migration_done {state, imported, skipped, errors}` (`errors`: count of every recorded folder). `GET /migration` (`disabled` with the file backend) adds `needed_bytes`, `free_bytes`, a localized `message` for `no_space`, and `errors: [{folder, reason, message, detail}]`. The job is built by `bootstrap.build_migration_job` (SQLite only) and **started by the app lifespan after `broadcaster.bind`** (so its events reach clients; building a container in tests starts no thread). When it ends it publishes `recovery_available` if interrupted sessions exist (imported interrupted folders). `/ws` sends `migration_progress` right after the first `status` while running.
- CLI `python -m vozata migrate [--dry-run]` (`cli/migrate.py`): exit 0 when every pending folder was handled (unreadable ones are reported, not fatal); 1 with `STORAGE_BACKEND=files`, a short disk (sizes in MB) or a database error (`cli.migrate_failed`).
- UI: `VozAta.Client/Migration.cs` (`MigrationSummary`, `MigrationFolderError`, `MigrationProgressEvent`, `MigrationDoneEvent`), `IEngineClient.GetMigrationAsync`. `MigrationViewModel`: banner "Importing old meetings… N of M" + progress bar (paused text while recording); on `migration_done` (and on every connect, `GET /migration`) the end shows the counts, "Show errors" (folder + localized reason) and the backup advice until dismissed; the Meetings list reloads when something was imported. A `done` found on connect is shown only if this engine run imported something or the app saw it running (errors from earlier runs do not nag). Markup at the top of the page area in `ShellView.axaml`.
- Checks run in the phase session: full engine suite 1689 passed (3 deselected) before the
  last CLI/UI commits, then the touched modules again (new modules 100 % of lines); ruff clean;
  UI suite 649 passed (resource parity included), `dotnet format --verify-no-changes` clean.

### Manual check recipe

Status: **A done 2026-10-18 (offline); B pending** (needs the desktop app).

**A. Offline, a copy of `engine/recordings` (done).** The three meetings of the reference
machine (10 s, 21 s, 9 min; `session.json`, WAVs, `transcript.jsonl`, `minutes.md`) were copied
twice to a scratch folder and their SHA-256 recorded. With `OUTPUT_DIR=<scratch>\cli`:

```powershell
..\.venv\Scripts\python -m vozata migrate --dry-run   # "3 folder(s) would be imported", exit 0
..\.venv\Scripts\python -m vozata migrate             # "Importing 1/3 …", "Imported 3, not imported 0."
..\.venv\Scripts\python -m vozata migrate             # "Nothing to import."
```

A script then built the real app (`bootstrap.build_api_container`, `TestClient` with the
lifespan) over both folders; for `<scratch>\serve` the import ran at start (`GET /migration` →
`done`, imported 3). Seen for both: `GET /sessions` lists the three meetings `done`; each detail
has `audio` with `mic` = `system` = `mixed` (10.4 s, 21.2 s, 551.4 s) and `folder: null`;
minutes `200`; `GET .../audio/mixed` `200 audio/wav` starting with `RIFF`; `Range: bytes=0-99` on
`mic` → `206 bytes 0-99/<size>`; `GET /search?q=próxima` → 4 hits. The folders' hashes are
unchanged (only `vozata.db` was added next to them).

**B. The desktop app (pending).**

1. Copy your `engine\recordings` (or any old `OUTPUT_DIR`) to a scratch folder and note its
   size; keep `STORAGE_BACKEND` empty (sqlite) and point `OUTPUT_DIR` at the copy, e.g.
   `$env:OUTPUT_DIR='C:\scratch\rec'; dotnet run --project ui/src/VozAta.Desktop`.
2. While the app starts, the banner shows "Importing old meetings… N of M" with a progress bar
   (with few small folders it may finish before the window connects: then it shows the counts
   at once). At the end: "Old meetings imported: M. Not imported: 0.", the backup advice, and
   the Meetings list shows every old meeting under its day.
3. Open an old meeting: minutes and transcript are there; Play mixed / mic / system work;
   search finds a word of an old transcript.
4. Optional: break one copy's `session.json` (e.g. delete its last `}`) in a new scratch copy
   and start again: the banner ends with "Not imported: 1" and "Show errors" lists that folder
   with "A file of the meeting … could not be read.".
5. Optional: start a recording right after launch with a large copy: the banner says the import
   is paused while recording and continues after Stop.
6. Compare the folder hashes with the originals (`Get-FileHash`): unchanged.
