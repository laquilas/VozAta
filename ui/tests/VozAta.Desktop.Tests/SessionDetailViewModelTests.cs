using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

public sealed class SessionDetailViewModelTests
{
    private const string Id = "20261016_090000";
    private const string Folder = @"C:\VozAta\recordings\20261016_090000";

    private readonly FakeEngineClient _client = new();
    private readonly FakeShell _shell = new();
    private readonly LocalizationService _localization = new();
    private readonly FakeFileSaver _saver = new();

    public SessionDetailViewModelTests()
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
        new(Id, "done", null, null, 75, "pt", true, files, Folder);

    private SessionDetailViewModel Create(string status = "done") => new(_client, _shell, _localization, _saver, Summary(status));

    [Fact]
    public async Task Loading_fills_the_transcript_and_the_minutes()
    {
        var detail = Create();

        await detail.LoadAsync();

        Assert.Equal(
            [new TranscriptLine("00:00:02", "Me", "Good morning.", "mic"), new TranscriptLine("00:01:05", "Others", "Hi.", "system")],
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
    public async Task Folder_and_audio_open_with_the_shell()
    {
        var detail = Create();
        await detail.LoadAsync();

        detail.OpenFolderCommand.Execute(null);
        detail.OpenAudioCommand.Execute("mixed");
        detail.OpenAudioCommand.Execute("system");

        Assert.Equal([Folder, Path.Combine(Folder, "mixed.wav"), Path.Combine(Folder, "system.wav")], _shell.Opened);
    }

    [Fact]
    public async Task Missing_audio_files_cannot_be_opened()
    {
        _client.Details[Id] = Detail(["session.json"]);
        var detail = Create();
        await detail.LoadAsync();

        Assert.False(detail.OpenAudioCommand.CanExecute("mixed"));
        Assert.False(detail.OpenAudioCommand.CanExecute(null));
        Assert.True(detail.OpenFolderCommand.CanExecute(null));
    }

    [Fact]
    public void The_title_shows_the_local_start_time()
    {
        var detail = Create();

        Assert.Equal(Summary().StartedAt!.Value.ToLocalTime().ToString("yyyy-MM-dd HH:mm", System.Globalization.CultureInfo.InvariantCulture), detail.Title);
        Assert.Equal(Id, detail.Id);
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
