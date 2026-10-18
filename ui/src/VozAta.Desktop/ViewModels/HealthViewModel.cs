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
    }

    [RelayCommand]
    private Task CheckAgainAsync() => LoadAsync();
}
