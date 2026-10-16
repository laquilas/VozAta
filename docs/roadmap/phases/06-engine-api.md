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
