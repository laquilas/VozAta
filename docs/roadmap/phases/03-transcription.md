# Phase 03 — Transcription

## Goal

Transcribe fixed windows with faster-whisper, complete sentences cut at window edges with the
carry-over stitcher, lock the conversation language in `auto` mode, and emit segments to sinks.

## Depends on

01

## Read first

- `engine/CLAUDE.md`
- [architecture.md](../architecture.md) §5 (`Transcriber`, `TranscriptSink`), §6 (threads, backlog),
  §7 (stitching — implement exactly), §8 (jsonl schema, segment ids), §9 (keys owned by 03),
  §10 (conversation language, `auto` lock)
- `__legacy__/transcrever.py` — CUDA DLL setup block, `carregar_modelo`

## Scope

| File | Content |
|------|---------|
| `transcription/cuda.py` | `register_cuda_dlls()` — adds `nvidia/cublas/bin` and `nvidia/cudnn/bin` from site-packages to the DLL search path (idempotent) |
| `transcription/faster_whisper.py` | `FasterWhisperTranscriber(settings)`: `WHISPER_DEVICE=auto` tries CUDA with a 1 s warm-up probe and falls back to CPU `WHISPER_CPU_MODEL` int8; `transcribe(samples, language, hints)` with `word_timestamps=True`, `vad_filter=True`, `condition_on_previous_text=False`, `beam_size=1`, `hotwords=hints`; returns `TranscriptionResult` (words with probability, detected language); `close()` deletes the model and runs `gc.collect()` |
| `transcription/stitcher.py` | `CarryOverStitcher(channel, transcriber, settings, language_provider, id_factory)` — architecture §7 |
| `transcription/language_lock.py` | `LanguageLock(initial: ConversationLanguage, on_detected)`: returns the Whisper code to use; in `auto` accumulates speech seconds and detected languages, locks after ≥ 3 s of speech (majority), calls `on_detected(lang)` once |
| `transcription/worker.py` | `TranscriptionWorker(queue, stitchers, sink)` thread: consumes `AudioChunk`s, routes by channel, emits segments; `stop()` drains the queue then flushes stitchers; logs a warning when backlog > 3 chunks per channel |
| `output/sinks.py` | `ConsoleSink`, `JsonlSink` (append + flush per segment), `MarkdownSink` (uses `formatting.render_line` + `SpeakerLabeler`), `CompositeSink` (one failing sink is logged, others continue) |
| `tests/fakes.py` | `FakeTranscriber` scripted with word lists per call |
| `tests/transcription/contract.py` | reusable contract tests for any `Transcriber` (empty result on silence, relative timestamps within audio length, probability in [0, 1]) |

## Design notes

- Segment ids: `<channel>-<6-digit counter>` per session (`mic-000001`).
- Absolute times = stitch buffer start + word relative time.
- `TAIL_MARGIN_SECONDS`, `PAUSE_GAP_SECONDS`, `MAX_CARRY_SECONDS`, `SILENCE_RMS_THRESHOLD`,
  `STT_PROVIDER`, `WHISPER_*` keys are added to `config.py` and `.env.example` here.
- The transcriber is shared by both channels and only called from the worker thread (one GPU).
- `hints` is accepted now and used by phase 19 (custom vocabulary).

## Acceptance criteria

- [ ] Stitcher tests cover: sentence-end cut, pause-gap cut, no safe cut → carry, forced commit at
      `MAX_CARRY_SECONDS`, silence skip without STT call, `flush()`, correct absolute timestamps, no
      duplicated words across windows.
- [ ] `LanguageLock` tests: fixed language passthrough, auto lock after 3 s majority, single callback.
- [ ] Worker drains and flushes on stop; sink failure isolation tested.
- [ ] `FakeTranscriber` passes the contract suite; `FasterWhisperTranscriber` passes it in a manual
      GPU smoke run (`pytest -m gpu`, skipped by default) on a short WAV from `__legacy__/gravacoes/`.
- [ ] GPU → CPU fallback verified manually by setting `WHISPER_DEVICE=cpu`.
- [ ] Coverage ≥ 80 %.

## Tests

`tests/transcription/test_stitcher.py`, `test_language_lock.py`, `test_worker.py`,
`tests/output/test_sinks.py`, `tests/transcription/test_faster_whisper_gpu.py` (marker `gpu`).

## Out of scope

Session wiring and CLI (05), echo dedupe (18), live speaker tags (15), vocabulary source (19).

## Kickoff prompt

> Execute phase 03 of the roadmap (`docs/roadmap/phases/03-transcription.md`), following
> `docs/roadmap/README.md`.
