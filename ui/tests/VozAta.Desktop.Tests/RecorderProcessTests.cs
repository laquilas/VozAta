using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.Tests;

/// <summary>The recorder process is started detached and never stopped by the app (phase 61).</summary>
public sealed class RecorderProcessTests : IDisposable
{
    private readonly string _root = Directory.CreateTempSubdirectory("vozata-recorder-").FullName;
    private readonly Health _client = new();
    private readonly Runner _runner = new();

    public RecorderProcessTests()
    {
        Directory.CreateDirectory(Path.Combine(_root, "engine"));
        Directory.CreateDirectory(Path.Combine(_root, ".venv", "Scripts"));
        File.WriteAllText(Path.Combine(_root, ".venv", "Scripts", "python.exe"), "");
        Directory.CreateDirectory(Path.Combine(_root, "ui"));
    }

    public void Dispose() => Directory.Delete(_root, recursive: true);

    [Fact]
    public async Task A_running_recorder_is_used()
    {
        Assert.Equal(RecorderStartResult.AlreadyRunning, await Recorder().EnsureRunningAsync());
        Assert.Empty(_runner.Started);
    }

    [Fact]
    public async Task A_missing_recorder_is_started_from_the_engine_folder_and_released_not_killed()
    {
        _client.Down = 2;

        var result = await Recorder().EnsureRunningAsync();

        Assert.Equal(RecorderStartResult.Started, result);
        var (file, arguments, directory) = _runner.Started.Single();
        Assert.Equal(Path.Combine(_root, ".venv", "Scripts", "python.exe"), file);
        Assert.Equal("-m vozata.recorder", arguments);
        Assert.Equal(Path.Combine(_root, "engine"), directory);
        Assert.True(_runner.Process!.Disposed);
        Assert.Equal(0, _runner.Process.Kills);
    }

    [Fact]
    public async Task The_installed_recorder_is_started_without_python()
    {
        _client.Down = 1;
        var folder = Path.Combine(_root, "data");
        Directory.CreateDirectory(Path.Combine(_root, "recorder"));
        File.WriteAllText(Path.Combine(_root, "recorder", "vozata-recorder.exe"), "");
        var options = new RecorderOptions { ExecutablePath = "recorder/vozata-recorder.exe", WorkingDirectory = folder };

        Assert.Equal(RecorderStartResult.Started, await Recorder(options).EnsureRunningAsync());

        var (file, arguments, directory) = _runner.Started.Single();
        Assert.Equal((Path.Combine(_root, "recorder", "vozata-recorder.exe"), "", folder), (file, arguments, directory));
        Assert.True(Directory.Exists(folder));
    }

    [Fact]
    public async Task A_recorder_that_exits_at_once_failed()
    {
        _client.Down = 100;
        _runner.ExitImmediately = true;

        Assert.Equal(RecorderStartResult.Failed, await Recorder().EnsureRunningAsync());
    }

    [Fact]
    public async Task A_recorder_that_never_answers_failed()
    {
        _client.Down = 1000;
        var options = new RecorderOptions { StartTimeout = TimeSpan.FromSeconds(1) };

        Assert.Equal(RecorderStartResult.Failed, await Recorder(options).EnsureRunningAsync());
    }

    [Fact]
    public async Task A_missing_executable_fails_without_starting()
    {
        _client.Down = 1;
        var options = new RecorderOptions { ExecutablePath = "nowhere/vozata-recorder.exe" };

        Assert.Equal(RecorderStartResult.Failed, await Recorder(options).EnsureRunningAsync());
        Assert.Empty(_runner.Started);
    }

    private RecorderProcess Recorder(RecorderOptions? options = null) =>
        new(
            _client,
            _runner,
            options ?? new RecorderOptions(),
            new PathResolver(Path.Combine(_root, "ui"), Path.Combine(_root, "ui")),
            (wait, token) => Task.CompletedTask);

    private sealed class Health : IRecorderClient
    {
        public int Down { get; set; }

        public Task<RecorderHealth> GetHealthAsync(CancellationToken cancellationToken = default)
        {
            if (Down-- > 0)
            {
                throw new EngineUnavailableException("refused", new HttpRequestException());
            }

            return Task.FromResult(new RecorderHealth("ok", "0.3.1", null));
        }

        public Task<DeviceList> GetDevicesAsync(CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<RecordingSummary> StartAsync(StartRecordingRequest request, CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<RecordingSummary> PauseAsync(CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<RecordingSummary> ResumeAsync(CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<RecordingSummary> StopAsync(CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<RecordingSummary> UpdateOptionsAsync(IReadOnlyDictionary<string, object?> options, CancellationToken cancellationToken = default) => throw new NotSupportedException();
    }

    private sealed class Runner : IProcessRunner
    {
        public List<(string File, string Arguments, string Directory)> Started { get; } = [];

        public Process? Process { get; private set; }

        public bool ExitImmediately { get; set; }

        public IRunningProcess Start(string fileName, string arguments, string workingDirectory)
        {
            Started.Add((fileName, arguments, workingDirectory));
            Process = new Process { HasExited = ExitImmediately };
            return Process;
        }
    }

    private sealed class Process : IRunningProcess
    {
        public bool HasExited { get; set; }

        public int Kills { get; private set; }

        public bool Disposed { get; private set; }

        public void Kill() => Kills++;

        public void Dispose() => Disposed = true;
    }
}
