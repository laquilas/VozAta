# Phase 55 — WER benchmark

## Goal

A repeatable benchmark of transcription quality and speed, so `CHUNK_SECONDS`, the pause-based
segmentation and the Whisper model can be tuned on numbers instead of impressions. From the
backlog ("WER benchmark harness").

## Depends on

27, 40

## Read first

- `engine/CLAUDE.md`
- `transcription/offline.py` (phase 40: the stored-audio transcription through the live
  chunker → transcriber → stitcher), `audio/chunker.py` and `audio/vad_chunker.py` (phase 27), `config.py`
  (`CHUNK_SECONDS`, `CHUNK_MODE`, VAD keys, Whisper keys)
- `scripts/two_pc_check.py` (the script layout of phase 52)

## Scope

- `benchmarks/<name>/reference.txt` (committed, the exact words said) and `audio.wav`
  (generated locally, git-ignored: `*.wav`). The first set is the TTS meeting of the reference
  machine (`benchmarks/tts-meeting/`), made by `scripts/make_tts_reference.ps1` (Windows voices,
  16 kHz mono).
- `scripts/wer_benchmark.py`: for each benchmark and each configuration of a grid
  (`--grid CHUNK_SECONDS=4,6,8 CHUNK_MODE=vad,fixed WHISPER_MODEL=large-v3`), runs the offline
  transcription of the engine on the audio (as the mic channel) and reports **WER**, word
  substitutions / insertions / deletions and the real-time factor, as a Markdown table (stdout
  and `benchmarks/results/<date>.md`, git-ignored). First-word latency does not exist offline;
  the live latency is the chunk length plus the transcription time, which the RTF bounds.
- WER on normalized words: lower case, punctuation removed, numbers as written; Levenshtein
  alignment on words (no new dependency).
- Pure parts (normalization, alignment, WER, grid parsing, report) unit-tested; the run itself
  needs the GPU and is a manual step.

## Acceptance criteria

- [ ] `scripts/wer_benchmark.py --grid CHUNK_SECONDS=4,6 ...` on the TTS meeting prints a table
      with WER and speed per configuration.
- [ ] The first results are recorded in this file and the defaults are kept or changed from them.

## Tests

Normalization (accents kept, punctuation, case), alignment counts (S / I / D) on known pairs,
WER edge cases (empty reference / hypothesis), grid parsing errors, report rendering.

## Out of scope

Speaker-attributed WER (cpWER), downloading public corpora, CI runs.

## Kickoff prompt

> Start phase 55 (`docs/roadmap/phases/55-wer-benchmark.md`): read its *Read first* files, write
> `plans/55-wer-benchmark.md`, then implement it task by task.

## Progress

- **Branch:** `feature/55-wer-benchmark`
- **Status:** in progress
- **Updated:** 2026-10-23
- **Next step:** task 4: run the grid `WHISPER_MODEL=large-v3,large-v3-turbo CHUNK_MODE=vad,fixed
  CHUNK_SECONDS=4,8` (`HF_HUB_OFFLINE=1`, `TRANSCRIPTION_LANGUAGE=pt`) and record the table here.

### Steps

- [x] Implementation plan (`plans/55-wer-benchmark.md`)
- [x] Pure parts: normalization, alignment, WER, grid, report
- [x] Runtime (offline transcription of a WAV) and the TTS reference
- [ ] First benchmark run, defaults kept or changed
- [ ] Docs, full suites, phase done

### Decisions and notes

- Commits stay local until the PR (user rule, 2026-10-20).
- The TTS meeting is 62.9 s (9 sentences, Microsoft Maria Desktop, 0.8 s pauses). A first run with
  the defaults (large-v3, VAD) got WER 0.0 % at RTF 0.44: clean TTS audio, so it mostly measures
  speed and chunking accidents; real recordings belong in further benchmark folders.
