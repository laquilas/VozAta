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
/// The system-tray menu: Start, Pause–Resume and Stop reuse the main window's commands; Show and
/// Quit are requests the composition root turns into window calls.
/// </summary>
public sealed partial class TrayViewModel : ObservableObject
{
    private readonly MainViewModel _main;
    private readonly ILocalizationService _localization;
    private readonly IUiPreferences _preferences;

    public TrayViewModel(MainViewModel main, ILocalizationService localization, IUiPreferences preferences)
    {
        _main = main;
        _localization = localization;
        _preferences = preferences;
        MinimizeToTray = preferences.Load().MinimizeToTray;
        main.PropertyChanged += OnMainChanged;
    }

    public event Action? ShowRequested;

    public event Action? QuitRequested;

    public IAsyncRelayCommand StartCommand => _main.StartCommand;

    public IAsyncRelayCommand PauseResumeCommand => _main.PauseResumeCommand;

    public IAsyncRelayCommand StopCommand => _main.StopCommand;

    public TrayState State => _main.State switch
    {
        RecordingState.Recording => TrayState.Recording,
        RecordingState.Paused => TrayState.Paused,
        _ => TrayState.Idle,
    };

    public string ToolTip => _localization.Format("TrayToolTip", _main.StatusText);

    public string StartText => _localization["Start"];

    public string PauseResumeText => _main.PauseResumeText;

    public string StopText => _localization["Stop"];

    public string ShowText => _localization["TrayShow"];

    public string QuitText => _localization["TrayQuit"];

    /// <summary>Minimizing the window hides it to the tray (remembered between runs).</summary>
    [ObservableProperty]
    public partial bool MinimizeToTray { get; set; }

    partial void OnMinimizeToTrayChanged(bool value) =>
        _preferences.Save(_preferences.Load() with { MinimizeToTray = value });

    [RelayCommand]
    private void Show() => ShowRequested?.Invoke();

    [RelayCommand]
    private void Quit() => QuitRequested?.Invoke();

    private void OnMainChanged(object? sender, PropertyChangedEventArgs args)
    {
        switch (args.PropertyName)
        {
            case nameof(MainViewModel.State):
                OnPropertyChanged(nameof(State));
                OnPropertyChanged(nameof(ToolTip));
                OnPropertyChanged(nameof(PauseResumeText));
                break;
            case nameof(MainViewModel.L):
                OnPropertyChanged(string.Empty); // every text, after a language switch
                break;
        }
    }
}
