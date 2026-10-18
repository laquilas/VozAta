using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>The session page of phase 37: player, line sync, title, delete, back and Ask.</summary>
public sealed class SessionPagePlayerTests : IDisposable
{
    private const string Id = "20261016_090000";

    private readonly FakeEngineClient _client = new();
    private readonly LocalizationService _localization = new();
    private readonly FakeAudioPlayer _player = new() { Duration = 75 };
    private readonly List<string> _actions = [];

    public SessionPagePlayerTests()
    {
        _client.Details[Id] = Detail(new Dictionary<string, double> { ["mic"] = 75, ["system"] = 75, ["mixed"] = 75 });
        _client.Transcripts[Id] = new Transcript("raw",
        [
            new Segment("mic-000001", "mic", "mic", "Me", 2.4, 4, "Good morning.", false, []),
            new Segment("system-000001", "system", "system", "Others", 10, 12, "Hi.", false, []),
            new Segment("mic-000002", "mic", "mic", "Me", 30, 31, "Bye.", false, []),
        ]);
    }

    public void Dispose() => _player.Dispose();

    private static SessionDetail Detail(IReadOnlyDictionary<string, double>? audio) =>
        new(Id, "done", null, null, 75, "pt", false, null, null, audio);

    private SessionPageViewModel Create(string status = "done", string? title = null) =>
        new(_client, new FakeShell(), _localization, new FakeFileSaver(),
            new SessionSummary(Id, status, new DateTimeOffset(2026, 10, 16, 9, 0, 0, TimeSpan.Zero), null, 75, "pt", false, title))
        {
            Players = (id, tracks) => new PlayerBarViewModel(
                _player, new ImmediateDispatcher(), track => new Uri($"http://engine/sessions/{id}/audio/{track}"), tracks, _localization),
            Renamed = summary =>
            {
                _actions.Add($"renamed {summary.Title}");
                return Task.CompletedTask;
            },
            DeleteMeeting = summary =>
            {
                _actions.Add($"delete {summary.Id}");
                return Task.CompletedTask;
            },
            GoBack = () =>
            {
                _actions.Add("back");
                return Task.CompletedTask;
            },
        };

    [Fact]
    public async Task A_recorded_session_gets_a_player_with_its_tracks()
    {
        var page = Create();

        await page.LoadAsync();

        Assert.NotNull(page.Player);
        Assert.Equal(["mixed", "mic", "system"], page.Player.Tracks.Select(track => track.Value));
        Assert.Equal("00:01:15", page.Duration);
    }

    [Fact]
    public async Task A_live_session_or_one_without_audio_has_no_player()
    {
        var live = Create("recording");
        await live.LoadAsync();
        _client.Details[Id] = Detail(null);
        var silent = Create();
        await silent.LoadAsync();
        var noFactory = new SessionPageViewModel(_client, new FakeShell(), _localization, new FakeFileSaver(),
            new SessionSummary(Id, "done", null, null, 75, "pt", false));
        _client.Details[Id] = Detail(new Dictionary<string, double> { ["mixed"] = 75 });
        await noFactory.LoadAsync();

        Assert.Null(live.Player);
        Assert.Null(silent.Player);
        Assert.Null(noFactory.Player);
    }

    [Fact]
    public async Task Clicking_a_line_plays_from_its_start()
    {
        var page = Create();
        await page.LoadAsync();

        await page.PlayLineCommand.ExecuteAsync(page.Lines[1]);

        Assert.Equal(["open http://engine/sessions/20261016_090000/audio/mixed", "seek 10", "play"], _player.Calls);
        await page.PlayLineCommand.ExecuteAsync(null); // nothing happens
        Assert.Equal(3, _player.Calls.Count);
    }

    [Fact]
    public async Task The_highlight_follows_the_playback_position()
    {
        var page = Create();
        await page.LoadAsync();
        await page.Player!.PlayPauseCommand.ExecuteAsync(null);

        _player.Advance(1);
        Assert.Null(page.CurrentLine);
        _player.Advance(3);
        Assert.Equal("mic-000001", page.CurrentLine!.SegmentId);
        Assert.True(page.Lines[0].IsCurrent);
        _player.Advance(3.5); // same line: nothing changes
        _player.Advance(15);
        Assert.Equal("system-000001", page.CurrentLine!.SegmentId);
        Assert.Equal([false, true, false], page.Lines.Select(line => line.IsCurrent));
        _player.Advance(0); // back before the first line
        Assert.Null(page.CurrentLine);
        Assert.All(page.Lines, line => Assert.False(line.IsCurrent));
    }

    [Fact]
    public async Task A_cue_before_loading_waits_for_the_player_and_then_shows_the_moment()
    {
        var page = Create();

        page.CueAt(30);
        await page.LoadAsync();

        Assert.Equal(30, page.Player!.Position);
        Assert.Equal("mic-000002", page.CurrentLine!.SegmentId);
        Assert.Empty(_player.Calls); // shown, not played
        page.CueAt(10);
        Assert.Equal(10, page.Player.Position);
    }

    [Fact]
    public async Task Renaming_saves_the_title_and_tells_the_list()
    {
        var page = Create();
        await page.LoadAsync();

        page.BeginRenameCommand.Execute(null);
        Assert.True(page.IsEditingTitle);
        Assert.Equal("", page.TitleDraft);
        page.TitleDraft = "  Weekly sync ";
        await page.SaveRenameCommand.ExecuteAsync(null);

        Assert.False(page.IsEditingTitle);
        Assert.Equal("Weekly sync", page.Title);
        Assert.True(page.ShowsDate);
        Assert.Equal([(Id, "Weekly sync")], _client.TitleUpdates);
        Assert.Equal(["renamed Weekly sync"], _actions);
        Assert.Equal("Weekly sync", page.Summary.Title);
    }

    [Fact]
    public async Task An_unchanged_title_or_a_cancel_saves_nothing()
    {
        var page = Create(title: "Daily");

        await page.SaveRenameCommand.ExecuteAsync(null); // not editing
        page.BeginRenameCommand.Execute(null);
        Assert.Equal("Daily", page.TitleDraft);
        await page.SaveRenameCommand.ExecuteAsync(null);
        page.BeginRenameCommand.Execute(null);
        page.CancelRenameCommand.Execute(null);

        Assert.False(page.IsEditingTitle);
        Assert.Empty(_client.TitleUpdates);
    }

    [Fact]
    public async Task A_failed_rename_keeps_the_box_open_with_the_error()
    {
        _client.TitleError = FakeEngineClient.ApiError("invalid_title", "Too long.");
        var page = Create();

        page.BeginRenameCommand.Execute(null);
        page.TitleDraft = "x";
        await page.SaveRenameCommand.ExecuteAsync(null);

        Assert.True(page.IsEditingTitle);
        Assert.Equal("Too long.", page.Error);
        Assert.Empty(_actions);
    }

    [Fact]
    public async Task Clearing_the_title_makes_it_untitled_without_a_listener()
    {
        var page = new SessionPageViewModel(_client, new FakeShell(), _localization, new FakeFileSaver(),
            new SessionSummary(Id, "done", null, null, 75, "pt", false, "Old"));

        page.BeginRenameCommand.Execute(null);
        page.TitleDraft = " ";
        await page.SaveRenameCommand.ExecuteAsync(null);

        Assert.Equal([(Id, (string?)null)], _client.TitleUpdates);
        Assert.False(page.ShowsDate);
        Assert.Equal(Id, page.Title); // no start date: the id
    }

    [Fact]
    public async Task Delete_and_back_go_to_the_meetings_page()
    {
        var page = Create();

        await page.DeleteCommand.ExecuteAsync(null);
        await page.BackCommand.ExecuteAsync(null);

        Assert.Equal([$"delete {Id}", "back"], _actions);
        Assert.False(Create("recording").DeleteCommand.CanExecute(null));
        var bare = new SessionPageViewModel(_client, new FakeShell(), _localization, new FakeFileSaver(),
            new SessionSummary(Id, "done", null, null, 75, "pt", false));
        Assert.False(bare.DeleteCommand.CanExecute(null));
        await bare.BackCommand.ExecuteAsync(null); // no listener: nothing happens
    }

    [Fact]
    public async Task The_ask_tab_is_scoped_to_the_meeting_and_a_citation_shows_its_moment()
    {
        var page = Create();
        await page.LoadAsync();

        Assert.Equal(Id, page.Ask.Scope);
        await page.Ask.OpenCitation!(new Citation(Id, "mic-000002", 30));

        Assert.Equal(SessionPageViewModel.TranscriptTab, page.SelectedTab);
        Assert.Equal("mic-000002", page.FocusedLine!.SegmentId);
        Assert.Equal(30, page.Player!.Position);
        Assert.Same(page.Ask, page.Ask);
    }

    [Fact]
    public async Task Dispose_releases_the_player()
    {
        var page = Create();
        await page.LoadAsync();

        page.Dispose();
        _player.Advance(15);

        Assert.True(_player.Disposed);
        Assert.Null(page.CurrentLine);
        Create().Dispose(); // no player: nothing to release
    }
}
