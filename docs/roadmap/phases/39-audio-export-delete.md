# Phase 39 — Delete a meeting's audio, export and import a meeting as a ZIP

## Goal

Since phase 32 the audio lives in `vozata.db` (raw PCM, ≈ 230 MB per hour) and there is no way
to free one meeting's audio or to take a recording out of the app. Add:

- **Delete audio**: drop a meeting's audio and keep its transcript, minutes, speakers and action
  items.
- **Export recording**: a ZIP holding the meeting as a phase 30 session folder (metadata,
  transcripts, minutes, action items, `mic.wav`, `system.wav`).
- **Import**: read such a ZIP back. An unknown meeting is added; a meeting that is already there
  without audio gets its audio back (the round trip after "Delete audio").

Audio stays in SQLite: the 1 s chunks are what make crash recovery a non-event, and
`STORAGE_BACKEND=files` still exists for whoever wants WAV files.

## Depends on

32, 37

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- [phase 32](32-audio-in-sqlite.md) (`AudioStore`, `audio_chunks`, `Database.reclaim`)
- [phase 33](33-folder-migration.md) (`FolderImporter`, `folder_reader.py`: the folder format)
- [phase 37](37-detail-and-player.md) (meeting page actions, player)
- `docs/roadmap/architecture.md` §8 (data model, session folder layout)

## Scope

**Engine**

| File | Content |
|------|---------|
| `ports.py` | `AudioStore.discard(session_id)`: remove a kept session's audio |
| `storage/sqlite/audio.py`, `storage/files/audio.py` | `discard`: chunks deleted and space reclaimed / WAVs to the Recycle Bin |
| `api/routes/audio.py` | `DELETE /sessions/{id}/audio` → 204; 404 `session_not_found`; 409 `session_live` |
| `storage/folder_writer.py` | writes a stored session as a session folder (reverse of `folder_reader.py`) |
| `export/bundle.py` | zips that folder (`ZIP_STORED`) |
| `storage/bundle_import.py` | safe extraction of an uploaded ZIP + `FolderImporter` rooted at the extraction dir |
| `api/routes/bundle.py` | `GET /sessions/{id}/bundle` (`<id>.zip`), `POST /sessions/import` (raw `application/zip` body) → `{id, mode}` |
| `locales/*.toml` | error messages |

**UI**

| File | Content |
|------|---------|
| `VozAta.Client/EngineClient.cs` | `DeleteSessionAudioAsync`, `DownloadBundleAsync`, `ImportBundleAsync` |
| `Services/FileSaver.cs` | streaming save; a `.zip` open picker |
| `SessionPage` | "Export recording (.zip)" and "Delete audio" actions |
| `MeetingsPage` | "Import" button; ZIP entry in the row export menu |
| Resources | strings in en / pt-BR / es |

## Design notes

- The ZIP has one top-level folder named after the session id, laid out as
  `storage/files/layout.py` (`SessionPaths`). No `mixed.wav`: the import computes the mix, as for
  phase 33 folders.
- Import safety: exactly one top-level folder matching `SESSION_ID`, no absolute paths or `..`,
  only known file names, and an uncompressed-size cap checked before extraction.
- An id that exists **with** audio is refused (409 `session_exists`); nothing is overwritten.
- The live session can neither lose its audio nor be exported.

## Acceptance criteria

- [ ] "Delete audio" on a meeting asks for confirmation, removes the player, keeps transcript /
      minutes / Ask, and `storage.size_bytes` drops once the space is reclaimed.
- [ ] "Export recording (.zip)" saves a ZIP that holds the session folder with `mic.wav` and
      `system.wav` of the full length.
- [ ] Importing that ZIP into another database adds the meeting with its transcript, minutes,
      speakers, action items and audio.
- [ ] Importing it after "Delete audio" restores the audio of the same meeting.
- [ ] Importing a ZIP of a meeting that still has audio, or an invalid ZIP, shows a clear error
      and changes nothing.
- [ ] Both storage backends pass the shared contract tests for `discard`.

## Tests

Engine: contract tests for `discard`; route tests (204 / 404 / 409, detail shows `audio: {}`);
writer → zip → import round trip (sqlite to sqlite, audio-only restore, `session_exists`, zip
slip, oversize, wrong layout). UI: client methods, page and list view models, locale parity.

## Out of scope

- Compressed audio (FLAC/Opus) inside the database or the ZIP.
- Exporting or importing several meetings at once.

## Progress

- **Branch:** `feature/39-audio-export-delete`
- **Status:** in progress
- **Updated:** 2026-10-19 17:45
- **Next step:** add `DELETE /sessions/{id}/audio` in `api/routes/audio.py` (204, 404, 409 live).

### Steps

- [x] Phase file and roadmap row
- [x] `AudioStore.discard` (sqlite + files) + contract tests
- [ ] `DELETE /sessions/{id}/audio`
- [ ] Session folder writer + `GET /sessions/{id}/bundle`
- [ ] `POST /sessions/import` (safe extraction + `FolderImporter`)
- [ ] API contract and architecture docs
- [ ] UI client methods
- [ ] Meeting page: export ZIP and delete audio
- [ ] Meetings page: import and ZIP export entry
- [ ] Full suites, manual check

### Decisions and notes

- Requested during the manual checks of phases 32/33/37: the user chose "delete audio only" and
  a ZIP that can be imported back, without `mixed.wav`.
