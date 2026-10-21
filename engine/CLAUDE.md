# Engine (Python)

## Stack

Python 3.13 · src layout `engine/src/vozata/` · virtualenv at repo root `.venv/` ·
faster-whisper (CUDA via pip `nvidia-*` wheels) · PyAudioWPatch (WASAPI loopback) · soxr ·
numpy · FastAPI + uvicorn · httpx · python-dotenv · pytest · ruff.

## Commands (run from `engine/`)

- Install: `../.venv/Scripts/python -m pip install -e ".[dev]"`
- Tests: `../.venv/Scripts/python -m pytest --cov=vozata --cov-report=term-missing`
- Lint/format: `../.venv/Scripts/ruff check src tests` · `../.venv/Scripts/ruff format src tests`
- Run: `../.venv/Scripts/python -m vozata record` · `... serve` · `... minutes <dir>`

## Rules

- Type hints everywhere; `from __future__ import annotations`; dataclasses (frozen) for values.
- Ports are `typing.Protocol` classes in `ports.py`; domain types live in `domain.py` (no I/O).
- `config.py` is the only module that reads environment variables; other modules receive
  `Settings` or plain values through their constructor.
- `bootstrap.py` is the only module that imports concrete providers; it exposes registries such as
  `TRANSCRIBERS: dict[str, Callable[[Settings, ModelDownloader], Transcriber]]`.
- One responsibility per module; keep files under ~200 lines.
- User-facing strings via `Localizer.t("key", **params)`; locale files
  `src/vozata/locales/{en,pt-BR,es}.toml`.
- Logging with `logging` (no `print` outside the CLI console sink).
- Tests mirror `src/`; shared fakes in `tests/fakes.py` (`FakeTranscriber`, `FakeLanguageModel`,
  `FakeAudioSource`, `FakeDiarizer`…); HTTP clients tested with `httpx.MockTransport`; API with
  FastAPI `TestClient`; audio with synthetic numpy arrays and `tmp_path`.
- Hardware/GPU code (`audio/capture.py`, `transcription/faster_whisper.py`,
  `diarization/pyannote.py`) stays thin and is covered by manual smoke checks listed in the phase.

## Checklists

**Add a provider (STT / LLM / diarizer / task exporter / export format)**
1. Implement the port in its package (e.g. `transcription/<name>.py`).
2. Register a factory in `bootstrap.py`.
3. Add its config keys to `config.py`, `.env.example`, `docs/roadmap/architecture.md` §9.
4. Contract tests: reuse the port's shared test suite (e.g. `tests/transcription/contract.py`).

**Add an app language**
1. Add the enum value in `domain.AppLanguage`.
2. Add `locales/<lang>.toml` with every key (the key-parity test fails otherwise).
3. Add the UI `.resx` (see `ui/CLAUDE.md`).
