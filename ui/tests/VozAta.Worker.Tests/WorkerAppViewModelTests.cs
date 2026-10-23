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
    private readonly WorkerTexts _texts = new(CultureInfo.GetCultureInfo("en"));
    private WorkerPorts _ports = new(8766, 8767);

    private WorkerAppViewModel Create() =>
        new(_process, _status, _startup, _firewall, _texts, () => _ports);

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
