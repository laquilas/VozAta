# Phase 06 — Engine API

## Goal

Expose the engine through a local FastAPI HTTP API and a WebSocket event stream, implementing every
row tagged **06** in the API contract.

## Depends on

05

## Read first

- `engine/CLAUDE.md`
- [api-contract.md](../api-contract.md) — all rows tagged 06, shapes, WebSocket envelope
- [architecture.md](../architecture.md) §6 (threads), §8 (session data), §9 (`API_HOST`,
  `API_PORT`, secrets)

## Scope

| File | Content |
|------|---------|
| `api/app.py` | `create_app(container) -> FastAPI`; error handler producing `{"error": {code, message}}` with localized messages |
| `api/schemas.py` | pydantic models for every request/response shape in the contract |
| `api/routes/health.py`, `devices.py`, `sessions.py`, `settings.py` | contract rows tagged 06 (`GET /settings` only; `PUT` is phase 10) |
| `api/ws.py` | `EventBroadcaster`: thread-safe publish (`loop.call_soon_threadsafe`) to per-client asyncio queues; drops oldest `level` events for slow clients; sends current `status` on connect |
| `api/session_manager.py` | `SessionManager`: one active session (409 otherwise), adapts `SessionObserver` → broadcaster, runs `stop()` finalization in a background thread, throttles `level` to ~10 Hz |
| `api/system_info.py` | GPU info via `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader` (timeout 2 s, graceful when missing) |
| `config.py` | field metadata (type, default, choices, secret) used by `GET /settings`; `API_HOST`, `API_PORT` |
| `__main__.py` | `serve` command (uvicorn); refuses `API_HOST=0.0.0.0` |
| `pyproject.toml` | add `fastapi`, `uvicorn[standard]` |

## Design notes

- Routes depend on `SessionManager`, `SessionStore`, `bootstrap` factories via FastAPI dependency
  injection — tests override them with fakes.
- `GET /sessions/{id}/transcript` returns display labels resolved with `SpeakerLabeler`.
- `SessionDetail` includes the absolute `folder` path (used by the UI to open files locally).
- Secrets are masked (`"********"`) in `GET /settings`.

## Acceptance criteria

- [x] Every 06 row of the contract implemented; OpenAPI at `/docs` matches the contract shapes.
- [x] `TestClient` tests: start/pause/resume/stop lifecycle with fake session, 409 on second
      start, 404 codes, settings masking, health with fake LLM availability.
- [x] WebSocket test: connect → initial `status`; fake session events arrive in order with the
      envelope; disconnect does not break publishing.
- [x] Manual: `python -m vozata serve`, then start/stop via `curl` and watch events with a
      WebSocket client (e.g. `python -m websockets ws://127.0.0.1:8765/ws`).
- [x] Coverage ≥ 80 %.

## Tests

`tests/api/test_health.py`, `test_sessions.py`, `test_settings_get.py`, `test_ws.py`,
`test_session_manager.py`.

## Out of scope

Settings writes (10), export (11), recovery (17), every row tagged with another phase.

## Kickoff prompt

> Execute phase 06 of the roadmap (`docs/roadmap/phases/06-engine-api.md`), following
> `docs/roadmap/README.md`.

## Progress

- **Branch:** `feature/06-engine-api`
- **Status:** ready for PR
- **Updated:** 2026-10-16 09:15
- **Next step:** open the PR (put the manual results below in its description) and merge.

### Steps

- [x] Start phase: status in progress, Progress section — `fd671b5`
- [x] Dependencies; `API_HOST` / `API_PORT`; settings schema metadata in `config.py` — `02a9678`
- [x] `api/ws.py` (`EventBroadcaster`) + tests — `82005b0`
- [x] `api/session_manager.py` (`SessionManager`) + tests — `69b6ff5`
- [x] `api/app.py`, `api/schemas.py`, error handler, `system_info.py`, routes `health`, `devices`,
      `settings` (GET) + tests — `134f808`
- [x] Routes `sessions` (start, pause, resume, stop, list, detail, transcript, minutes) + tests — `134f808`
- [x] `serve` command (uvicorn; refuses `0.0.0.0`) + tests — `21472c4`
- [x] Manual: `python -m vozata serve`, start/stop with `curl`, events with a WebSocket client
- [x] Verify; tick acceptance criteria; set phase `done`

### Decisions and notes

- The session observer port (`SessionObserver`, phase 05) is what `SessionManager` adapts to the
  broadcaster.

- Settings metadata lives in `settings_fields.py` (`FIELDS`, one row per key, also the source of
  `config.KEYS`); `settings_view.py` turns `Settings` into `GET /settings` values (secrets masked
  as `********`) and the schema. Schema types: number, integer, string, bool, choice, url, path.
  `TRANSCRIPTION_LANGUAGE` reports a `null` default (derived from `APP_LANGUAGE`).
- `SessionManager` treats a finalizing session as active (one GPU), so `POST /sessions` answers
  409 until finalization ends. `stop()` answers with status `finalizing` and runs
  `RecordingSession.stop()` on a non-daemon thread (the process waits for the files at exit).
  Pause/resume/stop without a recording or paused session raise `NoActiveSessionError`
  (`409 no_active_session`). A `status` heartbeat is published every 1 s while recording/paused.
- `RecordingSession.duration_seconds` (session clock) feeds the heartbeat and live summaries.
- App and every 06 route landed in one commit (the app module includes all routers). Routes read
  an `ApiContainer` from `app.state` (tests build one over fakes). Errors use the contract envelope
  everywhere, including validation (422 `invalid_request`), unknown paths (404 `not_found`),
  405 and unexpected errors (500 `internal_error`, details only in the log). Status codes:
  409 `session_already_active` / `no_active_session` / `session_still_recording`,
  404 `session_not_found` / `minutes_not_found` / `device_not_found`, 503 for device start errors
  (code from `SessionStartError`), 500 `invalid_configuration`.
- `SessionStore.load_transcript_with_source` gives the transcript endpoint its `source`.
- `OllamaLanguageModel.is_available` now uses a 3 s timeout (it backs `GET /health`).
- `minutes/session_minutes.py` (`write_session_minutes`) is shared by the CLI `minutes` command and
  `POST /sessions/{id}/minutes` (`api/minutes_job.py`, background thread, `minutes_ready` or a
  localized `error` event with code `minutes_failed` / `empty_transcript`).
- `GET /devices` uses `audio/catalog.py` (`WasapiCatalog`): every listing runs on its own
  short-lived `PortAudioThread`, never on the recording session's.
- `serve` refuses `0.0.0.0`, `::`, `[::]` and an empty host (the API has no authentication).
- **Manual check (2026-10-16)**: a script ran the real `python -m vozata serve`, called every
  endpoint with httpx (the same requests `curl` sends) and listened on `/ws` with the
  `websockets` client while a ~60 s Portuguese meeting played (TTS) and the USB mic recorded:
  - `/health` 200 (RTX 3050 6 GB, `large-v3`, Ollama `qwen2.5:7b` reachable); `/devices` listed
    both mics and both loopbacks with defaults; `/settings` 24 keys + schema.
  - `POST /sessions` 201 → second start 409 `session_already_active` (localized) → pause 200 →
    resume 200 → stop 202 `finalizing`; then `done` with mic/system/mixed WAVs, transcript (21
    segments with labels `Me`/`Others`) and minutes (`has_minutes: true`, `GET .../minutes` 200);
    unknown session 404 in the error envelope.
  - WebSocket: first message `{"status": "idle"}`, then status `recording → paused → recording →
    finalizing → done` (with the 1 s heartbeat), 21 `segment`, ~6 `level`/s per channel, one
    `minutes_ready`.
  - Found and fixed: finished sessions reported `ended_at - started_at` (finalization included)
    as `duration_seconds`; `session.json` now stores the recorded length.
