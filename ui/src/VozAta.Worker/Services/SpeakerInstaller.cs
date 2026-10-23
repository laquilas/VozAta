using System.Diagnostics;
using System.Diagnostics.CodeAnalysis;
using System.Text;

namespace VozAta.Worker.Services;

/// <summary>Downloads speaker identification onto this PC (phase 56): <c>engine speakers install</c>.</summary>
public interface ISpeakerInstaller
{
    /// <summary>Where the download's output goes.</summary>
    string LogPath { get; }

    /// <summary>Run the download; each output line is reported. False when it failed.</summary>
    Task<bool> InstallAsync(IProgress<string> progress, CancellationToken cancellationToken = default);
}

/// <summary>The engine's <c>speakers install</c> as a child process without a window.</summary>
[ExcludeFromCodeCoverage(Justification = "Starts a real process; covered by the manual check.")]
public sealed class SystemSpeakerInstaller(WorkerCommand? command) : ISpeakerInstaller
{
    public string LogPath =>
        Path.Combine(command?.WorkingDirectory ?? AppContext.BaseDirectory, "speakers-install.log");

    public async Task<bool> InstallAsync(IProgress<string> progress, CancellationToken cancellationToken = default)
    {
        if (command?.SpeakersInstall() is not { } install)
        {
            return false;
        }

        Directory.CreateDirectory(install.WorkingDirectory);
        await using var log = new StreamWriter(LogPath, append: false) { AutoFlush = true };
        var start = new ProcessStartInfo(install.FileName, install.Arguments)
        {
            WorkingDirectory = install.WorkingDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        start.Environment["PYTHONIOENCODING"] = "utf-8";
        using var process = new Process { StartInfo = start };
        void Line(string? text)
        {
            if (string.IsNullOrWhiteSpace(text))
            {
                return;
            }

            lock (log)
            {
                log.WriteLine(text);
            }

            progress.Report(text.Trim());
        }

        process.OutputDataReceived += (_, line) => Line(line.Data);
        process.ErrorDataReceived += (_, line) => Line(line.Data);
        process.Start();
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        try
        {
            await process.WaitForExitAsync(cancellationToken);
        }
        catch (OperationCanceledException)
        {
            process.Kill(entireProcessTree: true);
            throw;
        }

        return process.ExitCode == 0;
    }
}
