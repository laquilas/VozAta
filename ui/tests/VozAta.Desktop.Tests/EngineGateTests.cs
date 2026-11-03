using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>Only what needs the engine waits for it, with Retry connection (phase 62).</summary>
public sealed class EngineGateTests
{
    private readonly FakeEngineClient _client = new();
    private readonly FakeEngineEvents _events = new();
    private readonly FakeEngineProcess _process = new();
    private readonly FakeRecorderClient _recorder = new();
    private readonly FakeRecorderEvents _recorderEvents = new();
    private readonly LocalizationService _localization = new();

    private MainViewModel Create() =>
        new(_client, _events, _process, new ImmediateDispatcher(), _localization, new FakeDialogs(),
            new FakePreferences(), new FakeClock(), new FakeTimer(), new FakeShell(), new FakeFileSaver(),
            new FakeThemeService(), recorder: _recorder, recorderEvents: _recorderEvents,
            recorderProcess: new FakeRecorderProcess());

    private async Task SendAsync(MainViewModel viewModel, EngineEvent engineEvent)
    {
        var before = viewModel.HandledEvents;
        _events.Send(engineEvent);
        for (var i = 0; i < 200 && viewModel.HandledEvents == before; i++)
        {
            await Task.Delay(5);
        }
    }

    [Fact]
    public async Task A_failed_engine_gates_its_pages_but_not_the_recorder()
    {
        _process.Result = EngineStartResult.Failed;
        var viewModel = Create();

        await viewModel.InitializeAsync();

        Assert.Equal(EngineStatus.Failed, viewModel.EngineStatus);
        Assert.False(viewModel.IsEngineGateVisible); // the Recorder page is the first page
        Assert.Equal(_localization["EngineGateFailed"], viewModel.EngineGateTitle);
        viewModel.Shell.NavigateCommand.Execute(ShellViewModel.Meetings);
        Assert.True(viewModel.IsEngineGateVisible);
        Assert.True(viewModel.RetryConnectionCommand.CanExecute(null));
        Assert.NotNull(viewModel.EventLoop); // an engine started later is picked up
    }

    [Fact]
    public async Task Retry_starts_the_engine_and_its_data_loads_when_it_connects()
    {
        _process.NextResults.Enqueue(EngineStartResult.Failed);
        _process.Result = EngineStartResult.Started;
        var viewModel = Create();
        await viewModel.InitializeAsync();
        var settingsReads = _client.Calls.Count(call => call == "settings");

        await viewModel.RetryConnectionCommand.ExecuteAsync(null);
        Assert.Equal(EngineStatus.Reconnecting, viewModel.EngineStatus);
        Assert.False(viewModel.RetryConnectionCommand.CanExecute(null));
        await SendAsync(viewModel, new ConnectionChangedEvent(true));
        await viewModel.EngineDataRefresh;

        Assert.Equal(EngineStatus.Connected, viewModel.EngineStatus);
        Assert.False(viewModel.IsEngineGateVisible);
        Assert.Equal(2, _process.Ensures);
        Assert.True(_client.Calls.Count(call => call == "settings") > settingsReads);
    }

    [Fact]
    public async Task A_retry_that_fails_again_says_so()
    {
        _process.Result = EngineStartResult.Failed;
        var viewModel = Create();
        await viewModel.InitializeAsync();
        viewModel.Notifications.Clear();

        await viewModel.RetryConnectionCommand.ExecuteAsync(null);

        Assert.Equal(EngineStatus.Failed, viewModel.EngineStatus);
        Assert.Contains(_localization["EngineStartFailed"], viewModel.Notifications);
    }

    [Fact]
    public async Task A_reconnection_reloads_the_engine_data()
    {
        var viewModel = Create();
        await viewModel.InitializeAsync();
        await SendAsync(viewModel, new ConnectionChangedEvent(true));
        var settingsReads = _client.Calls.Count(call => call == "settings");

        await SendAsync(viewModel, new ConnectionChangedEvent(false));
        await SendAsync(viewModel, new ConnectionChangedEvent(true));
        await viewModel.EngineDataRefresh;

        Assert.True(_client.Calls.Count(call => call == "settings") > settingsReads);
    }

    [Fact]
    public async Task An_engine_that_exited_is_started_again_once_automatically()
    {
        var viewModel = Create();
        await viewModel.InitializeAsync();
        await SendAsync(viewModel, new ConnectionChangedEvent(true));
        _process.HasExited = true;

        await SendAsync(viewModel, new ConnectionChangedEvent(false));
        await viewModel.RetryRefresh;
        await SendAsync(viewModel, new ConnectionChangedEvent(true));
        await SendAsync(viewModel, new ConnectionChangedEvent(false));
        await viewModel.RetryRefresh;

        Assert.Equal(2, _process.Ensures); // the start, and one respawn: then Retry is the user's
    }

    [Fact]
    public async Task A_dropped_connection_without_a_crash_only_waits()
    {
        var viewModel = Create();
        await viewModel.InitializeAsync();
        await SendAsync(viewModel, new ConnectionChangedEvent(true));

        await SendAsync(viewModel, new ConnectionChangedEvent(false));

        Assert.Equal(1, _process.Ensures);
        Assert.Equal(_localization["EngineGateDisconnected"], viewModel.EngineGateTitle);
    }

    [Fact]
    public async Task Restarting_the_engine_is_refused_while_recording()
    {
        var session = new RecordingSessionService();
        var settings = new SettingsViewModel(_client, _process, _localization, session: session);
        settings.RestartKeys.Add("WHISPER_MODEL");
        Assert.True(settings.RestartEngineCommand.CanExecute(null));

        session.State = RecordingState.Recording;

        Assert.False(settings.RestartEngineCommand.CanExecute(null));
        await settings.RestartEngineCommand.ExecuteAsync(null);
        Assert.Equal(_localization["EngineRestartWhileRecording"], settings.Error);
        Assert.Equal(0, _process.Restarts);
    }

    [Fact]
    public void The_gate_text_follows_the_engine_state()
    {
        var viewModel = Create();

        Assert.Equal(_localization["EngineGateStarting"], viewModel.EngineGateTitle);
        Assert.Equal(_localization["EngineStarting"], viewModel.EngineText);
    }
}
