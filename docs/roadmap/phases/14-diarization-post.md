# Phase 14 — Speaker identification (post-session)

## Goal

After a session ends, identify the different remote speakers in `system.wav` and label system
segments `User 1`, `User 2`, … (localized) in the transcript, minutes and every reader.

## Depends on

05

## Read first

- `engine/CLAUDE.md` ("Add a provider" checklist)
- [architecture.md](../architecture.md) §6 (stop order step 5, VRAM rule), §8 (transcript
  precedence, `transcript.diarized.jsonl`, `speakers.json`), §11 (speaker identification)

## Scope

| File | Content |
|------|---------|
| `domain.py` / `ports.py` | `SpeakerTurn`; `Diarizer` port |
| `diarization/pyannote.py` | `PyannoteDiarizer(hf_token, device)`: loads the current pyannote speaker-diarization pipeline, runs on `system.wav`, returns `SpeakerTurn`s; `close()` frees GPU memory |
| `diarization/assign.py` | pure function `assign_speakers(segments, turns) -> list[TranscriptSegment]`: max-overlap assignment, split at word boundaries on speaker change, number speakers by first appearance (`system:1`, …); mic segments untouched |
| `session.py` | stop step 5 when `DIARIZATION_ENABLED`: release Whisper → diarize → assign → write `transcript.diarized.jsonl` + `speakers.json` → `diarizer.close()` → minutes |
| `__main__.py` | `diarize <session_dir>` for existing sessions (then optionally regenerate minutes) |
| `bootstrap.py` | `DIARIZERS` registry |
| `config.py`, `.env.example` | `DIARIZATION_ENABLED`, `DIARIZATION_PROVIDER`, `DIARIZATION_DEVICE` (`auto`/`cuda`/`cpu`), `HF_TOKEN` (secret), `MIN_SPEAKERS`, `MAX_SPEAKERS` |
| `pyproject.toml` | optional extra `diarization` (`pyannote.audio`, CUDA-enabled `torch`) |
| `labels.py` | `system:<n>` → `labels.user` with `n`, unless a name exists in `speakers.json` |

## Design notes

- **Setup (document in `.env.example` and the PR)**: create a Hugging Face token, accept the terms
  of the pyannote models used, set `HF_TOKEN`.
- `torch` and `ctranslate2` ship their own CUDA/cuDNN libraries — verify both still work in the same
  `.venv`; if they conflict, run the diarizer in a subprocess (keep the `Diarizer` port unchanged).
- Diarization is optional: disabled or failing → log a warning, keep `system` labels, continue to
  minutes.

## Acceptance criteria

- [x] `assign_speakers` tests: full overlap, partial overlap, split on change, unassigned gaps keep
      `system`, numbering by first appearance, mic untouched.
- [x] Session test with `FakeDiarizer`: order Whisper close → diarize → diarizer close → minutes;
      failure path continues.
- [x] `load_transcript` returns the diarized file; labels show `User N` per app language.
- [x] Manual: a recorded call with 2–3 remote people → distinct `User N` labels; GPU memory
      released between steps (check `nvidia-smi`). Done 2026-10-17 (see Progress).
- [x] Coverage ≥ 80 % (pyannote adapter excluded as hardware).

## Tests

`tests/diarization/test_assign.py`, `tests/test_session_diarization.py`, `tests/test_labels.py`
(extended).

## Out of scope

Live labels (15), renaming (16), diarizing the microphone channel.

## Kickoff prompt

> Execute phase 14 of the roadmap (`docs/roadmap/phases/14-diarization-post.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/14-diarization-post`
- **Status:** ready for PR
- **Updated:** 2026-10-17 18:30
- **Next step:** none (phase done). Manual check run 2026-10-17: torch 2.11+cu128 and
  `pyannote.audio` 4 installed in `.venv` (`pytest -m gpu` still passes with Whisper on CUDA),
  token with the community-1 terms accepted. A 95 s TTS call with three voices (Maria pt,
  Daniel pt, Zira en, 13 turns) played on the laptop speakers and recorded with
  `DIARIZATION_ENABLED=true`: `transcript.diarized.jsonl` and `speakers.json` written,
  `system:1` = Maria, `system:2` = Daniel, `system:3` = Zira on every whole turn; two Whisper
  segments that spanned a turn change went to the previous voice, and the last 1-word fragment
  became an extra `system:4`. `nvidia-smi`: Whisper ~3.8 GB → baseline 1.67 GB after it closed →
  diarization child ~3.8 GB → released → Ollama ~5.8 GB for minutes and action items → 1.4 GB
  at the end (never two models at once).

### Steps

- [x] `SpeakerTurn`, `Diarizer` port, `FakeDiarizer`
- [x] `assign_speakers` (pure) with tests
- [x] Config keys (`DIARIZATION_*`, `HF_TOKEN`, `MIN_SPEAKERS`, `MAX_SPEAKERS`), `.env.example`, UI settings strings
- [x] `speakers.json` in the store, labels from speaker names, `diarize_session`
- [x] Session stop step 5 + `DIARIZERS` registry
- [x] pyannote adapter (subprocess) + optional extra `diarization`
- [x] CLI `diarize <session_dir>`
- [x] Docs, acceptance criteria, PR

### Decisions and notes

- Unit tests use `FakeDiarizer`; torch / pyannote are not installed in the shared `.venv`.
- **pyannote runs in a child process** (`SubprocessDiarizer` → `python -m vozata.diarization.child`).
  Coexistence of `torch` and `ctranslate2` CUDA/cuDNN DLLs in one process could not be verified
  without installing torch (forbidden in the shared `.venv`), so the safe option was taken up front:
  the child never shares a process with faster-whisper, and its exit frees all VRAM before the
  minutes. The `Diarizer` port is unchanged. The request (token included) goes over stdin, never
  argv; turns come back through a temp JSON file (libraries may print to stdout).
- Model: `pyannote/speaker-diarization-community-1` (pyannote.audio ≥ 4), audio passed as a
  preloaded waveform (no ffmpeg / torchcodec decoding); the exclusive (overlap-free) annotation is
  used when available.
- Missing `HF_TOKEN` with diarization enabled → localized `errors.config.missing_hf_token` inside the
  `diarization_failed` error; the session continues to minutes.
- The PyInstaller installer (phase 13) does not bundle the extra; diarization needs a source install.

### Manual check recipe (pending manual: credentials + GPU)

Run it alone (audio hardware and GPU are shared with the other phases). From the repo root:

1. Token: create a read token at <https://huggingface.co/settings/tokens> and accept the terms on
   <https://huggingface.co/pyannote/speaker-diarization-community-1>.
2. Extra (in `.venv`, or a copy of it if you want to keep the shared one untouched):
   `.venv/Scripts/python -m pip install torch --index-url https://download.pytorch.org/whl/cu128`
   then `.venv/Scripts/python -m pip install -e "engine[diarization]"`. Check that Whisper still runs
   on the GPU afterwards: `cd engine; ../.venv/Scripts/python -m pytest -m gpu`.
3. `engine/.env`: `DIARIZATION_ENABLED=true`, `HF_TOKEN=hf_...`, optionally `MIN_SPEAKERS=2`,
   `MAX_SPEAKERS=3`.
4. In a second terminal: `nvidia-smi --query-gpu=memory.used --format=csv -l 1`.
5. `cd engine; ../.venv/Scripts/python -m vozata record`, play a call / video with 2–3 different
   remote voices for ~2 minutes (say a few words into the mic too), then Ctrl+C.
6. Expect in the session folder: `transcript.diarized.jsonl` with `system:1`…`system:N`,
   `speakers.json` with those ids, `minutes.md` / `transcript` readers showing `User 1`, `User 2`…
   (`Usuário N` with `APP_LANGUAGE=pt-BR`), `mic` lines unchanged, `transcript.jsonl` untouched.
   In `nvidia-smi`: memory drops after Whisper closes, rises while the
   `python -m vozata.diarization.child` process runs, drops to the baseline when it exits, then
   rises again for Ollama.
7. Existing session: `../.venv/Scripts/python -m vozata diarize recordings/<id> --minutes`.
8. Failure path: blank `HF_TOKEN`, record again → the console shows the localized
   `diarization_failed` message with the retry command, labels stay `Others`, minutes are written.
