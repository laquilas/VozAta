# Phase 15 — Speaker identification (live)

## Goal

Show `User N` labels on system segments **during** the meeting using speaker embeddings and online
clustering; the post-session pass (14) remains authoritative and corrects them at stop.

## Depends on

14, 06

## Read first

- `engine/CLAUDE.md`
- [architecture.md](../architecture.md) §6 (worker, VRAM), §11 (live mode)
- [api-contract.md](../api-contract.md) — `segment.speaker_id`, `speakers_relabeled`

## Scope

| File | Content |
|------|---------|
| `ports.py` | `SpeakerEmbedder.embed(samples) -> np.ndarray` |
| `diarization/embedder.py` | pyannote embedding model adapter (small, can stay loaded next to Whisper) |
| `diarization/live.py` | `LiveSpeakerTagger(embedder, threshold, min_seconds=1.0)`: cosine similarity vs. running centroids (running mean); above `SPEAKER_SIMILARITY_THRESHOLD` → existing speaker, else new `system:<n>`; segments shorter than `min_seconds` reuse the previous speaker |
| `transcription/worker.py` | pass each committed system segment **with its audio slice** to an optional tagger before emitting (stitcher exposes the committed audio range) |
| `session.py` / `api/session_manager.py` | after the post-session pass, emit `speakers_relabeled` |
| `config.py`, `.env.example` | `LIVE_DIARIZATION_ENABLED`, `SPEAKER_SIMILARITY_THRESHOLD` |
| UI | on `speakers_relabeled`, reload the transcript of the session (small change in `MainViewModel` / `SessionDetailViewModel`) |

## Design notes

- Live labels are best-effort; never block the transcription path (embedding time is logged; if it
  exceeds the window length the tagger disables itself with a warning).
- Check VRAM with Whisper + embedder loaded on the RTX 3050 (6 GB).

## Acceptance criteria

- [ ] Tagger tests with a `FakeEmbedder` returning synthetic vectors: new speaker creation,
      assignment above threshold, centroid update, short-segment rule, self-disable on slowness.
- [ ] Worker test: segments carry `speaker_id` from the tagger; without tagger they stay `system`.
- [ ] API/UI: `speakers_relabeled` emitted after stop and the UI reloads the transcript.
- [ ] Manual: live labels mostly stable during a 3-person call (note accuracy in the PR).

## Tests

`tests/diarization/test_live.py`, `tests/transcription/test_worker.py` (extended), UI ViewModel test
for the reload.

## Out of scope

Cross-session speaker recognition (remembering voices between meetings).

## Kickoff prompt

> Execute phase 15 of the roadmap (`docs/roadmap/phases/15-diarization-live.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/15-diarization-live`
- **Status:** in progress
- **Updated:** 2026-10-17 10:00
- **Next step:** add `LIVE_DIARIZATION_ENABLED` / `SPEAKER_SIMILARITY_THRESHOLD` to `config.py`,
  `settings_fields.py`, `.env.example`, architecture §9 and the UI settings strings.

### Steps

- [ ] Config keys `LIVE_DIARIZATION_ENABLED`, `SPEAKER_SIMILARITY_THRESHOLD`
- [ ] `SpeakerEmbedder` port, `FakeEmbedder`, `LiveSpeakerTagger` (`diarization/live.py`)
- [ ] Live tagging worker (own thread) between the echo filter and the sinks, fed by a system
      audio buffer; wired in `session_pipeline.py`
- [ ] pyannote embedder in a long-lived child process (`diarization/embedder.py`), `EMBEDDERS`
      registry in `bootstrap.py`
- [ ] `speakers_relabeled` after the post-session pass (observer, session, API)
- [ ] UI: parse `speakers_relabeled`, reload the transcript (main window + session detail)
- [ ] Docs (architecture §6/§9/§11, api-contract), acceptance criteria, full suites, PR

### Decisions and notes

- Live tagging is a sink stage with its own thread (`[EchoFilter] → [LiveSpeakerTagger]` in
  architecture §6), so the transcription thread only enqueues; `worker.py` stays unchanged.
