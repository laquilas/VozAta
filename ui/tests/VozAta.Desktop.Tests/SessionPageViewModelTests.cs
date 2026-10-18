using System.Net;
using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

public sealed class SessionPageViewModelTests : IDisposable
{
    private const string Id = "20261016_090000";
    private const string Folder = @"C:\VozAta\recordings\20261016_090000";

    private readonly FakeEngineClient _client = new();
    private readonly FakeShell _shell = new();
    private readonly LocalizationService _localization = new();
    private readonly FakeFileSaver _saver = new();
    private readonly string _audioFolder = Path.Combine(Path.GetTempPath(), "VozAta.Tests", Guid.NewGuid().ToString("N"));

    public void Dispose()
    {
        if (Directory.Exists(_audioFolder))
        {
            Directory.Delete(_audioFolder, recursive: true);
        }
    }

    public SessionPageViewModelTests()
    {
        _client.Details[Id] = Detail(["mic.wav", "mixed.wav", "session.json", "system.wav", "transcript.jsonl"]);
        _client.Transcripts[Id] = new Transcript("raw",
        [
            new Segment("mic-000001", "mic", "mic", "Me", 2.4, 4, "Good morning.", false, []),
            new Segment("system-000001", "system", "system", "Others", 65, 66, "Hi.", false, []),
        ]);
        _client.MinutesText[Id] = "## Summary\nShort meeting.\n\n- Ship it";
    }

    private static SessionSummary Summary(string status = "done") =>
        new(Id, status, new DateTimeOffset(2026, 10, 16, 9, 0, 0, TimeSpan.Zero), null, 75, "pt", true);

    private static SessionDetail Detail(IReadOnlyList<string> files) =>
        new(Id, "done", null, null, 75, "pt", true, files, Folder, new Dictionary<string, double> { ["mic"] = 75, ["system"] = 75, ["mixed"] = 75 });

    private SessionPageViewModel Create(string status = "done") =>
        new(_client, _shell, _localization, _saver, Summary(status), audioFolder: _audioFolder);

    [Fact]
    public async Task Loading_fills_the_transcript_and_the_minutes()
    {
        var detail = Create();

        await detail.LoadAsync();

        Assert.Equal(
            [new TranscriptLine("00:00:02", "Me", "Good morning.", "mic") { SegmentId = "mic-000001", Start = 2.4 },
             new TranscriptLine("00:01:05", "Others", "Hi.", "system") { SegmentId = "system-000001", Start = 65 }],
            detail.Lines);
        Assert.True(detail.HasMinutes);
        Assert.Equal(
            [new MarkdownBlock(MarkdownBlockKind.Heading2, "Summary"), new MarkdownBlock(MarkdownBlockKind.Paragraph, "Short meeting."), new MarkdownBlock(MarkdownBlockKind.Bullet, "Ship it")],
            detail.Blocks);
        Assert.False(detail.IsLoading);
        Assert.Null(detail.Error);
    }

    [Fact]
    public async Task A_session_without_minutes_or_transcript_shows_empty_states()
    {
        _client.MinutesText.Clear();
        _client.Transcripts.Clear();
        var detail = Create();

        await detail.LoadAsync();

        Assert.False(detail.HasMinutes);
        Assert.Empty(detail.Blocks);
        Assert.Empty(detail.Lines);
        Assert.False(detail.RegenerateMinutesCommand.CanExecute(null));  // nothing to summarize
    }

    [Fact]
    public async Task Load_errors_are_shown_in_the_detail()
    {
        _client.DetailError = new EngineUnavailableException("refused", new HttpRequestException());
        var detail = Create();

        await detail.LoadAsync();

        Assert.Equal(_localization["EngineUnavailable"], detail.Error);
        Assert.False(detail.IsLoading);
        Assert.False(detail.OpenFolderCommand.CanExecute(null));
    }

    [Fact]
    public async Task Regenerating_stays_busy_until_minutes_ready_then_reloads_them()
    {
        _client.MinutesText.Clear();
        var detail = Create();
        await detail.LoadAsync();

        await detail.RegenerateMinutesCommand.ExecuteAsync(null);
        Assert.Equal([Id], _client.Regenerated);
        Assert.True(detail.IsBusy);
        Assert.False(detail.RegenerateMinutesCommand.CanExecute(null));

        await detail.OnMinutesReadyAsync("another-session");
        Assert.True(detail.IsBusy);
        _client.MinutesText[Id] = "# New minutes";
        await detail.OnMinutesReadyAsync(Id);

        Assert.False(detail.IsBusy);
        Assert.True(detail.HasMinutes);
        Assert.Equal([new MarkdownBlock(MarkdownBlockKind.Heading1, "New minutes")], detail.Blocks);
    }

    [Fact]
    public async Task Speakers_relabeled_reloads_only_our_transcript()
    {
        var detail = Create();
        await detail.LoadAsync();
        _client.Transcripts[Id] = new Transcript(
            "diarized", [new Segment("system-000001", "system", "system:1", "User 1", 65, 66, "Hi.", false, [])]);

        await detail.OnSpeakersRelabeledAsync("another-session");
        Assert.Equal("Others", detail.Lines[^1].Label);
        await detail.OnSpeakersRelabeledAsync(Id);

        Assert.Equal([new TranscriptLine("00:01:05", "User 1", "Hi.", "system") { SegmentId = "system-000001", Start = 65 }], detail.Lines);
        Assert.Null(detail.Error);
    }

    [Fact]
    public async Task A_failed_reload_after_relabeling_shows_the_error()
    {
        var detail = Create();
        await detail.LoadAsync();
        _client.TranscriptError = new EngineApiException(System.Net.HttpStatusCode.NotFound, "session_not_found", "Gone.");

        await detail.OnSpeakersRelabeledAsync(Id);

        Assert.Equal("Gone.", detail.Error);
    }

    [Fact]
    public async Task A_failed_regeneration_reports_the_engine_error()
    {
        var detail = Create();
        await detail.LoadAsync();
        await detail.RegenerateMinutesCommand.ExecuteAsync(null);

        detail.OnError("another-session", "ignored");
        Assert.True(detail.IsBusy);
        detail.OnError(Id, "Ollama is offline.");

        Assert.False(detail.IsBusy);
        Assert.Equal("Ollama is offline.", detail.Error);
        Assert.True(detail.HasMinutes);  // the old minutes stay
    }

    [Fact]
    public async Task A_rejected_regenerate_request_is_shown_at_once()
    {
        _client.RegenerateError = FakeEngineClient.ApiError("session_active", "The session is still recording.");
        var detail = Create();
        await detail.LoadAsync();

        await detail.RegenerateMinutesCommand.ExecuteAsync(null);

        Assert.False(detail.IsBusy);
        Assert.Equal("The session is still recording.", detail.Error);
    }

    [Fact]
    public async Task A_live_session_cannot_regenerate_minutes()
    {
        var detail = Create(status: "recording");
        await detail.LoadAsync();

        Assert.True(detail.IsLive);
        Assert.False(detail.RegenerateMinutesCommand.CanExecute(null));
    }

    [Fact]
    public async Task The_folder_opens_with_the_shell()
    {
        var detail = Create();
        await detail.LoadAsync();

        detail.OpenFolderCommand.Execute(null);

        Assert.Equal([Folder], _shell.Opened);
    }

    [Fact]
    public async Task A_track_is_downloaded_from_the_engine_then_opened_in_the_player()
    {
        var detail = Create();
        await detail.LoadAsync();

        await detail.OpenAudioCommand.ExecuteAsync("mixed");
        await detail.OpenAudioCommand.ExecuteAsync("system");

        var mixed = Path.Combine(_audioFolder, $"{Id}-mixed.wav");
        var system = Path.Combine(_audioFolder, $"{Id}-system.wav");
        Assert.Equal([(Id, "mixed"), (Id, "system")], _client.AudioDownloads);
        Assert.Equal([mixed, system], _shell.Opened);
        Assert.Equal("RIFF"u8.ToArray(), await File.ReadAllBytesAsync(mixed));
        Assert.Null(detail.Error);
    }

    [Fact]
    public async Task A_track_still_open_in_the_player_is_opened_again_without_downloading()
    {
        var detail = Create();
        await detail.LoadAsync();
        Directory.CreateDirectory(_audioFolder);
        var path = Path.Combine(_audioFolder, $"{Id}-mic.wav");
        await File.WriteAllBytesAsync(path, [1]);
        using (new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
        {
            await detail.OpenAudioCommand.ExecuteAsync("mic");
        }

        Assert.Empty(_client.AudioDownloads);
        Assert.Equal([path], _shell.Opened);
    }

    [Fact]
    public async Task A_failed_download_shows_the_error_and_leaves_no_partial_file()
    {
        _client.AudioError = new EngineApiException(HttpStatusCode.NotFound, "audio_not_found", "No audio.");
        var detail = Create();
        await detail.LoadAsync();

        await detail.OpenAudioCommand.ExecuteAsync("mic");

        Assert.Equal("No audio.", detail.Error);
        Assert.Empty(_shell.Opened);
        Assert.False(File.Exists(Path.Combine(_audioFolder, $"{Id}-mic.wav")));
    }

    [Fact]
    public async Task An_unreachable_engine_is_reported_when_playing()
    {
        _client.AudioError = new EngineUnavailableException("down", new HttpRequestException());
        var detail = Create();
        await detail.LoadAsync();

        await detail.OpenAudioCommand.ExecuteAsync("system");

        Assert.Equal(_localization["EngineUnavailable"], detail.Error);
    }

    [Fact]
    public async Task Tracks_without_audio_cannot_be_played_and_a_sqlite_session_has_no_folder()
    {
        _client.Details[Id] = new SessionDetail(Id, "done", null, null, 75, "pt", true, null, null, new Dictionary<string, double> { ["mic"] = 75 });
        var detail = Create();
        Assert.False(detail.OpenAudioCommand.CanExecute("mic")); // before loading
        await detail.LoadAsync();

        Assert.True(detail.OpenAudioCommand.CanExecute("mic"));
        Assert.False(detail.OpenAudioCommand.CanExecute("mixed"));
        Assert.False(detail.OpenAudioCommand.CanExecute(null));
        Assert.False(detail.OpenFolderCommand.CanExecute(null));
    }

    [Fact]
    public async Task An_old_engine_without_the_audio_field_plays_nothing()
    {
        _client.Details[Id] = new SessionDetail(Id, "done", null, null, 75, "pt", true, ["mic.wav"], Folder);
        var detail = Create();
        await detail.LoadAsync();

        Assert.False(detail.OpenAudioCommand.CanExecute("mic"));
    }

    [Fact]
    public void The_title_shows_the_local_start_time()
    {
        var detail = Create();

        Assert.Equal(Summary().StartedAt!.Value.ToLocalTime().ToString("yyyy-MM-dd HH:mm", System.Globalization.CultureInfo.InvariantCulture), detail.Title);
        Assert.Equal(detail.Title, detail.Date);
        Assert.False(detail.ShowsDate);
        Assert.Equal(Id, detail.Id);
    }

    [Fact]
    public void A_titled_meeting_shows_its_title_with_the_date_under_it()
    {
        var detail = new SessionPageViewModel(_client, _shell, _localization, _saver, Summary() with { Title = "Budget review" });

        Assert.Equal("Budget review", detail.Title);
        Assert.Equal(Summary().StartedAt!.Value.ToLocalTime().ToString("yyyy-MM-dd HH:mm", System.Globalization.CultureInfo.InvariantCulture), detail.Date);
        Assert.True(detail.ShowsDate);
    }

    [Theory]
    [InlineData("md", "Markdown")]
    [InlineData("docx", "Word document")]
    [InlineData("pdf", "PDF document")]
    public async Task Export_downloads_the_format_and_saves_where_the_user_chooses(string format, string typeName)
    {
        var detail = Create();
        await detail.LoadAsync();

        await detail.ExportCommand.ExecuteAsync(format);

        Assert.Equal((Id, format), _client.Exports.Single());
        var (name, type, extension, content) = _saver.Saves.Single();
        Assert.Equal(($"{Id}-minutes.{format}", typeName, format), (name, type, extension));
        Assert.Equal([1, 2, 3], content);
        Assert.Equal(@"Saved to C:\Users\me\Documents\minutes.pdf", detail.Message);
        Assert.False(detail.IsExporting);
    }

    [Fact]
    public async Task A_cancelled_save_says_nothing()
    {
        _saver.Path = null;
        var detail = Create();

        await detail.ExportCommand.ExecuteAsync("pdf");

        Assert.Null(detail.Message);
        Assert.Null(detail.Error);
    }

    [Fact]
    public async Task Export_errors_are_shown()
    {
        _client.ExportError = FakeEngineClient.ApiError("session_not_found", "Session was not found.");
        var detail = Create();

        await detail.ExportCommand.ExecuteAsync("docx");

        Assert.Equal("Session was not found.", detail.Error);
        Assert.Empty(_saver.Saves);
    }

    [Fact]
    public void Live_sessions_and_unknown_formats_cannot_be_exported()
    {
        Assert.False(Create(status: "recording").ExportCommand.CanExecute("pdf"));
        Assert.False(Create().ExportCommand.CanExecute("odt"));
        Assert.False(Create().ExportCommand.CanExecute(null));
        Assert.True(Create().ExportCommand.CanExecute("md"));
    }
}
