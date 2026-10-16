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

- [ ] Passes the shared `Transcriber` contract suite using `httpx.MockTransport`.
- [ ] Tests: multipart body fields, language `None` for `auto`, word mapping, retry on 429 with
      `Retry-After`, give up after 3 attempts with a clear error, missing word timestamps → error.
- [ ] Manual: one session with `STT_PROVIDER=openai_compatible` against a real endpoint (OpenAI or
      Groq) — record latency and cost estimate in the PR.
- [ ] Coverage ≥ 80 %.

## Tests

`tests/transcription/test_openai_compatible.py`, `test_retry.py`.

## Out of scope

Parallel requests, streaming/realtime APIs, diarization from providers.

## Kickoff prompt

> Execute phase 12 of the roadmap (`docs/roadmap/phases/12-external-stt.md`), following
> `docs/roadmap/README.md`.
