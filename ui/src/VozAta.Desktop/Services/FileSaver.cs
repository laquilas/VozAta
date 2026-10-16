using System.Diagnostics.CodeAnalysis;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Platform.Storage;

namespace VozAta.Desktop.Services;

/// <summary>Asks where to save a file and writes it.</summary>
public interface IFileSaver
{
    /// <summary>The chosen path, or null when the user cancelled.</summary>
    Task<string?> SaveAsync(string suggestedName, string typeName, string extension, byte[] content);
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
}
