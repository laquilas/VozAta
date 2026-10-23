# Plan — Phase 55: WER benchmark

Phase file: `docs/roadmap/phases/55-wer-benchmark.md`. Branch `feature/55-wer-benchmark`.

## Shape (like phase 52's scripts)

- `scripts/wer_benchmark.py`: the pure parts, unit-tested in `engine/tests/scripts/`:
  `normalize(text)` (lower case, punctuation and symbols out, accents kept, whitespace collapsed),
  `align(reference, hypothesis) -> Counts(substitutions, insertions, deletions, words)` (word
  Levenshtein with a backtrace), `wer(counts)`, `parse_grid(["CHUNK_SECONDS=4,6", …])` → list of
  override dicts (cartesian product, order kept; `KEY=` errors), `render(rows)` (Markdown table),
  `main()` (argument parsing, the loop, the report file).
- `scripts/wer_runtime.py` (thin): `transcribe(wav, overrides) -> (text, seconds)` runs the
  engine's `OfflineTranscription` over an in-memory session (the WAV as the mic track, silence as
  the system track, no echo dedupe), with the configured chunker and transcriber; `load_wav`.
- `benchmarks/tts-meeting/reference.txt` (committed) and `scripts/make_tts_reference.ps1`
  (Windows PowerShell 5, System.Speech, "Microsoft Maria Desktop", 16 kHz mono, 0.8 s pauses) →
  `benchmarks/tts-meeting/audio.wav` (git-ignored like every WAV). Results go to
  `benchmarks/results/<timestamp>.md` (git-ignored).
- Metrics per configuration: WER, S / I / D, real-time factor (processing seconds / audio
  seconds). First-word latency does not exist offline and is left out (the live latency is the
  chunk length plus the transcription time, which RTF already bounds).

## Steps

1. Phase start (this plan, README, Progress).
2. Pure parts with tests first.
3. Runtime + TTS reference + `.gitignore` for `benchmarks/results/`.
4. Run the grid on the reference machine (`WHISPER_MODEL=large-v3`, `HF_HUB_OFFLINE=1`,
   `CHUNK_MODE=vad,fixed`, `CHUNK_SECONDS=4,6,8`), record the table in the phase file and keep or
   change the defaults from it.
5. Docs: a "Benchmark" section in `docs/INSTALL.md` (building yourself) or a new
   `docs/benchmark.md`; full suites; PR.
