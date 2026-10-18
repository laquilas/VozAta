using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>Phase 37: a meeting opens as its own page in the shell; search and citations play its moment.</summary>
public sealed class SessionNavigationTests : IDisposable
{
    private const string Id = "20261016_090000";

    private readonly FakeEngineClient _client = new();
    private readonly FakeEngineEvents _events = new();
    private readonly FakeDialogs _dialogs = new();
    private readonly LocalizationService _localization = new();
    private readonly FakeAudioPlayer _player = new() { Duration = 600 };

    public SessionNavigationTests()
    {
        var started = new DateTimeOffset(2026, 10, 16, 9, 0, 0, TimeSpan.Zero);
        _client.Sessions.Add(new SessionSummary(Id, "done", started, null, 600, "en", false, "Weekly sync"));
        _client.Details[Id] = new SessionDetail(Id, "done", started, null, 600, "en", false, null, null,
            new Dictionary<string, double> { ["mixed"] = 600 });
        _client.Transcripts[Id] = new Transcript("raw",
        [
            new Segment("mic-000001", "mic", "mic", "Me", 5, 9, "Hello.", false, []),
            new Segment("mic-000002", "mic", "mic", "Me", 300, 301, "Later.", false, []),
        ]);
    }

    public void Dispose() => _player.Dispose();

    private MainViewModel Create(bool players = true) =>
        new(_client, _events, new FakeEngineProcess(), new ImmediateDispatcher(), _localization, _dialogs,
            new FakePreferences(), new FakeClock(), new FakeTimer(), new FakeShell(), new FakeFileSaver(),
            new FakeThemeService(), players: players ? () => _player : null, engineUri: new Uri("http://127.0.0.1:9000/"));

    private static async Task OpenAsync(MainViewModel viewModel)
    {
        await viewModel.History.LoadAsync();
        viewModel.History.Selected = viewModel.History.Rows[0];
        await viewModel.History.DetailLoading;
    }

    [Fact]
    public async Task Opening_a_meeting_shows_its_page_and_back_shows_the_list()
    {
        var viewModel = Create();

        await OpenAsync(viewModel);

        var page = Assert.IsType<SessionPageViewModel>(viewModel.Shell.CurrentPage);
        Assert.Equal(ShellViewModel.Meetings, viewModel.Shell.CurrentItem.Key);
        Assert.NotNull(page.Player);
        await page.BackCommand.ExecuteAsync(null);

        Assert.Same(viewModel.Meetings, viewModel.Shell.CurrentPage);
        Assert.Null(viewModel.History.Detail);
        Assert.True(_player.Disposed);
    }

    [Fact]
    public async Task The_player_streams_the_engine_track_url()
    {
        var viewModel = Create();
        await OpenAsync(viewModel);

        await viewModel.History.Detail!.Player!.PlayPauseCommand.ExecuteAsync(null);

        Assert.Equal(new Uri("http://127.0.0.1:9000/sessions/20261016_090000/audio/mixed"), _player.Opened);
        Assert.Equal(new Uri("http://127.0.0.1:8765/sessions/a%20b/audio/mic"), MainViewModel.AudioUri(null, "a b", "mic"));
    }

    [Fact]
    public async Task Without_a_player_factory_the_page_has_no_player()
    {
        var viewModel = Create(players: false);

        await OpenAsync(viewModel);

        Assert.Null(viewModel.History.Detail!.Player);
    }

    [Fact]
    public async Task Another_page_from_the_sidebar_closes_the_meeting()
    {
        var viewModel = Create();
        await OpenAsync(viewModel);

        viewModel.Shell.NavigateCommand.Execute(ShellViewModel.Ask);
        await viewModel.SessionClosing;

        Assert.IsType<AskPageViewModel>(viewModel.Shell.CurrentPage);
        Assert.Null(viewModel.History.Detail);
        viewModel.Shell.NavigateCommand.Execute(ShellViewModel.Meetings); // no meeting open: nothing to close
        Assert.Same(viewModel.Meetings, viewModel.Shell.CurrentPage);
    }

    [Fact]
    public async Task Unsaved_edits_kept_by_the_user_bring_the_meeting_back()
    {
        var viewModel = Create();
        await OpenAsync(viewModel);
        var page = viewModel.History.Detail!;
        page.Editor.EditCommand.Execute(null);
        page.Editor.Segments[0].Text = "Changed.";
        _dialogs.Answer = false; // "keep editing"

        viewModel.Shell.NavigateCommand.Execute(ShellViewModel.Config);
        await viewModel.SessionClosing;

        Assert.Same(page, viewModel.Shell.CurrentPage);
        Assert.Same(page, viewModel.History.Detail);
    }

    [Fact]
    public async Task A_search_hit_opens_the_meeting_at_its_moment()
    {
        var viewModel = Create();
        await viewModel.History.LoadAsync();

        await viewModel.History.OpenHitAsync(new SearchHit(Id, "mic-000002", 300, "mic", "Me", "later"));
        await viewModel.History.DetailLoading;

        var page = Assert.IsType<SessionPageViewModel>(viewModel.Shell.CurrentPage);
        Assert.Equal("mic-000002", page.FocusedLine!.SegmentId);
        Assert.Equal(300, page.Player!.Position);
        Assert.Equal("mic-000002", page.CurrentLine!.SegmentId);
    }

    [Fact]
    public async Task A_citation_on_the_ask_page_opens_the_meeting_at_its_moment()
    {
        var viewModel = Create();
        await viewModel.History.LoadAsync();
        var ask = Assert.IsType<AskPageViewModel>(viewModel.Shell.Pages.Single(item => item.Key == ShellViewModel.Ask).Page);
        viewModel.Shell.NavigateCommand.Execute(ShellViewModel.Ask);

        await ask.Ask.OpenCitation!(new Citation(Id, "mic-000002", 300));
        await viewModel.History.DetailLoading;

        var page = Assert.IsType<SessionPageViewModel>(viewModel.Shell.CurrentPage);
        Assert.Equal(300, page.Player!.Position);
    }

    [Fact]
    public async Task Renaming_and_deleting_on_the_page_go_through_the_meetings_list()
    {
        var viewModel = Create();
        await viewModel.Meetings.LoadAsync();
        await OpenAsync(viewModel);
        var page = viewModel.History.Detail!;

        page.BeginRenameCommand.Execute(null);
        page.TitleDraft = "Renamed sync";
        await page.SaveRenameCommand.ExecuteAsync(null);
        Assert.Contains(viewModel.Meetings.Weeks.SelectMany(week => week.Days).SelectMany(day => day.Rows),
            row => row.Summary.Title == "Renamed sync");

        await page.DeleteCommand.ExecuteAsync(null);
        await viewModel.Meetings.PendingDelete;

        Assert.Single(_dialogs.Asked);
        Assert.Null(viewModel.History.Detail);
        Assert.Same(viewModel.Meetings, viewModel.Shell.CurrentPage);
    }

    [Fact]
    public async Task Answers_reach_the_ask_tab_of_the_open_meeting()
    {
        var viewModel = Create();
        await viewModel.InitializeAsync();
        await OpenAsync(viewModel);
        var ask = viewModel.History.Detail!.Ask;
        ask.Question = "What was decided?";
        await ask.AskCommand.ExecuteAsync(null);
        var answerId = _client.NextAnswerId;

        _events.Send(new AnswerChunkEvent(Id, answerId, "Ship it."));
        _events.Send(new AnswerDoneEvent(Id, answerId, [], null));
        for (var i = 0; i < 200 && ask.IsAsking; i++)
        {
            await Task.Delay(5);
        }

        Assert.Equal("Ship it.", ask.Answer);
        Assert.False(ask.IsAsking);
    }

    [Fact]
    public async Task The_player_texts_follow_the_language()
    {
        var viewModel = Create();
        await OpenAsync(viewModel);

        viewModel.SelectedAppLanguage = viewModel.AppLanguages.Single(option => option.Value == "es");

        Assert.Equal(_localization["PlayerPlay"], viewModel.History.Detail!.Player!.PlayPauseText);
    }
}
