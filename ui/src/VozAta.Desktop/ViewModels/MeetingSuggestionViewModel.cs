using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>
/// The banner of a <c>meeting_detected</c> event (phase 54): "Microsoft Teams is in a call. Record
/// it?" with Record (the recorder's Start, with the current devices) and Not now. It never records
/// by itself; a recording that starts closes it, and a newer call replaces it.
/// </summary>
public sealed partial class MeetingSuggestionViewModel(ILocalizationService localization, IAsyncRelayCommand start)
    : ObservableObject
{
    private string? _name;

    [ObservableProperty]
    public partial bool IsOpen { get; private set; }

    [ObservableProperty]
    public partial string? Message { get; private set; }

    public void Offer(MeetingDetectedEvent detected)
    {
        _name = detected.Name;
        RefreshTexts();
        IsOpen = true;
    }

    /// <summary>A recording started (from here or elsewhere): nothing left to suggest.</summary>
    public void OnRecordingStarted() => IsOpen = false;

    public void RefreshTexts()
    {
        if (_name is not null)
        {
            Message = localization.Format("MeetingDetected", _name);
        }
    }

    [RelayCommand]
    private async Task RecordAsync()
    {
        IsOpen = false;
        if (start.CanExecute(null))
        {
            await start.ExecuteAsync(null);
        }
    }

    [RelayCommand]
    private void NotNow() => IsOpen = false;
}
