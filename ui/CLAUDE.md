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
