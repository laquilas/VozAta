# VozAta worker API

The worker (`vozata worker`, phase 44) serves heavy model work to the engine of another PC of the
local network. It is a separate HTTP server from the engine API ([api-contract.md](api-contract.md)):
different port, its own settings, and a token on every request.

## Conventions

- Base URL: `http://{WORKER_HOST}:{WORKER_PORT}`, default `http://0.0.0.0:8766` (every network of
  the worker PC). Plain HTTP on the trusted LAN; TLS is out of scope.
- **Auth**: every route, `/health` included, needs `Authorization: Bearer {WORKER_TOKEN}`
  (constant-time compare). Otherwise `401 {"error": {"code": "worker_unauthorized"}}` with
  `WWW-Authenticate: Bearer`. Only a loopback host (`127.x`, `::1`, `localhost`) may run without a
  token; on any other host the first `vozata worker` run generates one into the `.env` of its
  working directory and prints it once.
- No OpenAPI or docs pages are served.
- One request is transcribed at a time (a lock); the model loads on the first request and is
  released when the worker stops.

## Endpoints

| Method | Path | Body | Response |
|--------|------|------|----------|
| GET | `/health` | — | `{worker: "ok", version, gpu: {available, name, vram_total_mb}, capabilities: ["speech"], models: [str]}`; `models` lists the loaded model (`WHISPER_MODEL`, or `WHISPER_CPU_MODEL` after a CPU fallback), empty before the first transcription |
| POST | `/transcribe?language={code\|empty}` | `application/octet-stream`: float32 little-endian mono samples at 16 kHz | `{words: [{text, start, end, probability}], language: str\|null, avg_logprob: float\|null}`; times are relative to the chunk; an empty or non-float32 body (length not a multiple of 4) is `422 {"error": {"code": "worker_invalid_audio"}}` |

`/transcribe` headers (optional, UTF-8 percent-encoded because HTTP headers are Latin-1):

| Header | Meaning |
|--------|---------|
| `X-Hints` | vocabulary terms (faster-whisper `hotwords`) |
| `X-Prompt` | the channel's recent text (faster-whisper `initial_prompt`, the rolling context) |

## Engine client (`worker_client/`)

- `WorkerClient`: Bearer token; the first request of a client is `GET /health` with a 3 s timeout,
  so a worker that is off fails in seconds (`WorkerUnreachableError(host)`); a `401` is a
  `ConfigError` on `WORKER_TOKEN` (no fallback: the user must fix it). `/transcribe` is retried on
  `429` / `5xx` / network errors (`transcription/retry.py`); a network failure on the last attempt
  is `WorkerUnreachableError`, an HTTP error is `TranscriptionRequestError` (the chunk is skipped as
  with any provider). Silence is never sent.
- `WorkerTranscriber` (the `Transcriber` port): on `WorkerUnreachableError` it tells
  `FallbackNotices`, builds the local `faster_whisper` once and transcribes that chunk and every
  later one on this PC.
- `bootstrap.build_transcriber` probes the worker when a transcriber is built (session start, the
  queue's transcribe step, the CLI): unreachable → local `faster_whisper` and the notice.
- The notice is an `error` event with code `worker_fallback` and the localized message
  `errors.worker.fallback` ("The VozAta worker at {host} did not answer: {task} runs on this PC.").

## Open routes (phase 47)

These two need no token; `/health` and `/transcribe` still do.

| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/pair` | `{code}` | `{token, id, name}` when `code` is the 6-digit code shown in VozAta Worker (valid 5 minutes, replaced once used); wrong code `403 worker_pairing_refused`; after 5 wrong codes `423 worker_pairing_locked` for 60 s (and a new code); a worker without a token (loopback) `409 worker_no_token` |
| GET | `/local/status` | — | for VozAta Worker on the same PC only (a non-loopback client gets `403 worker_local_only`): `{version, id, name, port, addresses: [ipv4], token, pairing_code, code_expires_in, gpu: {available, name, vram_total_mb}, models}`; `token`, `pairing_code` and `code_expires_in` are null for a loopback worker |

## Discovery (phase 47, UDP)

- A worker on the network (it has a `WORKER_ID`) listens on UDP `WORKER_DISCOVERY_PORT` (8767).
- Request (one datagram): `{"vozata": "discover", "v": 1}`; anything else is ignored.
- Answer, to the sender: `{"vozata": "worker", "v": 1, "id", "name", "port", "version", "gpu"}`
  (`gpu`: the GPU name or null). No secret.
- The engine (`worker_client/discovery.py`) broadcasts to `255.255.255.255` from every IPv4
  address of its PC (Windows sends a limited broadcast through one interface only), collects the
  answers for 1.5 s and dedupes them by id; the worker URL is `http://<sender address>:<port>`.

## Identity

`WORKER_ID` (a uuid, made with the token on the first start of a worker on the network) names the
worker; the engine saves it at pairing. When the paired worker does not answer at `WORKER_URL`,
the engine broadcasts once; the same id at another address becomes the new `WORKER_URL` before the
phase 44 fallback.

## Later phases

- 45: `/diarize` (job API) and `/embed` for speaker identification.
- 46: `/translate`.
