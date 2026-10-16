using VozAta.Client;

namespace VozAta.Desktop.Services;

/// <summary>Where the engine lives (`Engine` section of appsettings.json).</summary>
public sealed class EngineOptions
{
    public string BaseUrl { get; set; } = "http://127.0.0.1:8765/";

    public string PythonPath { get; set; } = "../.venv/Scripts/python.exe";

    public string WorkingDirectory { get; set; } = "../engine";

    /// <summary>The first start loads models, so it can take a while.</summary>
    public TimeSpan StartTimeout { get; set; } = TimeSpan.FromSeconds(60);
}

public interface IRunningProcess : IDisposable
{
    bool HasExited { get; }

    void Kill();
}

public interface IProcessRunner
{
    IRunningProcess Start(string fileName, string arguments, string workingDirectory);
}

public enum EngineStartResult
{
    AlreadyRunning,
    Started,
    Failed,
}

public interface IEngineProcess
{
    /// <summary>Use a running engine, or start one and wait until `/health` answers.</summary>
    Task<EngineStartResult> EnsureRunningAsync(CancellationToken cancellationToken = default);

    /// <summary>Stop the engine, but only if this app started it.</summary>
    void StopIfStarted();
}

public sealed class EngineProcess(
    IEngineClient client,
    IProcessRunner runner,
    EngineOptions options,
    PathResolver paths,
    Func<TimeSpan, CancellationToken, Task>? delay = null) : IEngineProcess
{
    public static readonly TimeSpan PollInterval = TimeSpan.FromSeconds(0.5);

    private readonly Func<TimeSpan, CancellationToken, Task> _delay = delay ?? Task.Delay;
    private IRunningProcess? _process;

    public async Task<EngineStartResult> EnsureRunningAsync(CancellationToken cancellationToken = default)
    {
        if (await IsHealthyAsync(cancellationToken))
        {
            return EngineStartResult.AlreadyRunning;
        }

        var python = paths.Resolve(options.PythonPath);
        var workingDirectory = paths.Resolve(options.WorkingDirectory);
        if (python is null || workingDirectory is null)
        {
            return EngineStartResult.Failed;
        }

        _process = runner.Start(python, "-m vozata serve", workingDirectory);
        for (var waited = TimeSpan.Zero; waited < options.StartTimeout; waited += PollInterval)
        {
            if (_process.HasExited)
            {
                break;
            }

            await _delay(PollInterval, cancellationToken);
            if (await IsHealthyAsync(cancellationToken))
            {
                return EngineStartResult.Started;
            }
        }

        StopIfStarted();
        return EngineStartResult.Failed;
    }

    public void StopIfStarted()
    {
        if (_process is null)
        {
            return;
        }

        if (!_process.HasExited)
        {
            _process.Kill();
        }

        _process.Dispose();
        _process = null;
    }

    private async Task<bool> IsHealthyAsync(CancellationToken cancellationToken)
    {
        try
        {
            await client.GetHealthAsync(cancellationToken);
            return true;
        }
        catch (Exception error) when (error is EngineUnavailableException or EngineApiException)
        {
            return false;
        }
    }
}

/// <summary>
/// Resolves configured paths: absolute paths as they are; relative ones against the current
/// directory, then against each folder above the app (so `../engine` works from `ui/` and from
/// the build output).
/// </summary>
public sealed class PathResolver(string currentDirectory, string appDirectory)
{
    public static PathResolver ForProcess() =>
        new(Environment.CurrentDirectory, AppContext.BaseDirectory);

    public string? Resolve(string path)
    {
        if (Path.IsPathRooted(path))
        {
            return Exists(path) ? path : null;
        }

        foreach (var root in Roots())
        {
            var candidate = Path.GetFullPath(Path.Combine(root, path));
            if (Exists(candidate))
            {
                return candidate;
            }
        }

        return null;
    }

    private IEnumerable<string> Roots()
    {
        yield return currentDirectory;
        for (var folder = new DirectoryInfo(appDirectory); folder is not null; folder = folder.Parent)
        {
            yield return folder.FullName;
        }
    }

    private static bool Exists(string path) => File.Exists(path) || Directory.Exists(path);
}
