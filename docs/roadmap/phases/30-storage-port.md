# Phase 30 — Storage port

## Goal

Put every read and write of session data behind ports, so that phases 31–33 can move sessions,
transcripts and audio into SQLite without touching the session, API, minutes, diarization or
recovery code again. No user-visible change.

## Depends on

17, 23

## Read first

- `engine/CLAUDE.md`
- [architecture.md](../architecture.md) §3 (SOLID mapping), §5 (ports), §6 (stop order), §8 (data
  model and session folder)

## Scope

**Engine**

| File | Content |
|------|---------|
| `ports.py` | `SessionRepository` protocol: `create(meta)`, `read_meta` / `write_meta`, `list(limit, offset)`, `append_segment(id, segment)`, `load_transcript(id) -> (segments, source)`, `load_raw_transcript`, `write_diarized`, `write_edited` / `delete_edited`, `append_translation` / `load_translations`, `speaker_names` / `write_speakers` / `rename_speakers`, `read_minutes` / `write_minutes` / `has_minutes`, `read_action_items` / `write_action_items`. `AudioStore` (open one writer per channel: `write(frames)`, `finalize()`) and `AudioReader` (`frames(id, channel, start, count)`, `length(id, channel)`, `materialize_wav(id, channel) -> Path`) |
| `storage/files/` | `FileSessionRepository` and `FileAudioStore` wrap the current `SessionStore`, `SessionPaths`, sinks, `AlignedWavWriter`, `storage/action_items.py` and `translations_file.py`; behavior and file names unchanged. `materialize_wav` returns the existing WAV path |
| Call sites | `api/routes/sessions.py` (`files`, `folder`, minutes), `api/routes/export.py`, `api/payloads.py`, `session.py` (mix, minutes), `minutes/session_minutes.py`, `diarization/session_diarization.py` (gets the WAV through `materialize_wav`), `storage/recovery.py`, `audio/mixer.py` (reads through `AudioReader`) move to the ports |
| `bootstrap.py` | `REPOSITORIES` / `AUDIO_STORES` registries with one entry, `files`; the only place that builds them |

## Design notes

- Pure refactor: every existing test keeps passing unchanged, except imports and constructor
  wiring. Add a shared **contract test suite** (`tests/storage/repository_contract.py`) that phase
  31 reuses against the SQLite implementation.
- `folder` and `files` stay in the API for the file backend; they become optional in the contract
  (phase 31 omits them).
- Crash-safety rules stay the same: per-segment fsync, atomic replace for JSON files,
  `repair_wav` in recovery. Recovery talks to a `RecoverableStore` capability that the file
  backend implements; SQLite will implement it differently.
- Keep each module under ~200 lines; split `session_store.py` if needed.

## Acceptance criteria

- [ ] No module outside `storage/` and `bootstrap.py` builds a session path or opens a session
      file (check with a grep for `SessionPaths`, `.wav"`, `minutes.md`, `.jsonl`).
- [ ] Contract test suite passes for `FileSessionRepository` / `FileAudioStore`.
- [ ] Full engine suite green, diff coverage ≥ 80 %.
- [ ] Manual: record a 1-minute session from the desktop app, then open minutes, transcript, play
      audio, export docx, run `recover` on a simulated crash (phase 17 recipe A): same results as
      before.

## Tests

`tests/storage/repository_contract.py`, `tests/storage/test_file_repository.py`, existing suites.

## Out of scope

Any new storage backend (31, 32), migration (33), API shape changes.

## Kickoff prompt

> Execute phase 30 of the roadmap (`docs/roadmap/phases/30-storage-port.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/30-storage-port`
- **Status:** in progress
- **Updated:** 2026-10-17 12:30
- **Next step:** document the storage ports in architecture §5/§8 and api-contract, tick the
  acceptance criteria, run the full suites and open the PR

### Steps

- [x] Start the phase (status, Progress)
- [x] Storage ports in `ports.py`, `storage/files/` (`FileSessionRepository`, `FileAudioStore`)
      and the shared contract suites (`tests/storage/repository_contract.py`,
      `tests/storage/audio_contract.py`)
- [x] Recording path on the ports: `session.py`, `session_pipeline.py`, live translation, mixer
      (`AudioReader`), diarization (`materialize_wav`); `REPOSITORIES` / `AUDIO_STORES` in
      `bootstrap.py`
- [x] Minutes, action items, task export, API routes and payloads on the repository
- [x] Recovery on `RecoverableStore`; CLI commands
- [ ] Docs (architecture §5/§8), grep check, full suites, PR

### Decisions and notes

- The port keeps the method names callers already used (`list_sessions()`,
  `load_transcript()` → segments, `load_transcript_with_source()` → `(source, segments)`) instead
  of the sketch's `list(limit, offset)` / `load_transcript() -> (segments, source)`: no caller
  pages in storage today, and phase 31 can add paging behind the same port.
- `append_segment` / `append_translation` became `open_transcript(id, labeler) -> TranscriptSink`
  and `open_translations(id) -> TranslationWriter`: the file backend keeps its open handles,
  per-segment fsync and `transcript.md`; SQLite returns sinks that insert rows.
- `AudioStore.write_mix(id, mixer)` keeps the mix: the file backend writes `mixed.wav`, SQLite
  (phase 32) can skip it and mix on the fly. Mixers read through `AudioReader`.
- Recovery takes a list of `RecoverableStore`s, run in order (`[audio, repository]`): the audio
  store repairs/pads WAVs and returns the length, the repository sets aside a cut transcript
  line. Failures surface as `StoreRepairError` (same message as before).
- `SessionNotFoundError` moved to `ports.py` (re-exported by `session_store`).
- `RecordingSession.paths` became `folder` (messages only); `GET /sessions/{id}` keeps `files` /
  `folder` for the file backend, the schema now allows them to be null for a backend without
  folders (no change in any current response).
- CLI `minutes` / `diarize <session_dir>` open a session folder through
  `storage/files/folder.py` (file backend of the parent); `recover <dir>` gets the store of the
  parent through `bootstrap.build_recovery(settings, output_dir)`.
- The grep check uses fixed strings (`grep -F`): the only hits outside `storage/` and
  `bootstrap.py` are docstrings and the in-memory `audio.wav` upload name of the OpenAI STT.
