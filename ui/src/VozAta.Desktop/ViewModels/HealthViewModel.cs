using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>Engine status from <c>GET /health</c>: GPU, speech-to-text and the minutes model.</summary>
public sealed partial class HealthViewModel(IEngineClient client, ILocalizationService localization) : ObservableObject
{
    private EngineHealth? _health;

    [ObservableProperty]
    public partial string GpuText { get; private set; } = "";

    [ObservableProperty]
    public partial string SpeechText { get; private set; } = "";

    [ObservableProperty]
    public partial string MinutesText { get; private set; } = "";

    [ObservableProperty]
    public partial string? Error { get; private set; }

    /// <summary>
    /// Where the worker's tasks run (phase 46): "Worker: host", "This PC (worker off)", or null when
    /// no task uses the worker.
    /// </summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasWorkerText))]
    public partial string? WorkerText { get; private set; }

    /// <summary>The worker is chosen but does not answer: this PC does the work.</summary>
    [ObservableProperty]
    public partial bool IsWorkerOff { get; private set; }

    public bool HasWorkerText => WorkerText is not null;

    /// <summary>The engine version (Config → About, phase 38); empty until the first check.</summary>
    [ObservableProperty]
    public partial string EngineVersion { get; private set; } = "";

    public async Task LoadAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            _health = await client.GetHealthAsync(cancellationToken);
            Error = null;
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message;
        }

        RefreshTexts();
    }

    public void RefreshTexts()
    {
        if (_health is not { } health)
        {
            return;
        }

        EngineVersion = health.Version;
        GpuText = health.Gpu.Available
            ? localization.Format("GpuName", health.Gpu.Name, health.Gpu.VramTotalMb)
            : localization["GpuNone"];
        SpeechText = localization.Format("SpeechModel", health.Stt.Model, health.Stt.Device);
        MinutesText = localization.Format(health.Llm.Reachable ? "MinutesReachable" : "MinutesUnreachable", health.Llm.Model);
        var places = health.Worker?.Tasks?.Values ?? [];
        IsWorkerOff = places.Contains("fallback");
        WorkerText = IsWorkerOff ? localization["WorkerStatusOff"]
            : places.Contains("worker") ? localization.Format("WorkerStatusOn", Host(health.Worker!.Url))
            : null;
    }

    private static string Host(string url) =>
        Uri.TryCreate(url, UriKind.Absolute, out var uri) ? uri.Host : url;

    [RelayCommand]
    private Task CheckAgainAsync() => LoadAsync();
}
