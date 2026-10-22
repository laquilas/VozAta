using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>
/// A "Test" button next to a service's settings (phase 38): <c>POST /settings/test/{target}</c>
/// with the saved settings, the result shown inline (✓ or the engine's message).
/// </summary>
public sealed partial class ConnectionTestViewModel(string target, IEngineClient client, ILocalizationService localization)
    : ObservableObject
{
    /// <summary>The engine's target: <see cref="ConnectionTargets"/>.</summary>
    public string Target { get; } = target;

    [ObservableProperty]
    public partial string ButtonText { get; private set; } = localization["ConnectionTest"];

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasResult))]
    [NotifyCanExecuteChangedFor(nameof(RunCommand))]
    public partial bool IsRunning { get; private set; }

    /// <summary>The last test passed (null: not run yet or running).</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasResult), nameof(IsOk), nameof(IsFailed))]
    public partial bool? Ok { get; private set; }

    [ObservableProperty]
    public partial string? Message { get; private set; }

    /// <summary>Runs after every test, once its result is shown (the Ollama test refreshes the model list).</summary>
    public Func<Task>? Completed { get; init; }

    public bool HasResult => Ok is not null && !IsRunning;

    public bool IsOk => Ok == true;

    public bool IsFailed => Ok == false;

    public void RefreshTexts() => ButtonText = localization["ConnectionTest"];

    private bool CanRun() => !IsRunning;

    [RelayCommand(CanExecute = nameof(CanRun))]
    private async Task RunAsync()
    {
        IsRunning = true;
        Ok = null;
        Message = localization["ConnectionTesting"];
        try
        {
            var result = await client.TestConnectionAsync(Target);
            Message = result.Message;
            Ok = result.Ok;
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Message = error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message;
            Ok = false;
        }
        finally
        {
            IsRunning = false;
        }

        if (Completed is { } completed)
        {
            await completed();
        }
    }
}
