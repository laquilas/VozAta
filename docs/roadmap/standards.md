# Standards

This file holds the exact content of the three `CLAUDE.md` files that phase 00 creates. Until
phase 00 is done, sessions follow this file directly. After phase 00, the `CLAUDE.md` files are the
source of truth and this file is only updated together with them.

---

## Root `CLAUDE.md`

````markdown
# VozAta

Near-real-time meeting transcription (microphone + system audio) and LLM-generated meeting
minutes. Python engine (`engine/`) + Avalonia desktop UI (`ui/`) over a local HTTP/WebSocket API.

## Layout

- `engine/` — Python engine (see `engine/CLAUDE.md`).
- `ui/` — Avalonia desktop app (see `ui/CLAUDE.md`).
- `docs/roadmap/` — roadmap, architecture, API contract. **Start every session at
  `docs/roadmap/README.md`.**
- `__legacy__/` — old prototypes. Read-only reference: never edit, never import from it.
- `.venv/` — shared Python virtualenv at the repo root.

## Session workflow

1. **Resume first**: `git fetch`, then look for unmerged `feature/*` branches (local, remote, open
   PRs). If one exists, check it out, check `git status` for uncommitted work, read the phase
   file's **Progress** section and continue from its *Next step*.
2. Otherwise read `docs/roadmap/README.md`; pick the phase (first `todo` with all dependencies
   `done`, or the one the user names).
3. Read only that phase file and the documents in its *Read first* section.
4. Branch `feature/<NN-slug>`. The first commit sets the phase to in progress (`feature/<NN-slug>`)
   in the README table and adds the **Progress** section to the phase file (template in
   `docs/roadmap/README.md`). Never delete a branch whose phase is in progress: its work is not in
   `main` yet.
5. Implement with TDD; one logical change per commit. Every commit also updates **Progress** (tick
   the step, set *Next step*) and is pushed, so a session cut short can be resumed.
6. Tick the phase acceptance criteria and set its status to `done` in the README table.
7. Shared contract changes (config keys, endpoints, events, data model) go into
   `docs/roadmap/architecture.md` / `docs/roadmap/api-contract.md` in the same branch.

## Global rules

- **English only** for code, comments, docs, commits, branch names, defaults and log messages.
- **Line endings**: LF everywhere, enforced by `.gitattributes` (`* text=auto eol=lf`; only `.sln`,
  `.bat` and `.cmd` use CRLF). It overrides the machine-level `core.autocrlf=true`; never commit CRLF.
- Diagrams in Markdown docs use **Mermaid** code blocks (` ```mermaid `), never ASCII art or images.
- User-facing text and LLM prompts are **never hard-coded**: they come from locale resources in
  `en` (default), `pt-BR` and `es`. Every new key is added to all three.
- **SOLID**: depend on ports (interfaces), not concrete classes; concrete classes are wired only in
  the composition root (`engine/src/vozata/bootstrap.py`, `ui/.../App.axaml.cs`); new
  providers are added through registries, not by editing orchestrators.
- Every new class, branch and bug fix gets unit tests; diff coverage ≥ 80 %.
- Unit tests never touch audio hardware, GPU, network or real LLMs — use fakes.
- Secrets live only in `.env` (git-ignored); never log them; mask them in API responses.
- Recording consent is the user's responsibility; the UI must make recording state obvious.
````

---

## `engine/CLAUDE.md`

````markdown
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
  `TRANSCRIBERS: dict[str, Callable[[Settings], Transcriber]]`.
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
````

---

## `ui/CLAUDE.md`

````markdown
# Desktop UI (Avalonia)

## Stack

.NET 10 (LTS) · latest stable Avalonia · CommunityToolkit.Mvvm · Microsoft.Extensions.DependencyInjection ·
System.Net.Http + System.Net.WebSockets · System.Text.Json (`SnakeCaseLower`) · xUnit.

## Solution

```
ui/VozAta.sln
ui/src/VozAta.Client/          IEngineClient, EngineClient, DTOs, EngineEvent stream
ui/src/VozAta.Desktop/         App.axaml(.cs), Views/, ViewModels/, Services/, Resources/Strings*.resx
ui/tests/VozAta.Desktop.Tests/ ViewModel + client tests
```

## Commands (run from `ui/`)

- Build: `dotnet build` · Test: `dotnet test` · Format: `dotnet format`
- Run: `dotnet run --project src/VozAta.Desktop`

## Rules

- MVVM: Views contain no logic (no code-behind beyond `InitializeComponent`); ViewModels use
  `[ObservableProperty]` / `[RelayCommand]`.
- DI composition root in `App.axaml.cs`; ViewModels receive interfaces (`IEngineClient`,
  `IEngineProcess`, `IDialogService`, `ILocalizationService`, `IClock`…).
- `IEngineClient` mirrors `docs/roadmap/api-contract.md`; DTOs are records; never call
  `HttpClient` from ViewModels.
- UI thread: marshal engine events with `Dispatcher.UIThread.Post`; ViewModels stay testable by
  depending on an `IUiDispatcher` abstraction.
- Nullable reference types enabled; warnings as errors.
- All user-facing strings in `Resources/Strings.resx` (en), `Strings.pt-BR.resx`, `Strings.es.resx`;
  a test asserts every key exists in all three; language switches at runtime.
- Tests: ViewModels with fake `IEngineClient`; client with a fake `HttpMessageHandler`.
````
