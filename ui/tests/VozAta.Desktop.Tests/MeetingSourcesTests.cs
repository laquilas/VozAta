using System.Net;
using System.Text.Json;
using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>The "Audio sources" tab of a recorded meeting (phase 66).</summary>
public sealed class MeetingSourcesTests
{
    private const string Id = "20261112_140724";

    private readonly FakeEngineClient _client = new();
    private readonly LocalizationService _localization = new();
    private readonly FakeDialogs _dialogs = new();

    private static MeetingSources Sources(params MeetingSource[] items) =>
        new(items, new DateTimeOffset(2026, 11, 19, 15, 0, 0, TimeSpan.FromHours(-3)));

    private static MeetingSource Source(string id, bool selected, string kind = "mic") =>
        new(id, kind, id.ToUpperInvariant(), selected, DurationSeconds: 125);

    private MeetingSourcesViewModel Create() => new(_client, _localization, _dialogs, Id);

    [Fact]
    public async Task The_client_reads_chooses_and_trims_the_sources()
    {
        var handler = new FakeHttpHandler(request => new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(request.RequestUri!.AbsolutePath.EndsWith("keep-selected", StringComparison.Ordinal)
                ? """{"removed":["in-room"]}"""
                : """{"items":[{"id":"in-jbl","kind":"mic","name":"JBL","selected":true,"preferred":true,"duration_seconds":12.5}],"kept_until":"2026-11-19T15:00:00-03:00"}"""),
        });
        var client = new EngineClient(handler.Client());

        var sources = await client.GetSessionSourcesAsync(Id);
        await client.ChooseSessionSourcesAsync(Id, ["in-jbl", "out-headset"]);
        var removed = await client.KeepSelectedSessionSourcesAsync(Id);

        Assert.Equal(("in-jbl", 12.5, true), (sources.Items[0].Id, sources.Items[0].DurationSeconds, sources.Items[0].Preferred));
        Assert.Equal(new DateTimeOffset(2026, 11, 19, 15, 0, 0, TimeSpan.FromHours(-3)), sources.KeptUntil);
        Assert.Equal(["in-room"], removed);
        Assert.Equal(
            [(HttpMethod.Get, $"/sessions/{Id}/sources"), (HttpMethod.Post, $"/sessions/{Id}/sources"),
             (HttpMethod.Post, $"/sessions/{Id}/sources/keep-selected")],
            handler.Requests.Select(request => (request.Method, request.Path)));
        using var body = JsonDocument.Parse(handler.Requests[1].Body!);
        Assert.Equal(["in-jbl", "out-headset"], body.RootElement.GetProperty("selected").EnumerateArray().Select(e => e.GetString()));
    }

    [Fact]
    public async Task Load_lists_the_sources_with_their_details()
    {
        _client.SessionSources = Sources(Source("in-jbl", true), Source("out-headset", false, "system"));
        var sources = Create();

        await sources.LoadAsync();

        Assert.True(sources.HasItems);
        Assert.Equal(["IN-JBL", "OUT-HEADSET"], sources.Items.Select(row => row.Name));
        Assert.Equal(_localization.Format("SourceDetails", _localization["SourceKindOutput"], "00:02:05"), sources.Items[1].Details);
        Assert.StartsWith(_localization.Format("SourcesKeptUntil", "").TrimEnd('.').Trim(), sources.KeptText, StringComparison.Ordinal);
        Assert.False(sources.HasChanges);
        Assert.False(sources.ApplyCommand.CanExecute(null));
        Assert.True(sources.KeepSelectedCommand.CanExecute(null));
    }

    [Fact]
    public async Task A_meeting_without_sources_or_an_engine_error_has_no_tab()
    {
        var sources = Create();
        await sources.LoadAsync();
        Assert.False(sources.HasItems);
        Assert.Equal(_localization["SourcesKeptForever"], sources.KeptText);

        _client.SourcesError = new EngineApiException(HttpStatusCode.NotFound, "not_found", "x");
        await sources.LoadAsync();
        Assert.False(sources.HasItems);
    }

    [Fact]
    public async Task Apply_asks_then_rebuilds_the_meeting_from_the_ticked_sources()
    {
        _client.SessionSources = Sources(Source("in-jbl", true), Source("in-room", false));
        var sources = Create();
        await sources.LoadAsync();

        sources.Items[1].IsSelected = true;

        Assert.True(sources.HasChanges);
        Assert.False(sources.KeepSelectedCommand.CanExecute(null)); // apply first
        await sources.ApplyCommand.ExecuteAsync(null);
        var choice = _client.SourceChoices.Single();
        Assert.Equal(Id, choice.Id);
        Assert.Equal(["in-jbl", "in-room"], choice.Selected);
        Assert.Equal([_localization["SourcesApplyTitle"]], _dialogs.Asked);
        Assert.Equal(_localization["SourcesApplied"], sources.Status);
        Assert.False(sources.HasChanges);
    }

    [Fact]
    public async Task Apply_cancelled_or_with_nothing_ticked_does_nothing()
    {
        _client.SessionSources = Sources(Source("in-jbl", true), Source("in-room", false));
        var sources = Create();
        await sources.LoadAsync();
        sources.Items[0].IsSelected = false;
        Assert.False(sources.HasChanges); // nothing ticked

        sources.Items[1].IsSelected = true;
        _dialogs.Answer = false;
        await sources.ApplyCommand.ExecuteAsync(null);

        Assert.Empty(_client.SourceChoices);
    }

    [Fact]
    public async Task An_engine_refusal_is_shown()
    {
        _client.SessionSources = Sources(Source("in-jbl", true), Source("in-room", false));
        var sources = Create();
        await sources.LoadAsync();
        sources.Items[1].IsSelected = true;
        _client.SourcesError = new EngineApiException(HttpStatusCode.Conflict, "session_still_active", "It is being processed");

        await sources.ApplyCommand.ExecuteAsync(null);

        Assert.Equal("It is being processed", sources.Status);
        Assert.False(sources.IsBusy);
        _client.SourcesError = new EngineUnavailableException("down", new HttpRequestException());
        await sources.ApplyCommand.ExecuteAsync(null);
        Assert.Equal(_localization["EngineUnavailable"], sources.Status);
    }

    [Fact]
    public async Task Keep_selected_deletes_the_others_and_reloads()
    {
        _client.SessionSources = Sources(Source("in-jbl", true), Source("in-room", false));
        var sources = Create();
        await sources.LoadAsync();

        await sources.KeepSelectedCommand.ExecuteAsync(null);

        Assert.Equal([Id], _client.SourcesTrimmed);
        Assert.Equal(["in-jbl"], sources.Items.Select(row => row.Id));
        Assert.Equal(_localization.Format("SourcesTrimmed", 1), sources.Status);
        Assert.False(sources.KeepSelectedCommand.CanExecute(null));
    }

    [Fact]
    public void The_page_offers_the_tab()
    {
        var page = new SessionPageViewModel(
            _client, new FakeShell(), _localization, new FakeFileSaver(),
            new SessionSummary(Id, "done", DateTimeOffset.Now, null, 60, "pt", false, null), dialogs: _dialogs);

        Assert.Same(page.Sources, page.Sources);
    }
}
