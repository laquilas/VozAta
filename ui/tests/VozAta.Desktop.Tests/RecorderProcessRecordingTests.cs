using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>The Recorder page records through the recorder process (phase 61).</summary>
public sealed class RecorderProcessRecordingTests
{
    private const string Id = "20261103_101500";

    private readonly FakeEngineClient _engine = new();
    private readonly FakeRecorderClient _recorder = new();
    private readonly LocalizationService _localization = new();
    private readonly ManualDelay _delay = new();
    private readonly List<string> _notified = [];
    private readonly RecordingSessionService _session = new();

    private RecorderPageViewModel Create(bool engine = false, bool recorder = true) =>
        new(_engine, _localization, new FakePreferences(), new FakeClock(), new FakeTimer(),
            new MinutesTemplatesViewModel(_engine), _session, _notified.Add, titleDelay: _delay.Wait,
            recorder: _recorder)
        {
            IsEngineConnected = engine,
            IsRecorderConnected = recorder,
        };

    private async Task<RecorderPageViewModel> RecordingAsync(string title = "", bool engine = false)
    {
        var page = Create(engine);
        page.Title = title;
        await page.StartCommand.ExecuteAsync(null);
        return page;
    }

    [Fact]
    public void Start_needs_only_the_recorder()
    {
        Assert.True(Create(engine: false, recorder: true).StartCommand.CanExecute(null));
        Assert.False(Create(engine: false, recorder: false).StartCommand.CanExecute(null));
    }

    [Fact]
    public async Task Start_records_through_the_recorder_with_the_meeting_options()
    {
        var page = Create();
        page.Title = "  Weekly   sync ";
        page.SessionTerms = "VozAta, Avalonia";

        await page.StartCommand.ExecuteAsync(null);

        var request = _recorder.Starts.Single();
        Assert.Equal("Weekly sync", request.Options["title"]);
        Assert.Equal("en", request.Options["language"]);
        Assert.Equal(true, request.Options["live_transcription"]);
        Assert.Equal(["VozAta", "Avalonia"], (IEnumerable<string>)request.Options["vocabulary"]!);
        Assert.Null(request.Options["translate_to"]);
        Assert.Empty(_engine.StartRequests);
        Assert.Equal((RecordingState.Recording, Id, "Weekly sync"), (_session.State, _session.SessionId, _session.Title));
        Assert.True(page.IsViaRecorder);
    }

    [Fact]
    public async Task Without_the_recorder_the_engine_records_as_before()
    {
        var page = Create(engine: true, recorder: false);

        await page.StartCommand.ExecuteAsync(null);

        Assert.Single(_engine.StartRequests);
        Assert.Empty(_recorder.Starts);
        Assert.False(page.IsViaRecorder);
    }

    [Fact]
    public async Task A_recorder_that_refuses_to_start_is_reported_and_the_page_stays_idle()
    {
        _recorder.StartError = FakeRecorderClient.ApiError("device_failed");
        var page = Create();

        await page.StartCommand.ExecuteAsync(null);

        Assert.Equal(RecordingState.Idle, _session.State);
        Assert.Equal(["device_failed"], _notified);
    }

    [Fact]
    public async Task Pause_resume_and_stop_go_to_the_recorder()
    {
        var page = await RecordingAsync();

        await page.PauseResumeCommand.ExecuteAsync(null);
        Assert.Equal(RecordingState.Paused, _session.State);
        await page.PauseResumeCommand.ExecuteAsync(null);
        await page.StopCommand.ExecuteAsync(null);

        Assert.Equal(["start", "pause", "resume", "stop"], _recorder.Calls);
        Assert.DoesNotContain("stop", _engine.Calls);
        Assert.Equal(RecordingState.Idle, _session.State);
        Assert.False(page.IsViaRecorder);
    }

    [Fact]
    public async Task The_engines_status_of_the_recording_does_not_drive_the_page()
    {
        var page = await RecordingAsync();

        page.Handle(new StatusEvent(null, "idle", null)); // the engine's snapshot before it attached
        page.Handle(new StatusEvent(Id, "recording", 99));

        Assert.Equal(RecordingState.Recording, _session.State);
        Assert.Equal("00:00:00", _session.Elapsed);
    }

    [Fact]
    public async Task The_recorders_status_sets_the_time_and_a_stop_elsewhere_ends_it()
    {
        var page = await RecordingAsync();

        page.HandleRecorder(new RecorderStatusEvent(new RecordingSummary(Id, "recording", DurationSeconds: 65)));
        Assert.Equal("00:01:05", _session.Elapsed);
        page.HandleRecorder(new RecorderStatusEvent(new RecordingSummary(Id, "paused", DurationSeconds: 70)));
        Assert.Equal(RecordingState.Paused, _session.State);
        page.HandleRecorder(new RecorderStatusEvent(new RecordingSummary(null, "idle")));

        Assert.Equal(RecordingState.Idle, _session.State);
    }

    [Fact]
    public void A_recording_already_running_is_adopted_with_its_title()
    {
        var page = Create();
        var options = FakeRecorderClient.Options("""{"title":"Kept","live_transcription":false}""");

        page.HandleRecorder(new RecorderStatusEvent(new RecordingSummary(Id, "recording", null, 120, options)));

        Assert.Equal((RecordingState.Recording, Id, "Kept"), (_session.State, _session.SessionId, _session.Title));
        Assert.Equal("Kept", page.Title);
        Assert.Equal("00:02:00", _session.Elapsed);
        Assert.True(page.IsViaRecorder);
        Assert.True(page.IsAudioOnlyNotice); // live transcription was off for this recording
    }

    [Fact]
    public async Task A_recording_the_engine_makes_itself_is_not_taken_over()
    {
        var page = Create(engine: true, recorder: false);
        await page.StartCommand.ExecuteAsync(null);

        page.HandleRecorder(new RecorderStatusEvent(new RecordingSummary("other", "recording", DurationSeconds: 5)));

        Assert.False(page.IsViaRecorder);
        Assert.NotEqual("other", _session.SessionId);
    }

    [Fact]
    public async Task The_recording_just_stopped_is_not_adopted_again()
    {
        var page = await RecordingAsync();
        await page.StopCommand.ExecuteAsync(null);

        page.HandleRecorder(new RecorderStatusEvent(new RecordingSummary(Id, "recording", DurationSeconds: 5)));

        Assert.Equal(RecordingState.Idle, _session.State);
    }

    [Fact]
    public async Task Levels_come_from_the_recorder_not_from_the_engines_replay()
    {
        var page = await RecordingAsync();

        page.Handle(new LevelEvent(Id, "mic", -6));
        Assert.Equal(0, page.MicMeter.Level);
        page.HandleRecorder(new RecorderLevelEvent("mic", -6));
        page.HandleRecorder(new RecorderLevelEvent("system", -6));

        Assert.True(page.MicMeter.Level > 0);
        Assert.True(page.SystemMeter.Level > 0);
    }

    [Fact]
    public void Recorder_levels_are_ignored_when_it_does_not_record_this_meeting()
    {
        var page = Create();

        Assert.False(page.HandleRecorder(new RecorderLevelEvent("mic", -6)));
        Assert.Equal(0, page.MicMeter.Level);
    }

    [Fact]
    public async Task A_new_title_goes_to_the_recording_and_to_the_engines_meeting()
    {
        var page = await RecordingAsync(engine: true);

        page.Title = "Renamed";
        _delay.Elapse();
        await page.TitleSave;

        Assert.Equal("Renamed", _recorder.OptionUpdates.Single()["title"]);
        Assert.Equal([(Id, "Renamed")], _engine.TitleUpdates);
        Assert.Equal("Renamed", _session.Title);
    }

    [Fact]
    public async Task A_title_before_the_engine_attached_is_kept_by_the_recording()
    {
        var page = await RecordingAsync(engine: true);
        _engine.TitleError = FakeEngineClient.ApiError("session_not_found", "not yet");

        page.Title = "Early";
        _delay.Elapse();
        await page.TitleSave;

        Assert.Equal("Early", _session.Title);
        Assert.Empty(_notified); // the engine takes it from the recording when it attaches
    }

    [Fact]
    public async Task A_title_the_recorder_refuses_is_reported()
    {
        var page = await RecordingAsync();
        _recorder.OptionsError = new EngineUnavailableException("gone", new HttpRequestException());

        page.Title = "Lost";
        _delay.Elapse();
        await page.TitleSave;

        Assert.Single(_notified);
        Assert.Empty(_engine.TitleUpdates);
    }

    [Fact]
    public void Connection_and_problems_of_the_recorder_are_shown()
    {
        var page = Create(recorder: false);

        page.HandleRecorder(new RecorderConnectionChangedEvent(true));
        page.HandleRecorder(new RecorderErrorEvent("disk_backlog", "40 s wait for the disk"));

        Assert.True(page.IsRecorderConnected);
        Assert.Contains("40 s wait for the disk", _notified.Single());
    }
}

/// <summary>A recording the page adopts shows its options and its lines so far (phase 62).</summary>
public sealed class ReattachTests
{
    private const string Id = "20261103_090000";

    private readonly FakeEngineClient _engine = new();
    private readonly FakeRecorderClient _recorder = new();
    private readonly RecordingSessionService _session = new();

    private RecorderPageViewModel Create(bool engine) =>
        new(_engine, new LocalizationService(), new FakePreferences(), new FakeClock(), new FakeTimer(),
            new MinutesTemplatesViewModel(_engine), _session, _ => { }, recorder: _recorder)
        {
            IsEngineConnected = engine,
            IsRecorderConnected = true,
        };

    private static Segment Line(string id, double start, string text) =>
        new(id, "mic", "mic", "Me", start, start + 1, text, false, []);

    private static RecorderStatusEvent Running(string options) =>
        new(new RecordingSummary(Id, "recording", null, 600, FakeRecorderClient.Options(options)));

    [Fact]
    public async Task The_options_and_the_lines_so_far_come_back()
    {
        _engine.Transcripts[Id] = new Transcript("raw", [Line("mic-000001", 1, "Bom dia"), Line("mic-000002", 5, "Vamos")]);
        var page = Create(engine: true);
        await page.LoadTemplatesAsync();

        page.HandleRecorder(Running(
            """{"language":"pt","template":"daily","translate_to":"es","vocabulary":["VozAta","JBL"],"live_transcription":true}"""));
        await page.TranscriptRestore;

        Assert.Equal("pt", page.SelectedLanguage.Value);
        Assert.Equal("daily", page.SelectedTemplate?.Id);
        Assert.Equal("es", page.SelectedTranslation.Value);
        Assert.Equal("VozAta, JBL", page.SessionTerms);
        Assert.Equal(["Bom dia", "Vamos"], page.Segments.Select(line => line.Text));
    }

    [Fact]
    public async Task Lines_that_arrived_live_meanwhile_are_kept_once()
    {
        _engine.Transcripts[Id] = new Transcript("raw", [Line("mic-000001", 1, "Earlier"), Line("mic-000002", 5, "Live")]);
        var page = Create(engine: false);
        page.HandleRecorder(Running("{}"));
        page.Handle(new SegmentEvent(Id, Line("mic-000002", 5, "Live")));

        page.IsEngineConnected = true; // the engine comes up: the earlier lines are read now
        await page.TranscriptRestore;

        Assert.Equal(["Earlier", "Live"], page.Segments.Select(line => line.Text));
    }

    [Fact]
    public async Task A_meeting_the_engine_has_not_attached_yet_keeps_the_live_lines()
    {
        _engine.TranscriptError = FakeEngineClient.ApiError("session_not_found", "not yet");
        var page = Create(engine: true);
        page.HandleRecorder(Running("{}"));
        page.Handle(new SegmentEvent(Id, Line("mic-000001", 1, "Live")));

        await page.TranscriptRestore;

        Assert.Equal(["Live"], page.Segments.Select(line => line.Text));
    }

    [Fact]
    public async Task A_recording_the_engine_makes_is_adopted_with_its_lines()
    {
        _engine.Transcripts[Id] = new Transcript("raw", [Line("mic-000001", 1, "Earlier")]);
        var page = Create(engine: true);

        page.Handle(new StatusEvent(Id, "recording", 30));
        await page.TranscriptRestore;

        Assert.Equal(["Earlier"], page.Segments.Select(line => line.Text));
    }
}
