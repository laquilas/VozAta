using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

public sealed class MainViewModelTests
{
    private readonly FakeEngineClient _client = new();
    private readonly FakeEngineEvents _events = new();
    private readonly FakeEngineProcess _process = new();
    private readonly FakeDialogs _dialogs = new();
    private readonly LocalizationService _localization = new();
    private readonly FakePreferences _preferences = new();
    private readonly FakeClock _clock = new();
    private readonly FakeTimer _timer = new();
    private readonly FakeShell _shell = new();

    private static readonly AudioDevice Mic = new(4, "JBL Quantum Stream", 48000, 1);
    private static readonly AudioDevice Laptop = new(1, "Microphone Array (Intel)", 48000, 2);
    private static readonly AudioDevice Speakers = new(7, "Speakers [Loopback]", 48000, 2);

    public MainViewModelTests()
    {
        _client.Devices = new DeviceList([Laptop, Mic], [Speakers], DefaultInputId: 4, DefaultLoopbackId: 7);
    }

    private MainViewModel Create() =>
        new(_client, _events, _process, new ImmediateDispatcher(), _localization, _dialogs, _preferences, _clock, _timer, _shell, new FakeFileSaver(), new FakeThemeService());

    private async Task<MainViewModel> ReadyAsync()
    {
        var viewModel = Create();
        await viewModel.InitializeAsync();
        await SendAsync(viewModel, new ConnectionChangedEvent(true));
        return viewModel;
    }

    /// <summary>Feed one event and wait until the view model has handled it.</summary>
    private async Task SendAsync(MainViewModel viewModel, EngineEvent engineEvent)
    {
        var before = viewModel.HandledEvents;
        _events.Send(engineEvent);
        for (var i = 0; i < 200 && viewModel.HandledEvents == before; i++)
        {
            await Task.Delay(5);
        }

        Assert.True(viewModel.HandledEvents > before, $"{engineEvent} was not handled");
    }

    private static Segment Line(string channel, string label, double start, string text) =>
        new($"{channel}-000001", channel, channel, label, start, start + 1, text, false, []);

    [Fact]
    public async Task Initialization_reads_health_settings_and_the_ui_language()
    {
        _client.SettingValues["APP_LANGUAGE"] = "pt-BR";
        _client.SettingValues["TRANSCRIPTION_LANGUAGE"] = "es";

        var viewModel = await ReadyAsync();

        Assert.Equal("pt-BR", _localization.Language);
        Assert.Equal("pt-BR", viewModel.SelectedAppLanguage!.Value);
        Assert.Equal("es", viewModel.Recorder.SelectedLanguage.Value);
        Assert.Equal("GPU: RTX 3050 (6144 MB)", viewModel.Health.GpuText);
        Assert.Equal("Fala: large-v3 em auto", viewModel.Health.SpeechText);
        Assert.Equal("Ata: qwen2.5:7b pronto", viewModel.Health.MinutesText);
        Assert.Equal("Motor conectado", viewModel.EngineText);
        Assert.True(viewModel.Recorder.StartCommand.CanExecute(null));
        Assert.Equal(RecordingState.Idle, viewModel.Recorder.State);
    }

    [Fact]
    public async Task Initialization_loads_the_devices_and_the_meter_labels()
    {
        _client.SettingValues["MIC_LABEL"] = "Host";

        var viewModel = await ReadyAsync();

        Assert.Equal([Laptop, Mic], viewModel.Recorder.Devices.Inputs);
        Assert.Equal((Mic, Speakers), (viewModel.Recorder.Devices.SelectedMic, viewModel.Recorder.Devices.SelectedLoopback));
        Assert.Equal(("Host", "Others"), (viewModel.Recorder.MicMeter.Label, viewModel.Recorder.SystemMeter.Label));
        viewModel.SelectedAppLanguage = viewModel.AppLanguages.Single(option => option.Value == "pt-BR");
        Assert.Equal(("Host", "Outros"), (viewModel.Recorder.MicMeter.Label, viewModel.Recorder.SystemMeter.Label));
    }

    [Fact]
    public async Task A_device_list_failure_is_shown_and_recording_still_uses_the_engine_defaults()
    {
        _client.DevicesError = FakeEngineClient.ApiError("devices_failed", "WASAPI did not answer.");

        var viewModel = await ReadyAsync();
        await viewModel.Recorder.StartCommand.ExecuteAsync(null);

        Assert.Contains("WASAPI did not answer.", viewModel.Notifications);
        Assert.Equal(new StartSessionRequest(null, null, "pt", "general"), _client.StartRequests.Single());
    }

    [Fact]
    public async Task Start_sends_the_selected_devices_and_locks_them_while_recording()
    {
        var viewModel = await ReadyAsync();
        viewModel.Recorder.Devices.SelectedMic = Laptop;

        await viewModel.Recorder.StartCommand.ExecuteAsync(null);

        var request = _client.StartRequests.Single();
        Assert.Equal((1, 7), (request.MicDeviceId, request.SystemDeviceId));
        Assert.False(viewModel.Recorder.Devices.IsEnabled);
        await SendAsync(viewModel, new StatusEvent("20261016_090000", "done", 3));
        Assert.True(viewModel.Recorder.Devices.IsEnabled);
    }

    [Fact]
    public async Task Level_events_drive_the_meters_and_the_timer_runs_only_while_recording()
    {
        var viewModel = await ReadyAsync();
        Assert.Equal(0, _timer.Running);
        await viewModel.Recorder.StartCommand.ExecuteAsync(null);
        Assert.Equal(1, _timer.Running);

        await SendAsync(viewModel, new LevelEvent("s", "mic", -15));
        await SendAsync(viewModel, new LevelEvent("s", "system", -30));
        Assert.Equal((0.75, 0.5), (viewModel.Recorder.MicMeter.Level, viewModel.Recorder.SystemMeter.Level));
        await SendAsync(viewModel, new LevelEvent("s", "mic", -60));
        _clock.Advance(TimeSpan.FromSeconds(0.2));
        _timer.Tick();
        Assert.True(viewModel.Recorder.MicMeter.Level < 0.75);

        await SendAsync(viewModel, new StatusEvent("20261016_090000", "done", 3));
        Assert.Equal(0, _timer.Running);
        Assert.Equal(0, viewModel.Recorder.MicMeter.Level);
    }

    [Fact]
    public async Task Silent_system_audio_shows_the_no_signal_hint_but_not_while_paused()
    {
        var viewModel = await ReadyAsync();
        await viewModel.Recorder.StartCommand.ExecuteAsync(null);
        await SendAsync(viewModel, new StatusEvent("20261016_090000", "paused", 1));

        _clock.Advance(TimeSpan.FromSeconds(31));
        _timer.Tick();
        Assert.False(viewModel.Recorder.SystemMeter.NoSignal);
        await SendAsync(viewModel, new StatusEvent("20261016_090000", "recording", 32));
        _clock.Advance(TimeSpan.FromSeconds(30));
        _timer.Tick();

        Assert.True(viewModel.Recorder.SystemMeter.NoSignal);
        Assert.False(viewModel.Recorder.MicMeter.NoSignal);
    }

    [Fact]
    public async Task The_window_size_is_restored_and_saved_on_shutdown()
    {
        _preferences.Data = new UiPreferencesData(WindowWidth: 1200, WindowHeight: 820);
        var viewModel = await ReadyAsync();
        Assert.Equal((1200d, 820d), (viewModel.WindowWidth, viewModel.WindowHeight));

        viewModel.Recorder.Devices.SelectedMic = Laptop;
        viewModel.WindowWidth = 1000;
        await viewModel.ShutdownAsync(TimeSpan.FromSeconds(1));

        Assert.Equal((1000d, 820d), (_preferences.Data.WindowWidth, _preferences.Data.WindowHeight));
        Assert.Equal(new DeviceChoice(1, "Microphone Array (Intel)"), _preferences.Data.Mic);  // kept
    }

    [Fact]
    public async Task Without_saved_preferences_the_window_uses_its_default_size()
    {
        var viewModel = await ReadyAsync();

        Assert.Equal((MainViewModel.DefaultWidth, MainViewModel.DefaultHeight), (viewModel.WindowWidth, viewModel.WindowHeight));
    }

    [Fact]
    public async Task The_history_loads_at_start_up_and_refreshes_when_a_session_starts_and_ends()
    {
        _client.Sessions.Add(new SessionSummary("20261015_100000", "done", null, null, 60, "pt", true));

        var viewModel = await ReadyAsync();
        Assert.Single(viewModel.History.Rows);
        Assert.Single(_client.ListRequests);

        await viewModel.Recorder.StartCommand.ExecuteAsync(null);
        await viewModel.HistoryRefresh;
        Assert.Equal(2, _client.ListRequests.Count);
        await SendAsync(viewModel, new StatusEvent("20261016_090000", "paused", 3));
        Assert.Equal(2, _client.ListRequests.Count);  // still the same session
        await SendAsync(viewModel, new StatusEvent("20261016_090000", "done", 5));
        await viewModel.HistoryRefresh;

        Assert.Equal(3, _client.ListRequests.Count);
        Assert.Equal(3, _client.DayRequests.Count); // the Meetings page follows (phase 36)
    }

    [Fact]
    public async Task The_meetings_page_reloads_on_events_follows_the_language_and_deletes_before_closing()
    {
        var started = new DateTimeOffset(_clock.Now.LocalDateTime.Date.AddHours(9)); // today, local time
        _client.Sessions.Add(new SessionSummary("20261016_090000", "done", started, null, 60, "pt", true));
        var viewModel = await ReadyAsync();
        Assert.Same(viewModel.Meetings, viewModel.Shell.Pages.Single(page => page.Key == ShellViewModel.Meetings).Page);
        Assert.Single(_client.DayRequests);

        await SendAsync(viewModel, new MinutesReadyEvent("20261016_090000"));
        await viewModel.HistoryRefresh;
        await SendAsync(viewModel, new ActionItemsReadyEvent("20261016_090000", 2));
        await viewModel.HistoryRefresh;
        Assert.Equal(3, _client.DayRequests.Count);

        _localization.SetLanguage("es");
        Assert.Equal("Esta semana", viewModel.Meetings.WeekLabel);

        var row = viewModel.Meetings.Weeks.Single().Days.Single().Rows.Single();
        await viewModel.Meetings.DeleteCommand.ExecuteAsync(row);
        Assert.Empty(_client.Deleted); // waiting for "Undo"
        await viewModel.ShutdownAsync(TimeSpan.FromMilliseconds(10));

        Assert.Equal(["20261016_090000"], _client.Deleted);
    }

    [Fact]
    public async Task Minutes_and_error_events_reach_the_open_session()
    {
        const string id = "20261015_100000";
        _client.Sessions.Add(new SessionSummary(id, "done", null, null, 60, "pt", false));
        _client.Details[id] = new SessionDetail(id, "done", null, null, 60, "pt", false, [], @"C:
");
        _client.Transcripts[id] = new Transcript("raw", [Line("mic", "Me", 1, "Hi.")]);
        var viewModel = await ReadyAsync();
        viewModel.History.Selected = viewModel.History.Rows[0];
        await viewModel.History.DetailLoading;
        var detail = viewModel.History.Detail!;

        await detail.RegenerateMinutesCommand.ExecuteAsync(null);
        await SendAsync(viewModel, new ErrorEvent(id, "minutes_failed", "Ollama offline"));
        Assert.Equal("Ollama offline", detail.Error);
        await detail.RegenerateMinutesCommand.ExecuteAsync(null);
        _client.MinutesText[id] = "# Minutes";
        await SendAsync(viewModel, new MinutesReadyEvent(id));
        await viewModel.HistoryRefresh;

        Assert.True(detail.HasMinutes);
        Assert.False(detail.IsBusy);
        Assert.Contains(_localization["MinutesReady"], viewModel.Notifications);
    }

    [Fact]
    public async Task Action_items_events_reach_the_open_session()
    {
        const string id = "20261015_100000";
        _client.Sessions.Add(new SessionSummary(id, "done", null, null, 60, "pt", true));
        _client.Details[id] = new SessionDetail(id, "done", null, null, 60, "pt", true, [], @"C:\r");
        _client.Transcripts[id] = new Transcript("raw", [Line("mic", "Me", 1, "Hi.")]);
        var viewModel = await ReadyAsync();
        viewModel.History.Selected = viewModel.History.Rows[0];
        await viewModel.History.DetailLoading;
        var actionItems = viewModel.History.Detail!.ActionItems;
        Assert.Contains($"action-items {id}", _client.Calls);
        await actionItems.ExtractCommand.ExecuteAsync(null);

        await SendAsync(viewModel, new ErrorEvent(id, "action_items_failed", "Ollama offline"));
        Assert.Equal("Ollama offline", actionItems.Error);
        await actionItems.ExtractCommand.ExecuteAsync(null);
        _client.ActionItems[id] = [new ActionItem("a1", "Call Bob", null, null, [], null)];
        await SendAsync(viewModel, new ActionItemsReadyEvent(id, 1));
        await viewModel.HistoryRefresh;

        Assert.False(actionItems.IsExtracting);
        Assert.Equal("Call Bob", Assert.Single(actionItems.Items).Description);
    }

    [Fact]
    public async Task Speakers_relabeled_reloads_the_live_lines_and_the_open_detail()
    {
        const string id = "20261015_100000";
        _client.Sessions.Add(new SessionSummary(id, "done", null, null, 60, "pt", false));
        _client.Details[id] = new SessionDetail(id, "done", null, null, 60, "pt", false, [], @"C:\r");
        _client.Transcripts[id] = new Transcript("raw", [Line("system", "Others", 1, "Hi.")]);
        var viewModel = await ReadyAsync();
        viewModel.History.Selected = viewModel.History.Rows[0];
        await viewModel.History.DetailLoading;
        await SendAsync(viewModel, new SegmentEvent(id, Line("system", "User 2", 1, "Hi.")));
        _client.Transcripts[id] = new Transcript("diarized", [Line("system", "User 1", 1, "Hi.")]);

        await SendAsync(viewModel, new SpeakersRelabeledEvent(id));
        await viewModel.HistoryRefresh;

        Assert.Equal(["User 1"], viewModel.Recorder.Segments.Select(line => line.Label));
        Assert.Equal(["User 1"], viewModel.History.Detail!.Lines.Select(line => line.Label));
    }

    [Fact]
    public async Task Speakers_relabeled_for_another_session_leaves_the_live_lines()
    {
        var viewModel = await ReadyAsync();
        await SendAsync(viewModel, new SegmentEvent("s1", Line("system", "User 2", 1, "Hi.")));
        _client.Transcripts["s0"] = new Transcript("diarized", [Line("system", "User 1", 1, "Old.")]);

        await SendAsync(viewModel, new SpeakersRelabeledEvent("s0"));
        await viewModel.HistoryRefresh;
        await SendAsync(viewModel, new SpeakersRelabeledEvent(null));
        await viewModel.HistoryRefresh;

        Assert.Equal(["Hi."], viewModel.Recorder.Segments.Select(line => line.Text));
    }

    [Fact]
    public async Task A_failed_reload_after_relabeling_is_notified()
    {
        var viewModel = await ReadyAsync();
        await SendAsync(viewModel, new SegmentEvent("s1", Line("system", "User 2", 1, "Hi.")));
        _client.TranscriptError = new EngineUnavailableException("refused", new HttpRequestException("refused"));

        await SendAsync(viewModel, new SpeakersRelabeledEvent("s1"));
        await viewModel.HistoryRefresh;

        Assert.Contains(_localization["EngineUnavailable"], viewModel.Notifications);
        Assert.Equal(["User 2"], viewModel.Recorder.Segments.Select(line => line.Label));
    }

    [Fact]
    public async Task The_history_texts_follow_the_ui_language()
    {
        _client.Sessions.Add(new SessionSummary("20261015_100000", "done", null, null, 60, "pt", true));
        var viewModel = await ReadyAsync();

        viewModel.SelectedAppLanguage = viewModel.AppLanguages.Single(option => option.Value == "es");

        Assert.Equal("Portugués", viewModel.History.Rows[0].Language);
    }

    private void AddSchema(string key, string type, string group, params string[] choices) =>
        _client.Schema.Add(new SettingSchema(
            key, type, System.Text.Json.JsonSerializer.SerializeToElement((object?)null), choices.Length > 0 ? choices : null, false, group));

    [Fact]
    public async Task The_settings_page_loads_at_start_up()
    {
        AddSchema("CHUNK_SECONDS", "number", "segmentation");
        _client.SettingValues["CHUNK_SECONDS"] = 5.0;

        var viewModel = await ReadyAsync();

        Assert.Equal(5.0m, viewModel.Settings.Groups.Single().Editors.Single().NumberValue);
    }

    [Fact]
    public async Task Saved_settings_apply_languages_and_labels_to_the_window()
    {
        AddSchema("APP_LANGUAGE", "choice", "general", "en", "pt-BR", "es");
        AddSchema("TRANSCRIPTION_LANGUAGE", "choice", "general", "en", "pt", "es", "auto");
        AddSchema("MIC_LABEL", "string", "general");
        _client.SettingValues["MIC_LABEL"] = null;
        var viewModel = await ReadyAsync();
        var editors = viewModel.Settings.Groups.Single().Editors;
        editors[0].SelectedChoice = editors[0].Choices.Single(choice => choice.Value == "es");
        editors[1].SelectedChoice = editors[1].Choices.Single(choice => choice.Value == "auto");
        editors[2].TextValue = "Host";

        await viewModel.Settings.SaveCommand.ExecuteAsync(null);

        Assert.Equal("es", _localization.Language);
        Assert.Equal("es", viewModel.SelectedAppLanguage!.Value);
        Assert.Equal("auto", viewModel.Recorder.SelectedLanguage.Value);
        Assert.Equal("Host", viewModel.Recorder.MicMeter.Label);
        Assert.Single(_client.Updates);  // the language switch did not save again
    }

    [Fact]
    public async Task The_interface_language_selector_saves_the_choice_after_start_up()
    {
        _client.SettingValues["APP_LANGUAGE"] = "pt-BR";
        var viewModel = await ReadyAsync();
        Assert.Empty(_client.Updates);  // restoring the saved language is not a change

        viewModel.SelectedAppLanguage = viewModel.AppLanguages.Single(option => option.Value == "es");
        await viewModel.LanguageSave;

        Assert.Equal("es", (string)_client.Updates.Single()["APP_LANGUAGE"]!);
    }

    [Fact]
    public async Task A_failed_language_save_is_shown_but_the_language_still_switches()
    {
        var viewModel = await ReadyAsync();
        _client.UpdateError = new EngineUnavailableException("refused", new HttpRequestException());

        viewModel.SelectedAppLanguage = viewModel.AppLanguages.Single(option => option.Value == "pt-BR");
        await viewModel.LanguageSave;

        Assert.Equal("pt-BR", _localization.Language);
        Assert.Contains(_localization["EngineUnavailable"], viewModel.Notifications);
    }

    [Fact]
    public async Task Pause_and_resume_toggle_through_the_engine()
    {
        var viewModel = await ReadyAsync();
        Assert.False(viewModel.Recorder.PauseResumeCommand.CanExecute(null));
        await viewModel.Recorder.StartCommand.ExecuteAsync(null);
        Assert.Equal("Pause", viewModel.Recorder.PauseResumeText);

        await viewModel.Recorder.PauseResumeCommand.ExecuteAsync(null);
        Assert.Equal(RecordingState.Paused, viewModel.Recorder.State);
        Assert.True(viewModel.Recorder.IsPaused && viewModel.Recorder.IsRecording && !viewModel.Recorder.IsActivelyRecording);
        Assert.Equal("Resume", viewModel.Recorder.PauseResumeText);
        Assert.True(viewModel.Recorder.StopCommand.CanExecute(null));

        await viewModel.Recorder.PauseResumeCommand.ExecuteAsync(null);

        Assert.Equal(RecordingState.Recording, viewModel.Recorder.State);
        Assert.Equal(["pause", "resume"], _client.Calls.Where(call => call is "pause" or "resume"));
    }

    [Fact]
    public async Task The_timer_freezes_while_paused_and_follows_the_engine_after_resume()
    {
        var viewModel = await ReadyAsync();
        await viewModel.Recorder.StartCommand.ExecuteAsync(null);
        await SendAsync(viewModel, new StatusEvent("20261016_090000", "recording", 10));

        await SendAsync(viewModel, new StatusEvent("20261016_090000", "paused", 12));
        await SendAsync(viewModel, new StatusEvent("20261016_090000", "paused", 40));  // heartbeat while paused
        Assert.Equal("00:00:12", viewModel.Recorder.Elapsed);
        await SendAsync(viewModel, new StatusEvent("20261016_090000", "recording", 41));

        Assert.Equal("00:00:41", viewModel.Recorder.Elapsed);
    }

    [Fact]
    public async Task A_rejected_pause_is_shown_and_keeps_recording()
    {
        var viewModel = await ReadyAsync();
        await viewModel.Recorder.StartCommand.ExecuteAsync(null);
        _client.PauseError = FakeEngineClient.ApiError("no_active_session", "Nothing is recording.");

        await viewModel.Recorder.PauseResumeCommand.ExecuteAsync(null);

        Assert.Equal(RecordingState.Recording, viewModel.Recorder.State);
        Assert.Contains("Nothing is recording.", viewModel.Notifications);
    }

    [Fact]
    public async Task The_pause_button_text_follows_the_ui_language()
    {
        var viewModel = await ReadyAsync();

        viewModel.SelectedAppLanguage = viewModel.AppLanguages.Single(option => option.Value == "pt-BR");

        Assert.Equal("Pausar", viewModel.Recorder.PauseResumeText);
    }

    [Fact]
    public async Task Health_without_gpu_and_unreachable_llm()
    {
        _client.Health = _client.Health with
        {
            Gpu = new GpuStatus(false, null, null),
            Llm = new LlmStatus("ollama", "qwen2.5:7b", false),
        };

        var viewModel = await ReadyAsync();

        Assert.Equal("No GPU (CPU only)", viewModel.Health.GpuText);
        Assert.Equal("Minutes: qwen2.5:7b not reachable (start Ollama)", viewModel.Health.MinutesText);
    }

    [Fact]
    public async Task A_failed_engine_start_is_reported_and_blocks_recording()
    {
        _process.Result = EngineStartResult.Failed;
        var viewModel = Create();

        await viewModel.InitializeAsync();

        Assert.Equal(_localization["EngineStartFailed"], viewModel.EngineText);
        Assert.Contains(_localization["EngineStartFailed"], viewModel.Notifications);
        Assert.False(viewModel.Recorder.StartCommand.CanExecute(null));
        Assert.DoesNotContain("settings", _client.Calls);
    }

    [Fact]
    public async Task Unknown_or_missing_languages_fall_back_to_safe_defaults()
    {
        _client.SettingValues["APP_LANGUAGE"] = null;
        _client.SettingValues["TRANSCRIPTION_LANGUAGE"] = "fr";

        var viewModel = await ReadyAsync();

        Assert.Equal("en", _localization.Language);
        Assert.Equal("en", viewModel.Recorder.SelectedLanguage.Value);
    }

    [Fact]
    public async Task Start_sends_the_selected_language_and_clears_the_previous_transcript()
    {
        var viewModel = await ReadyAsync();
        viewModel.Recorder.Segments.Add(new TranscriptLine("00:00:01", "Me", "old", "mic"));
        viewModel.Recorder.SelectedLanguage = viewModel.Recorder.ConversationLanguages.Single(option => option.Value == "auto");

        await viewModel.Recorder.StartCommand.ExecuteAsync(null);

        Assert.Equal("auto", _client.StartRequests.Single().Language);
        Assert.Empty(viewModel.Recorder.Segments);
        Assert.Equal(RecordingState.Recording, viewModel.Recorder.State);
        Assert.True(viewModel.Recorder.IsRecording);
        Assert.False(viewModel.Recorder.StartCommand.CanExecute(null));
        Assert.True(viewModel.Recorder.StopCommand.CanExecute(null));
    }

    [Fact]
    public async Task Start_errors_show_the_engine_message_and_return_to_idle()
    {
        var viewModel = await ReadyAsync();
        _client.StartError = FakeEngineClient.ApiError("device_timeout", "O microfone não abriu.");

        await viewModel.Recorder.StartCommand.ExecuteAsync(null);

        Assert.Equal(RecordingState.Idle, viewModel.Recorder.State);
        Assert.Contains("O microfone não abriu.", viewModel.Notifications);
    }

    [Fact]
    public async Task Start_while_the_engine_is_down_shows_unavailable()
    {
        var viewModel = await ReadyAsync();
        _client.StartError = new EngineUnavailableException("refused", new HttpRequestException());

        await viewModel.Recorder.StartCommand.ExecuteAsync(null);

        Assert.Contains(_localization["EngineUnavailable"], viewModel.Notifications);
        Assert.Equal(RecordingState.Idle, viewModel.Recorder.State);
    }

    [Fact]
    public async Task Status_events_drive_the_state_machine_and_elapsed_time()
    {
        var viewModel = await ReadyAsync();
        await viewModel.Recorder.StartCommand.ExecuteAsync(null);

        await SendAsync(viewModel, new StatusEvent("20261016_090000", "recording", 3725.4));
        Assert.Equal("01:02:05", viewModel.Recorder.Elapsed);
        await SendAsync(viewModel, new StatusEvent("20261016_090000", "paused", 3726));
        Assert.Equal(RecordingState.Paused, viewModel.Recorder.State);
        Assert.Equal(_localization["StatePaused"], viewModel.Recorder.StatusText);
        await viewModel.Recorder.StopCommand.ExecuteAsync(null);
        Assert.Equal(RecordingState.Idle, viewModel.Recorder.State);
        Assert.False(viewModel.Recorder.StopCommand.CanExecute(null));
        await SendAsync(viewModel, new StatusEvent("20261016_090000", "finalizing", 3729));
        await SendAsync(viewModel, new StatusEvent("20261016_090000", "done", 3730));

        Assert.Equal(RecordingState.Idle, viewModel.Recorder.State);
        Assert.True(viewModel.Recorder.StartCommand.CanExecute(null));
    }

    [Fact]
    public async Task Connecting_while_the_engine_records_adopts_its_session()
    {
        var viewModel = await ReadyAsync();

        await SendAsync(viewModel, new StatusEvent("20261016_090000", "recording", 10));

        Assert.Equal(RecordingState.Recording, viewModel.Recorder.State);
        await SendAsync(viewModel, new StatusEvent(null, "idle", null));
        Assert.Equal(RecordingState.Idle, viewModel.Recorder.State);
    }

    [Fact]
    public async Task Segments_are_appended_with_timestamp_label_and_speaker_colour()
    {
        var viewModel = await ReadyAsync();

        await SendAsync(viewModel, new SegmentEvent("s", Line("mic", "Eu", 65.2, "Bom dia.")));
        await SendAsync(viewModel, new SegmentEvent("s", Line("system", "Outros", 70, "Oi.")));

        Assert.Equal(
            [new TranscriptLine("00:01:05", "Eu", "Bom dia.", "mic"), new TranscriptLine("00:01:10", "Outros", "Oi.", "system")],
            viewModel.Recorder.Segments);
        Assert.Equal("[00:01:05] Eu: Bom dia.", viewModel.Recorder.Segments[0].Display);
        Assert.True(viewModel.Recorder.Segments[0].IsMic);
        Assert.False(viewModel.Recorder.Segments[0].IsSystem);
        Assert.True(viewModel.Recorder.Segments[1].IsSystem);
        Assert.False(viewModel.Recorder.Segments[1].IsMic);
    }

    [Theory]
    [InlineData("mic", true, false)]
    [InlineData("system", false, true)]
    [InlineData("mixed", false, false)]
    public void The_channel_picks_the_speaker_colour_class(string channel, bool isMic, bool isSystem)
    {
        var line = new TranscriptLine("00:00:01", "A", "text", channel);

        Assert.Equal(isMic, line.IsMic);
        Assert.Equal(isSystem, line.IsSystem);
    }

    [Fact]
    public async Task Language_detected_updates_the_badge_in_the_ui_language()
    {
        var viewModel = await ReadyAsync();

        await SendAsync(viewModel, new LanguageDetectedEvent("s", "pt"));
        Assert.Equal("Detected: Portuguese", viewModel.Recorder.DetectedLanguage);
        viewModel.SelectedAppLanguage = viewModel.AppLanguages.Single(option => option.Value == "es");

        Assert.Equal("Detectado: Portugués", viewModel.Recorder.DetectedLanguage);
        Assert.Equal("es", _localization.Language);
    }

    [Fact]
    public async Task Interim_text_is_one_line_per_channel_replaced_in_place_then_by_the_segment()
    {
        var viewModel = await ReadyAsync();
        Assert.True(viewModel.Recorder.IsTranscriptEmpty);

        await SendAsync(viewModel, new PartialEvent("s", "mic", "mic", "Eu", 65.2, "Bom"));
        await SendAsync(viewModel, new PartialEvent("s", "system", "system", "Outros", 70, "Oi"));
        await SendAsync(viewModel, new PartialEvent("s", "mic", "mic", "Eu", 65.2, "Bom dia, pess"));

        Assert.False(viewModel.Recorder.IsTranscriptEmpty);
        Assert.Equal(
            [new TranscriptLine("00:01:05", "Eu", "Bom dia, pess", "mic"), new TranscriptLine("00:01:10", "Outros", "Oi", "system")],
            viewModel.Recorder.Partials);
        await SendAsync(viewModel, new SegmentEvent("s", Line("mic", "Eu", 65.2, "Bom dia, pessoal.")));
        Assert.Equal([new TranscriptLine("00:01:10", "Outros", "Oi", "system")], viewModel.Recorder.Partials);
        await SendAsync(viewModel, new PartialEvent("s", "system", "system", "Outros", 70, ""));
        Assert.Empty(viewModel.Recorder.Partials);
        Assert.Single(viewModel.Recorder.Segments);
    }

    [Fact]
    public async Task Interim_text_is_cleared_when_a_session_starts_or_ends()
    {
        var viewModel = await ReadyAsync();
        await SendAsync(viewModel, new PartialEvent("s", "mic", "mic", "Eu", 1, "stale"));

        await viewModel.Recorder.StartCommand.ExecuteAsync(null);
        Assert.Empty(viewModel.Recorder.Partials);
        await SendAsync(viewModel, new PartialEvent("s", "mic", "mic", "Eu", 1, "Hel"));
        await SendAsync(viewModel, new StatusEvent("20261016_090000", "done", 5));

        Assert.Empty(viewModel.Recorder.Partials);
        Assert.True(viewModel.Recorder.IsTranscriptEmpty);
    }

    [Fact]
    public async Task Recording_starts_at_once_and_shows_the_model_loading_indicator()
    {
        var viewModel = await ReadyAsync();

        await viewModel.Recorder.StartCommand.ExecuteAsync(null);
        Assert.Equal(RecordingState.Recording, viewModel.Recorder.State);
        Assert.False(viewModel.Recorder.IsModelLoading);
        await SendAsync(viewModel, new ModelLoadingEvent("s", true));

        Assert.True(viewModel.Recorder.IsModelLoading);
        Assert.True(viewModel.Recorder.StopCommand.CanExecute(null));
        await SendAsync(viewModel, new ModelLoadingEvent("s", false));
        Assert.False(viewModel.Recorder.IsModelLoading);
    }

    [Fact]
    public async Task The_model_loading_indicator_is_cleared_when_the_session_ends()
    {
        var viewModel = await ReadyAsync();
        await viewModel.Recorder.StartCommand.ExecuteAsync(null);
        await SendAsync(viewModel, new ModelLoadingEvent("s", true));

        await SendAsync(viewModel, new StatusEvent("20261016_090000", "done", 5));

        Assert.False(viewModel.Recorder.IsModelLoading);
        Assert.Equal(RecordingState.Idle, viewModel.Recorder.State);
    }

    [Fact]
    public async Task Errors_and_minutes_ready_become_dismissable_notifications()
    {
        var viewModel = await ReadyAsync();

        await SendAsync(viewModel, new ErrorEvent("s", "minutes_failed", "Ollama offline"));
        await SendAsync(viewModel, new MinutesReadyEvent("s"));
        viewModel.DismissNotificationCommand.Execute("Ollama offline");

        Assert.Equal([_localization["MinutesReady"]], viewModel.Notifications);
    }

    [Fact]
    public async Task Connection_drops_are_shown_and_block_starting()
    {
        var viewModel = await ReadyAsync();

        await SendAsync(viewModel, new ConnectionChangedEvent(false));

        Assert.Equal(_localization["EngineDisconnected"], viewModel.EngineText);
        Assert.False(viewModel.Recorder.StartCommand.CanExecute(null));
        await SendAsync(viewModel, new UnknownEvent("s", "speakers_relabeled"));
        await SendAsync(viewModel, new LevelEvent("s", "mic", -20));
    }

    [Fact]
    public async Task Stop_errors_are_shown_and_keep_recording()
    {
        var viewModel = await ReadyAsync();
        await viewModel.Recorder.StartCommand.ExecuteAsync(null);
        _client.StopError = FakeEngineClient.ApiError("no_active_session", "Nada gravando.");

        await viewModel.Recorder.StopCommand.ExecuteAsync(null);

        Assert.Contains("Nada gravando.", viewModel.Notifications);
        Assert.Equal(RecordingState.Recording, viewModel.Recorder.State);
    }

    [Fact]
    public async Task Closing_while_idle_needs_no_confirmation()
    {
        var viewModel = await ReadyAsync();

        Assert.True(await viewModel.ConfirmCloseAsync());
        Assert.Empty(_dialogs.Asked);
    }

    [Fact]
    public async Task Closing_while_recording_asks_and_stops_the_session_first()
    {
        var viewModel = await ReadyAsync();
        await viewModel.Recorder.StartCommand.ExecuteAsync(null);

        Assert.True(await viewModel.ConfirmCloseAsync());

        Assert.Equal([_localization["ConfirmCloseTitle"], _localization["AppTitle"]], _dialogs.Asked);
        Assert.Contains("stop", _client.Calls);
        Assert.Equal(RecordingState.Idle, viewModel.Recorder.State);
    }

    [Fact]
    public async Task Close_with_pending_processing_warns_once_and_closes()
    {
        var viewModel = await ReadyAsync();
        await SendAsync(viewModel, new ProcessingEvent("a", new ProcessingInfo("running", 40, "transcribe")));
        await SendAsync(viewModel, new ProcessingEvent("b", new ProcessingInfo("queued", 0, null, 1)));

        Assert.Equal(2, viewModel.PendingProcessing);
        Assert.True(await viewModel.ConfirmCloseAsync());

        Assert.Equal([_localization["AppTitle"]], _dialogs.Asked);
        Assert.Equal([_localization.Format("Close_PendingProcessing", 2)], _dialogs.Messages);
    }

    [Fact]
    public async Task Cancelling_the_pending_processing_warning_keeps_the_app_open()
    {
        var viewModel = await ReadyAsync();
        await SendAsync(viewModel, new ProcessingEvent("a", new ProcessingInfo("running", 40, "transcribe")));
        _dialogs.Answer = false;

        Assert.False(await viewModel.ConfirmCloseAsync());
    }

    [Fact]
    public async Task Finished_processing_does_not_warn_on_close()
    {
        var viewModel = await ReadyAsync();
        await SendAsync(viewModel, new ProcessingEvent("a", new ProcessingInfo("running", 40, "transcribe")));
        await SendAsync(viewModel, new ProcessingEvent("a", new ProcessingInfo("done", 100, null)));

        Assert.True(await viewModel.ConfirmCloseAsync());

        Assert.Equal(0, viewModel.PendingProcessing);
        Assert.Empty(_dialogs.Asked);
    }

    [Fact]
    public async Task Recording_and_pending_processing_ask_both_questions()
    {
        var viewModel = await ReadyAsync();
        await viewModel.Recorder.StartCommand.ExecuteAsync(null);
        await SendAsync(viewModel, new ProcessingEvent("a", new ProcessingInfo("queued", 0, null, 1)));

        Assert.True(await viewModel.ConfirmCloseAsync());

        Assert.Equal([_localization["ConfirmCloseTitle"], _localization["AppTitle"]], _dialogs.Asked);
    }

    [Fact]
    public async Task Recording_with_an_empty_queue_counts_the_recorded_meeting_in_the_warning()
    {
        var viewModel = await ReadyAsync();
        await viewModel.Recorder.StartCommand.ExecuteAsync(null);

        Assert.True(await viewModel.ConfirmCloseAsync());

        Assert.Equal(_localization.Format("Close_PendingProcessing", 1), _dialogs.Messages[^1]);
        Assert.Contains("stop", _client.Calls);
    }

    [Fact]
    public async Task Cancelling_the_pending_warning_while_recording_stops_nothing()
    {
        var viewModel = await ReadyAsync();
        await viewModel.Recorder.StartCommand.ExecuteAsync(null);
        _dialogs.Answers = new Queue<bool>([true, false]);

        Assert.False(await viewModel.ConfirmCloseAsync());

        Assert.DoesNotContain("stop", _client.Calls);
        Assert.Equal(RecordingState.Recording, viewModel.Recorder.State);
    }

    [Fact]
    public async Task A_duplicate_processing_event_does_not_change_the_pending_count()
    {
        var viewModel = await ReadyAsync();
        await SendAsync(viewModel, new ProcessingEvent("a", new ProcessingInfo("running", 10, "transcribe")));
        await SendAsync(viewModel, new ProcessingEvent("a", new ProcessingInfo("running", 20, "transcribe")));

        Assert.Equal(1, viewModel.PendingProcessing);
    }

    [Fact]
    public async Task Losing_the_engine_connection_clears_the_processing_indicator()
    {
        var viewModel = await ReadyAsync();
        await SendAsync(viewModel, new ProcessingEvent("a", new ProcessingInfo("running", 40, "transcribe")));
        Assert.True(viewModel.Processing.IsVisible);

        await SendAsync(viewModel, new ConnectionChangedEvent(false));

        Assert.False(viewModel.Processing.IsVisible);
        Assert.Equal(0, viewModel.PendingProcessing);
    }

    [Fact]
    public async Task Closing_with_unsaved_transcript_edits_asks_first()
    {
        _client.Sessions.Add(new SessionSummary("20261015_202358", "done", null, null, 5, "en", false));
        _client.Details["20261015_202358"] = new SessionDetail("20261015_202358", "done", null, null, 5, "en", false, [], @"C:\r");
        _client.Transcripts["20261015_202358"] = new Transcript("raw", [new Segment("mic-000001", "mic", "mic", "Me", 0, 1, "Helo.", false, [])]);
        var viewModel = await ReadyAsync();
        viewModel.History.Selected = viewModel.History.Rows[0];
        await viewModel.History.DetailLoading;
        var editor = viewModel.History.Detail!.Editor;
        editor.EditCommand.Execute(null);
        editor.Segments[0].Text = "Hello.";
        _dialogs.Answer = false;

        Assert.False(await viewModel.ConfirmCloseAsync());

        Assert.Equal([_localization["ConfirmDiscardEditsTitle"]], _dialogs.Asked);
        Assert.True(editor.IsDirty);
    }

    [Fact]
    public async Task Declining_the_close_keeps_recording()
    {
        var viewModel = await ReadyAsync();
        await viewModel.Recorder.StartCommand.ExecuteAsync(null);
        _dialogs.Answer = false;

        Assert.False(await viewModel.ConfirmCloseAsync());

        Assert.DoesNotContain("stop", _client.Calls);
        Assert.Equal(RecordingState.Recording, viewModel.Recorder.State);
    }

    [Fact]
    public async Task Shutdown_does_not_wait_for_a_stopped_meeting_to_finish_processing()
    {
        var viewModel = await ReadyAsync();
        await viewModel.Recorder.StartCommand.ExecuteAsync(null);
        await viewModel.Recorder.StopCommand.ExecuteAsync(null);

        await viewModel.ShutdownAsync(TimeSpan.FromSeconds(5));

        Assert.Equal(1, _process.Stops);
    }

    [Fact]
    public async Task A_background_meeting_finishing_does_not_change_the_shared_recording_state()
    {
        var viewModel = await ReadyAsync();
        await viewModel.Recorder.StartCommand.ExecuteAsync(null);
        await viewModel.Recorder.StopCommand.ExecuteAsync(null);
        _client.NextSessionId = "20261016_091000";
        await viewModel.Recorder.StartCommand.ExecuteAsync(null);

        await SendAsync(viewModel, new StatusEvent("20261016_090000", "finalizing", 30));
        await SendAsync(viewModel, new StatusEvent("20261016_090000", "done", 30));

        Assert.Equal(RecordingState.Recording, viewModel.Session.State);
        Assert.Equal("20261016_091000", viewModel.Session.SessionId);
    }

    [Fact]
    public async Task Shutdown_gives_up_waiting_after_the_timeout()
    {
        var viewModel = await ReadyAsync();
        await viewModel.Recorder.StartCommand.ExecuteAsync(null);
        await viewModel.ShutdownAsync(TimeSpan.FromMilliseconds(50));

        Assert.Equal(1, _process.Stops);
    }

    [Fact]
    public async Task Status_text_follows_the_ui_language()
    {
        var viewModel = await ReadyAsync();
        Assert.Equal("Ready", viewModel.Recorder.StatusText);

        viewModel.SelectedAppLanguage = viewModel.AppLanguages.Single(option => option.Value == "pt-BR");

        Assert.Equal("Pronto", viewModel.Recorder.StatusText);
        Assert.Equal("Português", viewModel.Recorder.ConversationLanguages.Single(option => option.Value == "pt").Label);
    }

    [Fact]
    public async Task Switching_the_ui_language_refreshes_bindings_to_the_string_table()
    {
        var viewModel = await ReadyAsync();
        var changed = new List<string?>();
        viewModel.PropertyChanged += (_, args) => changed.Add(args.PropertyName);

        viewModel.SelectedAppLanguage = viewModel.AppLanguages.Single(option => option.Value == "es");

        Assert.Contains(nameof(MainViewModel.L), changed);  // `{Binding L[Key]}` re-reads every string
        Assert.Equal("Iniciar grabación", viewModel.L["Start"]);
    }

    [Fact]
    public async Task The_event_loop_ends_quietly_when_the_stream_completes()
    {
        var viewModel = await ReadyAsync();

        _events.Complete();
        await viewModel.EventLoop!;

        Assert.Equal(RecordingState.Idle, viewModel.Recorder.State);
    }

    [Fact]
    public async Task A_recovery_offer_opens_the_dialog_and_recovery_progress_shows_as_status()
    {
        const string id = "20261015_202358";
        _client.Details[id] = new SessionDetail(id, "interrupted", null, null, 90, "pt", false, [], @"C:\r");
        var viewModel = await ReadyAsync();

        await SendAsync(viewModel, new RecoveryAvailableEvent(null, [id]));
        await viewModel.RecoveryRefresh;
        Assert.True(viewModel.Recovery.IsOpen);

        await viewModel.Recovery.RecoverCommand.ExecuteAsync(null);
        await SendAsync(viewModel, new StatusEvent(id, "finalizing", 90));
        Assert.Equal(RecordingState.Idle, viewModel.Recorder.State); // recovery runs in the queue and never blocks Start
        Assert.True(viewModel.Recorder.StartCommand.CanExecute(null));

        await SendAsync(viewModel, new StatusEvent(id, "done", 90));
        await viewModel.RecoveryRefresh;
        Assert.Equal(RecordingState.Idle, viewModel.Recorder.State);
        Assert.Contains(_localization.Format("SessionRecovered", id), viewModel.Notifications);
        Assert.Equal([id], _client.Recovered);
    }

    [Fact]
    public async Task A_failed_recovery_and_a_lost_engine_reach_the_recovery_dialog()
    {
        const string id = "20261015_202358";
        _client.Details[id] = new SessionDetail(id, "interrupted", null, null, 90, "pt", false, [], @"C:\r");
        var viewModel = await ReadyAsync();
        await SendAsync(viewModel, new RecoveryAvailableEvent(null, [id]));
        await viewModel.RecoveryRefresh;
        await viewModel.Recovery.RecoverCommand.ExecuteAsync(null);

        await SendAsync(viewModel, new ErrorEvent(id, "recovery_failed", "Bad header."));
        Assert.Null(viewModel.Recovery.Recovering);
        Assert.Contains("Bad header.", viewModel.Notifications);

        await SendAsync(viewModel, new RecoveryAvailableEvent(null, [id]));
        await viewModel.RecoveryRefresh;
        await SendAsync(viewModel, new ConnectionChangedEvent(false));
        Assert.False(viewModel.Recovery.IsOpen);
    }

    [Fact]
    public async Task The_folder_import_shows_its_progress_then_its_end_and_reloads_the_meetings()
    {
        var viewModel = await ReadyAsync();

        await SendAsync(viewModel, new ConnectionChangedEvent(true));
        await viewModel.MigrationRefresh;
        Assert.Contains("migration", _client.Calls);
        Assert.False(viewModel.Migration.IsVisible); // disabled

        await SendAsync(viewModel, new MigrationProgressEvent(null, 1, 2, "20261015_202358", false));
        Assert.True(viewModel.Migration.IsRunning);

        _client.Migration = new MigrationSummary("done", 2, 2, null, false, 2, 0, null, null, null, []);
        await SendAsync(viewModel, new MigrationDoneEvent(null, "done", 2, 0, 0));
        await viewModel.MigrationRefresh;
        await viewModel.HistoryRefresh;
        Assert.True(viewModel.Migration.IsFinished);
        Assert.Equal(_localization.Format("MigrationDone", 2, 0), viewModel.Migration.Text);

        _client.Migration = new MigrationSummary("running", 0, 1, null, false, 0, 0, null, null, null, []);
        await SendAsync(viewModel, new MigrationProgressEvent(null, 0, 1, "x", false));
        await SendAsync(viewModel, new ConnectionChangedEvent(false));
        Assert.False(viewModel.Migration.IsVisible);
    }

    [Fact]
    public async Task Processing_events_update_the_meetings_row_and_a_background_done_refreshes_the_list()
    {
        var started = new DateTimeOffset(_clock.Now.LocalDateTime.Date.AddHours(9));
        const string id = "20261015_100000";
        _client.Sessions.Add(new SessionSummary(id, "finalizing", started, null, 60, "pt", false));
        var viewModel = await ReadyAsync();
        await viewModel.Recorder.StartCommand.ExecuteAsync(null); // a new meeting is recorded meanwhile
        var row = viewModel.Meetings.Weeks.Single().Days.Single().Rows.Single();

        await SendAsync(viewModel, new ProcessingEvent(id, new ProcessingInfo("running", 42, "transcribe")));
        Assert.Equal("Processing 42 %", row.ProcessingText);

        var requests = _client.DayRequests.Count;
        _client.Sessions[0] = _client.Sessions[0] with { Status = "done", SpeakerCount = 2 };
        await SendAsync(viewModel, new StatusEvent(id, "done", 60));
        await viewModel.HistoryRefresh;

        Assert.True(_client.DayRequests.Count > requests);
        Assert.Equal(2, viewModel.Meetings.Weeks.Single().Days.Single().Rows.Single().SpeakerCount);
        Assert.Equal(RecordingState.Recording, viewModel.Recorder.State);

        await SendAsync(viewModel, new ProcessingEvent(id, new ProcessingInfo("done", 100, null)));
        await viewModel.HistoryRefresh;
        Assert.True(viewModel.Meetings.Weeks.Single().Days.Single().Rows.Single().ShowsDoneCheck);
    }

    [Fact]
    public async Task An_open_meeting_page_keeps_its_instance_and_shows_the_done_check_when_processing_ends()
    {
        const string id = "20261015_100000";
        var queued = new ProcessingInfo("running", 90, "index");
        _client.Sessions.Add(new SessionSummary(id, "finalizing", null, null, 60, "pt", false, Processing: queued));
        _client.Details[id] = new SessionDetail(id, "finalizing", null, null, 60, "pt", false, [], @"C:\rec", Processing: queued);
        _client.Transcripts[id] = new Transcript("raw", [Line("mic", "Me", 1, "Hi.")]);
        var viewModel = await ReadyAsync();
        viewModel.History.Selected = viewModel.History.Rows[0];
        await viewModel.History.DetailLoading;
        var page = viewModel.History.Detail;
        Assert.True(page?.IsProcessing);

        _client.Sessions[0] = _client.Sessions[0] with { Status = "done", Processing = null };
        _client.MinutesText[id] = "## Done minutes";
        await SendAsync(viewModel, new ProcessingEvent(id, new ProcessingInfo("done", 100, null)));
        await viewModel.HistoryRefresh;

        Assert.Same(page, viewModel.History.Detail);
        Assert.Equal((false, true, true), (page!.IsProcessing, page.ShowsDoneCheck, page.HasMinutes));
    }
}
