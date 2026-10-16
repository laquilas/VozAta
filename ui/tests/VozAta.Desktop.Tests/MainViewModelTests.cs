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
        new(_client, _events, _process, new ImmediateDispatcher(), _localization, _dialogs, _preferences, _clock, _timer, _shell);

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
        Assert.Equal("es", viewModel.SelectedLanguage.Value);
        Assert.Equal("GPU: RTX 3050 (6144 MB)", viewModel.GpuText);
        Assert.Equal("Fala: large-v3 em auto", viewModel.SpeechText);
        Assert.Equal("Ata: qwen2.5:7b pronto", viewModel.MinutesText);
        Assert.Equal("Motor conectado", viewModel.EngineText);
        Assert.True(viewModel.StartCommand.CanExecute(null));
        Assert.Equal(RecordingState.Idle, viewModel.State);
    }

    [Fact]
    public async Task Initialization_loads_the_devices_and_the_meter_labels()
    {
        _client.SettingValues["MIC_LABEL"] = "Host";

        var viewModel = await ReadyAsync();

        Assert.Equal([Laptop, Mic], viewModel.Devices.Inputs);
        Assert.Equal((Mic, Speakers), (viewModel.Devices.SelectedMic, viewModel.Devices.SelectedLoopback));
        Assert.Equal(("Host", "Others"), (viewModel.MicMeter.Label, viewModel.SystemMeter.Label));
        viewModel.SelectedAppLanguage = viewModel.AppLanguages.Single(option => option.Value == "pt-BR");
        Assert.Equal(("Host", "Outros"), (viewModel.MicMeter.Label, viewModel.SystemMeter.Label));
    }

    [Fact]
    public async Task A_device_list_failure_is_shown_and_recording_still_uses_the_engine_defaults()
    {
        _client.DevicesError = FakeEngineClient.ApiError("devices_failed", "WASAPI did not answer.");

        var viewModel = await ReadyAsync();
        await viewModel.StartCommand.ExecuteAsync(null);

        Assert.Contains("WASAPI did not answer.", viewModel.Notifications);
        Assert.Equal(new StartSessionRequest(null, null, "pt"), _client.StartRequests.Single());
    }

    [Fact]
    public async Task Start_sends_the_selected_devices_and_locks_them_while_recording()
    {
        var viewModel = await ReadyAsync();
        viewModel.Devices.SelectedMic = Laptop;

        await viewModel.StartCommand.ExecuteAsync(null);

        var request = _client.StartRequests.Single();
        Assert.Equal((1, 7), (request.MicDeviceId, request.SystemDeviceId));
        Assert.False(viewModel.Devices.IsEnabled);
        await SendAsync(viewModel, new StatusEvent("s", "done", 3));
        Assert.True(viewModel.Devices.IsEnabled);
    }

    [Fact]
    public async Task Level_events_drive_the_meters_and_the_timer_runs_only_while_recording()
    {
        var viewModel = await ReadyAsync();
        Assert.Equal(0, _timer.Running);
        await viewModel.StartCommand.ExecuteAsync(null);
        Assert.Equal(1, _timer.Running);

        await SendAsync(viewModel, new LevelEvent("s", "mic", -15));
        await SendAsync(viewModel, new LevelEvent("s", "system", -30));
        Assert.Equal((0.75, 0.5), (viewModel.MicMeter.Level, viewModel.SystemMeter.Level));
        await SendAsync(viewModel, new LevelEvent("s", "mic", -60));
        _clock.Advance(TimeSpan.FromSeconds(0.2));
        _timer.Tick();
        Assert.True(viewModel.MicMeter.Level < 0.75);

        await SendAsync(viewModel, new StatusEvent("s", "done", 3));
        Assert.Equal(0, _timer.Running);
        Assert.Equal(0, viewModel.MicMeter.Level);
    }

    [Fact]
    public async Task Silent_system_audio_shows_the_no_signal_hint_but_not_while_paused()
    {
        var viewModel = await ReadyAsync();
        await viewModel.StartCommand.ExecuteAsync(null);
        await SendAsync(viewModel, new StatusEvent("s", "paused", 1));

        _clock.Advance(TimeSpan.FromSeconds(31));
        _timer.Tick();
        Assert.False(viewModel.SystemMeter.NoSignal);
        await SendAsync(viewModel, new StatusEvent("s", "recording", 32));
        _clock.Advance(TimeSpan.FromSeconds(30));
        _timer.Tick();

        Assert.True(viewModel.SystemMeter.NoSignal);
        Assert.False(viewModel.MicMeter.NoSignal);
    }

    [Fact]
    public async Task The_window_size_is_restored_and_saved_on_shutdown()
    {
        _preferences.Data = new UiPreferencesData(WindowWidth: 1200, WindowHeight: 820);
        var viewModel = await ReadyAsync();
        Assert.Equal((1200d, 820d), (viewModel.WindowWidth, viewModel.WindowHeight));

        viewModel.Devices.SelectedMic = Laptop;
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

        await viewModel.StartCommand.ExecuteAsync(null);
        await viewModel.HistoryRefresh;
        Assert.Equal(2, _client.ListRequests.Count);
        await SendAsync(viewModel, new StatusEvent("s", "paused", 3));
        Assert.Equal(2, _client.ListRequests.Count);  // still the same session
        await SendAsync(viewModel, new StatusEvent("s", "done", 5));
        await viewModel.HistoryRefresh;

        Assert.Equal(3, _client.ListRequests.Count);
    }

    [Fact]
    public async Task Minutes_and_error_events_reach_the_open_session()
    {
        const string id = "20261015_100000";
        _client.Sessions.Add(new SessionSummary(id, "done", null, null, 60, "pt", false));
        _client.Details[id] = new SessionDetail(id, "done", null, null, 60, "pt", false, [], @"C:");
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
    public async Task The_history_texts_follow_the_ui_language()
    {
        _client.Sessions.Add(new SessionSummary("20261015_100000", "done", null, null, 60, "pt", true));
        var viewModel = await ReadyAsync();

        viewModel.SelectedAppLanguage = viewModel.AppLanguages.Single(option => option.Value == "es");

        Assert.Equal("Portugués", viewModel.History.Rows[0].Language);
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

        Assert.Equal("No GPU (CPU only)", viewModel.GpuText);
        Assert.Equal("Minutes: qwen2.5:7b not reachable (start Ollama)", viewModel.MinutesText);
    }

    [Fact]
    public async Task A_failed_engine_start_is_reported_and_blocks_recording()
    {
        _process.Result = EngineStartResult.Failed;
        var viewModel = Create();

        await viewModel.InitializeAsync();

        Assert.Equal(_localization["EngineStartFailed"], viewModel.EngineText);
        Assert.Contains(_localization["EngineStartFailed"], viewModel.Notifications);
        Assert.False(viewModel.StartCommand.CanExecute(null));
        Assert.DoesNotContain("settings", _client.Calls);
    }

    [Fact]
    public async Task Unknown_or_missing_languages_fall_back_to_safe_defaults()
    {
        _client.SettingValues["APP_LANGUAGE"] = null;
        _client.SettingValues["TRANSCRIPTION_LANGUAGE"] = "fr";

        var viewModel = await ReadyAsync();

        Assert.Equal("en", _localization.Language);
        Assert.Equal("en", viewModel.SelectedLanguage.Value);
    }

    [Fact]
    public async Task Start_sends_the_selected_language_and_clears_the_previous_transcript()
    {
        var viewModel = await ReadyAsync();
        viewModel.Segments.Add(new TranscriptLine("00:00:01", "Me", "old", "mic"));
        viewModel.SelectedLanguage = viewModel.ConversationLanguages.Single(option => option.Value == "auto");

        await viewModel.StartCommand.ExecuteAsync(null);

        Assert.Equal("auto", _client.StartRequests.Single().Language);
        Assert.Empty(viewModel.Segments);
        Assert.Equal(RecordingState.Recording, viewModel.State);
        Assert.True(viewModel.IsRecording);
        Assert.False(viewModel.StartCommand.CanExecute(null));
        Assert.True(viewModel.StopCommand.CanExecute(null));
    }

    [Fact]
    public async Task Start_errors_show_the_engine_message_and_return_to_idle()
    {
        var viewModel = await ReadyAsync();
        _client.StartError = FakeEngineClient.ApiError("device_timeout", "O microfone não abriu.");

        await viewModel.StartCommand.ExecuteAsync(null);

        Assert.Equal(RecordingState.Idle, viewModel.State);
        Assert.Contains("O microfone não abriu.", viewModel.Notifications);
    }

    [Fact]
    public async Task Start_while_the_engine_is_down_shows_unavailable()
    {
        var viewModel = await ReadyAsync();
        _client.StartError = new EngineUnavailableException("refused", new HttpRequestException());

        await viewModel.StartCommand.ExecuteAsync(null);

        Assert.Contains(_localization["EngineUnavailable"], viewModel.Notifications);
        Assert.Equal(RecordingState.Idle, viewModel.State);
    }

    [Fact]
    public async Task Status_events_drive_the_state_machine_and_elapsed_time()
    {
        var viewModel = await ReadyAsync();
        await viewModel.StartCommand.ExecuteAsync(null);

        await SendAsync(viewModel, new StatusEvent("s", "recording", 3725.4));
        Assert.Equal("01:02:05", viewModel.Elapsed);
        await SendAsync(viewModel, new StatusEvent("s", "paused", 3726));
        Assert.Equal(RecordingState.Paused, viewModel.State);
        Assert.Equal(_localization["StatePaused"], viewModel.StatusText);
        await viewModel.StopCommand.ExecuteAsync(null);
        Assert.Equal(RecordingState.Finalizing, viewModel.State);
        Assert.False(viewModel.StopCommand.CanExecute(null));
        await SendAsync(viewModel, new StatusEvent("s", "done", 3730));

        Assert.Equal(RecordingState.Idle, viewModel.State);
        Assert.True(viewModel.StartCommand.CanExecute(null));
    }

    [Fact]
    public async Task Connecting_while_the_engine_records_adopts_its_session()
    {
        var viewModel = await ReadyAsync();

        await SendAsync(viewModel, new StatusEvent("s", "recording", 10));

        Assert.Equal(RecordingState.Recording, viewModel.State);
        await SendAsync(viewModel, new StatusEvent(null, "idle", null));
        Assert.Equal(RecordingState.Idle, viewModel.State);
    }

    [Fact]
    public async Task Segments_are_appended_with_timestamp_label_and_speaker_colour()
    {
        var viewModel = await ReadyAsync();

        await SendAsync(viewModel, new SegmentEvent("s", Line("mic", "Eu", 65.2, "Bom dia.")));
        await SendAsync(viewModel, new SegmentEvent("s", Line("system", "Outros", 70, "Oi.")));

        Assert.Equal(
            [new TranscriptLine("00:01:05", "Eu", "Bom dia.", "mic"), new TranscriptLine("00:01:10", "Outros", "Oi.", "system")],
            viewModel.Segments);
        Assert.Equal("[00:01:05] Eu: Bom dia.", viewModel.Segments[0].Display);
        Assert.NotEqual(viewModel.Segments[0].Color, viewModel.Segments[1].Color);
    }

    [Fact]
    public async Task Language_detected_updates_the_badge_in_the_ui_language()
    {
        var viewModel = await ReadyAsync();

        await SendAsync(viewModel, new LanguageDetectedEvent("s", "pt"));
        Assert.Equal("Detected: Portuguese", viewModel.DetectedLanguage);
        viewModel.SelectedAppLanguage = viewModel.AppLanguages.Single(option => option.Value == "es");

        Assert.Equal("Detectado: Portugués", viewModel.DetectedLanguage);
        Assert.Equal("es", _localization.Language);
    }

    [Fact]
    public async Task Interim_text_is_one_line_per_channel_replaced_in_place_then_by_the_segment()
    {
        var viewModel = await ReadyAsync();
        Assert.True(viewModel.IsTranscriptEmpty);

        await SendAsync(viewModel, new PartialEvent("s", "mic", "mic", "Eu", 65.2, "Bom"));
        await SendAsync(viewModel, new PartialEvent("s", "system", "system", "Outros", 70, "Oi"));
        await SendAsync(viewModel, new PartialEvent("s", "mic", "mic", "Eu", 65.2, "Bom dia, pess"));

        Assert.False(viewModel.IsTranscriptEmpty);
        Assert.Equal(
            [new TranscriptLine("00:01:05", "Eu", "Bom dia, pess", "mic"), new TranscriptLine("00:01:10", "Outros", "Oi", "system")],
            viewModel.Partials);
        await SendAsync(viewModel, new SegmentEvent("s", Line("mic", "Eu", 65.2, "Bom dia, pessoal.")));
        Assert.Equal([new TranscriptLine("00:01:10", "Outros", "Oi", "system")], viewModel.Partials);
        await SendAsync(viewModel, new PartialEvent("s", "system", "system", "Outros", 70, ""));
        Assert.Empty(viewModel.Partials);
        Assert.Single(viewModel.Segments);
    }

    [Fact]
    public async Task Interim_text_is_cleared_when_a_session_starts_or_ends()
    {
        var viewModel = await ReadyAsync();
        await SendAsync(viewModel, new PartialEvent("s", "mic", "mic", "Eu", 1, "stale"));

        await viewModel.StartCommand.ExecuteAsync(null);
        Assert.Empty(viewModel.Partials);
        await SendAsync(viewModel, new PartialEvent("s", "mic", "mic", "Eu", 1, "Hel"));
        await SendAsync(viewModel, new StatusEvent("s", "done", 5));

        Assert.Empty(viewModel.Partials);
        Assert.True(viewModel.IsTranscriptEmpty);
    }

    [Fact]
    public async Task Recording_starts_at_once_and_shows_the_model_loading_indicator()
    {
        var viewModel = await ReadyAsync();

        await viewModel.StartCommand.ExecuteAsync(null);
        Assert.Equal(RecordingState.Recording, viewModel.State);
        Assert.False(viewModel.IsModelLoading);
        await SendAsync(viewModel, new ModelLoadingEvent("s", true));

        Assert.True(viewModel.IsModelLoading);
        Assert.True(viewModel.StopCommand.CanExecute(null));
        await SendAsync(viewModel, new ModelLoadingEvent("s", false));
        Assert.False(viewModel.IsModelLoading);
    }

    [Fact]
    public async Task The_model_loading_indicator_is_cleared_when_the_session_ends()
    {
        var viewModel = await ReadyAsync();
        await viewModel.StartCommand.ExecuteAsync(null);
        await SendAsync(viewModel, new ModelLoadingEvent("s", true));

        await SendAsync(viewModel, new StatusEvent("s", "done", 5));

        Assert.False(viewModel.IsModelLoading);
        Assert.Equal(RecordingState.Idle, viewModel.State);
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
        Assert.False(viewModel.StartCommand.CanExecute(null));
        await SendAsync(viewModel, new UnknownEvent("s", "speakers_relabeled"));
        await SendAsync(viewModel, new LevelEvent("s", "mic", -20));
    }

    [Fact]
    public async Task Stop_errors_are_shown_and_keep_recording()
    {
        var viewModel = await ReadyAsync();
        await viewModel.StartCommand.ExecuteAsync(null);
        _client.StopError = FakeEngineClient.ApiError("no_active_session", "Nada gravando.");

        await viewModel.StopCommand.ExecuteAsync(null);

        Assert.Contains("Nada gravando.", viewModel.Notifications);
        Assert.Equal(RecordingState.Recording, viewModel.State);
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
        await viewModel.StartCommand.ExecuteAsync(null);

        Assert.True(await viewModel.ConfirmCloseAsync());

        Assert.Equal([_localization["ConfirmCloseTitle"]], _dialogs.Asked);
        Assert.Equal("stop", _client.Calls[^1]);
        Assert.Equal(RecordingState.Finalizing, viewModel.State);
    }

    [Fact]
    public async Task Declining_the_close_keeps_recording()
    {
        var viewModel = await ReadyAsync();
        await viewModel.StartCommand.ExecuteAsync(null);
        _dialogs.Answer = false;

        Assert.False(await viewModel.ConfirmCloseAsync());

        Assert.DoesNotContain("stop", _client.Calls);
        Assert.Equal(RecordingState.Recording, viewModel.State);
    }

    [Fact]
    public async Task Shutdown_waits_for_finalization_before_stopping_the_engine()
    {
        var viewModel = await ReadyAsync();
        await viewModel.StartCommand.ExecuteAsync(null);
        await viewModel.StopCommand.ExecuteAsync(null);

        var shutdown = viewModel.ShutdownAsync(TimeSpan.FromSeconds(5));
        await Task.Delay(50);
        Assert.False(shutdown.IsCompleted);
        Assert.Equal(0, _process.Stops);
        await SendAsync(viewModel, new StatusEvent("s", "done", 10));
        await shutdown;

        Assert.Equal(1, _process.Stops);
    }

    [Fact]
    public async Task Shutdown_gives_up_waiting_after_the_timeout()
    {
        var viewModel = await ReadyAsync();
        await viewModel.StartCommand.ExecuteAsync(null);
        await viewModel.StopCommand.ExecuteAsync(null);

        await viewModel.ShutdownAsync(TimeSpan.FromMilliseconds(50));

        Assert.Equal(1, _process.Stops);
    }

    [Fact]
    public async Task Status_text_follows_the_ui_language()
    {
        var viewModel = await ReadyAsync();
        Assert.Equal("Ready", viewModel.StatusText);

        viewModel.SelectedAppLanguage = viewModel.AppLanguages.Single(option => option.Value == "pt-BR");

        Assert.Equal("Pronto", viewModel.StatusText);
        Assert.Equal("Português", viewModel.ConversationLanguages.Single(option => option.Value == "pt").Label);
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

        Assert.Equal(RecordingState.Idle, viewModel.State);
    }
}
