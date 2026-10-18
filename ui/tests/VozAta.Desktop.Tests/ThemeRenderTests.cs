using System.Text.Json;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Headless;
using Avalonia.Threading;
using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;
using VozAta.Desktop.Views;

namespace VozAta.Desktop.Tests;

/// <summary>The real App styles on Avalonia's headless platform (CPU rendering, no window on screen).</summary>
public static class HeadlessApp
{
    public static AppBuilder BuildAvaloniaApp() => AppBuilder.Configure<App>()
        .UseSkia()
        .UseHeadless(new AvaloniaHeadlessPlatformOptions { UseHeadlessDrawing = false })
        .WithInterFont();
}

/// <summary>
/// Every page of the main window loads and renders with the design system in light and dark mode
/// (phase 34): a missing token or a broken style fails here. With <c>VOZATA_SCREENSHOTS</c> set to a
/// folder, the frames are saved there as PNG (the screenshots of the phase 34 PR).
/// </summary>
public sealed class ThemeRenderTests
{
    internal static readonly Lazy<HeadlessUnitTestSession> Session =
        new(() => HeadlessUnitTestSession.StartNew(typeof(HeadlessApp)));

    [Theory]
    [InlineData("light")]
    [InlineData("dark")]
    public async Task Every_page_renders_in_the_theme(string theme)
    {
        // The Func<Task<T>> overload waits for the whole async body on the UI thread.
        var rendered = await Session.Value.Dispatch<int>(
            async () =>
            {
                var (viewModel, client) = await SeededAsync(theme);
                Assert.Equal(theme == "dark" ? "Dark" : "Light", Application.Current!.ActualThemeVariant.ToString());
                Render<RecorderPage>(viewModel, ShellViewModel.Recorder, $"recorder-idle-{theme}.png");
                viewModel.History.Selected = viewModel.History.Rows[0]; // the recorder closed it: open it again
                await viewModel.History.DetailLoading;
                Render<Views.SessionPage>(viewModel, null, $"session-minutes-{theme}.png"); // the meeting page (phase 37)
                viewModel.History.Detail!.SelectedTab = 1;
                await viewModel.History.Detail.PlayLineCommand.ExecuteAsync(viewModel.History.Detail.Lines[1]);
                Render<Views.SessionPage>(viewModel, null, $"session-transcript-playing-{theme}.png");
                Assert.NotNull(viewModel.History.Detail.Player);
                await viewModel.History.CloseAsync(); // the list alone, as on opening the page (phase 36)
                await viewModel.Meetings.LoadOlderCommand.ExecuteAsync(null);
                Render<MeetingsPage>(viewModel, ShellViewModel.Meetings, $"meetings-week-{theme}.png");
                var row = viewModel.Meetings.Weeks[0].Days[1].Rows[0];
                viewModel.Meetings.BeginRenameCommand.Execute(row);
                row.EditTitle = "Design review — tokens";
                viewModel.Meetings.ToggleExportCommand.Execute(viewModel.Meetings.Weeks[0].Days[0].Rows[0]);
                Render<MeetingsPage>(viewModel, ShellViewModel.Meetings, $"meetings-rename-export-{theme}.png");
                viewModel.Meetings.CancelRenameCommand.Execute(row);
                viewModel.Meetings.ToggleExportCommand.Execute(viewModel.Meetings.Weeks[0].Days[0].Rows[0]);
                await viewModel.Meetings.DeleteCommand.ExecuteAsync(viewModel.Meetings.Weeks[0].Days[0].Rows[^1]);
                Render<MeetingsPage>(viewModel, ShellViewModel.Meetings, $"meetings-undo-{theme}.png");
                viewModel.Meetings.UndoCommand.Execute(null);
                viewModel.Meetings.Search.Query = "tokens";
                await viewModel.Meetings.Search.Pending;
                Render<MeetingsPage>(viewModel, ShellViewModel.Meetings, $"meetings-search-{theme}.png");
                viewModel.Meetings.Search.Query = "";
                Render<AskView>(viewModel, ShellViewModel.Ask, $"ask-{theme}.png");
                Render<ConfigPage>(viewModel, ShellViewModel.Config, $"config-{theme}.png");

                // Start goes to the fake engine only: no audio is captured.
                viewModel.Recorder.Title = "Weekly design review";
                await viewModel.Recorder.StartCommand.ExecuteAsync(null);
                Assert.True(viewModel.Recorder.IsRecording);
                viewModel.Recorder.Handle(new StatusEvent("20261016_090000", "recording", 754));
                AddTranscript(viewModel);
                Render<RecorderPage>(viewModel, ShellViewModel.Recorder, $"recorder-recording-{theme}.png");
                await viewModel.HistoryRefresh;
                var live = new DateTimeOffset(new DateTime(2026, 10, 16, 14, 0, 0, DateTimeKind.Local));
                client.Sessions.Add(new SessionSummary("20261016_140000", "recording", live, null, 754, "en", false, "Weekly design review"));
                await viewModel.Meetings.LoadAsync(); // the live meeting is pinned on the Meetings page
                Assert.NotNull(viewModel.Meetings.Live);
                Render<MeetingsPage>(viewModel, ShellViewModel.Meetings, $"meetings-while-recording-{theme}.png");
                viewModel.Shell.ToggleSidebarCommand.Execute(null);
                Render<RecorderPage>(viewModel, ShellViewModel.Recorder, $"recorder-recording-collapsed-{theme}.png");
                viewModel.Shell.ToggleSidebarCommand.Execute(null);
                return 14;
            },
            CancellationToken.None);

        Assert.Equal(14, rendered);
    }

#if DEBUG
    [Fact]
    public async Task The_theme_gallery_shows_both_themes()
    {
        var rendered = await Session.Value.Dispatch<bool>(
            () =>
            {
                var window = new Diagnostics.ThemeGalleryWindow { Width = 1500, Height = 1450 };
                window.Show();
                try
                {
                    Dispatcher.UIThread.RunJobs();
                    var frame = window.CaptureRenderedFrame();
                    Save(frame!, "theme-gallery.png");
                    return Task.FromResult(frame is not null);
                }
                finally
                {
                    window.Close();
                }
            },
            CancellationToken.None);

        Assert.True(rendered);
    }
#endif

    /// <summary>Show <paramref name="page"/> in a new main window, check its view is there, save the frame.</summary>
    internal static void Render<TView>(MainViewModel viewModel, string? page, string name)
        where TView : Control
    {
        if (page is not null) // null: the page shown now (a meeting page, phase 37)
        {
            viewModel.Shell.NavigateCommand.Execute(page);
        }

        var window = new MainWindow { DataContext = viewModel, Width = 1280, Height = 860 };
        window.Show();
        try
        {
            Dispatcher.UIThread.RunJobs();
            Assert.Single(Avalonia.VisualTree.VisualExtensions.GetVisualDescendants(window).OfType<ShellView>());
            Assert.NotNull(window.GetVisualDescendant<TView>());
            var frame = window.CaptureRenderedFrame();
            Assert.NotNull(frame);
            Save(frame, name);
        }
        finally
        {
            window.Close();
        }
    }
    private static void Save(Avalonia.Media.Imaging.Bitmap frame, string name)
    {
        var folder = Environment.GetEnvironmentVariable("VOZATA_SCREENSHOTS");
        if (!string.IsNullOrEmpty(folder))
        {
            Directory.CreateDirectory(folder);
            frame.Save(Path.Combine(folder, name), Avalonia.Media.Imaging.PngBitmapEncoderOptions.Default);
        }
    }

    /// <summary>A main window with a bit of everything: transcript, notification, history detail, settings.</summary>
    internal static async Task<(MainViewModel ViewModel, FakeEngineClient Client)> SeededAsync(
        string theme, Action<FakeEngineClient>? seed = null)
    {
        var client = new FakeEngineClient
        {
            Devices = new DeviceList(
                [new AudioDevice(1, "Headset Microphone (USB)", 48000, 1)],
                [new AudioDevice(7, "Speakers [Loopback]", 48000, 2)], 1, 7),
        };
        AddSetting(client, "APP_LANGUAGE", "choice", "en", "general", ["en", "pt-BR", "es"]);
        AddSetting(client, "GENERATE_MINUTES", "bool", true, "general");
        AddSetting(client, "CHUNK_SECONDS", "number", 5.0, "segmentation");
        AddSetting(client, "WHISPER_MODEL", "string", "large-v3-turbo", "transcription", applies: "restart");
        client.VocabularyTerms.AddRange(["VozAta", "Avalonia", "WASAPI"]);
        var started = new DateTimeOffset(2026, 10, 16, 9, 0, 0, TimeSpan.Zero);
        client.Sessions.Add(new SessionSummary("20261016_090000", "done", started, started.AddMinutes(42), 2520, "en", true, "Weekly sync", 4, true, "general"));
        AddWeekOfMeetings(client);
        client.Sessions.Add(new SessionSummary("20261015_140000", "done", started.AddDays(-1).AddHours(5), null, 1800, "pt", false));
        client.SearchHits.Add(new SearchHit("20261014_160000", "mic-000003", 312, "mic", "Me", "the design \u0002tokens\u0003 are ready for review"));
        client.SearchHits.Add(new SearchHit("20261016_090000", "mic-000001", 5, "mic", "Me", "shall we start with the design \u0002tokens\u0003?"));
        client.Details["20261016_090000"] = new SessionDetail("20261016_090000", "done", started, started.AddMinutes(42), 2520, "en", true, null, null,
            new Dictionary<string, double> { ["mic"] = 2520, ["system"] = 2520, ["mixed"] = 2520 });
        client.MinutesText["20261016_090000"] = "# Weekly sync\n\n## Decisions\n\n- Ship the design system first.\n- Keep the layout until phase 35.";
        client.Transcripts["20261016_090000"] = new Transcript("raw", [
            new Segment("mic-000001", "mic", "mic", "Me", 5, 9, "Good morning, shall we start with the design tokens?", false, []),
            new Segment("system-000001", "system", "system", "Others", 10, 14, "Yes, the dark theme looks good already.", false, []),
        ]);

        seed?.Invoke(client); // more data for a page's own renders (phase 38: Config)
        var events = new FakeEngineEvents();
        var preferences = new FakePreferences { Data = new UiPreferencesData(Theme: theme) };
        var viewModel = new MainViewModel(
            client, events, new FakeEngineProcess(), new ImmediateDispatcher(), new LocalizationService(),
            new FakeDialogs(), preferences, new FakeClock(), new FakeTimer(), new FakeShell(), new FakeFileSaver(),
            new AvaloniaThemeService(), players: () => new FakeAudioPlayer { Duration = 2520 });
        await viewModel.InitializeAsync();
        events.Send(new ConnectionChangedEvent(true));
        for (var i = 0; i < 200 && viewModel.HandledEvents == 0; i++)
        {
            await Task.Delay(5);
        }

        viewModel.Notifications.Add("Minutes are ready for the session of 16/10/2026 09:00.");
        AddTranscript(viewModel);
        await viewModel.Settings.LoadAsync();
        await viewModel.Vocabulary.LoadAsync();
        await viewModel.History.LoadAsync();
        viewModel.History.Selected = viewModel.History.Rows[0];
        for (var i = 0; i < 200 && viewModel.History.Detail is not { IsLoading: false }; i++)
        {
            await Task.Delay(5);
        }

        return (viewModel, client);
    }

    /// <summary>A week and a bit of meetings for the Meetings page (phase 36): titled and untitled, tags, speakers.</summary>
    private static void AddWeekOfMeetings(FakeEngineClient client)
    {
        (int Day, int Hour, int Minute, int Minutes, string? Title, string Language, string? Template, int Speakers)[] meetings =
        [
            (16, 11, 30, 72, "Client onboarding — Acme", "pt", "client", 3),
            (15, 10, 0, 15, "Daily standup", "en", "daily", 4),
            (14, 16, 0, 55, "Design review — tokens", "en", "general", 2),
            (13, 9, 30, 22, null, "es", null, 0),
            (12, 15, 0, 48, "Retro sprint 41", "pt", "retrospective", 5),
            (8, 10, 0, 31, "1:1 with Ana", "pt", "one_on_one", 2),
            (6, 13, 0, 12, null, "en", null, 0),
        ];
        foreach (var (day, hour, minute, minutes, title, language, template, speakers) in meetings)
        {
            var start = new DateTimeOffset(new DateTime(2026, 10, day, hour, minute, 0, DateTimeKind.Local));
            var id = start.ToString("yyyyMMdd_HHmmss", System.Globalization.CultureInfo.InvariantCulture);
            client.Sessions.Add(new SessionSummary(
                id, "done", start, start.AddMinutes(minutes), minutes * 60.0 + 17, language, title is not null, title, speakers, speakers > 2, template));
        }

        var older = new DateTimeOffset(new DateTime(2026, 9, 22, 10, 0, 0, DateTimeKind.Local));
        client.Sessions.Add(new SessionSummary("20260922_100000", "done", older, older.AddMinutes(40), 2400, "pt", true, "Kick-off"));
    }

    private static void AddTranscript(MainViewModel viewModel)
    {
        viewModel.Recorder.Segments.Add(new TranscriptLine("00:00:05", "Me", "Good morning, shall we start with the design tokens?", "mic"));
        viewModel.Recorder.Segments.Add(new TranscriptLine("00:00:10", "Others", "Yes, the dark theme looks good already.", "system")
        {
            Translation = "Sim, o tema escuro já está bom.",
        });
        viewModel.Recorder.Partials.Add(new TranscriptLine("00:00:15", "Me", "Then the icons and the", "mic"));
    }

    internal static void AddSetting(
        FakeEngineClient client, string key, string type, object? value, string group, string[]? choices = null, string applies = "next_session")
    {
        client.Schema.Add(new SettingSchema(key, type, JsonSerializer.SerializeToElement(value), choices, false, group, applies));
        client.SettingValues[key] = value;
    }
}

internal static class VisualExtensions
{
    public static T GetVisualDescendant<T>(this Visual root)
        where T : Visual =>
        Avalonia.VisualTree.VisualExtensions.GetVisualDescendants(root).OfType<T>().First();
}
