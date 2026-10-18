using System.Net;
using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>The crash recovery dialog (phase 17): offer, Recover one by one, Later.</summary>
public sealed class RecoveryViewModelTests
{
    private const string First = "20261015_202358";
    private const string Second = "20261014_090000";

    private readonly FakeEngineClient _client = new();
    private readonly LocalizationService _localization = new();
    private readonly List<string> _notes = [];

    public RecoveryViewModelTests()
    {
        _client.Details[First] = Detail(First, new DateTimeOffset(2026, 10, 15, 20, 23, 58, TimeSpan.FromHours(-3)), 754);
        _client.Details[Second] = Detail(Second, null, null);
    }

    private RecoveryViewModel Create() => new(_client, _localization, _notes.Add);

    private static SessionDetail Detail(string id, DateTimeOffset? started, double? duration) =>
        new(id, "interrupted", started, null, duration, "pt", false, [], @"C:\r");

    [Fact]
    public async Task An_offer_opens_the_dialog_with_date_and_duration()
    {
        var viewModel = Create();

        await viewModel.OfferAsync([First, Second]);

        Assert.True(viewModel.IsOpen);
        Assert.Equal(
            [
                new RecoverySession(First, SessionPageViewModel.FormatStart(_client.Details[First].StartedAt)!, "00:12:34"),
                new RecoverySession(Second, Second, "00:00:00"),
            ],
            viewModel.Sessions);
    }

    [Fact]
    public async Task A_repeated_offer_does_not_duplicate_sessions()
    {
        var viewModel = Create();

        await viewModel.OfferAsync([First]);
        await viewModel.OfferAsync([First, Second]);

        Assert.Equal([First, Second], viewModel.Sessions.Select(session => session.Id));
    }

    [Fact]
    public async Task An_empty_offer_keeps_the_dialog_closed()
    {
        var viewModel = Create();

        await viewModel.OfferAsync([]);

        Assert.False(viewModel.IsOpen);
    }

    [Fact]
    public async Task A_session_the_engine_cannot_describe_is_listed_by_its_id()
    {
        _client.DetailError = new EngineUnavailableException("refused", new HttpRequestException("refused"));
        var viewModel = Create();

        await viewModel.OfferAsync([First]);

        Assert.Equal([new RecoverySession(First, First, "")], viewModel.Sessions);
    }

    [Fact]
    public async Task Recover_starts_the_first_session_and_the_next_once_it_is_done()
    {
        var viewModel = Create();
        await viewModel.OfferAsync([First, Second]);

        await viewModel.RecoverCommand.ExecuteAsync(null);

        Assert.False(viewModel.IsOpen);
        Assert.Empty(viewModel.Sessions);
        Assert.Equal([First], _client.Recovered);
        Assert.Equal(First, viewModel.Recovering);

        await viewModel.OnStatusAsync(new StatusEvent(First, "finalizing", 754));
        Assert.Equal([First], _client.Recovered);

        await viewModel.OnStatusAsync(new StatusEvent(First, "done", 754));
        Assert.Equal([First, Second], _client.Recovered);
        Assert.Equal([_localization.Format("SessionRecovered", SessionPageViewModel.FormatStart(_client.Details[First].StartedAt))], _notes);

        await viewModel.OnStatusAsync(new StatusEvent(Second, "done", 0));
        Assert.Null(viewModel.Recovering);
        Assert.Equal(2, _notes.Count);
    }

    [Fact]
    public async Task A_failed_recovery_moves_on_to_the_next_session()
    {
        var viewModel = Create();
        await viewModel.OfferAsync([First, Second]);
        await viewModel.RecoverCommand.ExecuteAsync(null);

        await viewModel.OnErrorAsync(new ErrorEvent(First, "minutes_failed", "Ollama is down."));
        Assert.Equal([First], _client.Recovered); // only a failed repair ends the recovery

        await viewModel.OnErrorAsync(new ErrorEvent(First, "recovery_failed", "Bad header."));
        Assert.Equal([First, Second], _client.Recovered);
        Assert.Empty(_notes); // the error itself is shown by the main window
    }

    [Fact]
    public async Task Events_of_other_sessions_are_ignored()
    {
        var viewModel = Create();
        await viewModel.OnStatusAsync(new StatusEvent(First, "done", 1));
        await viewModel.OnErrorAsync(new ErrorEvent(First, "recovery_failed", "x"));
        await viewModel.OfferAsync([First]);
        await viewModel.RecoverCommand.ExecuteAsync(null);

        await viewModel.OnStatusAsync(new StatusEvent("20991231_000000", "done", 1));
        await viewModel.OnErrorAsync(new ErrorEvent("20991231_000000", "recovery_failed", "x"));

        Assert.Equal(First, viewModel.Recovering);
        Assert.Empty(_notes);
    }

    [Fact]
    public async Task A_session_left_interrupted_frees_the_queue_without_a_success_note()
    {
        var viewModel = Create();
        await viewModel.OfferAsync([First]);
        await viewModel.RecoverCommand.ExecuteAsync(null);

        await viewModel.OnStatusAsync(new StatusEvent(First, "interrupted", null));

        Assert.Null(viewModel.Recovering);
        Assert.Empty(_notes);
    }

    [Fact]
    public async Task A_refused_recover_is_reported_and_the_next_session_still_starts()
    {
        _client.RecoverError = new EngineApiException(HttpStatusCode.Conflict, "session_already_active", "A recording is in progress.");
        var viewModel = Create();
        await viewModel.OfferAsync([First, Second]);

        await viewModel.RecoverCommand.ExecuteAsync(null);

        Assert.Equal([First, Second], _client.Recovered);
        Assert.Equal(["A recording is in progress.", "A recording is in progress."], _notes); // both refused
        Assert.Null(viewModel.Recovering);
    }

    [Fact]
    public async Task An_unreachable_engine_is_reported_with_the_localized_text()
    {
        _client.RecoverError = new EngineUnavailableException("refused", new HttpRequestException("refused"));
        var viewModel = Create();
        await viewModel.OfferAsync([First]);

        await viewModel.RecoverCommand.ExecuteAsync(null);

        Assert.Equal([_localization["EngineUnavailable"]], _notes);
    }

    [Fact]
    public async Task Later_closes_the_dialog_without_recovering_and_a_new_offer_reopens_it()
    {
        var viewModel = Create();
        await viewModel.OfferAsync([First]);

        viewModel.LaterCommand.Execute(null);

        Assert.False(viewModel.IsOpen);
        Assert.Empty(viewModel.Sessions);
        Assert.Empty(_client.Recovered);

        await viewModel.OfferAsync([First]);
        Assert.True(viewModel.IsOpen);
    }

    [Fact]
    public async Task A_lost_connection_forgets_the_queue_and_the_session_being_recovered()
    {
        var viewModel = Create();
        await viewModel.OfferAsync([First, Second]);
        await viewModel.RecoverCommand.ExecuteAsync(null);

        viewModel.OnConnectionLost();
        await viewModel.OnStatusAsync(new StatusEvent(First, "done", 1));

        Assert.Null(viewModel.Recovering);
        Assert.Equal([First], _client.Recovered);
        await viewModel.OfferAsync([First]); // offered again once the engine is back
        Assert.True(viewModel.IsOpen);
    }

    [Fact]
    public async Task The_session_being_recovered_is_not_offered_again()
    {
        var viewModel = Create();
        await viewModel.OfferAsync([First, Second]);
        await viewModel.RecoverCommand.ExecuteAsync(null);

        await viewModel.OfferAsync([First, Second]);

        Assert.False(viewModel.IsOpen); // First is recovering, Second is queued
    }
}
