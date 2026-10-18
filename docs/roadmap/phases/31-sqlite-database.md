# Phase 31 — SQLite session database

## Goal

Store sessions, transcripts, speakers, translations, minutes, action items and the search index in
one SQLite database, `vozata.db`, instead of one folder of JSON and Markdown files per session.

## Depends on

30

## Read first

- `engine/CLAUDE.md`
- [architecture.md](../architecture.md) §5 (ports), §8 (data model), §9 (config keys)
- [api-contract.md](../api-contract.md) — `GET /sessions`, `GET /sessions/{id}`, `GET /search`
- [phase 30](30-storage-port.md) — the ports and the repository contract test suite

## Scope

**Engine**

| File | Content |
|------|---------|
| `storage/sqlite/db.py` | `Database(path)`: opens with `journal_mode=WAL`, `synchronous=NORMAL` (FULL for the per-segment commit), `foreign_keys=ON`, `busy_timeout`; one connection per thread (`threading.local`), writes serialized by a lock; schema migrations by `PRAGMA user_version` (`storage/sqlite/migrations/NNN_*.sql`, package data) |
| Schema | `sessions(id PK, status, started_at, ended_at, duration_seconds, last_heartbeat_at, language, language_source, app_language, template, title NULL, meta_json, imported_from NULL)` · `segments(session_id FK, source raw\|diarized\|edited, segment_id, channel, speaker_id, start, end, text, words_json, edited, PK(session_id, source, segment_id))` · `translations(session_id, segment_id, language, text)` · `speakers(session_id, speaker_id, name)` · `minutes(session_id PK, markdown, template, generated_at)` · `action_items(session_id, item_id, description, owner, due, source_ids_json, exported_url)` · `segments_fts` (FTS5, same tokenizer as today's `index.db`, kept in sync by triggers on the best source) |
| `storage/sqlite/repository.py` | `SqliteSessionRepository` implementing `SessionRepository`; transcript precedence edited → diarized → raw by query; `delete(session_id)` cascades |
| `storage/search_index.py` | becomes a thin query layer over `segments_fts`; `reindex` rebuilds the FTS table; `index.db` is no longer created |
| `config.py`, `settings_fields.py`, `.env.example` | `STORAGE_BACKEND=sqlite\|files` (default `sqlite`, restart), `DATABASE_PATH` (empty = `OUTPUT_DIR/vozata.db`, restart) |
| API | `GET /sessions/{id}`: `folder` / `files` only for the file backend; new `storage: "sqlite"\|"files"` |
| Recovery | a session row in `recording` / `paused` / `finalizing` without a live session is `interrupted`; committed segments are complete by construction (no `.damaged` handling) |

**UI**: hide "Open folder" when the session has no `folder`; nothing else (audio still comes from
files until phase 32).

## Design notes

- Audio stays in WAV files in this phase (`FileAudioStore`), in `OUTPUT_DIR/<id>/`; phase 32 moves
  it into the database. The session folder then holds only audio.
- The database must not live in a OneDrive-synced folder while the engine runs (sync locks the
  file and can corrupt WAL). On start, if `DATABASE_PATH` is under a OneDrive root, log a warning
  and show it in `GET /health` (`storage.warning`); document it.
- Heartbeat writes only `last_heartbeat_at` / `duration_seconds` (one small UPDATE).
- `meta_json` keeps the less-queried `session.json` fields (devices, pauses, settings,
  `echo_dropped`, vocabulary) so the schema doesn't grow with every phase.
- Schema documented in architecture §8 (replacing the folder table for the sqlite backend).

## Acceptance criteria

- [ ] The phase 30 repository contract suite passes for `SqliteSessionRepository` (temp db).
- [ ] Tests: migrations from an empty file and from version N-1; WAL and foreign keys on;
      concurrent reader during writes; FTS stays in sync on edit/revert/diarize; cascade delete;
      OneDrive path warning.
- [ ] Crash test (unit): kill a writer subprocess mid-session → every committed segment readable,
      session detected as interrupted.
- [ ] Manual: record from the desktop app with the default `STORAGE_BACKEND=sqlite`; history,
      transcript, speakers rename, edit, search, ask, minutes regenerate and export all work; no
      JSON/MD files are written in the session folder.
- [ ] Resource parity test passes.

## Tests

`tests/storage/sqlite/test_db.py`, `tests/storage/sqlite/test_repository.py` (contract),
`tests/storage/sqlite/test_fts.py`, `tests/api/test_sessions.py` (storage field).

## Out of scope

Audio in the database (32), importing old folders (33), settings in the database (stay in `.env`).

## Kickoff prompt

> Execute phase 31 of the roadmap (`docs/roadmap/phases/31-sqlite-database.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/31-sqlite-database`
- **Status:** in progress
- **Updated:** 2026-10-17 21:30
- **Next step:** write `storage/sqlite/db.py` and the migrations (`001_schema.sql`,
  `002_search.sql`) test-first in `tests/storage/sqlite/test_db.py`.

### Steps

- [x] Start the phase (status, Progress); phase 30 manual check part B recorded as done
- [ ] `Database` (WAL, foreign keys, per-thread connections, write lock) and migrations
- [ ] `SqliteSessionRepository` passing the phase 30 contract suite; cascade delete
- [ ] FTS: `segments_fts` kept in sync by triggers on the best source; `SqliteSearch`
- [ ] Config (`STORAGE_BACKEND`, `DATABASE_PATH`), bootstrap wiring, OneDrive warning in
      `GET /health`, `storage` field in `GET /sessions/{id}`, CLI session folders
- [ ] Crash test: a writer subprocess killed mid-session
- [ ] UI: hide "Open folder" without a folder; setting labels for the new keys
- [ ] Docs (architecture §8/§9, api-contract), full suites, manual check recipe

### Decisions and notes

- (none yet)
