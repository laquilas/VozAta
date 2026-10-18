using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

public sealed class HistoryViewModelTests
{
    private readonly FakeEngineClient _client = new();
    private readonly FakeShell _shell = new();
    private readonly LocalizationService _localization = new();

    private static SessionSummary Session(int day, string status = "done", bool minutes = true, string? language = "pt") =>
        new($"session_{day:000}", status, new DateTimeOffset(2026, 9, 30, 9, 0, 0, TimeSpan.Zero).AddDays(day), null, 3725.6, language, minutes);

    private HistoryViewModel Create() => new(_client, _shell, _localization, new FakeFileSaver());

    private void AddSessions(int count)
    {
        for (var day = count; day >= 1; day--)
        {
            _client.Sessions.Add(Session(day));
            _client.Details[Session(day).Id] = new SessionDetail(Session(day).Id, "done", null, null, 1, "pt", true, [], @"C:\r");
        }
    }

    [Fact]
    public async Task The_first_page_lists_date_duration_language_and_minutes()
    {
        _client.Sessions.Add(Session(16, minutes: false, language: "auto"));
        _client.Sessions.Add(Session(15));
        var history = Create();

        await history.LoadAsync();

        Assert.Equal([(HistoryViewModel.PageSize, 0)], _client.ListRequests);
        var row = history.Rows[0];
        Assert.Equal(SessionDetailViewModel.FormatStart(Session(16).StartedAt), row.Date);
        Assert.Equal(("01:02:05", "Detect automatically", false, false), (row.Duration, row.Language, row.HasMinutes, row.IsLive));
        Assert.Equal("Portuguese", history.Rows[1].Language);
        Assert.False(history.IsEmpty);
        Assert.False(history.CanLoadMore);
    }

    [Fact]
    public async Task More_pages_are_appended_until_every_session_is_listed()
    {
        AddSessions(45);
        var history = Create();

        await history.LoadAsync();
        Assert.True(history.CanLoadMore);
        await history.LoadMoreCommand.ExecuteAsync(null);
        await history.LoadMoreCommand.ExecuteAsync(null);

        Assert.Equal(45, history.Rows.Count);
        Assert.False(history.CanLoadMore);
        Assert.False(history.LoadMoreCommand.CanExecute(null));
        Assert.Equal([(20, 0), (20, 20), (20, 40)], _client.ListRequests);
    }

    [Fact]
    public async Task No_sessions_shows_the_empty_state()
    {
        var history = Create();

        await history.LoadAsync();

        Assert.True(history.IsEmpty);
        Assert.Null(history.Detail);
    }

    [Fact]
    public async Task List_errors_are_shown()
    {
        _client.ListError = new EngineUnavailableException("refused", new HttpRequestException());
        var history = Create();

        await history.LoadAsync();

        Assert.Equal(_localization["EngineUnavailable"], history.Error);
        Assert.False(history.IsEmpty);  // the error explains the empty list
    }

    [Fact]
    public async Task The_live_session_is_marked()
    {
        _client.Sessions.Add(Session(16, status: "recording", minutes: false));
        var history = Create();

        await history.LoadAsync();

        Assert.True(history.Rows[0].IsLive);
    }

    [Fact]
    public async Task Selecting_a_row_loads_its_detail()
    {
        AddSessions(2);
        var history = Create();
        await history.LoadAsync();

        history.Selected = history.Rows[1];
        await history.DetailLoading;

        Assert.Equal(Session(1).Id, history.Detail!.Id);
        Assert.Equal(@"C:\r", history.Detail.Folder);
        history.Selected = null;
        Assert.Null(history.Detail);
    }

    [Fact]
    public async Task Refresh_keeps_the_selected_session_and_its_detail()
    {
        AddSessions(2);
        var history = Create();
        await history.LoadAsync();
        history.Selected = history.Rows[1];
        await history.DetailLoading;
        var detail = history.Detail;
        _client.Sessions.Insert(0, Session(17));
        _client.Details[Session(17).Id] = _client.Details[Session(1).Id] with { Id = Session(17).Id };

        await history.RefreshCommand.ExecuteAsync(null);

        Assert.Equal(3, history.Rows.Count);
        Assert.Equal(Session(1).Id, history.Selected!.Id);
        Assert.Same(detail, history.Detail);
    }

    [Fact]
    public async Task Minutes_events_reach_the_open_detail_and_update_its_row()
    {
        _client.Sessions.Add(Session(16, minutes: false));
        _client.Details[Session(16).Id] = new SessionDetail(Session(16).Id, "done", null, null, 1, "pt", false, [], @"C:\r");
        _client.Transcripts[Session(16).Id] = new Transcript("raw", [new Segment("mic-000001", "mic", "mic", "Me", 1, 2, "Hi.", false, [])]);
        var history = Create();
        await history.LoadAsync();
        history.Selected = history.Rows[0];
        await history.DetailLoading;
        await history.Detail!.RegenerateMinutesCommand.ExecuteAsync(null);
        _client.MinutesText[Session(16).Id] = "# Minutes";
        _client.Sessions[0] = Session(16, minutes: true);

        await history.OnMinutesReadyAsync(Session(16).Id);

        Assert.True(history.Detail.HasMinutes);
        Assert.False(history.Detail.IsBusy);
        Assert.True(history.Rows[0].HasMinutes);
        await history.Detail.RegenerateMinutesCommand.ExecuteAsync(null);
        history.OnError(Session(16).Id, "Ollama is offline.");
        Assert.Equal("Ollama is offline.", history.Detail.Error);
    }

    [Fact]
    public async Task Events_without_an_open_detail_are_harmless()
    {
        var history = Create();
        await history.LoadAsync();

        await history.OnMinutesReadyAsync("x");
        await history.OnSpeakersRelabeledAsync("x");
        history.OnError("x", "message");

        Assert.Null(history.Detail);
    }

    [Fact]
    public async Task Row_texts_follow_the_ui_language()
    {
        _client.Sessions.Add(Session(16));
        var history = Create();
        await history.LoadAsync();

        _localization.SetLanguage("es");
        history.RefreshTexts();

        Assert.Equal("Portugués", history.Rows[0].Language);
    }

    [Fact]
    public async Task Rows_read_well_for_screen_readers()
    {
        _client.Sessions.Add(Session(16));
        var history = Create();
        await history.LoadAsync();

        var row = history.Rows[0];
        Assert.Equal($"{row.Date}, 01:02:05, Portuguese", row.ToString());
        Assert.Equal("JBL Quantum Stream", new AudioDevice(4, "JBL Quantum Stream", 48000, 1).ToString());
        Assert.Equal((null, false), (row.Title, row.HasTitle));
    }

    [Fact]
    public async Task A_titled_meeting_shows_its_title_in_the_list()
    {
        _client.Sessions.Add(Session(16) with { Title = "Budget review" });
        var history = Create();
        await history.LoadAsync();

        var row = history.Rows[0];
        Assert.Equal(("Budget review", true), (row.Title, row.HasTitle));
        Assert.Equal($"Budget review, {row.Date}, 01:02:05, Portuguese", row.ToString());
    }
}
