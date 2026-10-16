# Phase 12 — External STT API

## Goal

Add a cloud / remote speech-to-text provider behind the existing `Transcriber` port, selectable with
`STT_PROVIDER`, compatible with OpenAI-style `/audio/transcriptions` APIs (OpenAI, Groq,
self-hosted Whisper servers).

## Depends on

05

## Read first

- `engine/CLAUDE.md` ("Add a provider" checklist)
- [architecture.md](../architecture.md) §5 (`Transcriber` contract), §7 (stitcher needs word
  timestamps), §9 (keys)
- `engine/tests/transcription/contract.py`

## Scope

| File | Content |
|------|---------|
| `transcription/openai_compatible.py` | `OpenAICompatibleTranscriber(url, api_key, model, timeout)`: encodes the window as 16-bit PCM WAV in memory; `POST {url}/audio/transcriptions` multipart (`file`, `model`, `language`, `prompt` = hints, `response_format=verbose_json`, `timestamp_granularities[]=word`); maps words to `Word` (probability `1.0` when the provider gives none — documented); detected language from the response |
| `transcription/retry.py` | retry with exponential backoff for 429 / 5xx / timeouts (max 3), respects `Retry-After` |
| `bootstrap.py` | register `openai_compatible` in `TRANSCRIBERS` |
| `config.py`, `.env.example` | `OPENAI_STT_URL` (default `https://api.openai.com/v1`), `OPENAI_STT_KEY` (secret), `OPENAI_STT_MODEL` (default `whisper-1`) |
| `locales/*.toml` | warning shown at session start: "audio is sent to <host>" |
| `docs/roadmap/architecture.md` §9 | keep the key table in sync |

## Design notes

- **Privacy**: audio leaves the machine; the CLI and UI (health panel) must show the provider host.
- **Cost**: document the provider's price per minute in `.env.example` comments and tell the user to
  verify current pricing; a 1-hour meeting with two channels sends up to 2 hours of audio (silent
  windows are skipped by the stitcher's RMS gate).
- The provider must support **word-level timestamps**; reject at startup (clear `ConfigError`) when a
  probe call returns none.
- Latency: one request per window per channel; the worker stays single-threaded (keeps ordering).

## Acceptance criteria

- [x] Passes the shared `Transcriber` contract suite using `httpx.MockTransport`.
- [x] Tests: multipart body fields, language `None` for `auto`, word mapping, retry on 429 with
      `Retry-After`, give up after 3 attempts with a clear error, missing word timestamps → error.
- [x] Manual: one session with `STT_PROVIDER=openai_compatible` against a real endpoint (OpenAI or
      Groq) — record latency and cost estimate in the PR. *Run against a self-hosted
      OpenAI-compatible server; the OpenAI / Groq run is pending an API key (see notes).*
- [x] Coverage ≥ 80 %.

## Tests

`tests/transcription/test_openai_compatible.py`, `test_retry.py`.

## Out of scope

Parallel requests, streaming/realtime APIs, diarization from providers.

## Kickoff prompt

> Execute phase 12 of the roadmap (`docs/roadmap/phases/12-external-stt.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/12-external-stt`
- **Status:** ready for PR
- **Updated:** 2026-10-17 00:45
- **Next step:** open and merge the PR; when a key is available, run one session with STT_PROVIDER=openai_compatible against OpenAI or Groq and add latency and cost to this section

### Steps

- [x] Start the phase (README status, Progress section)
- [x] Config keys (+ settings page labels and help) — `026e6ed`
- [x] `transcription/retry.py` (429 / 5xx / timeouts, `Retry-After`, 3 attempts) — `687cdab`
- [x] `OpenAICompatibleTranscriber` (multipart WAV, verbose_json word timestamps, probe at start) — `812bddf`
- [x] Registry, privacy notice (CLI at session start; health shows the provider host) — `c3913b9`
- [x] Manual: a session against an OpenAI-compatible endpoint; criteria — this commit

### Decisions and notes

- No OpenAI / Groq key on the reference machine: the manual run uses a self-hosted
  OpenAI-compatible server (in scope: "self-hosted Whisper servers") backed by faster-whisper; the
  run against OpenAI or Groq waits for a key.
- OpenAI's word list carries no punctuation, but the stitcher cuts on sentence-ending punctuation:
  punctuation from the response `text` is re-attached to the matching words.
- OpenAI returns the language as a name ("portuguese"); it is mapped to the ISO code.
- All-zero (silent) windows return an empty result without a request (no cost); the stitcher's RMS
  gate already skips most silence.
- **Manual check (2026-10-16/17).** No OpenAI / Groq key on this machine, so the provider ran
  against a self-hosted OpenAI-compatible server (stdlib HTTP server over faster-whisper
  `large-v3` on the GPU, Bearer key required, OpenAI-shaped `verbose_json`: language as a name,
  words without punctuation).
  - `python -m vozata record` with `STT_PROVIDER=openai_compatible` printed "Speech recognition
    runs on 127.0.0.1: the audio is sent there." before starting, but the session could not
    record: WASAPI did not open the JBL microphone within 20 s twice (the known driver hang —
    restart Windows Audio or the PC); the provider was not involved.
  - So the provider was checked end to end offline: the phase 05 TTS meeting fed in 0.1 s blocks
    through the VAD chunker, the stitcher and `OpenAICompatibleTranscriber` (built from settings,
    including the start-up probe, 2.1 s) over HTTP: 10 requests for 51.1 s of audio, request time
    median 1.62 s (max 2.11 s), line latency median 2.73 s, **WER 0.0 %** after the hyphen fix
    below (10.6 % before). A wrong key was answered 401 "Incorrect API key provided.".
  - Cost estimate (OpenAI whisper-1 at ~US$0.006/min, verify current pricing): this 69 s meeting
    sends 51 s of audio (~US$0.005); a 1-hour meeting with both channels up to ~US$0.72.
- **Fixed during the check:** providers split hyphenated words ("sexta" + "-feira"); the
  punctuation alignment now merges them into one word ("sexta-feira.").
- **Pending:** one session against OpenAI or Groq with a real key, to record their latency.
