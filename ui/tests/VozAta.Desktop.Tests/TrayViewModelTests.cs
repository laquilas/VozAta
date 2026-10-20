using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

public sealed class TrayViewModelTests
{
    private readonly FakeEngineClient _client = new();
    private readonly FakeEngineEvents _events = new();
    private readonly LocalizationService _localization = new();
    private readonly FakePreferences _preferences = new();

    private async Task<(MainViewModel Main, TrayViewModel Tray)> ReadyAsync()
    {
        var main = new MainViewModel(
            _client, _events, new FakeEngineProcess(), new ImmediateDispatcher(), _localization, new FakeDialogs(),
            _preferences, new FakeClock(), new FakeTimer(), new FakeShell(), new FakeFileSaver(), new FakeThemeService());
        await main.InitializeAsync();
        var before = main.HandledEvents;
        _events.Send(new ConnectionChangedEvent(true));
        for (var i = 0; i < 200 && main.HandledEvents == before; i++)
        {
            await Task.Delay(5);
        }

        return (main, new TrayViewModel(main.Recorder, _localization, _preferences));
    }

    [Fact]
    public async Task Menu_commands_drive_the_recording()
    {
        var (main, tray) = await ReadyAsync();
        Assert.Equal(TrayState.Idle, tray.State);
        Assert.True(tray.StartCommand.CanExecute(null));
        Assert.False(tray.StopCommand.CanExecute(null));

        await tray.StartCommand.ExecuteAsync(null);
        Assert.Equal(TrayState.Recording, tray.State);
        await tray.PauseResumeCommand.ExecuteAsync(null);
        Assert.Equal(TrayState.Paused, tray.State);
        Assert.Equal("Resume", tray.PauseResumeText);
        await tray.StopCommand.ExecuteAsync(null);

        Assert.Equal(RecordingState.Idle, main.Recorder.State);
        Assert.Equal(["start", "pause", "stop"], _client.Calls.Where(call => call is "start" or "pause" or "stop"));
    }

    [Fact]
    public async Task Show_and_quit_are_requests_for_the_window()
    {
        var (_, tray) = await ReadyAsync();
        var requests = new List<string>();
        tray.ShowRequested += () => requests.Add("show");
        tray.QuitRequested += () => requests.Add("quit");

        tray.ShowCommand.Execute(null);
        tray.QuitCommand.Execute(null);

        Assert.Equal(["show", "quit"], requests);
    }

    [Fact]
    public async Task The_tooltip_and_menu_texts_follow_state_and_language()
    {
        var (main, tray) = await ReadyAsync();
        var changed = new List<string?>();
        tray.PropertyChanged += (_, args) => changed.Add(args.PropertyName);
        Assert.Equal("VozAta — Ready", tray.ToolTip);

        await tray.StartCommand.ExecuteAsync(null);
        Assert.Equal("VozAta — Recording", tray.ToolTip);
        Assert.Contains(nameof(TrayViewModel.State), changed);
        main.SelectedAppLanguage = main.AppLanguages.Single(option => option.Value == "pt-BR");

        Assert.Equal(("Iniciar gravação", "Pausar", "Parar", "Mostrar o VozAta", "Sair"), (tray.StartText, tray.PauseResumeText, tray.StopText, tray.ShowText, tray.QuitText));
        Assert.Equal("VozAta — Gravando", tray.ToolTip);
    }

    [Fact]
    public async Task The_tooltip_shows_the_meeting_title_while_recording()
    {
        var (main, tray) = await ReadyAsync();
        var changed = new List<string?>();
        tray.PropertyChanged += (_, args) => changed.Add(args.PropertyName);
        main.Recorder.Title = "Weekly sync";

        await tray.StartCommand.ExecuteAsync(null);
        Assert.Equal("VozAta — Recording: Weekly sync", tray.ToolTip);
        main.Recorder.Title = "Budget review";
        await main.Recorder.EnterCommand.ExecuteAsync(null);

        Assert.Equal("VozAta — Recording: Budget review", tray.ToolTip);
        Assert.Contains(nameof(TrayViewModel.ToolTip), changed);
    }

    [Fact]
    public async Task The_main_window_owns_a_tray_menu()
    {
        var (main, _) = await ReadyAsync();

        Assert.Same(main.Recorder.StartCommand, main.Tray.StartCommand);
    }

    [Fact]
    public async Task Minimize_to_tray_is_remembered()
    {
        var (_, tray) = await ReadyAsync();
        Assert.False(tray.MinimizeToTray);

        tray.MinimizeToTray = true;

        Assert.True(_preferences.Data.MinimizeToTray);
        var (_, again) = await ReadyAsync();
        Assert.True(again.MinimizeToTray);
    }
}
