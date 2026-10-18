using System.Reflection;
using CommunityToolkit.Mvvm.Input;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>A license link of Config → About.</summary>
public sealed record LicenseLink(string Name, string Url)
{
    public override string ToString() => Name;
}

/// <summary>
/// Config → About (phase 38): app and engine versions, GPU and models (the engine status that
/// phase 35 moved to Config), and links to the licenses.
/// </summary>
public sealed partial class AboutViewModel(HealthViewModel health, IShellService shell)
{
    /// <summary>The desktop app version (assembly informational version, without the commit hash).</summary>
    public string AppVersion { get; } = Version(typeof(AboutViewModel).Assembly);

    public HealthViewModel Health { get; } = health;

    public IReadOnlyList<LicenseLink> Licenses { get; } =
    [
        new("VozAta (MIT)", "https://github.com/laquilas/VozAta/blob/main/LICENSE"),
        new("Avalonia (MIT)", "https://github.com/AvaloniaUI/Avalonia/blob/master/licence.md"),
        new("faster-whisper (MIT)", "https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE"),
        new("pyannote.audio (MIT)", "https://github.com/pyannote/pyannote-audio/blob/develop/LICENSE"),
        new("Ollama (MIT)", "https://github.com/ollama/ollama/blob/main/LICENSE"),
    ];

    [RelayCommand]
    private void OpenLink(LicenseLink? link)
    {
        if (link is not null)
        {
            shell.Open(link.Url);
        }
    }

    private static string Version(Assembly assembly)
    {
        var version = assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion
            ?? assembly.GetName().Version?.ToString() ?? "?";
        var plus = version.IndexOf('+', StringComparison.Ordinal);
        return plus < 0 ? version : version[..plus];
    }
}
