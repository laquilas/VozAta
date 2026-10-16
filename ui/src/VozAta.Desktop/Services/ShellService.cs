using System.Diagnostics;
using System.Diagnostics.CodeAnalysis;

namespace VozAta.Desktop.Services;

/// <summary>Opens a file or folder with its default Windows program (player, Explorer).</summary>
public interface IShellService
{
    void Open(string path);
}

[ExcludeFromCodeCoverage(Justification = "Starts external programs; tests use a fake.")]
public sealed class ShellService : IShellService
{
    public void Open(string path) => Process.Start(new ProcessStartInfo(path) { UseShellExecute = true })?.Dispose();
}
