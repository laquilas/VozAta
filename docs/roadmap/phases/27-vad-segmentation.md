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

## Progress

- **Branch:** `feature/27-vad-segmentation`
- **Status:** in progress
- **Updated:** 2026-10-16 18:40
- **Next step:** manual comparison: play the phase 05 TTS meeting on the speakers and record it once with `CHUNK_MODE=fixed` and once with `CHUNK_MODE=vad` (env overrides from memory); compare WER against the script and speech-end-to-line latency; record both in Progress and the PR

### Steps

- [x] Start the phase (README status, Progress section)
- [x] Config: `CHUNK_MODE` (`vad` | `fixed`), `VAD_THRESHOLD`, `VAD_MIN_SILENCE_MS`,
      `VAD_MIN_CHUNK_SECONDS`, `VAD_MAX_CHUNK_SECONDS`, `VAD_SPEECH_PAD_MS` — `21963c2`
- [x] Ports `Chunker` and `SpeechDetector`; `VadChunker` (fake-detector tests) — `8fa408e`
- [x] `AudioChunk.complete`; the stitcher commits every word of a complete chunk — `59ea83e`
- [x] `SileroSpeechDetector`, `CHUNKERS` registry, `CapturePipeline` builds chunkers through a factory — this commit
- [ ] Manual: TTS meeting `fixed` vs `vad` (latency, WER); acceptance criteria

### Decisions and notes

- **Raw spans from the detector, policy in the chunker.** `SileroSpeechDetector` returns unpadded
  speech spans (`min_silence_duration_ms=100`, `speech_pad_ms=0`); `VadChunker` merges spans closer
  than `VAD_MIN_SILENCE_MS`, applies `VAD_SPEECH_PAD_MS`, picks cuts and handles blips, so all the
  behaviour is unit-tested with a fake detector.
- **Complete chunks.** The stitcher holds back words ending within `TAIL_MARGIN_SECONDS` of the
  chunk end. A pause cut ends ~0.3 s after the last word, so the last phrase would wait for the next
  speech — losing the latency gain. `AudioChunk` gets `complete: bool = False`; `VadChunker` sets it
  when the cut lies in a pause ≥ `VAD_MIN_SILENCE_MS`, and the stitcher then commits every word and
  drops the rest of the chunk. Forced cuts without such a pause stay incomplete and use the normal
  carry-over.
- **Blips.** Speech shorter than `VAD_MIN_CHUNK_SECONDS` is not cut on its own; it joins the next
  utterance, or leaves at the forced cut (`VAD_MAX_CHUNK_SECONDS`) / `flush()` if nobody speaks.
- Silero (faster-whisper 1.2.1 `get_speech_timestamps`) is stateless per call and runs on CPU with
  one ONNX thread, so one shared model serves both channels.
