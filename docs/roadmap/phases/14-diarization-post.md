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

- [ ] `assign_speakers` tests: full overlap, partial overlap, split on change, unassigned gaps keep
      `system`, numbering by first appearance, mic untouched.
- [ ] Session test with `FakeDiarizer`: order Whisper close → diarize → diarizer close → minutes;
      failure path continues.
- [ ] `load_transcript` returns the diarized file; labels show `User N` per app language.
- [ ] Manual: a recorded call with 2–3 remote people → distinct `User N` labels; GPU memory
      released between steps (check `nvidia-smi`).
- [ ] Coverage ≥ 80 % (pyannote adapter excluded as hardware).

## Tests

`tests/diarization/test_assign.py`, `tests/test_session_diarization.py`, `tests/test_labels.py`
(extended).

## Out of scope

Live labels (15), renaming (16), diarizing the microphone channel.

## Kickoff prompt

> Execute phase 14 of the roadmap (`docs/roadmap/phases/14-diarization-post.md`), following
> `docs/roadmap/README.md`.
