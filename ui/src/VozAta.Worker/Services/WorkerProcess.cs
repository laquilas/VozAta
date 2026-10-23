using System.Diagnostics;
using System.Diagnostics.CodeAnalysis;

namespace VozAta.Worker.Services;

public interface IWorkerProcess
{
    bool IsRunning { get; }

    /// <summary>Where the worker's output goes.</summary>
    string LogPath { get; }

    /// <summary>Start the worker; false when its program was not found.</summary>
    bool Start();

    void Terminate();
}

/// <summary>The worker as a child process without a window; its output goes to <c>worker.log</c>.</summary>
[ExcludeFromCodeCoverage(Justification = "Starts a real process; covered by the manual check.")]
public sealed class SystemWorkerProcess(WorkerCommand? command) : IWorkerProcess, IDisposable
{
    private Process? _process;
    private StreamWriter? _log;

    public bool IsRunning => _process is { HasExited: false };

    public string LogPath => Path.Combine(command?.WorkingDirectory ?? AppContext.BaseDirectory, "worker.log");

    public bool Start()
    {
        if (command is null)
        {
            return false;
        }

        Terminate();
        Directory.CreateDirectory(command.WorkingDirectory);
        _log = new StreamWriter(LogPath, append: false) { AutoFlush = true };
        var start = new ProcessStartInfo(command.FileName, command.Arguments)
        {
            WorkingDirectory = command.WorkingDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        start.Environment["PYTHONIOENCODING"] = "utf-8";
        _process = new Process { StartInfo = start, EnableRaisingEvents = true };
        _process.OutputDataReceived += (_, line) => Write(line.Data);
        _process.ErrorDataReceived += (_, line) => Write(line.Data);
        _process.Start();
        _process.BeginOutputReadLine();
        _process.BeginErrorReadLine();
        return true;
    }

    public void Terminate()
    {
        if (_process is { HasExited: false } running)
        {
            running.Kill(entireProcessTree: true);
            running.WaitForExit(5000);
        }

        _process?.Dispose();
        _process = null;
        _log?.Dispose();
        _log = null;
    }

    public void Dispose() => Terminate();

    private void Write(string? line)
    {
        if (line is not null)
        {
            lock (this)
            {
                _log?.WriteLine(line);
            }
        }
    }
}
