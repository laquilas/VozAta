using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>The Toggl-style shell (phase 35): pages, shortcuts, sidebar and the recording indicator.</summary>
public sealed class ShellViewModelTests
{
    private readonly FakeEngineClient _client = new();
    private readonly FakeEngineEvents _events = new();
    private readonly LocalizationService _localization = new();
    private readonly FakePreferences _preferences = new();
    private readonly FakeThemeService _theme = new();

    private MainViewModel Create() =>
        new(_client, _events, new FakeEngineProcess(), new ImmediateDispatcher(), _localization, new FakeDialogs(),
            _preferences, new FakeClock(), new FakeTimer(), new FakeShell(), new FakeFileSaver(), _theme);

    private async Task<MainViewModel> ReadyAsync()
    {
        var main = Create();
        await main.InitializeAsync();
        _events.Send(new ConnectionChangedEvent(true));
        for (var i = 0; i < 200 && main.HandledEvents == 0; i++)
        {
            await Task.Delay(5);
        }

        return main;
    }

    [Fact]
    public void The_shell_starts_on_the_recorder_with_four_pages()
    {
        var shell = Create().Shell;

        Assert.Equal(
            [ShellViewModel.Recorder, ShellViewModel.Meetings, ShellViewModel.Ask, ShellViewModel.Config],
            shell.Pages.Select(item => item.Key));
        Assert.IsType<RecorderPageViewModel>(shell.CurrentPage);
        Assert.True(shell.Pages[0].IsCurrent);
        Assert.Equal(["Recorder", "Meetings", "Ask", "Config"], shell.Pages.Select(item => item.Label));
        Assert.Equal(["Icon.Record", "Icon.History", "Icon.Chat", "Icon.Settings"], shell.Pages.Select(item => item.Icon));
    }

    [Fact]
    public void Each_page_wraps_the_existing_view_models()
    {
        var main = Create();
        var shell = main.Shell;

        Assert.Same(main.Recorder, shell.Pages[0].Page);
        Assert.Same(main.History, Assert.IsType<MeetingsPageViewModel>(shell.Pages[1].Page).History);
        Assert.Same(main.History.Ask, Assert.IsType<AskPageViewModel>(shell.Pages[2].Page).Ask);
        Assert.Same(main.Settings, Assert.IsType<ConfigPageViewModel>(shell.Pages[3].Page).Settings);
    }

    [Theory]
    [InlineData("meetings", typeof(MeetingsPageViewModel))]
    [InlineData("ask", typeof(AskPageViewModel))]
    [InlineData("config", typeof(ConfigPageViewModel))]
    [InlineData("recorder", typeof(RecorderPageViewModel))]
    public void Navigate_shows_the_page_and_marks_it_current(string key, Type page)
    {
        var shell = Create().Shell;
        var changed = new List<string?>();
        shell.PropertyChanged += (_, args) => changed.Add(args.PropertyName);
        shell.NavigateCommand.Execute(ShellViewModel.Config);

        shell.NavigateCommand.Execute(key);

        Assert.IsType(page, shell.CurrentPage);
        Assert.Equal([key], shell.Pages.Where(item => item.IsCurrent).Select(item => item.Key));
        Assert.Contains(nameof(ShellViewModel.CurrentPage), changed);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("reports")]
    public void An_unknown_page_is_ignored(string? key)
    {
        var shell = Create().Shell;

        shell.NavigateCommand.Execute(key);

        Assert.IsType<RecorderPageViewModel>(shell.CurrentPage);
    }

    [Fact]
    public void Ctrl_1_to_4_are_the_page_shortcuts_in_sidebar_order()
    {
        var shell = Create().Shell;

        Assert.Equal(["Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+4"], shell.Pages.Select(item => item.Gesture));
    }

    [Fact]
    public void The_main_window_binds_every_shortcut_to_its_page()
    {
        var shell = Create().Shell;
        var window = System.Xml.Linq.XDocument.Load(
            Path.Combine(ThemeTokensTests.DesktopFolder(), "Views", "MainWindow.axaml"));

        var bindings = window.Descendants()
            .Where(element => element.Name.LocalName == "KeyBinding")
            .Select(element => ((string?)element.Attribute("Gesture"), (string?)element.Attribute("CommandParameter")));

        Assert.Equal(shell.Pages.Select(item => ((string?)item.Gesture, (string?)item.Key)), bindings);
    }

    [Fact]
    public void The_sidebar_collapse_is_remembered()
    {
        var shell = Create().Shell;
        Assert.Equal((false, true, "Collapse the sidebar"), (shell.IsCollapsed, shell.IsExpanded, shell.ToggleSidebarText));
        Assert.Equal(0, _preferences.Saves);

        shell.ToggleSidebarCommand.Execute(null);

        Assert.Equal((true, false, "Expand the sidebar"), (shell.IsCollapsed, shell.IsExpanded, shell.ToggleSidebarText));
        Assert.True(_preferences.Data.SidebarCollapsed);
        var saves = _preferences.Saves;
        Assert.True(Create().Shell.IsCollapsed);
        Assert.Equal(saves, _preferences.Saves); // restoring does not save again
    }

    [Fact]
    public async Task The_recording_indicator_is_visible_on_every_page()
    {
        var main = await ReadyAsync();
        var shell = main.Shell;
        await main.Recorder.StartCommand.ExecuteAsync(null);
        await main.Recorder.PauseResumeCommand.ExecuteAsync(null); // paused still counts as recording

        foreach (var item in shell.Pages)
        {
            shell.NavigateCommand.Execute(item.Key);
            Assert.True(shell.Session.IsRecording);
            Assert.Equal(item.Key != ShellViewModel.Recorder, shell.IsRecordingElsewhere);
        }
    }

    [Fact]
    public async Task The_banner_over_other_pages_follows_the_elapsed_time_and_the_end()
    {
        var main = await ReadyAsync();
        var shell = main.Shell;
        await main.Recorder.StartCommand.ExecuteAsync(null);
        shell.NavigateCommand.Execute(ShellViewModel.Meetings);
        var changed = new List<string?>();
        shell.PropertyChanged += (_, args) => changed.Add(args.PropertyName);

        _events.Send(new StatusEvent("s", "recording", 125));
        await WaitAsync(() => main.Session.Elapsed == "00:02:05");
        Assert.Equal("Recording 00:02:05 — open the recorder", shell.RecordingBannerText);
        Assert.Contains(nameof(ShellViewModel.RecordingBannerText), changed);

        _events.Send(new StatusEvent("s", "done", 130));
        await WaitAsync(() => !main.Session.IsRecording);
        Assert.False(shell.IsRecordingElsewhere);
        Assert.Contains(nameof(ShellViewModel.IsRecordingElsewhere), changed);
    }

    [Fact]
    public async Task Labels_follow_the_interface_language()
    {
        var main = await ReadyAsync();

        main.SelectedAppLanguage = main.AppLanguages.Single(option => option.Value == "pt-BR");

        Assert.Equal(["Gravador", "Reuniões", "Perguntar", "Configurações"], main.Shell.Pages.Select(item => item.Label));
        Assert.Equal("Recolher a barra lateral", main.Shell.ToggleSidebarText);
    }

    [Fact]
    public async Task A_source_on_the_ask_page_opens_its_meeting_on_the_meetings_page()
    {
        var main = await ReadyAsync();
        var shell = main.Shell;
        shell.NavigateCommand.Execute(ShellViewModel.Ask);
        var ask = Assert.IsType<AskPageViewModel>(shell.CurrentPage).Ask;

        await ask.OpenCitation!(new Citation("20261015_202358", "mic-000001", 3.0));

        Assert.IsType<MeetingsPageViewModel>(shell.CurrentPage);
    }

    [Fact]
    public void The_ask_page_works_without_an_earlier_source_handler()
    {
        var ask = new AskViewModel(_client, _localization);
        var shown = 0;
        var page = new AskPageViewModel(ask, () => shown++);

        Assert.True(page.Ask.OpenCitation!(new Citation("x", "y", 0)).IsCompleted);
        Assert.Equal(1, shown);
    }

    [Theory]
    [InlineData("system", false, "dark")]
    [InlineData("system", true, "light")]
    [InlineData("light", false, "dark")]
    [InlineData("dark", false, "light")]
    public void The_theme_button_switches_between_light_and_dark(string saved, bool systemIsDark, string expected)
    {
        _preferences.Data = new UiPreferencesData(Theme: saved);
        _theme.SystemIsDark = systemIsDark;
        var main = Create();

        main.Appearance.ToggleCommand.Execute(null);

        Assert.Equal(expected, main.Appearance.SelectedTheme.Value);
        Assert.Equal(expected, _theme.Applied.Last());
        Assert.Equal(expected, _preferences.Data.Theme);
    }

    private static async Task WaitAsync(Func<bool> condition)
    {
        for (var i = 0; i < 200 && !condition(); i++)
        {
            await Task.Delay(5);
        }

        Assert.True(condition());
    }
}
