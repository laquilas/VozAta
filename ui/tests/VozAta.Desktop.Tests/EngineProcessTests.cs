using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;

namespace VozAta.Desktop.Tests;

public sealed class EngineProcessTests : IDisposable
{
    private readonly string _root = Directory.CreateTempSubdirectory("vozata-ui-").FullName;
    private readonly FakeEngineClient _client = new();
    private readonly FakeRunner _runner = new();

    public EngineProcessTests()
    {
        Directory.CreateDirectory(Path.Combine(_root, "engine"));
        Directory.CreateDirectory(Path.Combine(_root, ".venv", "Scripts"));
        File.WriteAllText(Path.Combine(_root, ".venv", "Scripts", "python.exe"), "");
        Directory.CreateDirectory(Path.Combine(_root, "ui"));
    }

    public void Dispose() => Directory.Delete(_root, recursive: true);

    [Fact]
    public async Task A_running_engine_is_used_and_never_stopped()
    {
        var engine = Engine();

        Assert.Equal(EngineStartResult.AlreadyRunning, await engine.EnsureRunningAsync());
        engine.StopIfStarted();

        Assert.Empty(_runner.Started);
    }

    [Fact]
    public async Task A_missing_engine_is_started_and_awaited_until_healthy()
    {
        _client.UnavailableHealthChecks = 3;
        var engine = Engine();

        var result = await engine.EnsureRunningAsync();

        Assert.Equal(EngineStartResult.Started, result);
        var (file, arguments, directory) = _runner.Started.Single();
        Assert.Equal(Path.Combine(_root, ".venv", "Scripts", "python.exe"), file);
        Assert.Equal("-m vozata serve", arguments);
        Assert.Equal(Path.Combine(_root, "engine"), directory);
        Assert.Equal(4, _client.Calls.Count(call => call == "health"));
    }

    [Fact]
    public async Task An_engine_started_by_the_ui_is_stopped_on_exit_once()
    {
        _client.UnavailableHealthChecks = 1;
        var engine = Engine();
        await engine.EnsureRunningAsync();

        engine.StopIfStarted();
        engine.StopIfStarted();

        var process = _runner.Processes.Single();
        Assert.Equal(1, process.Kills);
        Assert.True(process.Disposed);
    }

    [Fact]
    public async Task An_already_exited_process_is_not_killed()
    {
        _client.UnavailableHealthChecks = 1;
        var engine = Engine();
        await engine.EnsureRunningAsync();
        _runner.Processes.Single().HasExited = true;

        engine.StopIfStarted();

        Assert.Equal(0, _runner.Processes.Single().Kills);
    }

    [Fact]
    public async Task Start_fails_after_the_timeout_and_stops_the_process()
    {
        _client.UnavailableHealthChecks = int.MaxValue;
        var engine = Engine(TimeSpan.FromSeconds(2));

        Assert.Equal(EngineStartResult.Failed, await engine.EnsureRunningAsync());

        Assert.Equal(1, _runner.Processes.Single().Kills);
        Assert.Equal(5, _client.Calls.Count(call => call == "health"));  // 1 + 4 polls of 0.5 s
    }

    [Fact]
    public async Task Start_fails_at_once_when_the_process_exits()
    {
        _client.UnavailableHealthChecks = int.MaxValue;
        _runner.ExitImmediately = true;
        var engine = Engine();

        Assert.Equal(EngineStartResult.Failed, await engine.EnsureRunningAsync());

        Assert.Single(_client.Calls);
        Assert.Equal(0, _runner.Processes.Single().Kills);
    }

    [Fact]
    public async Task Start_fails_without_running_anything_when_paths_do_not_exist()
    {
        _client.UnavailableHealthChecks = 1;
        var engine = new EngineProcess(
            _client,
            _runner,
            new EngineOptions { PythonPath = "missing/python.exe" },
            new PathResolver(Path.Combine(_root, "ui"), Path.Combine(_root, "ui")),
            NoDelay);

        Assert.Equal(EngineStartResult.Failed, await engine.EnsureRunningAsync());
        Assert.Empty(_runner.Started);
    }

    [Fact]
    public void Paths_resolve_from_the_current_directory_then_from_the_app_folders()
    {
        var bin = Directory.CreateDirectory(Path.Combine(_root, "ui", "bin", "Debug")).FullName;
        var fromUi = new PathResolver(Path.Combine(_root, "ui"), bin);
        var fromElsewhere = new PathResolver(Path.GetTempPath(), bin);
        var absolute = Path.Combine(_root, "engine");

        Assert.Equal(Path.Combine(_root, "engine"), fromUi.Resolve("../engine"));
        Assert.Equal(Path.Combine(_root, "engine"), fromElsewhere.Resolve("engine"));
        Assert.Equal(absolute, fromUi.Resolve(absolute));
        Assert.Null(fromUi.Resolve(Path.Combine(_root, "nope")));
        Assert.Null(fromElsewhere.Resolve("definitely-not-here-123"));
    }

    [Fact]
    public async Task Restart_stops_the_engine_it_started_and_starts_a_new_one()
    {
        _client.UnavailableHealthChecks = 1;
        var engine = Engine();
        await engine.EnsureRunningAsync();
        _client.UnavailableHealthChecks = 1;  // the old engine is gone

        var result = await engine.RestartAsync();

        Assert.Equal(EngineRestartResult.Restarted, result);
        Assert.Equal(2, _runner.Started.Count);
        Assert.Equal((1, true), (_runner.Processes[0].Kills, _runner.Processes[0].Disposed));
        engine.StopIfStarted();
        Assert.Equal(1, _runner.Processes[1].Kills);
    }

    [Fact]
    public async Task An_engine_started_elsewhere_is_not_restarted()
    {
        var engine = Engine();
        await engine.EnsureRunningAsync();

        Assert.Equal(EngineRestartResult.NotOwned, await engine.RestartAsync());
        Assert.Empty(_runner.Started);
    }

    [Fact]
    public async Task A_restart_that_cannot_start_the_engine_again_fails()
    {
        _client.UnavailableHealthChecks = 1;
        var engine = Engine(TimeSpan.FromSeconds(1));
        await engine.EnsureRunningAsync();
        _client.UnavailableHealthChecks = 1000;
        _runner.ExitImmediately = true;

        Assert.Equal(EngineRestartResult.Failed, await engine.RestartAsync());
    }

    [Fact]
    public async Task An_installed_engine_runs_its_executable_in_an_expanded_working_folder()
    {
        _client.UnavailableHealthChecks = 1;
        var exe = Path.Combine(_root, "app", "engine", "vozata-engine.exe");
        Directory.CreateDirectory(Path.GetDirectoryName(exe)!);
        File.WriteAllText(exe, "");
        Environment.SetEnvironmentVariable("VOZATA_TEST_DATA", Path.Combine(_root, "data"));
        var engine = Installed("%VOZATA_TEST_DATA%/VozAta");

        var result = await engine.EnsureRunningAsync();

        Assert.Equal(EngineStartResult.Started, result);
        var (file, arguments, directory) = _runner.Started.Single();
        Assert.Equal((exe, "serve"), (file, arguments));
        Assert.Equal(Path.GetFullPath(Path.Combine(_root, "data", "VozAta")), directory);
        Assert.True(Directory.Exists(directory));  // created for the engine's .env and logs
    }

    [Fact]
    public async Task A_missing_installed_engine_fails_without_falling_back_to_python()
    {
        _client.UnavailableHealthChecks = 1;

        var result = await Installed(Path.Combine(_root, "data")).EnsureRunningAsync();

        Assert.Equal(EngineStartResult.Failed, result);
        Assert.Empty(_runner.Started);
    }

    private EngineProcess Installed(string workingDirectory) =>
        new(
            _client,
            _runner,
            new EngineOptions { ExecutablePath = "engine/vozata-engine.exe", WorkingDirectory = workingDirectory },
            new PathResolver(Path.Combine(_root, "elsewhere"), Path.Combine(_root, "app")),
            NoDelay);

    private EngineProcess Engine(TimeSpan? timeout = null) =>
        new(
            _client,
            _runner,
            new EngineOptions { StartTimeout = timeout ?? TimeSpan.FromSeconds(60) },
            new PathResolver(Path.Combine(_root, "ui"), Path.Combine(_root, "ui")),
            NoDelay);

    private static Task NoDelay(TimeSpan wait, CancellationToken token) => Task.CompletedTask;

    private sealed class FakeRunner : IProcessRunner
    {
        public List<(string File, string Arguments, string Directory)> Started { get; } = [];

        public List<FakeProcess> Processes { get; } = [];

        public bool ExitImmediately { get; set; }

        public IRunningProcess Start(string fileName, string arguments, string workingDirectory)
        {
            Started.Add((fileName, arguments, workingDirectory));
            var process = new FakeProcess { HasExited = ExitImmediately };
            Processes.Add(process);
            return process;
        }
    }

    private sealed class FakeProcess : IRunningProcess
    {
        public bool HasExited { get; set; }

        public int Kills { get; private set; }

        public bool Disposed { get; private set; }

        public void Kill()
        {
            Kills++;
            HasExited = true;
        }

        public void Dispose() => Disposed = true;
    }
}
