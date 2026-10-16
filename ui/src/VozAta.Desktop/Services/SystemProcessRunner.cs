using System.Diagnostics;
using System.Diagnostics.CodeAnalysis;

namespace VozAta.Desktop.Services;

[ExcludeFromCodeCoverage(Justification = "Starts real processes; covered by the manual check.")]
public sealed class SystemProcessRunner : IProcessRunner
{
    public IRunningProcess Start(string fileName, string arguments, string workingDirectory)
    {
        var process = Process.Start(new ProcessStartInfo(fileName, arguments)
        {
            WorkingDirectory = workingDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
        }) ?? throw new InvalidOperationException($"Could not start {fileName}");
        return new Running(process);
    }

    private sealed class Running(Process process) : IRunningProcess
    {
        public bool HasExited => process.HasExited;

        public void Kill() => process.Kill(entireProcessTree: true);

        public void Dispose() => process.Dispose();
    }
}
