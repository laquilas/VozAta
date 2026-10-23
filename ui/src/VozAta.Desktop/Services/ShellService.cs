using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Input.Platform;
using System.Diagnostics;
using System.Diagnostics.CodeAnalysis;

namespace VozAta.Desktop.Services;

/// <summary>Opens a file or folder with its default Windows program (player, Explorer).</summary>
public interface IShellService
{
    void Open(string path);

    /// <summary>Put <paramref name="text"/> on the clipboard (phase 48: partial minutes).</summary>
    Task CopyTextAsync(string text);
}

[ExcludeFromCodeCoverage(Justification = "Starts external programs; tests use a fake.")]
public sealed class ShellService : IShellService
{
    public void Open(string path) => Process.Start(new ProcessStartInfo(path) { UseShellExecute = true })?.Dispose();

    public async Task CopyTextAsync(string text)
    {
        if (Application.Current?.ApplicationLifetime is IClassicDesktopStyleApplicationLifetime { MainWindow.Clipboard: { } clipboard })
        {
            await clipboard.SetTextAsync(text);
        }
    }
}
