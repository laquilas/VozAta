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

- [ ] Every 06 row of the contract implemented; OpenAPI at `/docs` matches the contract shapes.
- [ ] `TestClient` tests: start/pause/resume/stop lifecycle with fake session, 409 on second
      start, 404 codes, settings masking, health with fake LLM availability.
- [ ] WebSocket test: connect → initial `status`; fake session events arrive in order with the
      envelope; disconnect does not break publishing.
- [ ] Manual: `python -m vozata serve`, then start/stop via `curl` and watch events with a
      WebSocket client (e.g. `python -m websockets ws://127.0.0.1:8765/ws`).
- [ ] Coverage ≥ 80 %.

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
- **Status:** in progress
- **Updated:** 2026-10-16 09:08
- **Next step:** add `bootstrap.build_api_container(settings)` (real devices on a PortAudio thread, GPU via nvidia-smi, Ollama reachability, background minutes regeneration publishing `minutes_ready`/`error`) and the `serve` command in `__main__.py` (uvicorn on API_HOST:API_PORT, refuse 0.0.0.0) with tests.

### Steps

- [x] Start phase: status in progress, Progress section — `fd671b5`
- [x] Dependencies; `API_HOST` / `API_PORT`; settings schema metadata in `config.py` — `02a9678`
- [x] `api/ws.py` (`EventBroadcaster`) + tests — `82005b0`
- [x] `api/session_manager.py` (`SessionManager`) + tests — `69b6ff5`
- [x] `api/app.py`, `api/schemas.py`, error handler, `system_info.py`, routes `health`, `devices`,
      `settings` (GET) + tests
- [x] Routes `sessions` (start, pause, resume, stop, list, detail, transcript, minutes) + tests
- [ ] `serve` command (uvicorn; refuses `0.0.0.0`) + tests
- [ ] Manual: `python -m vozata serve`, start/stop with `curl`, events with a WebSocket client
- [ ] Verify; tick acceptance criteria; set phase `done`

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
