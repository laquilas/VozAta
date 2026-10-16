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

    private MainViewModel Create() =>
        new(_client, _events, _process, new ImmediateDispatcher(), _localization, _dialogs);

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
