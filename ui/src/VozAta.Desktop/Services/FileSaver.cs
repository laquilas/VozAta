using System.Diagnostics.CodeAnalysis;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Platform.Storage;

namespace VozAta.Desktop.Services;

/// <summary>Asks where to save a file and writes it, or which file to read (phase 39).</summary>
public interface IFileSaver
{
    /// <summary>The chosen path, or null when the user cancelled.</summary>
    Task<string?> SaveAsync(string suggestedName, string typeName, string extension, byte[] content);

    /// <summary>
    /// Like <see cref="SaveAsync(string, string, string, byte[])"/>, but <paramref name="write"/> streams the content
    /// into the chosen file; when it fails the file is removed and the error rethrown.
    /// </summary>
    Task<string?> SaveAsync(string suggestedName, string typeName, string extension, Func<Stream, Task> write);

    /// <summary>The chosen file of one type, open for reading; null when the user cancelled.</summary>
    Task<Stream?> OpenAsync(string title, string typeName, string extension);
}

[ExcludeFromCodeCoverage(Justification = "Avalonia's save dialog; tests use a fake.")]
public sealed class AvaloniaFileSaver(IClassicDesktopStyleApplicationLifetime desktop) : IFileSaver
{
    public async Task<string?> SaveAsync(string suggestedName, string typeName, string extension, byte[] content)
    {
        if (desktop.MainWindow?.StorageProvider is not { } storage)
        {
            return null;
        }

        var file = await storage.SaveFilePickerAsync(new FilePickerSaveOptions
        {
            SuggestedFileName = suggestedName,
            DefaultExtension = extension,
            ShowOverwritePrompt = true,
            FileTypeChoices = [new FilePickerFileType(typeName) { Patterns = [$"*.{extension}"] }],
        });
        if (file is null)
        {
            return null;
        }

        await using (var stream = await file.OpenWriteAsync())
        {
            stream.SetLength(0);
            await stream.WriteAsync(content);
        }

        return file.TryGetLocalPath() ?? file.Name;
    }

    public async Task<string?> SaveAsync(string suggestedName, string typeName, string extension, Func<Stream, Task> write)
    {
        if (desktop.MainWindow?.StorageProvider is not { } storage)
        {
            return null;
        }

        var file = await storage.SaveFilePickerAsync(new FilePickerSaveOptions
        {
            SuggestedFileName = suggestedName,
            DefaultExtension = extension,
            ShowOverwritePrompt = true,
            FileTypeChoices = [new FilePickerFileType(typeName) { Patterns = [$"*.{extension}"] }],
        });
        if (file is null)
        {
            return null;
        }

        try
        {
            await using var stream = await file.OpenWriteAsync();
            stream.SetLength(0);
            await write(stream);
        }
        catch
        {
            await file.DeleteAsync(); // no half-written file is left behind
            throw;
        }

        return file.TryGetLocalPath() ?? file.Name;
    }

    public async Task<Stream?> OpenAsync(string title, string typeName, string extension)
    {
        if (desktop.MainWindow?.StorageProvider is not { } storage)
        {
            return null;
        }

        var files = await storage.OpenFilePickerAsync(new FilePickerOpenOptions
        {
            Title = title,
            AllowMultiple = false,
            FileTypeFilter = [new FilePickerFileType(typeName) { Patterns = [$"*.{extension}"] }],
        });
        return files.Count == 0 ? null : await files[0].OpenReadAsync();
    }
}
