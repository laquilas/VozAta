using System.ComponentModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>Which icon the tray shows.</summary>
public enum TrayState
{
    Idle,
    Recording,
    Paused,
}

/// <summary>
/// The system-tray menu: Start, Pause–Resume and Stop reuse the recorder page's commands; Show and
/// Quit are requests the composition root turns into window calls.
/// </summary>
public sealed partial class TrayViewModel : ObservableObject
{
    private readonly RecorderPageViewModel _recorder;
    private readonly ILocalizationService _localization;
    private readonly IUiPreferences _preferences;

    public TrayViewModel(RecorderPageViewModel recorder, ILocalizationService localization, IUiPreferences preferences)
    {
        _recorder = recorder;
        _localization = localization;
        _preferences = preferences;
        MinimizeToTray = preferences.Load().MinimizeToTray;
        recorder.PropertyChanged += OnRecorderChanged;
        recorder.Session.PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(RecordingSessionService.Title))
            {
                OnPropertyChanged(nameof(ToolTip));
            }
        };
    }

    public event Action? ShowRequested;

    public event Action? QuitRequested;

    public IAsyncRelayCommand StartCommand => _recorder.StartCommand;

    public IAsyncRelayCommand PauseResumeCommand => _recorder.PauseResumeCommand;

    public IAsyncRelayCommand StopCommand => _recorder.StopCommand;

    public TrayState State => _recorder.State switch
    {
        RecordingState.Recording => TrayState.Recording,
        RecordingState.Paused => TrayState.Paused,
        _ => TrayState.Idle,
    };

    /// <summary>"VozAta — Recording", with the meeting title when the recording has one (phase 35).</summary>
    public string ToolTip => _recorder.Session.Title is { } title
        ? _localization.Format("TrayToolTipTitled", _recorder.StatusText, title)
        : _localization.Format("TrayToolTip", _recorder.StatusText);

    public string StartText => _localization["Start"];

    public string PauseResumeText => _recorder.PauseResumeText;

    public string StopText => _localization["Stop"];

    public string ShowText => _localization["TrayShow"];

    public string QuitText => _localization["TrayQuit"];

    /// <summary>Minimizing the window hides it to the tray (remembered between runs).</summary>
    [ObservableProperty]
    public partial bool MinimizeToTray { get; set; }

    /// <summary>Every text, after a language switch.</summary>
    public void RefreshTexts() => OnPropertyChanged(string.Empty);

    partial void OnMinimizeToTrayChanged(bool value) =>
        _preferences.Save(_preferences.Load() with { MinimizeToTray = value });

    [RelayCommand]
    private void Show() => ShowRequested?.Invoke();

    [RelayCommand]
    private void Quit() => QuitRequested?.Invoke();

    private void OnRecorderChanged(object? sender, PropertyChangedEventArgs args)
    {
        if (args.PropertyName == nameof(RecorderPageViewModel.State))
        {
            OnPropertyChanged(nameof(State));
            OnPropertyChanged(nameof(ToolTip));
            OnPropertyChanged(nameof(PauseResumeText));
        }
    }
}
