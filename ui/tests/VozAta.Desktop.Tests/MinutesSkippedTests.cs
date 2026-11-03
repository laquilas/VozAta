using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>"Minutes when finished" and the "minutes not generated" marker (phase 64).</summary>
public sealed class MinutesSkippedTests
{
    private readonly FakeEngineClient _engine = new();
    private readonly FakeRecorderClient _recorder = new();
    private readonly FakePreferences _preferences = new();
    private readonly LocalizationService _localization = new();
    private readonly ManualDelay _delay = new();
    private readonly RecordingSessionService _session = new();

    private RecorderPageViewModel Create(bool viaRecorder) =>
        new(_engine, _localization, _preferences, new FakeClock(), new FakeTimer(),
            new MinutesTemplatesViewModel(_engine), _session, _ => { }, titleDelay: _delay.Wait, recorder: _recorder)
        {
            IsEngineConnected = true,
            IsRecorderConnected = viaRecorder,
        };

    [Fact]
    public void The_chip_is_on_by_default_and_remembered()
    {
        var page = Create(viaRecorder: false);
        Assert.True(page.GenerateMinutes);

        page.ToggleGenerateMinutesCommand.Execute(null);

        Assert.False(page.GenerateMinutes);
        Assert.False(_preferences.Data.GenerateMinutes);
        Assert.False(Create(viaRecorder: false).GenerateMinutes);
    }

    [Fact]
    public async Task Off_goes_with_the_start_to_the_engine_and_to_the_recorder()
    {
        var engine = Create(viaRecorder: false);
        engine.GenerateMinutes = false;
        await engine.StartCommand.ExecuteAsync(null);
        await engine.StopCommand.ExecuteAsync(null);
        var recorder = Create(viaRecorder: true);
        await recorder.StartCommand.ExecuteAsync(null);

        Assert.False(_engine.StartRequests.Single().GenerateMinutes);
        Assert.Equal(false, _recorder.Starts.Single().Options["generate_minutes"]);
    }

    [Fact]
    public async Task On_is_not_sent_with_the_start()
    {
        var page = Create(viaRecorder: false);

        await page.StartCommand.ExecuteAsync(null);

        Assert.Null(_engine.StartRequests.Single().GenerateMinutes); // the setting decides
    }

    [Fact]
    public async Task The_chip_changes_the_meeting_being_recorded()
    {
        var page = Create(viaRecorder: false);
        await page.StartCommand.ExecuteAsync(null);

        page.GenerateMinutes = false;
        _delay.Elapse();
        await page.OptionsSave;

        Assert.Equal(false, _engine.SessionUpdates.Single().Changes["generate_minutes"]);
    }

    [Theory]
    [InlineData("skipped_not_ready", "MinutesSkippedNotReady")]
    [InlineData("skipped_by_user", "MinutesSkippedByUser")]
    [InlineData("generated", null)]
    [InlineData("none", null)]
    public void A_skipped_meeting_says_why(string state, string? key)
    {
        var summary = new SessionSummary("x", "done", null, null, 60, "pt", false, MinutesState: state);

        var text = MeetingsPageViewModel.MinutesSkippedText(_localization, summary);

        Assert.Equal(key is null ? "" : _localization[key], text);
        Assert.Equal(key is not null, summary.MinutesSkipped);
    }

    [Fact]
    public void The_event_and_the_state_are_read()
    {
        var parsed = EngineEventParser.Parse("""{"type":"minutes_skipped","session_id":"x","data":{"session_id":"x","reason":"not_ready"}}""");

        Assert.Equal(new MinutesSkippedEvent("x", "not_ready"), parsed);
    }

    [Fact]
    public async Task The_window_tells_when_minutes_were_skipped()
    {
        var events = new FakeEngineEvents();
        var window = new MainViewModel(
            _engine, events, new FakeEngineProcess(), new ImmediateDispatcher(), _localization, new FakeDialogs(),
            new FakePreferences(), new FakeClock(), new FakeTimer(), new FakeShell(), new FakeFileSaver(),
            new FakeThemeService());
        await window.InitializeAsync();
        var before = window.HandledEvents;

        events.Send(new MinutesSkippedEvent("x", "by_user"));
        for (var i = 0; i < 200 && window.HandledEvents == before; i++)
        {
            await Task.Delay(5);
        }

        Assert.Contains(_localization["MinutesSkippedByUser"], window.Notifications);
    }
}
