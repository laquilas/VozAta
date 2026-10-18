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
    private static readonly Lazy<HeadlessUnitTestSession> Session =
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
                var viewModel = await SeededAsync(theme);
                Assert.Equal(theme == "dark" ? "Dark" : "Light", Application.Current!.ActualThemeVariant.ToString());
                Render<RecorderPage>(viewModel, ShellViewModel.Recorder, $"recorder-idle-{theme}.png");
                Render<HistoryView>(viewModel, ShellViewModel.Meetings, $"meetings-minutes-{theme}.png");
                viewModel.History.Detail!.SelectedTab = 1;
                Render<HistoryView>(viewModel, ShellViewModel.Meetings, $"meetings-transcript-{theme}.png");
                Render<AskView>(viewModel, ShellViewModel.Ask, $"ask-{theme}.png");
                Render<SettingsView>(viewModel, ShellViewModel.Config, $"config-{theme}.png");

                // Start goes to the fake engine only: no audio is captured.
                viewModel.Recorder.Title = "Weekly design review";
                await viewModel.Recorder.StartCommand.ExecuteAsync(null);
                Assert.True(viewModel.Recorder.IsRecording);
                viewModel.Recorder.Handle(new StatusEvent("20261016_090000", "recording", 754));
                AddTranscript(viewModel);
                Render<RecorderPage>(viewModel, ShellViewModel.Recorder, $"recorder-recording-{theme}.png");
                Render<HistoryView>(viewModel, ShellViewModel.Meetings, $"meetings-while-recording-{theme}.png");
                viewModel.Shell.ToggleSidebarCommand.Execute(null);
                Render<RecorderPage>(viewModel, ShellViewModel.Recorder, $"recorder-recording-collapsed-{theme}.png");
                viewModel.Shell.ToggleSidebarCommand.Execute(null);
                return 9;
            },
            CancellationToken.None);

        Assert.Equal(9, rendered);
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
    private static void Render<TView>(MainViewModel viewModel, string page, string name)
        where TView : Control
    {
        viewModel.Shell.NavigateCommand.Execute(page);
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
    private static async Task<MainViewModel> SeededAsync(string theme)
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
        client.Sessions.Add(new SessionSummary("20261016_090000", "done", started, started.AddMinutes(42), 2520, "en", true, "Weekly sync"));
        client.Sessions.Add(new SessionSummary("20261015_140000", "done", started.AddDays(-1).AddHours(5), null, 1800, "pt", false));
        client.Details["20261016_090000"] = new SessionDetail("20261016_090000", "done", started, started.AddMinutes(42), 2520, "en", true, [], @"C:\recordings\20261016_090000");
        client.MinutesText["20261016_090000"] = "# Weekly sync\n\n## Decisions\n\n- Ship the design system first.\n- Keep the layout until phase 35.";
        client.Transcripts["20261016_090000"] = new Transcript("raw", [
            new Segment("mic-000001", "mic", "mic", "Me", 5, 9, "Good morning, shall we start with the design tokens?", false, []),
            new Segment("system-000001", "system", "system", "Others", 10, 14, "Yes, the dark theme looks good already.", false, []),
        ]);

        var events = new FakeEngineEvents();
        var preferences = new FakePreferences { Data = new UiPreferencesData(Theme: theme) };
        var viewModel = new MainViewModel(
            client, events, new FakeEngineProcess(), new ImmediateDispatcher(), new LocalizationService(),
            new FakeDialogs(), preferences, new FakeClock(), new FakeTimer(), new FakeShell(), new FakeFileSaver(),
            new AvaloniaThemeService());
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

        return viewModel;
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

    private static void AddSetting(
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
