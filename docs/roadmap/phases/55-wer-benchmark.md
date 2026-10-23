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
- **Next step:** task 3: `scripts/wer_runtime.py` (`OfflineTranscription` over an in-memory session:
  the WAV as mic, silence as system, no echo dedupe) and `scripts/make_tts_reference.ps1`;
  `benchmarks/results/` git-ignored.

### Steps

- [x] Implementation plan (`plans/55-wer-benchmark.md`)
- [x] Pure parts: normalization, alignment, WER, grid, report
- [ ] Runtime (offline transcription of a WAV) and the TTS reference
- [ ] First benchmark run, defaults kept or changed
- [ ] Docs, full suites, phase done

### Decisions and notes

- Commits stay local until the PR (user rule, 2026-10-20).