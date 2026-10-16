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
| `ui/MeetingMinutes.sln` | three projects from `ui/CLAUDE.md` |
| `MeetingMinutes.Client` | `IEngineClient` (health, devices, sessions CRUD rows tagged 06, settings GET), `EngineClient` (HttpClient, snake_case JSON), `IEngineEvents` exposing `IAsyncEnumerable<EngineEvent>` over `ClientWebSocket` with auto-reconnect + backoff; DTO records |
| `Services/EngineProcess.cs` | `IEngineProcess`: if `/health` fails, start `{Engine:PythonPath} -m meeting_minutes serve` in `{Engine:WorkingDirectory}` (from `appsettings.json`, defaults `../.venv/Scripts/python.exe` and `../engine`), wait for health (timeout 60 s, model load), stop it on exit only if the UI started it |
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

`MeetingMinutes.Desktop.Tests/MainViewModelTests.cs`, `EngineClientTests.cs`,
`LocalizationResourcesTests.cs`, `EngineProcessTests.cs` (with a fake process runner).

## Out of scope

Device pickers and meters (08), history (09), settings screen (10), tray/pause/export (11).

## Kickoff prompt

> Execute phase 07 of the roadmap (`docs/roadmap/phases/07-ui-skeleton.md`), following
> `docs/roadmap/README.md`. Ask me before installing the .NET SDK.
