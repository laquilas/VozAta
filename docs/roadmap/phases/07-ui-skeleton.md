# Phase 07 — UI skeleton

## Goal

Create the Avalonia desktop app: connects to (or launches) the engine, Start/Stop button,
conversation-language selector, live transcript, health status bar, localization in en / pt-BR / es.

## Depends on

06

## Read first

- `ui/CLAUDE.md` (or the "ui/CLAUDE.md" section of [standards.md](../standards.md))
- [api-contract.md](../api-contract.md) — rows tagged 06 and the WebSocket section
- [architecture.md](../architecture.md) §10 (i18n, conversation language)

## Scope

| Item | Content |
|------|---------|
| Prerequisite | **.NET SDK is not installed.** Ask the user, then `winget install Microsoft.DotNet.SDK.10`; `dotnet new install Avalonia.Templates` |
| `ui/VozAta.sln` | three projects from `ui/CLAUDE.md` |
| `VozAta.Client` | `IEngineClient` (health, devices, sessions CRUD rows tagged 06, settings GET), `EngineClient` (HttpClient, snake_case JSON), `IEngineEvents` exposing `IAsyncEnumerable<EngineEvent>` over `ClientWebSocket` with auto-reconnect + backoff; DTO records |
| `Services/EngineProcess.cs` | `IEngineProcess`: if `/health` fails, start `{Engine:PythonPath} -m vozata serve` in `{Engine:WorkingDirectory}` (from `appsettings.json`, defaults `../.venv/Scripts/python.exe` and `../engine`), wait for health (timeout 60 s, model load), stop it on exit only if the UI started it |
| `ViewModels/MainViewModel.cs` | state machine `Idle → Starting → Recording → Finalizing → Idle`; `StartCommand`, `StopCommand`; elapsed time; `ConversationLanguages` (`en`, `pt`, `es`, `auto`) with default from `GET /settings` `TRANSCRIPTION_LANGUAGE`; `Segments` collection; detected-language badge |
| `Views/MainWindow.axaml` | big Start/Stop button with a clear red recording indicator, language ComboBox, auto-scrolling transcript (`[hh:mm:ss] Label: text`, colour per speaker), status bar (engine, GPU, STT device, LLM reachable) |
| `Resources/Strings.resx`, `Strings.pt-BR.resx`, `Strings.es.resx` + `ILocalizationService` | runtime culture switch; initial language = engine `APP_LANGUAGE` |
| `.github/workflows/ci.yml` | add `ui` job (`windows-latest`, `dotnet test`) |

## Design notes

- ViewModels depend on `IEngineClient`, `IEngineEvents`, `IEngineProcess`, `IUiDispatcher`,
  `ILocalizationService` — all faked in tests.
- Engine errors (`error` events, HTTP errors) show a non-blocking notification with the localized
  message from the engine.
- Closing the window while recording asks for confirmation and stops the session first.

## Acceptance criteria

- [ ] `dotnet build` and `dotnet test` pass; `dotnet format --verify-no-changes` clean.
- [ ] ViewModel tests: state transitions, Start sends the selected language, segments appended from
      events, `language_detected` updates the badge, error handling, close-while-recording guard.
- [ ] Client tests with a fake `HttpMessageHandler` (snake_case mapping, error envelope).
- [ ] Resource key-parity test for the three `.resx` files.
- [ ] Manual: launching the app starts the engine automatically; Start → live lines appear; Stop →
      status goes Finalizing → Idle; switching UI language changes all visible strings.

## Tests

`VozAta.Desktop.Tests/MainViewModelTests.cs`, `EngineClientTests.cs`,
`LocalizationResourcesTests.cs`, `EngineProcessTests.cs` (with a fake process runner).

## Out of scope

Device pickers and meters (08), history (09), settings screen (10), tray/pause/export (11).

## Kickoff prompt

> Execute phase 07 of the roadmap (`docs/roadmap/phases/07-ui-skeleton.md`), following
> `docs/roadmap/README.md`. Ask me before installing the .NET SDK.

## Progress

- **Branch:** `feature/07-ui-skeleton`
- **Status:** in progress
- **Updated:** 2026-10-16 10:02
- **Next step:** verify everything (build, tests, format, coverage), tick the acceptance criteria, set the phase to done and open the PR.

### Steps

- [x] Start phase: status in progress, Progress section — `6ae4ec1`
- [x] Solution scaffold, `Directory.Build.props`, CI `ui` job — `2b1ddf3`
- [x] `VozAta.Client`: DTOs, `IEngineClient` / `EngineClient`, error envelope + tests — `56bb664`
- [x] `IEngineEvents` (WebSocket, auto-reconnect with backoff) + tests — `8a3c247`
- [x] Desktop services: `EngineProcess`, `ILocalizationService` + `.resx` (en, pt-BR, es) +
      parity test, `IUiDispatcher` — `422167e`
- [x] `MainViewModel` (state machine, commands, segments, language badge, errors, close guard)
      + tests — `1036014`
- [x] `MainWindow.axaml`, `App.axaml.cs` composition root
- [x] Manual: app starts the engine; Start → live lines; Stop → Finalizing → Idle; UI language
      switch
- [ ] Verify; tick acceptance criteria; set phase `done`

### Decisions and notes

- .NET SDK 10.0.402 and Avalonia templates were installed with the user's approval
  (2026-10-16); the templates use Avalonia 12.1.4.

- `.resx` files are generated from one table (all three languages side by side) by a script kept
  out of the repo; the parity test guards against drift. `LocalizationService` raises
  `PropertyChanged("Item[]")` so `{Binding L[Key]}` bindings refresh on a language switch.
- `PathResolver` resolves `Engine:PythonPath` / `Engine:WorkingDirectory` against the current
  directory, then every folder above the app, so the defaults (`../.venv/...`, `../engine`) work
  from `ui/` and from `bin/Debug/net10.0/`. The engine is stopped on exit with
  `Kill(entireProcessTree)` only if the UI started it.
- `MainViewModel` maps engine `status` events onto `RecordingState` (`done`/`idle`/`interrupted`
  → Idle) and reads the elapsed time from them (the engine's 1 s heartbeat), so no UI timer is
  needed. `ShutdownAsync(maxWait)` waits for finalization before stopping an engine the UI
  started, so closing never kills the WAV/minutes step.
- **Manual check (2026-10-16)**: the app was driven through Windows UI Automation (and used by
  hand by the user at the same time):
  - Launch with no engine running → the app started `python -m vozata serve` itself (healthy in
    7–11 s); status bar: engine connected, RTX 3050 6 GB, `large-v3` on auto, Ollama ready.
  - Interface language switched to pt-BR → every visible string changed (button, labels,
    placeholder, status bar); the meeting language list relabelled itself.
  - Start (meeting language Português) → "Gravando", elapsed time ticking, live coloured lines
    (`[00:00:49] Others: Todos concordam?`); Stop → "Finalizando…" → "Pronto" with the
    "A ata está pronta" notification.
  - Closing the window while idle closed the app and stopped the engine it had started.
- **Fixed during the manual check**: `{Binding L[Key]}` labels did not switch language (compiled
  indexer bindings ignore `Item[]` notifications) → `L` is now a `Strings` wrapper replaced on
  every switch; the Stop button was announced as "Avalonia.Controls.StackPanel" to UI
  Automation/screen readers → `AutomationProperties.Name`; Stop turned grey on hover → `danger`
  style for every state; the engine reported clock time (finalization included) in `finalizing`
  / `done` status events → it now reports the recorded length.
- Speaker labels ("Me"/"Others") come from the engine's `APP_LANGUAGE`, not the UI language;
  phase 10 (settings) will let the UI change `APP_LANGUAGE`.
- Starting a session blocks ~20–25 s on this machine while Whisper loads (status "Iniciando…").
