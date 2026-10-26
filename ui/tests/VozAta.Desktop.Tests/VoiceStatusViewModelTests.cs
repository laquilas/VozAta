using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>The sidebar's voice command status (phase 59).</summary>
public sealed class VoiceStatusViewModelTests
{
    private readonly LocalizationService _localization = new();
    private readonly FakePreferences _preferences = new();
    private readonly RecordingSessionService _session = new() { State = RecordingState.Recording, SessionId = "s1" };
    private readonly FakeSound _sound = new();
    private readonly List<(TimeSpan Hold, TaskCompletionSource Done)> _holds = [];

    private VoiceStatusViewModel Create()
    {
        // no context: a released hold continues at once, as it would on the UI thread
        SynchronizationContext.SetSynchronizationContext(null);
        return new(_localization, _session, _preferences, _sound, Delay);
    }

    private Task Delay(TimeSpan hold, CancellationToken cancellationToken)
    {
        var done = new TaskCompletionSource();
        _holds.Add((hold, done));
        return done.Task;
    }

    /// <summary>End a hold: what it does next runs at once (no synchronization context).</summary>
    private static Task ReleaseAsync(VoiceStatusViewModel status, (TimeSpan Hold, TaskCompletionSource Done) hold)
    {
        hold.Done.SetResult();
        Assert.NotNull(status);
        return Task.CompletedTask;
    }

    private static RequestUpdatedEvent Voice(
        string status, string kind = "minutes_so_far", string id = "r1", string? message = null, string session = "s1") =>
        new(session, new RequestEntry(
            id, "2026-10-23T10:00:00-03:00", 754.0, kind, "voice", kind == "ask" ? "O que decidimos?" : "gere a ata",
            status, null, message, null));

    [Fact]
    public void It_is_gray_and_shown_only_while_recording()
    {
        var status = Create();

        Assert.True(status.IsVisible);
        Assert.True(status.IsIdle);
        Assert.Equal(_localization["VoiceStatus_Idle"], status.Text);
        Assert.Equal(_localization["VoiceStatus_IdleHint"], status.ToolTipText);

        _session.State = RecordingState.Idle;

        Assert.False(status.IsVisible);
    }

    [Fact]
    public async Task Minutes_go_green_yellow_green_then_gray()
    {
        var status = Create();

        status.OnRequest(Voice("recognized"));
        status.OnRequest(Voice("running")); // arrives at once: held until the green was seen

        Assert.Equal(VoiceStatusState.Recognized, status.State);
        Assert.True(status.IsOk);
        Assert.Equal(_localization["VoiceStatus_Minutes"], status.Text);
        Assert.Equal(VoiceStatusViewModel.RecognizedHold, _holds[0].Hold);
        Assert.Equal(1, _sound.Chimes);

        await ReleaseAsync(status, _holds[0]);

        Assert.Equal(VoiceStatusState.Processing, status.State);
        Assert.True(status.IsBusy);
        Assert.Equal(_localization["VoiceStatus_Writing"], status.Text);

        status.OnRequest(Voice("done"));

        Assert.Equal(VoiceStatusState.Done, status.State);
        Assert.Equal(_localization.Format("VoiceStatus_MinutesReadyUpTo", "00:12:34"), status.Text);
        Assert.Contains(_localization["VoiceStatus_ClickToOpen"], status.ToolTipText);
        Assert.Equal(VoiceStatusViewModel.DoneHold, _holds[1].Hold);

        await ReleaseAsync(status, _holds[1]);

        Assert.True(status.IsIdle);
    }

    [Fact]
    public async Task A_question_shows_itself_then_answering_then_ready()
    {
        var status = Create();

        status.OnRequest(Voice("recognized", "ask"));
        Assert.Equal("O que decidimos?", status.Text);
        await ReleaseAsync(status, _holds[0]);
        status.OnRequest(Voice("running", "ask"));
        Assert.Equal(_localization["VoiceStatus_Answering"], status.Text);

        status.OnRequest(Voice("done", "ask"));

        Assert.Equal(_localization["VoiceStatus_AnswerReady"], status.Text);
    }

    [Fact]
    public async Task A_failure_is_red_with_its_reason_then_gray()
    {
        var status = Create();
        status.OnRequest(Voice("recognized"));
        await ReleaseAsync(status, _holds[0]);

        status.OnRequest(Voice("failed", message: "llm_unreachable"));

        Assert.True(status.IsFailed);
        Assert.Equal(
            _localization.Format("VoiceStatus_Failed", _localization["VoiceStatus_Error_llm_unreachable"]), status.Text);
        Assert.Equal(VoiceStatusViewModel.FailedHold, _holds[1].Hold);
        await ReleaseAsync(status, _holds[1]);
        Assert.True(status.IsIdle);
    }

    [Fact]
    public async Task An_unknown_failure_points_to_the_notification()
    {
        var status = Create();
        status.OnRequest(Voice("recognized"));
        await ReleaseAsync(status, _holds[0]);

        status.OnRequest(Voice("failed", message: "something_new"));

        Assert.Equal(_localization.Format("VoiceStatus_Failed", _localization["VoiceStatus_Error_other"]), status.Text);
    }

    [Fact]
    public async Task A_busy_failure_during_the_green_shows_after_it()
    {
        var status = Create();
        status.OnRequest(Voice("recognized"));
        status.OnRequest(Voice("failed", message: "voice_command_busy"));

        Assert.True(status.IsOk);
        await ReleaseAsync(status, _holds[0]);

        Assert.True(status.IsFailed);
    }

    [Fact]
    public async Task A_repeat_says_already_on_it_then_shows_the_running_one_again()
    {
        var status = Create();
        status.OnRequest(Voice("recognized"));
        await ReleaseAsync(status, _holds[0]);
        status.OnRequest(Voice("running"));

        status.OnRequest(Voice("ignored", id: "r2", message: "voice_command_repeated"));

        Assert.True(status.IsBusy);
        Assert.Equal(_localization["VoiceStatus_RepeatMinutes"], status.Text);
        await ReleaseAsync(status, _holds[1]);
        Assert.Equal(_localization["VoiceStatus_Writing"], status.Text);
    }

    [Fact]
    public async Task A_repeat_with_nothing_running_goes_back_to_gray()
    {
        var status = Create();

        status.OnRequest(Voice("ignored", "ask", message: "voice_command_repeated"));
        Assert.Equal(_localization["VoiceStatus_RepeatAsk"], status.Text);
        await ReleaseAsync(status, _holds[0]);

        Assert.True(status.IsIdle);
    }

    [Fact]
    public async Task A_newer_command_cancels_the_old_hold()
    {
        var status = Create();
        status.OnRequest(Voice("recognized"));
        await ReleaseAsync(status, _holds[0]);
        status.OnRequest(Voice("done"));

        status.OnRequest(Voice("recognized", "ask", "r2"));
        await ReleaseAsync(status, _holds[1]); // the old 5 s "ready" ends: nothing changes

        Assert.Equal("O que decidimos?", status.Text);
        await ReleaseAsync(status, _holds[2]);
        Assert.Equal(VoiceStatusState.Recognized, status.State); // no pending state arrived
    }

    [Fact]
    public async Task A_stale_green_hold_does_not_release_the_newer_one()
    {
        var status = Create();
        status.OnRequest(Voice("recognized"));
        status.OnRequest(Voice("recognized", id: "r2"));
        status.OnRequest(Voice("running", id: "r2"));

        await ReleaseAsync(status, _holds[0]); // the first green ends: the second still holds
        Assert.True(status.IsOk);
        await ReleaseAsync(status, _holds[1]);

        Assert.True(status.IsBusy);
    }

    [Fact]
    public void Other_sources_and_meetings_are_ignored()
    {
        var status = Create();

        status.OnRequest(Voice("recognized", session: "other"));
        status.OnRequest(new RequestUpdatedEvent(
            "s1", new RequestEntry("r9", "t", null, "minutes", "app", "", "running", null, null, null)));
        status.OnRequest(new RequestUpdatedEvent(
            null, new RequestEntry("r8", "t", null, "minutes", "voice", "", "running", null, null, null)));

        Assert.True(status.IsIdle);
        Assert.Equal(0, _sound.Chimes);
    }

    [Fact]
    public async Task Stopping_the_recording_resets_it()
    {
        var status = Create();
        status.OnRequest(Voice("recognized"));
        await ReleaseAsync(status, _holds[0]);
        status.OnRequest(Voice("running"));

        _session.State = RecordingState.Idle;

        Assert.True(status.IsIdle);
        Assert.False(status.IsVisible);
    }

    [Fact]
    public async Task Opening_a_ready_result_raises_it()
    {
        var status = Create();
        RequestEntry? opened = null;
        status.Opened += request => opened = request;
        Assert.False(status.OpenCommand.CanExecute(null));
        status.OnRequest(Voice("recognized"));
        await ReleaseAsync(status, _holds[0]);
        status.OnRequest(Voice("done"));

        status.OpenCommand.Execute(null);

        Assert.Equal("r1", opened?.Id);
    }

    [Fact]
    public void The_sound_can_be_switched_off_and_is_remembered()
    {
        var status = Create();
        Assert.True(status.IsSoundOn);

        status.IsSoundOn = false;
        status.OnRequest(Voice("recognized"));

        Assert.Equal(0, _sound.Chimes);
        Assert.False(_preferences.Data.VoiceCommandSound);
        Assert.False(Create().IsSoundOn);
    }

    [Fact]
    public void Minutes_ready_without_a_second_have_no_time()
    {
        var status = Create();
        var entry = new RequestEntry("r1", "t", null, "minutes_so_far", "voice", "gere a ata", "done", "p1", null, null);

        status.OnRequest(new RequestUpdatedEvent("s1", entry));

        Assert.Equal(_localization["VoiceStatus_MinutesReady"], status.Text);
    }

    [Fact]
    public void The_texts_follow_the_language()
    {
        var status = Create();
        var changed = new List<string?>();
        status.PropertyChanged += (_, args) => changed.Add(args.PropertyName);

        status.RefreshTexts();

        Assert.Contains(nameof(VoiceStatusViewModel.Text), changed);
    }

    [Fact]
    public void The_chime_is_a_short_wav()
    {
        var wav = Chime.Wav();

        Assert.Equal("RIFF"u8.ToArray(), wav[..4]);
        Assert.Equal("WAVE"u8.ToArray(), wav[8..12]);
        Assert.Equal(44 + (Chime.SampleRate * 90 / 1000 * 2 * 2), wav.Length);
        new SilentSoundPlayer().PlayChime(); // plays nothing
    }

    private sealed class FakeSound : ISoundPlayer
    {
        public int Chimes { get; private set; }

        public void PlayChime() => Chimes++;
    }
}
