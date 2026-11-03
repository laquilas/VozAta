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
