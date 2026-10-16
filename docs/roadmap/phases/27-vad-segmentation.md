# Phase 27 — Pause-based segmentation (VAD)

## Goal

Cut transcription chunks where people pause instead of every `CHUNK_SECONDS`. Whisper gets whole
phrases (accuracy, punctuation), short sentences appear as soon as the speaker stops (latency),
and silence never reaches the GPU. Origin: [optimizations.md](../optimizations.md) O1.

## Depends on

05

## Read first

- `engine/CLAUDE.md`
- [optimizations.md](../optimizations.md) — O1 (design and diagram)
- [architecture.md](../architecture.md) §6 (data flow), §7 (stitcher), §9 (keys)

## Scope

| File | Content |
|------|---------|
| `ports.py` | `SpeechDetector` port: `speech_spans(samples) -> list[(start, end)]` in seconds |
| `audio/silero.py` | `SileroSpeechDetector` over `faster_whisper.vad.get_speech_timestamps` (bundled Silero ONNX, CPU; no new dependency) — thin, covered by a manual check |
| `audio/vad_chunker.py` | `VadChunker` with the `FixedWindowChunker` interface (`feed`, `flush`, `paused`): buffers since the last cut; every `VAD_CHECK_SECONDS` (0.25) asks the detector; cuts in the middle of a pause ≥ `VAD_MIN_SILENCE_MS` after speech; forces a cut at the longest pause (or the limit) at `VAD_MAX_CHUNK_SECONDS`; drops leading silence while keeping `AudioChunk.start` in session time; merges blips shorter than `VAD_MIN_CHUNK_SECONDS` into the next chunk |
| `bootstrap.py` | `CHUNKERS` registry (`fixed`, `vad`) selected by `CHUNK_MODE` |
| `session_pipeline.py` | build the chunker through the factory (no other change) |
| `config.py`, `settings_fields.py`, `.env.example` | `CHUNK_MODE` (`vad`), `VAD_THRESHOLD` (0.5), `VAD_MIN_SILENCE_MS` (600), `VAD_MIN_CHUNK_SECONDS` (1.0), `VAD_MAX_CHUNK_SECONDS` (15), `VAD_SPEECH_PAD_MS` (200) |

## Design notes

- The carry-over stitcher stays as the safety net for forced cuts; with pause cuts it should
  rarely carry anything.
- Detector cost is bounded by `VAD_MAX_CHUNK_SECONDS` of audio per call (a few ms on CPU).
- `fixed` remains available (benchmarks, noisy environments).

## Acceptance criteria

- [ ] Tests with a fake detector: cut after the pause, forced cut at the maximum, leading silence
      dropped with the correct `start`, blip merging, pause/resume flush, `flush()` at stop.
- [ ] Manual (phase 05 TTS meeting + live speech): compare `fixed` vs `vad` — speech-end-to-line
      latency and WER on the TTS script; record both in the PR. `vad` must not be worse on WER.
- [ ] Coverage ≥ 80 %.

## Tests

`tests/audio/test_vad_chunker.py`, `tests/test_bootstrap.py`, `tests/test_config.py`.

## Out of scope

Per-channel thresholds (only if the manual check shows loopback music being treated as speech).

## Kickoff prompt

> Execute phase 27 of the roadmap (`docs/roadmap/phases/27-vad-segmentation.md`), following
> `docs/roadmap/README.md`.
