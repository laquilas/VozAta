using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

public enum RecordingState
{
    Idle,
    Starting,
    Recording,
    Paused,
    Finalizing,
}

public enum EngineStatus
{
    Starting,
    Connected,
    Disconnected,
    Failed,
}

/// <summary>One transcript line: `[hh:mm:ss] Label: text`, coloured by speaker.</summary>
public sealed record TranscriptLine(string Timestamp, string Label, string Text, string Channel)
{
    public string Display => $"[{Timestamp}] {Label}: {Text}";

    public string Color => Channel switch
    {
        "mic" => "#2E7D32",
        "system" => "#1565C0",
        _ => "#6A1B9A",
    };

    public static string FormatTime(double seconds)
    {
        var time = TimeSpan.FromSeconds(Math.Max(0, Math.Floor(seconds)));
        return string.Create(
            CultureInfo.InvariantCulture, $"{(int)time.TotalHours:00}:{time.Minutes:00}:{time.Seconds:00}");
    }
}

/// <summary>A choice shown with a localized label (refreshed when the UI language changes).</summary>
public sealed partial class ChoiceOption(string value, string labelKey) : ObservableObject
{
    public string Value { get; } = value;

    public string LabelKey { get; } = labelKey;

    [ObservableProperty]
    public partial string Label { get; private set; } = labelKey;

    public void Refresh(ILocalizationService localization) => Label = localization[LabelKey];

    /// <summary>What screen readers announce for the option.</summary>
    public override string ToString() => Label;
}

/// <summary>Read-only view of the string table for XAML bindings (<c>L[Key]</c>).</summary>
public sealed class Strings(ILocalizationService localization)
{
    public string this[string key] => localization[key];
}
