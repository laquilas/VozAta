using VozAta.Desktop.Services;

namespace VozAta.Desktop.Tests.Fakes;

/// <summary>Answers Browse with <see cref="Folder"/> / <see cref="File"/> (null = cancelled) and records the calls.</summary>
internal sealed class FakePathPicker : IPathPicker
{
    public string? Folder { get; set; } = @"D:\Meetings";

    public string? File { get; set; } = @"D:\Lists\terms.txt";

    public List<(string Kind, string Title, string? Start)> Calls { get; } = [];

    public Task<string?> PickFolderAsync(string title, string? start)
    {
        Calls.Add(("folder", title, start));
        return Task.FromResult(Folder);
    }

    public Task<string?> PickFileAsync(string title, string? start)
    {
        Calls.Add(("file", title, start));
        return Task.FromResult(File);
    }
}
