using VozAta.Client;
using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>The window starts the recorder process before the engine and follows it (phase 61).</summary>
public sealed class MainViewModelRecorderTests
{
    private readonly FakeEngineClient _client = new();
    private readonly FakeEngineEvents _events = new();
    private readonly FakeEngineProcess _process = new();
    private readonly FakeRecorderClient _recorder = new();
    private readonly FakeRecorderEvents _recorderEvents = new();
    private readonly FakeRecorderProcess _recorderProcess = new();
    private readonly LocalizationService _localization = new();

    private MainViewModel Create() =>
        new(_client, _events, _process, new ImmediateDispatcher(), _localization, new FakeDialogs(),
            new FakePreferences(), new FakeClock(), new FakeTimer(), new FakeShell(), new FakeFileSaver(),
            new FakeThemeService(), recorder: _recorder, recorderEvents: _recorderEvents,
            recorderProcess: _recorderProcess);

    private static async Task SendAsync(MainViewModel viewModel, FakeRecorderEvents events, RecorderEvent recorderEvent)
    {
        var before = viewModel.HandledEvents;
        events.Send(recorderEvent);
        for (var i = 0; i < 200 && viewModel.HandledEvents == before; i++)
        {
            await Task.Delay(5);
        }

        Assert.True(viewModel.HandledEvents > before, $"{recorderEvent} was not handled");
    }

    [Fact]
    public async Task The_recorder_starts_first_and_recording_works_while_the_engine_failed()
    {
        _process.Result = EngineStartResult.Failed;
        var viewModel = Create();

        await viewModel.InitializeAsync();
        await SendAsync(viewModel, _recorderEvents, new RecorderConnectionChangedEvent(true));

        Assert.Equal(1, _recorderProcess.Starts);
        Assert.True(viewModel.HasRecorder);
        Assert.True(viewModel.IsRecorderConnected);
        Assert.Equal(_localization["RecorderConnected"], viewModel.RecorderText);
        Assert.Equal(EngineStatus.Failed, viewModel.EngineStatus);
        Assert.True(viewModel.Recorder.StartCommand.CanExecute(null));
        await viewModel.Recorder.StartCommand.ExecuteAsync(null);
        Assert.Equal(RecordingState.Recording, viewModel.Session.State);
        Assert.Single(_recorder.Starts);
    }

    [Fact]
    public async Task A_recorder_that_does_not_start_is_reported_and_the_engine_still_starts()
    {
        _recorderProcess.Result = RecorderStartResult.Failed;
        var viewModel = Create();

        await viewModel.InitializeAsync();
        await SendAsync(viewModel, _recorderEvents, new RecorderConnectionChangedEvent(false));

        Assert.Contains(_localization["RecorderStartFailed"], viewModel.Notifications);
        Assert.False(viewModel.IsRecorderConnected);
        Assert.Equal(_localization["RecorderDisconnected"], viewModel.RecorderText);
        Assert.NotNull(viewModel.EventLoop);
    }

    [Fact]
    public async Task A_recording_that_kept_going_while_the_app_was_closed_is_shown_again()
    {
        var viewModel = Create();
        await viewModel.InitializeAsync();

        await SendAsync(viewModel, _recorderEvents, new RecorderConnectionChangedEvent(true));
        await SendAsync(viewModel, _recorderEvents, new RecorderStatusEvent(
            new RecordingSummary("20261103_090000", "recording", DurationSeconds: 1800)));

        Assert.Equal(RecordingState.Recording, viewModel.Session.State);
        Assert.Equal("20261103_090000", viewModel.Session.SessionId);
        Assert.Equal("00:30:00", viewModel.Session.Elapsed);
    }

    [Fact]
    public void Without_a_recorder_client_nothing_changes()
    {
        var viewModel = new MainViewModel(
            _client, _events, _process, new ImmediateDispatcher(), _localization, new FakeDialogs(),
            new FakePreferences(), new FakeClock(), new FakeTimer(), new FakeShell(), new FakeFileSaver(),
            new FakeThemeService(), recorderEvents: _recorderEvents, recorderProcess: _recorderProcess);

        Assert.False(viewModel.HasRecorder);
        Assert.Null(viewModel.RecorderEventLoop);
    }
}

/// <summary>Closing the window while the recorder records (phase 62).</summary>
public sealed class CloseWhileRecordingTests
{
    private readonly FakeEngineClient _client = new();
    private readonly FakeEngineProcess _process = new();
    private readonly FakeRecorderClient _recorder = new();
    private readonly FakeDialogs _dialogs = new();
    private readonly LocalizationService _localization = new();

    private async Task<MainViewModel> RecordingAsync()
    {
        var viewModel = new MainViewModel(
            _client, new FakeEngineEvents(), _process, new ImmediateDispatcher(), _localization, _dialogs,
            new FakePreferences(), new FakeClock(), new FakeTimer(), new FakeShell(), new FakeFileSaver(),
            new FakeThemeService(), recorder: _recorder, recorderEvents: new FakeRecorderEvents(),
            recorderProcess: new FakeRecorderProcess());
        await viewModel.InitializeAsync();
        viewModel.Recorder.IsRecorderConnected = true;
        await viewModel.Recorder.StartCommand.ExecuteAsync(null);
        return viewModel;
    }

    [Fact]
    public async Task Keep_recording_closes_the_window_and_leaves_the_recorder_and_the_engine_running()
    {
        var viewModel = await RecordingAsync();
        _dialogs.Choice = 0;

        Assert.True(await viewModel.ConfirmCloseAsync());
        await viewModel.ShutdownAsync(TimeSpan.FromMilliseconds(10));

        Assert.True(viewModel.KeepsRecording);
        Assert.DoesNotContain("stop", _recorder.Calls);
        Assert.Equal(0, _process.Stops);
        Assert.Equal(
            [_localization["Close_KeepRecording"], _localization["Close_StopAndClose"], _localization["Close_Cancel"]],
            _dialogs.Choices.Single());
    }

    [Fact]
    public async Task Stop_and_close_stops_the_recording_first()
    {
        var viewModel = await RecordingAsync();
        _dialogs.Choice = 1;

        Assert.True(await viewModel.ConfirmCloseAsync());
        await viewModel.ShutdownAsync(TimeSpan.FromSeconds(1));

        Assert.Contains("stop", _recorder.Calls);
        Assert.False(viewModel.KeepsRecording);
        Assert.Equal(1, _process.Stops);
    }

    [Theory]
    [InlineData(2)]
    [InlineData(-1)]
    public async Task Cancel_or_closing_the_dialog_changes_nothing(int choice)
    {
        var viewModel = await RecordingAsync();
        _dialogs.Choice = choice;

        Assert.False(await viewModel.ConfirmCloseAsync());

        Assert.Equal(RecordingState.Recording, viewModel.Session.State);
        Assert.DoesNotContain("stop", _recorder.Calls);
    }
}
