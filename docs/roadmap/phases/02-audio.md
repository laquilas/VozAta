# Phase 02 — Audio capture and files

## Goal

Capture microphone and system audio (WASAPI loopback) as separate 16 kHz mono streams, write
clock-aligned WAVs, cut fixed transcription windows, and mix the final tracks.

## Depends on

01

## Read first

- `engine/CLAUDE.md`
- [architecture.md](../architecture.md) §1 (legacy code table), §5 (`AudioSource`, `AudioSink`,
  `AudioMixer`), §6 (data flow, pause), §8 (WAV files), §9 (`MIX_MODE`)
- `__legacy__/gravar_reuniao.py` — `Fonte`, `misturar_estereo`, `main()` device discovery

## Scope

| File | Content |
|------|---------|
| `audio/devices.py` | `DeviceInfo` dataclass; `list_input_devices()`, `list_loopback_devices()`, `default_input()`, `default_loopback()`, `find_device(id)` (PyAudioWPatch) |
| `audio/capture.py` | `WasapiSource(device, clock, sample_rate)` implementing `AudioSource`: callback → queue → consumer thread; downmix; `soxr.ResampleStream`; calls `on_samples(samples, session_time)`; counts overflows |
| `audio/clock.py` | `SessionClock` (`start()`, `now() -> float` seconds since start) — injectable, faked in tests |
| `audio/wav_writer.py` | `AlignedWavWriter(path, sample_rate, tolerance=0.15)` implementing `AudioSink`: inserts silence when `at` is ahead of written samples by more than the tolerance; `finalize(total_seconds)` pads to the exact length and closes |
| `audio/chunker.py` | `FixedWindowChunker(channel, chunk_seconds, sample_rate, on_chunk)`: accumulates samples, emits `AudioChunk(start=…)` every window, `flush()` emits the partial window, `paused` flag drops audio |
| `audio/mixer.py` | `MonoMixer` (float sum, hard clip to [-1, 1]) and `StereoMixer` (L = mic, R = system), both streaming in 60 s blocks |
| `audio/levels.py` | `rms_db(samples) -> float` (floor −90 dB) — used by the console meter (05) and `level` events (06) |
| `engine/scripts/smoke_capture.py` | manual check: records 10 s of both devices to a temp folder and prints levels |

## Design notes

- Windows loopback delivers **no data while nothing plays** — `AlignedWavWriter` fills gaps so mic
  and system WAVs stay aligned to the session clock (legacy `Fonte._gravar`).
- Use a resampler with state (`soxr.ResampleStream`) to avoid clicks between blocks.
- Capture block size 0.1 s; never block inside the PortAudio callback.
- Mixers are selected by `MIX_MODE` in `bootstrap.py` (phase 05); this phase only adds the
  classes and the `MIX_MODE` key (`mono` | `stereo`) to `config.py` / `.env.example`.
- Paused audio: chunker drops samples; WAV writer writes silence (keeps alignment).

## Acceptance criteria

- [x] Gap filling, padding and equal final length proven by unit tests with a fake clock.
- [x] Chunker emits windows with correct `start` values, flushes partial windows, respects pause.
- [x] Mono and stereo mixes verified sample-by-sample on synthetic WAVs (including clipping and
      different input lengths).
- [x] `smoke_capture.py` run manually: both WAVs have equal duration and audible content (record
      the result in the PR description).
- [x] Coverage ≥ 80 % excluding `capture.py`/`devices.py` (hardware, marked `# pragma: no cover`
      only on device calls).

## Tests

`tests/audio/test_wav_writer.py`, `test_chunker.py`, `test_mixer.py`, `test_levels.py`
(numpy synthetic audio, `tmp_path`, fake clock).

## Out of scope

Transcription (03), session orchestration and CLI (05), device selection UI (08).

## Kickoff prompt

> Execute phase 02 of the roadmap (`docs/roadmap/phases/02-audio.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/02-audio`
- **Status:** ready for PR
- **Updated:** 2026-10-16 07:40
- **Next step:** open the PR (record the smoke results below in its description) and merge.

### Steps

- [x] Start phase: status `in progress`, Progress section — `5e91877`
- [x] `audio/levels.py` (`rms_db`) + `audio/clock.py` (`SessionClock`) — `f957159`
- [x] `audio/wav_writer.py` (`AlignedWavWriter`): gap fill, pause, padding — `69a0f8c`
- [x] `audio/chunker.py` (`FixedWindowChunker`): windows, gap fill, flush, pause — `cce70a1`
- [x] `audio/mixer.py` (`MonoMixer`, `StereoMixer`) + `MIX_MODE` in config — `604e113`
- [x] `audio/devices.py` (testable with a fake PyAudio) — `3a98cdd`
- [x] `audio/capture.py` (`WasapiSource`) + `engine/scripts/smoke_capture.py`; run the smoke check — `a91d072`
- [x] Verify; tick acceptance criteria; set phase `done`

### Decisions and notes

- **`at` in `AudioSink.write(samples, at)`** is the session time of the block's first sample. `WasapiSource` timestamps blocks in the PortAudio callback and subtracts the block duration.
- **Chunker gap fill**: the chunker fills loopback gaps with zeros (same 0.15 s tolerance as the writer), so window `start` values follow the session clock. Pausing flushes the partial window and drops audio; windows restart at the resume time.
- **Equal length**: `AlignedWavWriter.samples_written` lets the session (05) finalize every WAV to the longest one; `finalize` pads and never truncates.
- `tests/` and `tests/audio/` are packages (`__init__.py`) so test modules in subfolders get unique names.
- Device discovery lists **WASAPI** devices; `default_input()` uses WASAPI's default capture device (the system default is MME). On the reference machine: WASAPI mic id 9, default loopback id 10.
- Device names from PortAudio can contain mis-decoded characters (seen: `Intel�`); phase 08 (device UI) should handle display names.
- **Smoke check blocked (2026-10-15 23:06–23:12)**: opening the microphone (Intel Smart Sound array mic) hung in `pa.open` on WASAPI and MME, and `ffmpeg` DirectShow could not record from it either. At 23:09 Windows logged `AppHangXProcB1` (`svchost.exe_Audiosrv` waiting on `audiodg.exe`) and killed Windows Audio, which auto-restarted at 23:10. After that, `PyAudio()` initialization itself hangs, so audio needs a reboot. Before the stack wedged, the loopback (id 10) opened in 1.7 s and streamed. It is unclear whether the first WASAPI mic open triggered the driver hang or met an already-wedged driver.
- **Robustness (for phase 05)**: a device open can hang indefinitely in the driver. `RecordingSession` must start sources with a timeout (e.g. open on a worker thread and fail the session with a localized error), never block forever.
- **Smoke check (2026-10-16, after a reboot)**: `smoke_capture.py --seconds 10 --tone` produced
  `mic.wav` and `system.wav` of **equal length (40.160 s, 642 568 samples each)**, 0 overflows;
  `system.wav` RMS -23.2 dBFS (tone captured), `mic.wav` RMS -63.6 dBFS (quiet room). The files
  were 40 s, not 10 s, because opening the first device took ~30 s; the writer gap-filled that
  time with silence as designed. A separate run delivered 2 s of mic audio (32 000 samples at
  16 kHz) with a 0.18 s open.
- **The Intel Smart Sound mic driver is unreliable on the reference machine**: in later runs the
  open took 46 s, hung indefinitely (`pa.open` in `pyaudiowpatch.Stream.__init__`), then failed
  with `Invalid device` / a segfault, until WASAPI listed no input devices at all. Plain PyAudio
  opens fail the same way, so the cause is the driver, not `WasapiSource`. This confirms the
  phase 05 requirement: open sources on a worker thread with a timeout and fail the session with
  a localized error.
