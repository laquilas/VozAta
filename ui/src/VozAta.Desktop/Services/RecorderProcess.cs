using VozAta.Client;

namespace VozAta.Desktop.Services;

/// <summary>Where the recorder process lives (`Recorder` section of appsettings.json, phase 61).</summary>
public sealed class RecorderOptions
{
    public string BaseUrl { get; set; } = "http://127.0.0.1:8769/";

    public string PythonPath { get; set; } = "../.venv/Scripts/python.exe";

    /// <summary>
    /// Where the recorder runs and reads its <c>.env</c>: the engine's folder, so both use the same
    /// recordings folder. Environment variables are expanded; with <see cref="ExecutablePath"/> it is created.
    /// </summary>
    public string WorkingDirectory { get; set; } = "../engine";

    /// <summary>The packaged recorder (<c>vozata-recorder.exe</c>); when set, Python is not used.</summary>
    public string? ExecutablePath { get; set; }

    /// <summary>It answers in about a second; a slow disk or antivirus may take longer.</summary>
    public TimeSpan StartTimeout { get; set; } = TimeSpan.FromSeconds(15);
}

public enum RecorderStartResult
{
    AlreadyRunning,
    Started,
    Failed,
}

/// <summary>
/// The recorder process (phase 61). It is started detached and never stopped by the app: it keeps
/// recording when the app closes or crashes, and the next app start finds it running.
/// </summary>
public interface IRecorderProcess
{
    /// <summary>Use a running recorder, or start one and wait until <c>/health</c> answers.</summary>
    Task<RecorderStartResult> EnsureRunningAsync(CancellationToken cancellationToken = default);
}

public sealed class RecorderProcess(
    IRecorderClient client,
    IProcessRunner runner,
    RecorderOptions options,
    PathResolver paths,
    Func<TimeSpan, CancellationToken, Task>? delay = null) : IRecorderProcess
{
    public static readonly TimeSpan PollInterval = TimeSpan.FromMilliseconds(250);

    private readonly Func<TimeSpan, CancellationToken, Task> _delay = delay ?? Task.Delay;

    public async Task<RecorderStartResult> EnsureRunningAsync(CancellationToken cancellationToken = default)
    {
        if (await IsHealthyAsync(cancellationToken))
        {
            return RecorderStartResult.AlreadyRunning;
        }

        if (Command() is not var (fileName, arguments, workingDirectory))
        {
            return RecorderStartResult.Failed;
        }

        using var process = runner.Start(fileName, arguments, workingDirectory); // released, never killed
        for (var waited = TimeSpan.Zero; waited < options.StartTimeout; waited += PollInterval)
        {
            await _delay(PollInterval, cancellationToken);
            if (await IsHealthyAsync(cancellationToken))
            {
                return RecorderStartResult.Started;
            }

            if (process.HasExited && !await IsHealthyAsync(cancellationToken))
            {
                return RecorderStartResult.Failed; // e.g. its port is taken by something else
            }
        }

        return RecorderStartResult.Failed;
    }

    private (string FileName, string Arguments, string WorkingDirectory)? Command()
    {
        var workingDirectory = Environment.ExpandEnvironmentVariables(options.WorkingDirectory);
        if (options.ExecutablePath is { Length: > 0 } executable)
        {
            if (paths.Resolve(executable) is not { } recorder)
            {
                return null;
            }

            Directory.CreateDirectory(workingDirectory);
            return (recorder, "", Path.GetFullPath(workingDirectory));
        }

        var python = paths.Resolve(options.PythonPath);
        var folder = paths.Resolve(workingDirectory);
        return python is null || folder is null ? null : (python, "-m vozata.recorder", folder);
    }

    private async Task<bool> IsHealthyAsync(CancellationToken cancellationToken)
    {
        try
        {
            await client.GetHealthAsync(cancellationToken);
            return true;
        }
        catch (Exception error) when (error is EngineUnavailableException or EngineApiException
                                          or System.Text.Json.JsonException or TaskCanceledException)
        {
            return false;
        }
    }
}
