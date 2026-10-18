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

- [x] No module outside `storage/` and `bootstrap.py` builds a session path or opens a session
      file (check with a grep for `SessionPaths`, `.wav"`, `minutes.md`, `.jsonl`).
- [x] Contract test suite passes for `FileSessionRepository` / `FileAudioStore`.
- [x] Full engine suite green, diff coverage ≥ 80 %.
- [x] Manual: record a 1-minute session from the desktop app, then open minutes, transcript, play
      audio, export docx, run `recover` on a simulated crash (phase 17 recipe A): same results as
      before. *(`recover` on a simulated crash done offline 2026-10-17; the recording (recipe
      part B) verified on the reference machine 2026-10-17: a real 67 s recording from the
      desktop app, same file set as `main`, API 200s, History shows the session. The tracker
      export of step 5 is left to a manual run with credentials.)*

## Tests

`tests/storage/repository_contract.py`, `tests/storage/test_file_repository.py`, existing suites.

## Out of scope

Any new storage backend (31, 32), migration (33), API shape changes.

## Kickoff prompt

> Execute phase 30 of the roadmap (`docs/roadmap/phases/30-storage-port.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/30-storage-port`
- **Status:** ready for PR
- **Updated:** 2026-10-17 20:50
- **Next step:** open the PR; before merge run part B of the manual check recipe below on the
  reference machine (audio hardware, one phase at a time).

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
- [x] Docs (architecture §2/§5/§8, api-contract), grep check, full suites, manual check recipe
- [x] PR #45 opened; CI (lint, format, compile) green

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
- Checks run in the phase session: full engine suite 1259 passed (3 deselected), coverage
  99.92 % (every new or changed module 100 % of lines), `ruff check` / `ruff format --check`
  clean. `ui/` not touched.

### Manual check recipe

Status: **A done 2026-10-17 (offline, minutes off); B done 2026-10-17** (real 67 s recording from
the desktop app, same file set as `main`, API 200s, History shows the session; the tracker export
of step 5 is pending a manual run with credentials) — run B on the reference machine,
one phase at a time (audio is shared). Nothing about the files may differ from `main`: same
names, same content, same messages.

**A. Simulated crash, no microphone (done).** Phase 17 recipe A with the phase 17 script
`make_crashed_session.py` (copy it from `17-crash-recovery.md`, recipe A step 1), from the repo
root in PowerShell:

```powershell
.venv\Scripts\python make_crashed_session.py engine\recordings engine\tests\data\speech_en.wav
cd engine
..\.venv\Scripts\python -m vozata recover recordings\<printed id>   # exit 0, "Recovered: …"
..\.venv\Scripts\python -m vozata recover recordings\<printed id>   # exit 1, "… was not interrupted …"
```

Expected (seen with `GENERATE_MINUTES=false`, `DIARIZATION_ENABLED=false`): the folder holds
`mic.wav`, `system.wav`, `mixed.wav` (same length), `transcript.jsonl` (2 lines),
`transcript.jsonl.damaged` (the half line), `session.json` with `status: done`,
`duration_seconds: 5.699` and `ended_at`. With minutes on (Ollama running), `minutes.md` is also
written (beta on Friday / Ana).

**B. Real recording from the desktop app (done 2026-10-17; the tracker export is pending, it
needs credentials).**

1. Note the newest folder in `engine/recordings`, then start the app
   (`dotnet run --project ui/src/VozAta.Desktop`) and record ~1 minute while speaking and playing
   a video (both channels). Stop and wait for *idle*.
2. The new session folder has `session.json`, `mic.wav`, `system.wav`, `mixed.wav`,
   `transcript.jsonl`, `transcript.md` and `minutes.md` (plus `action_items.json` with
   `EXTRACT_ACTION_ITEMS=true`, `transcript.diarized.jsonl` + `speakers.json` with
   `DIARIZATION_ENABLED=true`, `transcript.translated.jsonl` when translating) — the same set a
   recording on `main` produces.
3. History → the session: the transcript, minutes and speakers show; rename a speaker, edit a
   line and revert it; "Open folder" opens the folder; the three WAVs play in the OS player with
   the same length.
4. Export → DOCX (and MD / PDF): the files open and contain the minutes and the transcript.
5. Action items: extract again, edit one, export (with a configured tracker): the exported item
   keeps its link after a reload; its description ends with "Session folder: <absolute folder>".
6. API spot check while `serve` runs (`API_PORT`, default 8765):
   `curl http://127.0.0.1:8765/sessions/<id>` lists `files` and the absolute `folder` as before;
   `.../transcript`, `.../minutes` and `.../export?format=docx` answer 200.
7. Run recipe A again with minutes on.
