# Phase 44 — Worker on another PC: server and remote speech

## Goal

Take the speech model (Whisper) off this laptop: a **VozAta worker** runs on a PC of the local
network that has an NVIDIA GPU and transcribes for the engine, live and after Stop. Phase 43 moved
the language model to a remote Ollama; this phase starts the worker that later phases extend to
speaker identification (45) and translation (46).

- `vozata worker` (packaged as `vozata-engine.exe worker`) serves `/health` and `/transcribe` on
  the LAN, protected by a token.
- The engine gets a `vozata_worker` speech provider with the same results as local faster-whisper.
- **Local or remote**: the user picks the worker with `STT_PROVIDER=vozata_worker`. When the worker
  does not answer, VozAta **falls back to this PC on its own and says so** (user decision,
  2026-10-22).

Requested by the user on 2026-10-22: "take the processing load off this PC and move it to an
external server" (their own PC on the LAN, with a GPU).

## Depends on

43

## Read first

- `engine/CLAUDE.md`, `ui/CLAUDE.md`
- [phase 43](43-remote-ollama.md) (`net.py`, fail-fast probe, `remote_llm_host` in the gate)
- [phase 40](40-background-processing.md) (GPU gate, queue steps), [phase 26](26-capture-first.md)
  (capture-first: audio is always kept)
- `ports.py` (`Transcriber`), `transcription/faster_whisper.py`, `transcription/openai_compatible.py`,
  `transcription/retry.py`, `transcription/worker.py`, `transcription/shared.py`,
  `bootstrap.py` (`TRANSCRIBERS`, `build_session`, shared Whisper), `bootstrap_processing.py`,
  `processing/gpu_gate.py`, `connection_checks.py`, `cli/serve.py`, `packaging/engine.spec`,
  `docs/remote-ollama.md`

## Current state (facts, 2026-10-22)

- `TRANSCRIBERS` has `faster_whisper` and `openai_compatible`. The OpenAI path sends WAV multipart,
  sets every word probability to 1.0, merges `hints` into the prompt and has no `avg_logprob`
  (so the rolling-context guard never fires); it refuses replies without word timestamps.
- Transcribers are built in three places: `build_session` (`bootstrap.py:550`), the kept Whisper
  (`bootstrap.py:798`) and the queue's transcribe step (`bootstrap_processing.py:84, 132`).
- The live worker thread is the only caller of the transcriber; a failing chunk is logged and
  skipped (`transcription/worker.py:151`).
- `gpu_usage.speech` is `stt_provider == "faster_whisper" and device != cpu and cuda`.
- The engine API has no authentication and `serve` refuses every-interface hosts.

## Scope

**Worker (new, `engine/src/vozata/worker/`)**

| File | Content |
|------|---------|
| `worker/app.py` | FastAPI app: `GET /health` (version, GPU, loaded models, capabilities `["speech"]`), `POST /transcribe` |
| `worker/auth.py` | Bearer token dependency; constant-time compare; 401 without a valid token (`/health` too) |
| `worker/speech.py` | one kept `FasterWhisperTranscriber` per (model, device), loaded on first use, one request at a time (lock) |
| `worker/settings.py` | `WORKER_HOST` (default `0.0.0.0`), `WORKER_PORT` (8766), `WORKER_TOKEN`, Whisper keys reused from `Settings` |
| `cli/worker.py` + `__main__.py` | `vozata worker`: refuses a non-loopback host without a token; first run generates a token into the worker's `.env` and prints it once |
| `packaging/engine.spec`, `build.ps1` | same bundle; smoke test `vozata-engine.exe worker --check` |

**Engine**

| File | Content |
|------|---------|
| `worker_client/client.py` (new) | httpx client: Bearer, probe `GET /health` (3 s) once, `WorkerUnreachableError(host)`, retry with `transcription/retry.py` |
| `worker_client/transcriber.py` (new) | `WorkerTranscriber` (the `Transcriber` port): raw float32 LE body, `language` / `hints` / `prompt` separate, full `TranscriptionResult` back; silence never sent |
| `bootstrap.py` | `TRANSCRIBERS["vozata_worker"]`; one `build_transcriber(settings, downloader, notices)` used by the three call sites: worker reachable → worker, else the local `faster_whisper` and a `worker_fallback` notice |
| `ports.py` | `FallbackNotices` port: `fallback(task, host)`; wired to the broadcaster (API) and the console (CLI) |
| `processing/gpu_gate.py` | `speech` is false when the session's speech runs on the worker (resolved choice), true again after a fallback |
| `config.py`, `settings_fields.py`, `.env.example` | `WORKER_URL`, `WORKER_TOKEN` (secret), group `worker` |
| `connection_checks.py` | target `worker`: `/health` with the token (`ok`, `unauthorized`, `unreachable`) |
| `api/routes/health.py`, `api/schemas.py` | `worker: {url, reachable, version}`, `stt.device` = worker host when used |
| `locales/*.toml` | fallback notice, CLI texts, check results |

**UI**

| File | Content |
|------|---------|
| `SettingsViewModel` | Test button anchored on `WORKER_URL` (target `worker`) |
| Resources | labels / help for the new keys (en, pt-BR, es) |

**Docs**: `docs/remote-worker.md` (GPU PC setup: copy or install VozAta, `vozata-engine.exe worker`,
token, firewall rule on the private profile, start with Windows; this PC: URL, token, Test,
`STT_PROVIDER`), `docs/remote-ollama.md` (the "engine cannot run on another PC" section now points
to the worker), `docs/roadmap/worker-api.md` (the worker's API), `architecture.md` §5 / §9,
`api-contract.md` (`/health.worker`, `worker_fallback`).

## Design notes

- **Why not `openai_compatible`**: parity with local Whisper — real word probabilities (low
  confidence marks), `avg_logprob` (context guard), `hotwords` separate from `initial_prompt`, any
  language code.
- **Wire format**: `POST /transcribe?language=pt` with `application/octet-stream` float32 LE
  samples at 16 kHz and `X-Hints` / `X-Prompt` (UTF-8, percent-encoded) headers; reply
  `{words: [{text, start, end, probability}], language, avg_logprob}`.
- **Fallback**: resolved when a transcriber is built (session start, queue step). Mid-session loss:
  `WorkerTranscriber` switches once to a lazily built local transcriber, publishes the same notice
  and keeps going; the queue's transcribe step after Stop fills any chunk lost meanwhile.
- **Notice**: an `error` event with code `worker_fallback` and a localized message, e.g. "The worker
  at {host} did not answer: speech runs on this PC." The UI shows `error` messages as a notification
  already; no UI code is needed for it.
- **Security**: the token travels in clear on the LAN (plain HTTP), like Ollama's traffic; the guide
  says so and keeps the firewall rule on the Private profile. TLS is out of scope.
- **VRAM on the worker**: Whisper stays loaded there between meetings (no `WHISPER_KEEP_LOADED`
  dance); Ollama on the same PC competes for the same GPU — the guide lists the sizes.

## Acceptance criteria

- [ ] `vozata worker` starts with a token, refuses a LAN host without one, and answers `/health`
      and `/transcribe` only with the token.
- [ ] With `STT_PROVIDER=vozata_worker`, a recording is transcribed live by the worker and the
      laptop loads no Whisper; `/health` reports the worker.
- [ ] With the worker off, the next recording (and a queued transcribe step) runs on this PC and a
      `worker_fallback` notification names the host; losing the worker mid-recording does the same
      without stopping the recording.
- [ ] The Config page has `WORKER_URL`, `WORKER_TOKEN` and a working Test button.
- [ ] Guide and contract docs updated.

## Tests

Engine: worker auth (missing / wrong / right token, host refusal), `/transcribe` with a fake
transcriber, client probe and retry with `httpx.MockTransport`, `WorkerTranscriber` against
`tests/transcription/contract.py`, fallback at build and mid-session with the notice, gate rule,
`/health.worker`, connection check. UI: Test anchor, resource parity.

## Out of scope

- Speaker identification on the worker (phase 45), translation on the worker (phase 46).
- TLS, user accounts, discovering workers automatically, several workers.
- Running the whole engine on another PC (capture stays local).

## Kickoff prompt

> Start phase 44 (`docs/roadmap/phases/44-worker-speech.md`): read its *Read first* files and
> `plans/44-worker-speech.md`, then continue from the Progress section's *Next step*.

## Progress

- **Branch:** `feature/44-worker-speech`
- **Status:** in progress
- **Updated:** 2026-10-22
- **Next step:** Task 1 of `plans/44-worker-speech.md` (worker settings, token auth and `/health`).

### Steps

- [x] Phases 44–46 and the implementation plan (`plans/44-worker-speech.md`)
- [ ] Worker: settings, token auth, `/health`, `vozata worker` command
- [ ] Worker: `/transcribe` with a kept faster-whisper
- [ ] Engine: worker client and `WorkerTranscriber`
- [ ] Engine: `build_transcriber` with fallback and the `worker_fallback` notice; gate rule
- [ ] Engine: settings, connection check, `/health.worker`; UI Test anchor
- [ ] Packaging entry and smoke test; guide and contract docs
- [ ] Full suites, manual check (this PC's LAN address as the worker), phase done

### Decisions and notes

- Commits stay local until the PR (user rule, 2026-10-20).
- Fallback to this PC when the worker does not answer, with a notification (user, 2026-10-22).
- The worker is a subcommand of the engine bundle, not a second program, so it reuses the providers
  and the packaging.
