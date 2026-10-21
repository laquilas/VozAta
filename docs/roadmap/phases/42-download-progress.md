# Phase 42 — Model download progress bar

## Goal

When a model is not in the local cache, the first recording silently downloads it (≈ 1.6 GB for
`large-v3-turbo`) and the app looks frozen. Show a **progress bar at the bottom of the window**
while any model downloads, with the text **in the middle of the bar** saying what is being
downloaded, e.g. "Downloading speech model large-v3-turbo — 45 % (720 MB of 1.6 GB)". It
disappears when the download ends.

Found on 2026-10-20 while testing the packaged app: a 16 s meeting stayed `finalizing` for
≈ 20 min because the speech model was downloading at ≈ 700 KB/s with no feedback.

## Depends on

26, 35

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- `docs/roadmap/architecture.md` §16 (desktop shell)
- [phase 26](26-capture-first.md) (`model_loading`, `_DeferredTranscriber`)
- `transcription/faster_whisper.py`, `translation/opus_mt.py`, `diarization/` (where models load)

## Current state (facts, 2026-10-20)

- `FasterWhisperTranscriber` builds `WhisperModel(size, device, compute_type)`, which downloads
  from Hugging Face on first use; `HF_HUB_DISABLE_XET=1` is set. Opus-MT uses
  `huggingface_hub.snapshot_download`. No progress callback exists anywhere; the only event is
  `model_loading {loading}`.
- The shell (`ShellView.axaml`) has top banners (migration has a `ProgressBar`) and bottom-right
  toasts; there is no bottom bar.

## Scope

**Engine**

| File | Content |
|------|---------|
| `models/download.py` (new) | `ModelDownloader` port + Hugging Face implementation: before a model loads, if the repo is not fully cached, `snapshot_download` with a progress hook (custom `tqdm_class`) summing bytes over files; reports `{kind, model, downloaded_bytes, total_bytes}` |
| `transcription/faster_whisper.py` | resolve the model through the downloader first, then load from the local path |
| `translation/opus_mt.py`, diarization model load | the same downloader |
| `api/events` / `session_manager.py` or a small `DownloadTracker` | `download_progress` event, throttled (≤ 2 per second), plus a snapshot on WebSocket connect while a download runs |
| `bootstrap.py` | wiring |

**UI**

| File | Content |
|------|---------|
| `VozAta.Client` | `DownloadProgressEvent` |
| `DownloadBarViewModel` (new) | current download(s): text, percent, visible |
| `ShellView.axaml` | a full-width bar docked at the bottom of the page area: `ProgressBar` with the label centered over it |
| Resources | model kind names and the label format in en / pt-BR / es |

## Design notes

- Event `download_progress`: `{kind: "speech" | "speakers" | "translation", model,
  downloaded_bytes, total_bytes, state: "running" | "done" | "failed"}` (envelope `session_id`
  null). `total_bytes` may be null when unknown: the bar is then indeterminate and the text shows
  only the downloaded size.
- Label: "Downloading <kind> model <model> — 45 % (720 MB of 1.6 GB)". Two downloads at once show
  one bar with the sum and "2 models".
- A failed download (network down) hides the bar and shows an error toast with the reason; the
  existing `model_failed` path follows.
- The bar is independent of recording: it shows during a recording, during background processing
  (phase 40, when its transcribe or diarize step needs a model) and on the Config page's model
  tests.
- Closing the app kills the engine and its download; there is no download outside the engine.
- Offline mode (`HF_HUB_OFFLINE=1`) never downloads: no bar, the existing error applies.
- No resume: huggingface_hub 2.2.0 writes each file to a unique `.{uuid}.incomplete` and deletes it
  on failure, so an interrupted download starts again from 0 (amended 2026-10-20).
- pyannote loads its models in a child process with no progress channel: the engine pre-downloads
  both pyannote repos (with `HF_TOKEN`) through the downloader before spawning the child, which then
  loads from the cache (amended 2026-10-20).
- `HF_HUB_DISABLE_XET` is read once when huggingface_hub is first imported: it is set at the start
  of `vozata.__main__` (the late `setdefault` in the transcriber had no effect under `serve`).

## Acceptance criteria

- [ ] With the speech model missing from the cache, starting a recording shows the bottom bar with
      "Downloading speech model …", the percent grows, and the bar disappears when the model
      loads.
- [ ] A UI that reconnects to the running engine during a download (e.g. the window restored
      from the tray) shows the bar again with the current percent.
- [ ] After the app is closed mid-download, the next time the model is needed (a recording, or
      the phase 40 queue resuming) the download starts again and the bar shows it (no resume:
      see the design notes).
- [ ] Pulling the network cable shows an error toast and hides the bar.
- [ ] Cached models never show the bar.
- [ ] Contract docs updated (`download_progress`).

## Tests

Engine: progress summing over several files with a fake hub, throttling, done/failed events,
cached model skips the download, offline mode. UI: bar visibility, label text and percent,
indeterminate state, two downloads, failure toast, locale parity.

## Out of scope

- Pre-downloading models from the Config page (a later "Download now" button can reuse this).
- Ollama model pulls (Ollama manages them).

## Progress

- **Branch:** `feature/42-download-progress`
- **Status:** in progress
- **Updated:** 2026-10-20 23:30
- **Next step:** Task 4 of `plans/42-download-progress.md` (full suites, manual check).

### Steps

- [x] Implementation plan (`plans/42-download-progress.md`) and spec amendments
- [x] Downloader and tracker
- [x] Wire the downloads and the event
- [x] UI bottom bar
- [ ] Full suites, manual check

### Decisions and notes

- Commits stay local until the PR (user rule, 2026-10-20: save GitHub Actions minutes).
- The three design notes marked "amended 2026-10-20" come from the code map: no resume in
  huggingface_hub 2.2.0, pyannote pre-downloaded in the engine, XET switched off at engine start.
- huggingface_hub 2.2.0 feeds every HTTP chunk to two byte bars (transfer and reconstruct): the
  byte counter reports the furthest byte bar, not their sum, so bytes are not counted twice.
- The registries' model providers take `(settings, downloader)`; `serve` shares one
  `HubDownloader` over one `DownloadTracker` (`download_progress`), the CLI prints progress to stderr instead.
  The event's `model` is the name the user knows (`large-v3-turbo`, `ROMANCE-en`,
  `speaker-diarization-community-1`), and `total_bytes` leaves out files already cached.
- `HF_HUB_OFFLINE` is read by `config.py` from the process environment only (huggingface_hub
  ignores `.env`), as `Settings.hf_hub_offline`; `PUT /settings` keeps the start-up value.
- Review fix: the queue's `diarize` step downloads pyannote inside the diarizer factory, before a
  cancellable diarizer exists; the finisher now checks the token right after the factory (closes
  it, `StepCancelled`) and `SubprocessDiarizer.cancel()` is final, so a live recording that
  pre-empts the step during the download never gets the child spawned next to its Whisper.
- Final review fix: the CLI download progress was logged at INFO under a WARNING-level logging
  setup, so it never showed; `cli_progress.DownloadReporter` now prints localized lines
  (`cli.download_*`) to stderr every 5 s and when the download ends.
- Final review fix: `huggingface_hub>=2.2,<3` is a main dependency (the downloader relies on its
  2.x `snapshot_download`: two byte bars through `tqdm_class`, `IncompleteSnapshotError`).
- Final review fix: `Settings.hf_hub_offline` also reads `TRANSFORMERS_OFFLINE` when
  `HF_HUB_OFFLINE` is unset or empty, as huggingface_hub does.
- Final review fix: concurrent `ensure()` calls for the same repo and `allow_patterns` share one
  download (one tracker handle); the byte counter moved to `models/byte_counter.py`.
- Final review fix: a `failed` event's `reason` is the error's first line (hub messages are
  multi-line), at most 200 characters.
