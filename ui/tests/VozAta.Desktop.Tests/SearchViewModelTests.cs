using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>A debounce delay the test releases by hand.</summary>
internal sealed class ManualDelay
{
    private readonly List<TaskCompletionSource> _waiting = [];

    public List<TimeSpan> Requested { get; } = [];

    public Task Wait(TimeSpan delay, CancellationToken cancellationToken)
    {
        Requested.Add(delay);
        var done = new TaskCompletionSource();
        cancellationToken.Register(() => done.TrySetCanceled(cancellationToken));
        _waiting.Add(done);
        return done.Task;
    }

    public void Elapse()
    {
        foreach (var done in _waiting)
        {
            done.TrySetResult();
        }

        _waiting.Clear();
    }
}

public sealed class SearchViewModelTests
{
    private const string First = "20261015_202358";
    private const string Second = "20261016_090000";

    private readonly FakeEngineClient _client = new();
    private readonly LocalizationService _localization = new();
    private readonly ManualDelay _delay = new();

    private static SearchHit Hit(string session, string segment, double start, string snippet = "the \u0002budget\u0003") =>
        new(session, segment, start, "mic", "Me", snippet);

    private SearchViewModel Create() => new(_client, _localization, _delay.Wait);

    private async Task TypeAndWait(SearchViewModel search, string query)
    {
        search.Query = query;
        _delay.Elapse();
        await search.Pending;
    }

    [Fact]
    public void Snippets_split_into_plain_and_matched_parts()
    {
        var parts = SnippetPart.Parse("…a \u0002decisão\u0003: a \u0002decisão\u0003 final");

        Assert.Equal(
            [new SnippetPart("…a ", false), new SnippetPart("decisão", true), new SnippetPart(": a ", false),
             new SnippetPart("decisão", true), new SnippetPart(" final", false)],
            parts);
    }

    [Fact]
    public void Snippets_without_markers_or_with_an_unclosed_one_are_kept()
    {
        Assert.Equal([new SnippetPart("plain", false)], SnippetPart.Parse("plain"));
        Assert.Equal([new SnippetPart("a ", false), new SnippetPart("open", true)], SnippetPart.Parse("a \u0002open"));
        Assert.Empty(SnippetPart.Parse(""));
    }

    [Theory]
    [InlineData("20261015_202358", "2026-10-15 20:23")]
    [InlineData("20261015_202358_2", "2026-10-15 20:23")]
    [InlineData("session_016", "session_016")]
    public void Session_ids_show_as_dates(string id, string expected) =>
        Assert.Equal(expected, SearchViewModel.FormatSessionDate(id));

    [Fact]
    public async Task Typing_searches_once_the_debounce_elapses()
    {
        var search = Create();

        search.Query = "bud";
        Assert.Empty(_client.Searches);
        Assert.Equal([SearchViewModel.Debounce], _delay.Requested);
        _delay.Elapse();
        await search.Pending;

        Assert.Equal(["bud"], _client.Searches);
    }

    [Fact]
    public async Task Fast_typing_sends_only_the_last_query()
    {
        _client.SearchHits.Add(Hit(First, "mic-000001", 1));
        var search = Create();

        search.Query = "bu";
        var first = search.Pending;
        search.Query = "bud";
        search.Query = "budget ";
        _delay.Elapse();
        await first;
        await search.Pending;

        Assert.Equal(["budget"], _client.Searches);
        Assert.Single(search.Groups);
        Assert.True(search.IsActive);
    }

    [Fact]
    public async Task A_new_query_cancels_a_search_in_flight()
    {
        _client.SearchGate = new TaskCompletionSource();
        var search = Create();
        search.Query = "old";
        _delay.Elapse();
        var stale = search.Pending;

        search.Query = "new";
        await stale; // canceled quietly
        _client.SearchGate.SetResult();
        _client.SearchHits.Add(Hit(First, "mic-000001", 1));
        _delay.Elapse();
        await search.Pending;

        Assert.Equal(["old", "new"], _client.Searches);
        Assert.Single(search.Groups);
        Assert.False(search.IsSearching);
    }

    [Theory]
    [InlineData("")]
    [InlineData("b")]
    [InlineData("  b  ")]
    public async Task Short_queries_clear_the_results_without_searching(string query)
    {
        _client.SearchHits.Add(Hit(First, "mic-000001", 1));
        var search = Create();
        await TypeAndWait(search, "budget");

        search.Query = query;

        Assert.Single(_client.Searches);
        Assert.Empty(search.Groups);
        Assert.False(search.IsActive);
        Assert.False(search.NoResults);
    }

    [Fact]
    public async Task Hits_are_grouped_by_session_in_transcript_order()
    {
        _client.SearchHits.AddRange(
        [
            Hit(Second, "mic-000009", 90),
            Hit(First, "mic-000002", 20),
            Hit(Second, "mic-000003", 30),
        ]);
        var search = Create();

        await TypeAndWait(search, "budget");

        Assert.Equal([Second, First], search.Groups.Select(group => group.SessionId));
        var group = search.Groups[0];
        Assert.Equal("2026-10-16 09:00", group.Date);
        Assert.Equal(["mic-000003", "mic-000009"], group.Rows.Select(row => row.Hit.SegmentId));
        Assert.Equal(("00:00:30", "Me"), (group.Rows[0].Time, group.Rows[0].Label));
        Assert.Equal([new SnippetPart("the ", false), new SnippetPart("budget", true)], group.Rows[0].Parts);
        Assert.Equal("00:00:30 Me: the budget", group.Rows[0].ToString());
        Assert.Equal("2026-10-16 09:00", group.ToString());
    }

    [Fact]
    public async Task No_hits_shows_the_empty_state()
    {
        var search = Create();

        await TypeAndWait(search, "nothing");

        Assert.True(search.NoResults);
        Assert.False(search.IsSearching);
    }

    [Fact]
    public async Task Engine_errors_are_shown_and_cleared_by_the_next_search()
    {
        _client.SearchError = new EngineUnavailableException("refused", new HttpRequestException());
        var search = Create();

        await TypeAndWait(search, "budget");
        Assert.Equal(_localization["EngineUnavailable"], search.Error);
        Assert.False(search.NoResults);

        _client.SearchError = FakeEngineClient.ApiError("bad", "Bad query");
        await TypeAndWait(search, "budget plan");
        Assert.Equal("Bad query", search.Error);

        _client.SearchError = null;
        await TypeAndWait(search, "budget");
        Assert.Null(search.Error);
    }

    [Fact]
    public async Task Clear_empties_the_query_and_the_results()
    {
        _client.SearchHits.Add(Hit(First, "mic-000001", 1));
        var search = Create();
        await TypeAndWait(search, "budget");

        search.ClearCommand.Execute(null);

        Assert.Equal("", search.Query);
        Assert.Empty(search.Groups);
    }

    [Fact]
    public async Task Opening_a_result_calls_back_with_its_hit()
    {
        _client.SearchHits.Add(Hit(First, "mic-000001", 1));
        var search = Create();
        await TypeAndWait(search, "budget");
        await search.OpenCommand.ExecuteAsync(search.Groups[0].Rows[0]); // no callback yet: ignored
        var opened = new List<SearchHit>();
        search.OpenHit = hit =>
        {
            opened.Add(hit);
            return Task.CompletedTask;
        };

        await search.OpenCommand.ExecuteAsync(search.Groups[0].Rows[0]);
        await search.OpenCommand.ExecuteAsync(null);

        Assert.Equal([_client.SearchHits[0]], opened);
    }
}

public sealed class SearchNavigationTests
{
    private readonly FakeEngineClient _client = new();
    private readonly ManualDelay _delay = new();

    private static SessionSummary Session(int day) =>
        new($"session_{day:000}", "done", new DateTimeOffset(2026, 9, 30, 9, 0, 0, TimeSpan.Zero).AddDays(day), null, 60, "pt", true);

    private HistoryViewModel Create() => new(_client, new FakeShell(), new LocalizationService(), new FakeFileSaver(), searchDelay: _delay.Wait);

    private void AddSessions(int count)
    {
        for (var day = count; day >= 1; day--)
        {
            var id = Session(day).Id;
            _client.Sessions.Add(Session(day));
            _client.Details[id] = new SessionDetail(id, "done", null, null, 60, "pt", true, [], @"C:\r");
            _client.Transcripts[id] = new Transcript("raw",
            [
                new Segment("mic-000001", "mic", "mic", "Me", 1, 2, "Hello.", false, []),
                new Segment("mic-000002", "mic", "mic", "Me", 50, 52, "The budget.", false, []),
            ]);
        }
    }

    private static SearchHit Hit(string session, string segment = "mic-000002") =>
        new(session, segment, 50, "mic", "Me", "The \u0002budget\u0003.");

    [Fact]
    public async Task Opening_a_hit_selects_its_session_on_the_transcript_at_the_segment()
    {
        AddSessions(3);
        var history = Create();
        await history.LoadAsync();

        await history.Search.OpenHit!(Hit("session_002"));
        await history.DetailLoading;

        Assert.Equal("session_002", history.Selected!.Id);
        var detail = history.Detail!;
        Assert.Equal(SessionPageViewModel.TranscriptTab, detail.SelectedTab);
        Assert.Equal("mic-000002", detail.FocusedLine!.SegmentId);
        Assert.True(detail.FocusedLine.IsFocused);
        Assert.Same(detail.FocusedLine, detail.Lines[1]);
        Assert.False(detail.Lines[0].IsFocused);
    }

    [Fact]
    public async Task Opening_a_hit_in_an_older_session_loads_more_pages()
    {
        AddSessions(45);
        var history = Create();
        await history.LoadAsync();

        await history.OpenHitAsync(Hit("session_003"));
        await history.DetailLoading;

        Assert.Equal(45, history.Rows.Count);
        Assert.Equal("session_003", history.Detail!.Id);
        Assert.Equal("mic-000002", history.Detail.FocusedLine!.SegmentId);
    }

    [Fact]
    public async Task Another_hit_in_the_open_session_moves_the_focus()
    {
        AddSessions(2);
        var history = Create();
        await history.LoadAsync();
        await history.OpenHitAsync(Hit("session_001"));
        await history.DetailLoading;
        var detail = history.Detail!;

        await history.OpenHitAsync(Hit("session_001", "mic-000001"));

        Assert.Same(detail, history.Detail);
        Assert.Equal("mic-000001", detail.FocusedLine!.SegmentId);
        Assert.True(detail.Lines[0].IsFocused);
        Assert.False(detail.Lines[1].IsFocused);
    }

    [Fact]
    public async Task A_hit_of_an_unknown_session_changes_nothing()
    {
        AddSessions(2);
        var history = Create();
        await history.LoadAsync();

        await history.OpenHitAsync(Hit("session_999"));

        Assert.Null(history.Selected);
        Assert.Null(history.Detail);
    }

    [Fact]
    public async Task Focus_waits_for_the_transcript_to_load()
    {
        AddSessions(1);
        var detail = new SessionPageViewModel(
            _client, new FakeShell(), new LocalizationService(), new FakeFileSaver(), Session(1));

        detail.FocusSegment("mic-000002");
        Assert.Null(detail.FocusedLine);
        await detail.LoadAsync();

        Assert.Equal("mic-000002", detail.FocusedLine!.SegmentId);
        Assert.Equal(SessionPageViewModel.TranscriptTab, detail.SelectedTab);
    }

    [Fact]
    public async Task An_unknown_segment_is_ignored()
    {
        AddSessions(1);
        var detail = new SessionPageViewModel(
            _client, new FakeShell(), new LocalizationService(), new FakeFileSaver(), Session(1));
        await detail.LoadAsync();

        detail.FocusSegment("mic-999999");

        Assert.Null(detail.FocusedLine);
        Assert.All(detail.Lines, line => Assert.False(line.IsFocused));
    }

    [Fact]
    public void The_search_is_created_once()
    {
        var history = Create();

        Assert.Same(history.Search, history.Search);
        Assert.NotNull(history.Search.OpenHit);
    }
}
