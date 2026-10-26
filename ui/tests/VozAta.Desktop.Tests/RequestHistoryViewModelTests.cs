using System.Net;
using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>The request history of a meeting (phase 59).</summary>
public sealed class RequestHistoryViewModelTests
{
    private readonly FakeEngineClient _client = new();
    private readonly LocalizationService _localization = new();

    private static RequestEntry Entry(
        string id, string status = "done", string kind = "minutes_so_far", string source = "voice",
        double? at = 754, string? message = null, string text = "gere a ata") =>
        new(id, "2026-10-23T10:05:00-03:00", at, kind, source, text, status, null, message, null);

    [Fact]
    public async Task The_history_loads_newest_first()
    {
        _client.Requests["s1"] = [Entry("r1"), Entry("r2", "failed", "action_items", "app", null, "llm_unreachable", "")];
        var history = new RequestHistoryViewModel(_client, _localization, "s1");

        await history.LoadAsync();

        Assert.True(history.HasRows);
        Assert.Equal(["r2", "r1"], history.Rows.Select(row => row.Entry.Id));
        var failed = history.Rows[0];
        Assert.Equal($"{_localization["RequestSource_app"]} · {_localization["RequestKind_action_items"]}", failed.What);
        Assert.Equal(
            $"{_localization["RequestStatus_failed"]}: {_localization["RequestReason_llm_unreachable"]}", failed.StatusText);
        Assert.True(failed.IsFailed);
        Assert.False(failed.HasText);
        Assert.Matches(@"^\d\d:\d\d$", failed.Time); // no meeting second: the clock time
        var voice = history.Rows[1];
        Assert.Equal("00:12:34", voice.Time);
        Assert.Equal(_localization["RequestStatus_done"], voice.StatusText);
        Assert.True(voice.IsOk);
        Assert.Equal("gere a ata", voice.Text);
    }

    [Fact]
    public async Task An_unknown_code_shows_as_it_is()
    {
        _client.Requests["s1"] = [Entry("r1", "ignored", message: "new_code")];
        var history = new RequestHistoryViewModel(_client, _localization, "s1");

        await history.LoadAsync();

        Assert.Equal($"{_localization["RequestStatus_ignored"]}: new_code", history.Rows[0].StatusText);
        Assert.True(history.Rows[0].IsBusy);
    }

    [Fact]
    public async Task Updates_change_their_row_or_add_one_on_top()
    {
        _client.Requests["s1"] = [Entry("r1", "running")];
        var history = new RequestHistoryViewModel(_client, _localization, "s1");
        await history.LoadAsync();

        history.OnRequest(new RequestUpdatedEvent("s1", Entry("r1", "done")));
        history.OnRequest(new RequestUpdatedEvent("s1", Entry("r2", "recognized", "ask", text: "Who?")));
        history.OnRequest(new RequestUpdatedEvent("other", Entry("r3")));
        history.OnRequest(new RequestUpdatedEvent(null, Entry("r4")));

        Assert.Equal(["r2", "r1"], history.Rows.Select(row => row.Entry.Id));
        Assert.True(history.Rows[1].IsOk);
        Assert.True(history.Rows[0].IsBusy);
    }

    [Fact]
    public async Task The_recorder_follows_the_meeting_being_recorded()
    {
        _client.Requests["s1"] = [Entry("r1")];
        _client.Requests["s2"] = [];
        var history = new RequestHistoryViewModel(_client, _localization);
        await history.LoadAsync(); // nothing followed yet: nothing asked
        Assert.DoesNotContain(_client.Calls, call => call.StartsWith("requests", StringComparison.Ordinal));

        await history.FollowAsync("s1");
        Assert.Single(history.Rows);
        await history.FollowAsync("s1"); // the same: not read again
        await history.FollowAsync("s2");

        Assert.Empty(history.Rows);
        Assert.False(history.HasRows);
        Assert.Equal(["requests s1", "requests s2"], _client.Calls.Where(call => call.StartsWith("requests", StringComparison.Ordinal)));
    }

    [Fact]
    public async Task A_failed_load_says_why()
    {
        _client.RequestsError = new EngineApiException(HttpStatusCode.NotFound, "session_not_found", "Not found.");
        var history = new RequestHistoryViewModel(_client, _localization, "s1");

        await history.LoadAsync();

        Assert.Equal("Not found.", history.Error);
        Assert.False(history.HasRows);
    }

    [Fact]
    public async Task An_unavailable_engine_says_so()
    {
        _client.RequestsError = new EngineUnavailableException("down", new HttpRequestException());
        var history = new RequestHistoryViewModel(_client, _localization, "s1");

        await history.LoadAsync();

        Assert.Equal(_localization["EngineUnavailable"], history.Error);
    }

    [Fact]
    public async Task Texts_refresh_on_a_language_switch()
    {
        _client.Requests["s1"] = [Entry("r1")];
        var history = new RequestHistoryViewModel(_client, _localization, "s1");
        await history.LoadAsync();
        var changed = new List<string?>();
        history.Rows[0].PropertyChanged += (_, args) => changed.Add(args.PropertyName);

        _localization.SetLanguage("pt-BR");
        history.RefreshTexts();

        Assert.Contains(nameof(RequestRow.StatusText), changed);
        Assert.Equal("Pronto", history.Rows[0].StatusText);
    }
}
