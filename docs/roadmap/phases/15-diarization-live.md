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

- [x] Tagger tests with a `FakeEmbedder` returning synthetic vectors: new speaker creation,
      assignment above threshold, centroid update, short-segment rule, self-disable on slowness.
      (`tests/diarization/test_live.py`)
- [x] Worker test: segments carry `speaker_id` from the tagger; without tagger they stay `system`.
      (`tests/diarization/test_live_sink.py`, `tests/test_session_live_speakers.py`: the live
      worker is a sink stage, see Decisions)
- [x] API/UI: `speakers_relabeled` emitted after stop and the UI reloads the transcript.
- [ ] Manual: live labels mostly stable during a 3-person call (note accuracy in the PR).
      **pending manual (credentials)**: needs `HF_TOKEN`, the `diarization` extra and the audio
      hardware; recipe in Progress.

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
- **Status:** ready for PR
- **Updated:** 2026-10-17 14:46
- **Next step:** merge `origin/main`, run the full engine and UI suites, open the PR and watch its checks; then run the manual check recipe below on the reference machine.

### Steps

- [x] Config keys `LIVE_DIARIZATION_ENABLED`, `SPEAKER_SIMILARITY_THRESHOLD`
- [x] `SpeakerEmbedder` port, `FakeEmbedder`, `LiveSpeakerTagger` (`diarization/live.py`)
- [x] Live tagging worker (own thread) between the echo filter and the sinks, fed by a system
      audio buffer; wired in `session_pipeline.py`
- [x] pyannote embedder in a long-lived child process (`diarization/embedder.py`), `EMBEDDERS`
      registry in `bootstrap.py`
- [x] `speakers_relabeled` after the post-session pass (observer, session, API)
- [x] UI: parse `speakers_relabeled`, reload the transcript (main window + session detail)
- [x] Docs (architecture §6/§9/§11, api-contract), acceptance criteria, full suites, PR

### Decisions and notes

- Live tagging is a sink stage with its own thread (`[EchoFilter] → [LiveSpeakerTagger]` in
  architecture §6), so the transcription thread only enqueues; `worker.py` stays unchanged.
- The live worker sits between the echo filter and the sinks (`LiveSpeakerSink`), so `transcript.jsonl` stores the live `system:<n>`; the post-session pass stays authoritative in `transcript.diarized.jsonl`. Its clip comes from `AudioHistory` (system chunks kept 60 s + `MAX_CARRY_SECONDS`), so neither `worker.py` nor the stitcher changed. The embedder loads on its own thread; lines before it is ready keep `system`. A failed load reports `error` `live_diarization_failed`.
- The live embedder (`pyannote/wespeaker-voxceleb-resnet34-LM`, `EMBEDDERS[DIARIZATION_PROVIDER]`) lives in one child process per session (`python -m vozata.diarization.embed_child`, line protocol with an `@vozata ` reply prefix); it loads and warms up once, each clip is one round trip (30 s timeout), and stdin EOF at stop ends it. Tests run a stand-in child script (`tests/diarization/fake_embed_child.py`), never torch.

### Manual check recipe (pending manual (credentials))

Run on the reference machine, one phase at a time (shared audio hardware):

1. Accept the terms of `pyannote/wespeaker-voxceleb-resnet34-LM` and
   `pyannote/speaker-diarization-community-1` on Hugging Face; install the extra:
   `.venv/Scripts/python -m pip install -e "engine[diarization]"`.
2. In `engine/.env`: `HF_TOKEN=<token>`, `LIVE_DIARIZATION_ENABLED=true`,
   `DIARIZATION_ENABLED=true` (keep `SPEAKER_SIMILARITY_THRESHOLD=0.7`).
3. Child smoke test (no audio), from `engine/`:
   `../.venv/Scripts/python -c "import numpy as np; from vozata.config import load_settings; from vozata.diarization.subprocess_embedder import pyannote_embedder_from_settings as f; e = f(load_settings()); print(e.embed((np.random.randn(32000) * 0.1).astype('float32')).shape); e.close()"`
   → prints a 1-D shape such as `(256,)`; the first run downloads the model.
4. `python -m vozata serve` + the UI. Start a session and play a 3-person call (or a
   3-speaker panel video) through the speakers for ~5 min. Expect: after the model loads (a few
   seconds; earlier lines say "Others"), system lines show `User 1` / `User 2` / `User 3`; note
   how often a line gets the wrong user (accuracy for the PR). `nvidia-smi` during recording:
   Whisper + embedder child fit in 6 GB. No `Live speaker identification disabled` warning in
   the engine log (DEBUG shows `Speaker embedding took … s`).
5. Stop: once finalizing reaches speaker identification, the main window transcript and an open
   History detail reload with the post-session `User N` labels (`speakers_relabeled`); the
   embedder child process is gone (Task Manager) before the minutes start.
6. Negative: empty `HF_TOKEN`, start again → an error notification "Live speaker labels are
   off (…HF_TOKEN…)", recording and transcription go on with "Others".
7. If one voice splits into several users, lower `SPEAKER_SIMILARITY_THRESHOLD` (e.g. 0.6); if
   voices merge, raise it (e.g. 0.8). Record the value used and the accuracy in the PR.
- The acceptance test named `tests/transcription/test_worker.py` lives in `tests/diarization/test_live_sink.py` and `tests/test_session_live_speakers.py`: tagging is a sink stage, so `worker.py` and the stitcher did not change (smaller overlap with phase 29). Live and post-session speaker numbers are independent.
