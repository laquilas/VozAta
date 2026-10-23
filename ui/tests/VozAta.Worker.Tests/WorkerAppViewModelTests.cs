using System.Globalization;
using VozAta.Worker.Services;
using VozAta.Worker.ViewModels;

namespace VozAta.Worker.Tests;

public sealed class WorkerAppViewModelTests
{
    private static readonly LocalStatus Status = new(
        "0.9.0", "4f1c", "GPU-PC", 8766, ["192.168.0.20", "172.26.32.1"], "t0k", "123456", 272,
        new WorkerGpu(true, "RTX 4070"), ["large-v3-turbo"]);

    private readonly FakeProcess _process = new();
    private readonly FakeStatus _status = new();
    private readonly FakeStartup _startup = new();
    private readonly FakeFirewall _firewall = new();
    private readonly FakeSpeakers _speakers = new();
    private readonly WorkerTexts _texts = new(CultureInfo.GetCultureInfo("en"));
    private WorkerPorts _ports = new(8766, 8767);

    private WorkerAppViewModel Create() =>
        new(_process, _status, _startup, _firewall, _speakers, _texts, () => _ports);

    [Fact]
    public async Task Starting_waits_for_the_worker_then_shows_how_to_reach_it()
    {
        var app = Create();

        app.StartCommand.Execute(null);
        await app.RefreshAsync(); // loading the model: no answer yet

        Assert.Equal(WorkerState.Starting, app.State);
        Assert.Equal(_texts["WorkerState_Starting"], app.StateText);
        Assert.False(app.StartCommand.CanExecute(null));

        _status.Answer = Status;
        await app.RefreshAsync();

        Assert.True(app.IsRunning);
        Assert.Equal(_texts["WorkerTag_Running"], app.StateTag);
        Assert.Equal(["http://192.168.0.20:8766", "http://172.26.32.1:8766"], app.Addresses);
        Assert.Equal(("GPU-PC", "0.9.0", "RTX 4070", "large-v3-turbo"), (app.Name, app.Version, app.Gpu, app.Model));
        Assert.Equal(("123456", "t0k"), (app.PairingCode, app.Token));
        Assert.True(app.HasPairingCode);
        Assert.Equal(_texts.Format("WorkerCodeExpires", "4:32"), app.CodeExpires);
        Assert.Equal([8766, 8766], _status.Ports);
    }

    [Fact]
    public async Task The_tasks_say_what_is_offered_and_why_one_is_missing()
    {
        _status.Answer = Status with
        {
            Tasks =
            [
                new WorkerTaskStatus("speech", true, null),
                new WorkerTaskStatus("speakers", false, "missing_hf_token"),
                new WorkerTaskStatus("translation", false, "missing_extra"),
            ],
        };
        var app = Create();
        app.StartCommand.Execute(null);

        await app.RefreshAsync();

        var env = @"C:\Users\me\AppData\Roaming\VozAta\worker\.env";
        Assert.Equal(
            [
                new WorkerTaskRow(_texts["WorkerTask_speech"], true, _texts["WorkerTaskOffered"]),
                new WorkerTaskRow(_texts["WorkerTask_speakers"], false, _texts.Format("WorkerTaskNeedsToken", env)),
                new WorkerTaskRow(_texts["WorkerTask_translation"], false, _texts["WorkerTaskNotInEdition"]),
            ],
            app.Tasks);
        Assert.True(app.HasTasks);
    }

    [Fact]
    public async Task Speakers_not_installed_can_be_downloaded_then_the_worker_restarts()
    {
        _status.Answer = Status with { Tasks = [new WorkerTaskStatus("speakers", false, "missing_extra")] };
        var app = Create();
        app.StartCommand.Execute(null);
        await app.RefreshAsync();
        Assert.Equal([new WorkerTaskRow(_texts["WorkerTask_speakers"], false, _texts["WorkerTaskNotInstalled"])], app.Tasks);
        Assert.True(app.CanDownloadSpeakers);
        SynchronizationContext.SetSynchronizationContext(null); // xUnit's posts: report at once
        string? seen = null;
        _speakers.During = () => seen = app.DownloadProgress;

        await app.DownloadSpeakersCommand.ExecuteAsync(null);

        Assert.Equal("2/4 PyTorch...", seen);
        Assert.Equal(_texts["WorkerSpeakersInstalled"], app.Message);
        Assert.Equal((1, WorkerState.Starting), (_process.Stops, app.State));
        Assert.False(app.CanDownloadSpeakers);
        Assert.False(app.IsDownloadingSpeakers);
        Assert.Null(app.DownloadProgress);
        Assert.Empty(app.Tasks);
    }

    [Fact]
    public async Task A_failed_download_names_its_log_and_keeps_the_worker()
    {
        _status.Answer = Status with { Tasks = [new WorkerTaskStatus("speakers", false, "missing_extra")] };
        _speakers.Result = false;
        var app = Create();
        app.StartCommand.Execute(null);
        await app.RefreshAsync();

        await app.DownloadSpeakersCommand.ExecuteAsync(null);

        Assert.Equal(_texts.Format("WorkerSpeakersFailed", _speakers.LogPath), app.Error);
        Assert.Equal((0, WorkerState.Running), (_process.Stops, app.State));
        Assert.True(app.DownloadSpeakersCommand.CanExecute(null));
    }

    [Fact]
    public async Task A_download_while_the_worker_is_stopped_does_not_start_it()
    {
        _status.Answer = Status with { Tasks = [new WorkerTaskStatus("speakers", false, "missing_extra")] };
        var app = Create();
        app.StartCommand.Execute(null);
        await app.RefreshAsync();
        var command = app.DownloadSpeakersCommand;
        app.StopCommand.Execute(null);

        Assert.False(command.CanExecute(null)); // stopped: the tasks are gone
        Assert.Equal(WorkerState.Stopped, app.State);
    }

    [Fact]
    public async Task Translation_missing_still_points_to_the_installation()
    {
        _status.Answer = Status with { Tasks = [new WorkerTaskStatus("translation", false, "missing_extra")] };
        var app = Create();
        app.StartCommand.Execute(null);

        await app.RefreshAsync();

        Assert.False(app.CanDownloadSpeakers);
    }

    [Fact]
    public async Task A_task_missing_for_an_unknown_reason_is_just_not_offered()
    {
        _status.Answer = Status with { Tasks = [new WorkerTaskStatus("speakers", false, null)] };
        var app = Create();
        app.StartCommand.Execute(null);

        await app.RefreshAsync();
        await app.RefreshAsync(); // the same answer again: the rows stay

        Assert.Equal([new WorkerTaskRow(_texts["WorkerTask_speakers"], false, _texts["WorkerTaskNotOffered"])], app.Tasks);
    }

    [Fact]
    public async Task An_older_worker_without_tasks_shows_no_task_card()
    {
        _status.Answer = Status; // no `tasks` in /local/status (before phase 51)
        var app = Create();
        app.StartCommand.Execute(null);

        await app.RefreshAsync();

        Assert.Empty(app.Tasks);
        Assert.False(app.HasTasks);
    }

    [Fact]
    public async Task Stopping_clears_the_tasks()
    {
        _status.Answer = Status with { Tasks = [new WorkerTaskStatus("speech", true, null)] };
        var app = Create();
        app.StartCommand.Execute(null);
        await app.RefreshAsync();

        app.StopCommand.Execute(null);

        Assert.Empty(app.Tasks);
        Assert.False(app.HasTasks);
    }

    [Fact]
    public async Task A_worker_without_gpu_model_or_token_says_so()
    {
        _status.Answer = Status with { Gpu = new WorkerGpu(false, null), Models = [], Token = null, PairingCode = null, CodeExpiresIn = null };
        var app = Create();
        app.StartCommand.Execute(null);

        await app.RefreshAsync();

        Assert.Equal((_texts["WorkerNoGpu"], _texts["WorkerNoModel"]), (app.Gpu, app.Model));
        Assert.False(app.HasPairingCode);
        Assert.Null(app.CodeExpires);
    }

    [Fact]
    public async Task The_ports_come_from_the_worker_settings()
    {
        _ports = new WorkerPorts(9000, 9001);
        var app = Create();
        app.StartCommand.Execute(null);

        await app.RefreshAsync();
        await app.AllowNetworkCommand.ExecuteAsync(null);

        Assert.Equal([9000], _status.Ports);
        Assert.Equal([(9000, 9001)], _firewall.Calls);
    }

    [Fact]
    public async Task A_worker_that_exits_is_a_failure_naming_its_log()
    {
        _status.Answer = Status;
        var app = Create();
        app.StartCommand.Execute(null);
        await app.RefreshAsync();

        _process.Running = false;
        await app.RefreshAsync();

        Assert.Equal(WorkerState.Failed, app.State);
        Assert.True(app.IsFailed);
        Assert.Equal(_texts.Format("WorkerExited", _process.LogPath), app.Error);
        Assert.Empty(app.Addresses);
        Assert.Null(app.PairingCode);
        Assert.True(app.StartCommand.CanExecute(null));
    }

    [Fact]
    public void A_missing_worker_program_is_reported()
    {
        _process.Found = false;
        var app = Create();

        app.StartCommand.Execute(null);

        Assert.Equal(WorkerState.Failed, app.State);
        Assert.Equal(_texts["WorkerNotFound"], app.Error);
    }

    [Fact]
    public async Task Stopping_stops_the_process_and_clears_the_status()
    {
        _status.Answer = Status;
        var app = Create();
        app.StartCommand.Execute(null);
        await app.RefreshAsync();

        app.StopCommand.Execute(null);
        await app.RefreshAsync(); // stopped: nothing is asked

        Assert.Equal(WorkerState.Stopped, app.State);
        Assert.Equal(1, _process.Stops);
        Assert.Null(app.Token);
        Assert.Single(_status.Ports);
        Assert.False(app.StopCommand.CanExecute(null));
    }

    [Fact]
    public void Exiting_the_app_stops_the_worker()
    {
        var app = Create();
        app.StartCommand.Execute(null);

        app.Shutdown();

        Assert.Equal(1, _process.Stops);
    }

    [Fact]
    public void Start_with_windows_reads_and_writes_the_startup_entry()
    {
        _startup.Enabled = true;
        var app = Create();
        Assert.True(app.StartWithWindows);

        app.StartWithWindows = false;
        app.StartWithWindows = false; // unchanged: written once

        Assert.Equal([false], _startup.Writes);
    }

    [Theory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task Allowing_on_the_network_reports_the_outcome(bool allowed)
    {
        _firewall.Result = allowed;
        var app = Create();

        await app.AllowNetworkCommand.ExecuteAsync(null);

        Assert.Equal(allowed ? _texts.Format("WorkerFirewallDone", 8766, 8767) : null, app.Message);
        Assert.Equal(allowed ? null : _texts["WorkerFirewallFailed"], app.Error);
    }

    private sealed class FakeProcess : IWorkerProcess
    {
        public bool Found { get; set; } = true;

        public bool Running { get; set; }

        public int Stops { get; private set; }

        public bool IsRunning => Running;

        public string LogPath => @"C:\Users\me\AppData\Roaming\VozAta\worker\worker.log";

        public bool Start()
        {
            Running = Found;
            return Found;
        }

        public void Terminate()
        {
            Stops++;
            Running = false;
        }
    }

    private sealed class FakeStatus : IWorkerStatusClient
    {
        public LocalStatus? Answer { get; set; }

        public List<int> Ports { get; } = [];

        public Task<LocalStatus?> GetAsync(int port, CancellationToken cancellationToken = default)
        {
            Ports.Add(port);
            return Task.FromResult(Answer);
        }
    }

    private sealed class FakeStartup : IStartupRegistry
    {
        public bool Enabled { get; set; }

        public List<bool> Writes { get; } = [];

        public bool IsEnabled => Enabled;

        public void Apply(bool enabled) => Writes.Add(enabled);
    }

    [Fact]
    public void Progress_is_reported_on_the_context_it_was_made_on()
    {
        var context = new RecordingContext();
        SynchronizationContext.SetSynchronizationContext(context);
        var lines = new List<string>();
        var progress = new ContextProgress(lines.Add);
        SynchronizationContext.SetSynchronizationContext(null);

        ((IProgress<string>)progress).Report("1/4 Python 3.13...");
        Assert.Empty(lines);
        context.RunPosted();

        Assert.Equal(["1/4 Python 3.13..."], lines);
    }

    private sealed class RecordingContext : SynchronizationContext
    {
        private readonly List<(SendOrPostCallback, object?)> _posted = [];

        public override void Post(SendOrPostCallback d, object? state) => _posted.Add((d, state));

        public void RunPosted() => _posted.ForEach(item => item.Item1(item.Item2));
    }

    private sealed class FakeSpeakers : ISpeakerInstaller
    {
        public bool Result { get; set; } = true;

        public Action? During { get; set; }

        public string LogPath => @"C:\Users\me\AppData\Roaming\VozAta\worker\speakers-install.log";

        public Task<bool> InstallAsync(IProgress<string> progress, CancellationToken cancellationToken = default)
        {
            progress.Report("2/4 PyTorch...");
            During?.Invoke();
            return Task.FromResult(Result);
        }
    }

    private sealed class FakeFirewall : IFirewall
    {
        public bool Result { get; set; } = true;

        public List<(int, int)> Calls { get; } = [];

        public Task<bool> AllowAsync(int httpPort, int discoveryPort)
        {
            Calls.Add((httpPort, discoveryPort));
            return Task.FromResult(Result);
        }
    }
}
