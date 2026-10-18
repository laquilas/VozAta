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

- [ ] Tests (tmp_path folders built by fixtures): full session, session without minutes, with
      edits/diarization/translations/action items, interrupted folder, corrupt JSON, corrupt WAV,
      second run imports nothing, crash mid-import resumes, pause while recording, free-space
      check.
- [ ] Manual: copy the reference machine's `engine/recordings` to a scratch `OUTPUT_DIR`, start
      the app: banner progress, every meeting appears in history with minutes, search finds old
      words, audio plays; the folders are unchanged (compare hashes).
- [ ] Resource parity test passes.

## Tests

`tests/storage/test_migration.py`, `tests/api/test_migration.py`, `MigrationViewModelTests.cs`.

## Out of scope

Exporting the database back to folders (backlog), deleting the folders.

## Kickoff prompt

> Execute phase 33 of the roadmap (`docs/roadmap/phases/33-folder-migration.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/33-folder-migration` (stacked on `feature/32-audio-in-sqlite`, PR #49)
- **Status:** in progress
- **Updated:** 2026-10-18 19:39
- **Next step:** UI: `MigrationViewModel` (banner while running, summary when done, errors dialog), wired in `MainViewModel` (events + `GET /migration` on connect), markup in `ShellView.axaml`, strings in the three resx; client DTOs in `VozAta.Client/Migration.cs` are written but not committed yet.

### Steps

- [x] Start the phase (status, Progress)
- [x] Schema `004_migration.sql`: `imported_at`, index on `imported_from`, `migration_errors`
- [x] `import_track` bulk audio helper; `write_minutes(generated_at=...)`
- [x] `storage/migration.py` `FolderImporter`: full import in one transaction, interrupted
      folders (repairs only), bad folders → `migration_errors`, free-space check
- [x] `SessionManager.busy`; background migration job in `serve` (pauses while recording)
- [ ] API: `GET /migration`, `migration_progress` / `migration_done` events, first WS messages
- [x] CLI `python -m vozata migrate [--dry-run]`
- [ ] UI: client DTOs, `MigrationViewModel`, banner + done toast + errors dialog, strings
- [ ] Docs (architecture §8, api-contract), full suites, manual check recipe

### Decisions and notes

- Stacked on phase 32 (user's choice): the PR targets `feature/32-audio-in-sqlite`; GitHub
  retargets it to `main` once #49 merges.
- Schema `004_migration.sql`: `sessions.imported_at`, index `sessions_imported_from`, and `migration_errors(folder PK, reason, detail, at)` (`reason` is a `[migration]` locale key, `detail` the error text). A folder listed there is not tried again.
- `SqliteAudioStore.import_pcm(id, channel, blocks)` replaces a channel's chunks from PCM blocks in one transaction (joins the caller's); `audio_writer.INSERT_CHUNK` is the shared insert. `write_minutes(..., generated_at=None)` keeps the original minutes time on import.
- `FolderImporter(output_dir, files, file_audio, repository, audio, sample_rate, free_space, now)`: `pending()` (folders with `session.json` and no row of that id, plus phase 31 SQLite session folders holding WAVs whose row has no audio; minus `migration_errors`), oldest first; `import_one(id)` → None or the recorded `MigrationError`; raises `NotEnoughSpaceError` before writing. The folder id stays the session id. `storage/folder_reader.py` reads a folder strictly (an unreadable transcript line or `action_items.json` is an error, unlike the file backend). Reasons: `unreadable_json`, `unreadable_wav`, `unsupported_wav` (not mono 16-bit at `SAMPLE_RATE`; no resampling), `id_in_use`. Minutes keep the mtime of `minutes.md` as `generated_at`. Interrupted folders get the phase 17 repairs only (WAV headers + pad, half-written transcript line); no LLM; the row is `interrupted` so the recovery prompt offers it. `SqliteSessionRepository.replace_segments` is public (used for `raw`).
- `SessionManager.busy`: a session is active (until finalization ends) or being recovered. `api/migration_job.py` `MigrationJob`: states `idle` / `running` / `done` / `no_space` / `failed`; waits (1 s polls) while `busy` before each folder; publishes `migration_progress {done, total, current, paused}` before each folder and on pause, and `migration_done {state, imported, skipped, errors}` (`errors`: count of every recorded folder). `GET /migration` (`disabled` with the file backend) adds `needed_bytes`, `free_bytes`, a localized `message` for `no_space`, and `errors: [{folder, reason, message, detail}]`. The job is built by `bootstrap.build_migration_job` (SQLite only) and **started by the app lifespan after `broadcaster.bind`** (so its events reach clients; building a container in tests starts no thread). When it ends it publishes `recovery_available` if interrupted sessions exist (imported interrupted folders). `/ws` sends `migration_progress` right after the first `status` while running.
- CLI `python -m vozata migrate [--dry-run]` (`cli/migrate.py`): exit 0 when every pending folder was handled (unreadable ones are reported, not fatal); 1 with `STORAGE_BACKEND=files`, a short disk (sizes in MB) or a database error (`cli.migrate_failed`).





