using System.Diagnostics.CodeAnalysis;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Platform.Storage;

namespace VozAta.Desktop.Services;

/// <summary>Asks the user for a folder or a file (the Browse buttons of the Config page).</summary>
public interface IPathPicker
{
    /// <summary>The chosen folder's local path, or null when the user cancelled.</summary>
    Task<string?> PickFolderAsync(string title, string? start);

    /// <summary>The chosen file's local path, or null when the user cancelled.</summary>
    Task<string?> PickFileAsync(string title, string? start);
}

[ExcludeFromCodeCoverage(Justification = "Avalonia's storage provider dialogs; tests use a fake.")]
public sealed class AvaloniaPathPicker(IClassicDesktopStyleApplicationLifetime desktop) : IPathPicker
{
    public async Task<string?> PickFolderAsync(string title, string? start)
    {
        if (desktop.MainWindow?.StorageProvider is not { } storage)
        {
            return null;
        }

        var folders = await storage.OpenFolderPickerAsync(new FolderPickerOpenOptions
        {
            Title = title,
            AllowMultiple = false,
            SuggestedStartLocation = await StartAsync(storage, start),
        });
        return folders.Count == 0 ? null : folders[0].TryGetLocalPath();
    }

    public async Task<string?> PickFileAsync(string title, string? start)
    {
        if (desktop.MainWindow?.StorageProvider is not { } storage)
        {
            return null;
        }

        var files = await storage.OpenFilePickerAsync(new FilePickerOpenOptions
        {
            Title = title,
            AllowMultiple = false,
            SuggestedStartLocation = await StartAsync(storage, start is null ? null : Path.GetDirectoryName(start)),
        });
        return files.Count == 0 ? null : files[0].TryGetLocalPath();
    }

    private static async Task<IStorageFolder?> StartAsync(IStorageProvider storage, string? folder) =>
        string.IsNullOrEmpty(folder) || !Directory.Exists(folder) ? null : await storage.TryGetFolderFromPathAsync(folder);
}
