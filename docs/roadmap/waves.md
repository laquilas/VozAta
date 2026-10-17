# VozAta — Parallel waves

The phases still `todo` in [README.md](README.md), grouped into waves. Phases in the same wave run
at the same time, each in its own session or agent and on its own `feature/<NN-slug>` branch. A
wave starts once every PR of the previous wave is merged into `main`.

The waves are chosen to keep phases that edit the same hotspot apart:

- `session.py` stop sequence: 14, 17, 22, 23.
- Transcription path (`worker.py`, `session_pipeline.py`): 15, 18, 19, 29.
- Session detail (`HistoryView` / `SessionDetailViewModel`): 20, 21, 22, 23.
- Start screen (`MainWindow` / `MainViewModel`): 17, 19, 20, 29.

| Wave | Phases | Notes |
|------|--------|-------|
| 1 | 14, 18, 20, 22 | 14 and 18 are engine only; 20 and 22 share only a little of the session detail |
| 2 | 16, 19, 21, 24 | need 14 (16) and 22 (21, 24); 19 is the only one in the transcription path |
| 3 | 15, 17, 23, 29 | 17 comes after the stop steps have settled; 15 and 29 use separate workers |

```mermaid
graph LR
  W1[Wave 1: 14 18 20 22] --> W2[Wave 2: 16 19 21 24]
  W2 --> W3[Wave 3: 15 17 23 29]
```

## Rules for parallel phases

1. Follow [README.md](README.md) *How to run a session* and the project `CLAUDE.md`.
2. **Resume first**:
   - Run `git fetch`.
   - If `feature/<NN-slug>` exists (local, remote or as an open PR), check it out, run
     `git status`, and continue from the phase file's Progress *Next step*.
   - Otherwise, branch from an up-to-date `main`.
3. Touch only what the phase needs. Expect **additive** conflicts with the other phases of the
   wave, in:
   - `config.py`, `settings_fields.py` (`FIELDS`) and `engine/.env.example`;
   - `Strings*.resx`, `Dtos.cs`, `EngineClient.cs` and `FakeEngineClient.cs`;
   - the README status table.

   Resolve them by merging `origin/main` into the branch. Never rebase or force-push.
4. Work with TDD and keep one concern per commit. Every commit updates Progress and is pushed.
5. Do not run microphone, speaker or GPU checks inside a parallel session. The audio hardware is
   shared, so these run one phase at a time before merge. Write an exact **manual check recipe**
   in Progress instead.
6. A check that needs credentials you don't have (HF token, Azure DevOps PAT, GitHub token) is
   marked `pending manual (credentials)` in Progress. The phase is still finished on fakes.
7. When done:
   - Tick the acceptance criteria and set the README status to `done`.
   - Run the full engine and UI test suites locally (PR CI only lints and compiles), then open
     the PR and wait for the checks. Fix failures from the logs, at most 5 cycles.
   - Report the PR number and the manual check recipe.

## Prompts

Paste a prompt into a fresh session, either to start the phase or to resume it.

### Wave 1

**14 — Speaker identification (post-session)**
> Execute (or resume) phase 14 of the roadmap (`docs/roadmap/phases/14-diarization-post.md`),
> following `docs/roadmap/README.md` and the rules in `docs/roadmap/waves.md`. It runs in parallel
> with phases 18, 20 and 22.
> - pyannote sits behind the `Diarizer` port, as the optional extra `diarization`.
> - If torch and ctranslate2 clash over CUDA, run the diarizer in a subprocess.
> - Without HF_TOKEN, mark the real check `pending manual (credentials)`.

**18 — Echo dedupe**
> Execute (or resume) phase 18 of the roadmap (`docs/roadmap/phases/18-echo-dedupe.md`), following
> `docs/roadmap/README.md` and the rules in `docs/roadmap/waves.md`. It runs in parallel with
> phases 14, 20 and 22.
> - Engine only.
> - The filter goes in front of the sinks.
> - Document the new counter `session.json.echo_dropped` in architecture §8.

**20 — Minutes templates**
> Execute (or resume) phase 20 of the roadmap (`docs/roadmap/phases/20-minutes-templates.md`),
> following `docs/roadmap/README.md` and the rules in `docs/roadmap/waves.md`. It runs in parallel
> with phases 14, 18 and 22.
> - Templates are package data (`pyproject.toml`), in en, pt-BR and es.
> - Keep the session detail changes to the regenerate action.

**22 — Cross-session search**
> Execute (or resume) phase 22 of the roadmap (`docs/roadmap/phases/22-search.md`), following
> `docs/roadmap/README.md` and the rules in `docs/roadmap/waves.md`. It runs in parallel with
> phases 14, 18 and 20.
> - Use stdlib sqlite3 FTS5; check that it is available.
> - Indexing is a stop step in `session.py`.
> - Expose `SearchIndex` so phases 21 and 24 can reuse it.

### Wave 2

**16 — UI speaker rename**
> Execute (or resume) phase 16 of the roadmap (`docs/roadmap/phases/16-ui-speaker-rename.md`),
> following `docs/roadmap/README.md` and the rules in `docs/roadmap/waves.md`. It runs in parallel
> with phases 19, 21 and 24.
> - Use the `speakers.json` written by phase 14.
> - The rename UI lives in the session detail.

**19 — Custom vocabulary**
> Execute (or resume) phase 19 of the roadmap (`docs/roadmap/phases/19-custom-vocabulary.md`),
> following `docs/roadmap/README.md` and the rules in `docs/roadmap/waves.md`. It runs in parallel
> with phases 16, 21 and 24.
> - It is the only phase of the wave that touches `worker.py` and `faster_whisper.py`.
> - Add the glossary to the minutes prompt without breaking phase 20's templates.

**21 — Editable transcript**
> Execute (or resume) phase 21 of the roadmap (`docs/roadmap/phases/21-editable-transcript.md`),
> following `docs/roadmap/README.md` and the rules in `docs/roadmap/waves.md`. It runs in parallel
> with phases 16, 19 and 24.
> - After saving edits, call `SearchIndex.index_session` (phase 22).
> - Document the `edited` field in api-contract and architecture §8.

**24 — Ask the meeting**
> Execute (or resume) phase 24 of the roadmap (`docs/roadmap/phases/24-ask-the-meeting.md`),
> following `docs/roadmap/README.md` and the rules in `docs/roadmap/waves.md`. It runs in parallel
> with phases 16, 19 and 21.
> - Retrieval reuses phase 22's `SearchIndex`.
> - The LLM goes through the `LanguageModel` port, with a fake in tests.

### Wave 3

**15 — Speaker identification (live)**
> Execute (or resume) phase 15 of the roadmap (`docs/roadmap/phases/15-diarization-live.md`),
> following `docs/roadmap/README.md` and the rules in `docs/roadmap/waves.md`. It runs in parallel
> with phases 17, 23 and 29.
> - Live diarization runs in its own worker and never blocks the transcription path.
> - Without HF_TOKEN, mark the real check `pending manual (credentials)`.

**17 — Crash recovery**
> Execute (or resume) phase 17 of the roadmap (`docs/roadmap/phases/17-crash-recovery.md`),
> following `docs/roadmap/README.md` and the rules in `docs/roadmap/waves.md`. It runs in parallel
> with phases 15, 23 and 29.
> - `recover()` reuses the session's own stop-step list, so it includes diarization (14),
>   indexing (22) and action items (23) without duplicating them.

**23 — Action items export**
> Execute (or resume) phase 23 of the roadmap (`docs/roadmap/phases/23-action-items.md`),
> following `docs/roadmap/README.md` and the rules in `docs/roadmap/waves.md`. It runs in parallel
> with phases 15, 17 and 29.
> - The Azure DevOps and GitHub exporters are registered in `TASK_EXPORTERS`.
> - Tests use fakes or mocked HTTP.
> - The real export is `pending manual (credentials)` without tokens.

**29 — Live translation**
> Execute (or resume) phase 29 of the roadmap (`docs/roadmap/phases/29-live-translation.md`),
> following `docs/roadmap/README.md` and the rules in `docs/roadmap/waves.md`. It runs in parallel
> with phases 15, 17 and 23.
> - The CPU translator runs in its own worker.
> - Record the provider choice in architecture.
> - If the model download is impractical, the real check stays pending.
