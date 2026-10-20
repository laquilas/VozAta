using System.Text.Json;
using VozAta.Client;

namespace VozAta.Desktop.Services;

/// <summary>
/// A remembered audio device. WASAPI ids change when devices are plugged in or out, so the name is
/// kept too and wins when restoring.
/// </summary>
public sealed record DeviceChoice(int Id, string Name);

/// <summary>What the desktop app remembers between runs (not engine settings).</summary>
public sealed record UiPreferencesData(
    DeviceChoice? Mic = null,
    DeviceChoice? Loopback = null,
    double? WindowWidth = null,
    double? WindowHeight = null,
    bool MinimizeToTray = false,
    string Theme = "system",
    bool SidebarCollapsed = false,
    bool? LiveTranscription = null);

public interface IUiPreferences
{
    /// <summary>The saved preferences; empty when nothing (valid) was saved.</summary>
    UiPreferencesData Load();

    /// <summary>Persist the preferences; failures are ignored (preferences are a convenience).</summary>
    void Save(UiPreferencesData preferences);
}

/// <summary><see cref="IUiPreferences"/> in a JSON file, by default <c>%APPDATA%/VozAta/ui.json</c>.</summary>
public sealed class JsonFileUiPreferences(string path) : IUiPreferences
{
    public static string DefaultPath() => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "VozAta", "ui.json");

    public UiPreferencesData Load()
    {
        try
        {
            return JsonSerializer.Deserialize<UiPreferencesData>(File.ReadAllText(path), EngineJson.Options)
                ?? new UiPreferencesData();
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException)
        {
            return new UiPreferencesData();
        }
    }

    public void Save(UiPreferencesData preferences)
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            File.WriteAllText(path, JsonSerializer.Serialize(preferences, EngineJson.Options));
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            // Not worth interrupting the user: the defaults apply next time.
        }
    }
}
