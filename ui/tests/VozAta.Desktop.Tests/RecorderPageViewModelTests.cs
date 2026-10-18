using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>The recorder page on its own (phase 35): the meeting title, Enter and the locked options.</summary>
public sealed class RecorderPageViewModelTests
{
    private const string SessionId = "20261016_090000";

    private readonly FakeEngineClient _client = new();
    private readonly LocalizationService _localization = new();
    private readonly ManualDelay _delay = new();
    private readonly List<string> _notified = [];
    private readonly RecordingSessionService _session = new();

    private RecorderPageViewModel Create() =>
        new(_client, _localization, new FakePreferences(), new FakeClock(), new FakeTimer(),
            new MinutesTemplatesViewModel(_client), _session, _notified.Add, titleDelay: _delay.Wait)
        {
            IsEngineConnected = true,
        };

    private async Task<RecorderPageViewModel> RecordingAsync(string title = "")
    {
        var recorder = Create();
        recorder.Title = title;
        await recorder.StartCommand.ExecuteAsync(null);
        return recorder;
    }

    [Theory]
    [InlineData("  Weekly   sync \n", "Weekly sync")]
    [InlineData("   ", null)]
    [InlineData("", null)]
    public async Task The_title_is_sent_on_start_trimmed(string typed, string? sent)
    {
        var recorder = await RecordingAsync(typed);

        Assert.Equal(sent, _client.StartRequests.Single().Title);
        Assert.Equal((SessionId, sent), (_session.SessionId, _session.Title));
        Assert.Empty(_client.TitleUpdates);
    }

    [Fact]
    public async Task Enter_in_the_title_box_starts_the_recording()
    {
        var recorder = Create();
        recorder.Title = "Kickoff";

        await recorder.EnterCommand.ExecuteAsync(null);

        Assert.True(recorder.IsRecording);
        Assert.Equal("Kickoff", _client.StartRequests.Single().Title);
    }

    [Fact]
    public async Task Enter_does_nothing_while_the_engine_is_down()
    {
        var recorder = Create();
        recorder.IsEngineConnected = false;

        await recorder.EnterCommand.ExecuteAsync(null);

        Assert.Empty(_client.StartRequests);
    }

    [Fact]
    public async Task Editing_the_title_while_recording_patches_it_once_typing_pauses()
    {
        var recorder = await RecordingAsync("Draft");

        recorder.Title = "Budg";
        recorder.Title = "Budget review";
        Assert.Empty(_client.TitleUpdates); // still typing
        _delay.Elapse();
        await recorder.TitleSave;

        Assert.Equal([(SessionId, (string?)"Budget review")], _client.TitleUpdates);
        Assert.Equal([RecorderPageViewModel.TitleDebounce, RecorderPageViewModel.TitleDebounce], _delay.Requested);
        Assert.Equal("Budget review", _session.Title);
    }

    [Fact]
    public async Task Enter_while_recording_sends_the_title_at_once()
    {
        var recorder = await RecordingAsync();

        recorder.Title = "Retro";
        await recorder.EnterCommand.ExecuteAsync(null);
        _delay.Elapse(); // the pending debounce was dropped
        await recorder.TitleSave;

        Assert.Equal([(SessionId, (string?)"Retro")], _client.TitleUpdates);
        Assert.Single(_client.StartRequests);
    }

    [Fact]
    public async Task Clearing_the_title_while_recording_patches_null()
    {
        var recorder = await RecordingAsync("Draft");

        recorder.Title = "  ";
        await recorder.EnterCommand.ExecuteAsync(null);

        Assert.Equal([(SessionId, (string?)null)], _client.TitleUpdates);
        Assert.Null(_session.Title);
    }

    [Fact]
    public async Task An_unchanged_title_is_not_patched_again()
    {
        var recorder = await RecordingAsync("Draft");

        recorder.Title = " Draft ";
        await recorder.EnterCommand.ExecuteAsync(null);

        Assert.Empty(_client.TitleUpdates);
    }

    [Fact]
    public async Task Stop_sends_a_title_still_being_typed_first()
    {
        var recorder = await RecordingAsync();
        recorder.Title = "Planning";

        await recorder.StopCommand.ExecuteAsync(null);

        Assert.Equal(["start", "title", "stop"], _client.Calls.Where(call => call is "start" or "title" or "stop"));
    }

    [Fact]
    public async Task A_rejected_title_is_notified_and_recording_goes_on()
    {
        var recorder = await RecordingAsync("Draft");
        _client.TitleError = FakeEngineClient.ApiError("title_too_long", "The title can have at most 200 characters.");

        recorder.Title = "Too long";
        await recorder.EnterCommand.ExecuteAsync(null);

        Assert.Equal(["The title can have at most 200 characters."], _notified);
        Assert.True(recorder.IsRecording);
        Assert.Equal("Draft", _session.Title);
    }

    [Fact]
    public void Typing_a_title_before_start_sends_nothing()
    {
        var recorder = Create();

        recorder.Title = "Kickoff";

        Assert.Empty(_delay.Requested);
        Assert.Empty(_client.TitleUpdates);
    }

    [Fact]
    public async Task The_title_is_cleared_when_the_recording_ends()
    {
        var recorder = await RecordingAsync("Kickoff");

        recorder.Handle(new StatusEvent(SessionId, "done", 3));

        Assert.Equal("", recorder.Title);
        Assert.Equal((null, null), (_session.SessionId, _session.Title));
        Assert.Empty(_client.TitleUpdates);
    }

    [Fact]
    public async Task A_failed_start_keeps_the_typed_title()
    {
        _client.StartError = FakeEngineClient.ApiError("device_timeout", "The mic did not open.");
        var recorder = Create();
        recorder.Title = "Kickoff";

        await recorder.StartCommand.ExecuteAsync(null);

        Assert.Equal("Kickoff", recorder.Title);
        Assert.False(recorder.IsRecording);
    }

    [Fact]
    public void A_recording_that_started_elsewhere_is_adopted_for_renaming()
    {
        var recorder = Create();

        recorder.Handle(new StatusEvent("20261016_100000", "recording", 12));
        recorder.Title = "Adopted";
        _delay.Elapse();

        Assert.Equal("20261016_100000", _session.SessionId);
        Assert.Equal([("20261016_100000", (string?)"Adopted")], _client.TitleUpdates);
    }

    [Fact]
    public async Task The_options_are_locked_while_recording_but_the_title_is_not()
    {
        var recorder = Create();
        Assert.True((recorder.CanEditOptions, recorder.CanEditTitle) == (true, true));
        var changed = new List<string?>();
        recorder.PropertyChanged += (_, args) => changed.Add(args.PropertyName);

        await recorder.StartCommand.ExecuteAsync(null);
        Assert.Equal((false, true), (recorder.CanEditOptions, recorder.CanEditTitle));
        Assert.False(recorder.Devices.IsEnabled);
        Assert.Contains(nameof(RecorderPageViewModel.CanEditOptions), changed);

        await recorder.PauseResumeCommand.ExecuteAsync(null);
        Assert.Equal((false, true), (recorder.CanEditOptions, recorder.CanEditTitle));

        await recorder.StopCommand.ExecuteAsync(null);
        Assert.Equal((false, false), (recorder.CanEditOptions, recorder.CanEditTitle)); // finalizing

        recorder.Handle(new StatusEvent(SessionId, "done", 3));
        Assert.Equal((true, true), (recorder.CanEditOptions, recorder.CanEditTitle));
    }

    [Theory]
    [InlineData(null, null)]
    [InlineData(" a \t b ", "a b")]
    [InlineData("Reunião", "Reunião")]
    public void NormalizeTitle_matches_the_engine(string? typed, string? expected) =>
        Assert.Equal(expected, RecorderPageViewModel.NormalizeTitle(typed));

    [Fact]
    public async Task The_shared_session_shows_the_elapsed_time_and_state()
    {
        var recorder = await RecordingAsync();

        recorder.Handle(new StatusEvent(SessionId, "recording", 75));

        Assert.Equal(("00:01:15", RecordingState.Recording), (_session.Elapsed, _session.State));
        Assert.True(_session.IsActivelyRecording);
    }
}
