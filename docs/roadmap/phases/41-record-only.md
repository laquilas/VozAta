# Phase 41 — Live transcription toggle (record only, transcribe after)

## Goal

A **"Live transcription"** checkbox on the recorder (pt-BR "Transcrição simultânea", es
"Transcripción simultánea"):

- **Checked** (default): today's behavior; after Stop the remaining work goes to the phase 40
  queue.
- **Unchecked**: the meeting is **only recorded** (audio + level meters). Nothing is transcribed,
  translated or diarized live, and no model is loaded. **As soon as Stop is pressed**, the meeting
  enters the processing queue, which transcribes the **whole recording** and then runs speaker
  identification, minutes and action items, with progress in %.

Requested by the user on 2026-10-20.

## Depends on

40

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- [phase 40](40-background-processing.md) (queue, job steps, GPU gate, `OfflineTranscription`,
  `processing` event)
- `docs/roadmap/architecture.md` §5 (`AudioReader`, `AudioTracks`), §6 (live pipeline), §7
  (stitching)
- [phase 26](26-capture-first.md), [phase 27](27-vad-segmentation.md) (chunkers)

## Current state (facts, 2026-10-20)

- The live path is chunker (`FixedWindowChunker` / `VadChunker`, pure numpy, `feed(samples float32,
  at)`, `flush()`) → queue → `TranscriptionWorker` → `CarryOverStitcher` per channel →
  `EchoFilter` → `LiveSpeakerSink` → sinks. `CapturePipeline.receiver(channel)` writes the WAV
  and feeds the chunker.
- Phase 40 adds `OfflineTranscription` (stored audio from a start time, through the live
  components) and the queue's `transcribe` step.
- Stored audio is readable through `AudioReader.frames(session_id, channel, start, count)` (int16)
  and `length()`, `sample_rate()`, for both storage backends.
- Per-recording options travel in `POST /sessions` (`StartSession`, `extra="forbid"`) →
  `StartOptions` → `build_session` → `SessionMeta`; defaults come from engine settings
  (`TRANSCRIPTION_LANGUAGE`, `MINUTES_TEMPLATE`, `TRANSLATE_TO`).

## Scope

**Engine**

| File | Content |
|------|---------|
| `config.py`, `settings_fields.py`, `.env.example` | `LIVE_TRANSCRIPTION=true` (default for new recordings) |
| `api/schemas.py`, `routes/sessions.py`, `session_manager.py` | `StartSession.live_transcription: bool \| null` (null = the setting) |
| `bootstrap.build_session`, `session.py` | with live transcription off: capture + WAV/chunk writing only; no chunkers, transcriber, live diarization, translation or partials |
| `session_meta.py` | `live_transcription` stored per session (recovery and re-enqueue read it) |
| `processing/job.py` | for sessions recorded without live transcription the phase 40 `transcribe` step starts at 0 (the whole recording) |
| `cli` | `python -m vozata transcribe <id>` (same component, for support) |
| `locales/*.toml` | step name, messages |

**UI**

| File | Content |
|------|---------|
| `RecorderPage.axaml`, `RecorderPageViewModel` | the checkbox in the recording options (editable only while idle, like language/template); its default from the engine setting; the last choice remembered in `ui.json`; translation option disabled when unchecked |
| Recorder transcript area | when unchecked: "Recording audio only. The transcript is created after you stop." instead of the live transcript |
| `ConfigPage` | the setting in the transcription section |
| `VozAta.Client` | `live_transcription` in `StartSessionRequest` and session detail |
| Resources | strings in en / pt-BR / es |

## Design notes

- Phase 40's offline transcription **reuses the live components**, so the stored transcript is the same
  format (`transcript.jsonl` sources, timestamps on the session clock, `mic` / `system` labels)
  and everything downstream (diarization, minutes, search, editing, export) works unchanged.
- Pauses inside the recording (phase 11) are silence in the stored audio; the chunkers already
  handle silence (VAD skips it).
- Progress of the `transcribe` step = audio seconds fed / track length; it is the biggest weight
  of the job (phase 40 note).
- GPU gate (phase 40): an audio-only recording uses no model, so it never interrupts the queue;
  a live recording started later does interrupt an audio-only meeting's transcription, which
  resumes from where it stopped.
- Language: `auto` detects per meeting as live does (language lock); a fixed language is used as
  is. Vocabulary and template stored at start are used.
- Recovery (phase 17): an interrupted audio-only meeting is recovered and then queued with the
  `transcribe` step, so its transcript is created too.
- A faster-than-real-time offline run is expected (≈ 2 s per 5 s phrase on the reference GPU);
  the CPU fallback is slow but works.

## Acceptance criteria

- [ ] Unchecked: during the recording no model is loaded (VRAM unchanged), the level meters work,
      and the recorder says it is recording audio only.
- [ ] After Stop, the meeting is queued, shows "Processing N %" driven by the transcription, and
      ends with transcript, speakers, minutes and action items like a live meeting.
- [ ] Mic and system speech of the same moment are not duplicated (echo dedupe works offline).
- [ ] A live-transcription recording started while an audio-only meeting is transcribing
      interrupts that job, which later resumes from where it stopped; an audio-only recording does
      not interrupt it.
- [ ] The checkbox default comes from Config; the last choice is remembered.
- [ ] Contract docs updated (`live_transcription` in `POST /sessions`, `LIVE_TRANSCRIPTION`,
      `session.json`).

## Tests

Engine: a job for an audio-only session transcribes from 0 (fake transcriber), interrupted and
resumed by the gate; session built without live components, option plumbing (`null` = setting), recovery → queue with
`transcribe`, CLI command. UI: checkbox state and persistence, request field, recorder message,
translation disabled, locale parity.

## Out of scope

- Transcribing imported audio files that were never recorded by VozAta.
- Changing the choice in the middle of a recording.

## Progress

- **Branch:** `feature/41-record-only`
- **Status:** in progress
- **Updated:** 2026-10-20 17:10
- **Next step:** Task 2 of `plans/41-record-only.md` (audio-only capture).

### Steps

- [x] Implementation plan (`plans/41-record-only.md`)
- [x] `LIVE_TRANSCRIPTION` setting and the per-recording option (this commit)
- [ ] Audio-only capture
- [ ] `python -m vozata transcribe <id>`
- [ ] UI checkbox, preference and notices
- [ ] Full suites, manual check

### Decisions and notes

- Since phase 40 the queue's `transcribe` step lives in `processing/session_job.py` and already starts
  at 0 for an empty raw transcript (and recovery goes through it), so the queue needs no change.
- The remembered checkbox choice (ui.json) wins over `LIVE_TRANSCRIPTION`; saving the setting in
  Config resets it.
