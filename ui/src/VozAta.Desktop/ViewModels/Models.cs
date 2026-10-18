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

    /// <summary>The engine's segment id (history detail only; search opens a session there).</summary>
    public string? SegmentId { get; init; }

    /// <summary>The live translation shown under the line (phase 29); null until it arrives.</summary>
    public string? Translation { get; init; }

    public bool HasTranslation => !string.IsNullOrEmpty(Translation);

    /// <summary>The line a search result opened (highlighted and scrolled into view).</summary>
    public bool IsFocused { get; init; }

    /// <summary>The text split around low-confidence words (phase 21); null when none is highlighted.</summary>
    public IReadOnlyList<TextPart>? LowConfidenceParts { get; init; }

    /// <summary><see cref="Display"/> in parts, for the highlighted history transcript.</summary>
    public IReadOnlyList<TextPart> DisplayParts =>
        [new TextPart($"[{Timestamp}] {Label}: "), .. LowConfidenceParts ?? [new TextPart(Text)]];

    /// <summary>Spoken into the microphone: the view colors it with <c>Brush.ChannelMic</c>.</summary>
    public bool IsMic => IsMicChannel(Channel);

    /// <summary>Heard on the system output: the view colors it with <c>Brush.ChannelSystem</c>.</summary>
    public bool IsSystem => IsSystemChannel(Channel);

    public static bool IsMicChannel(string channel) => channel == "mic";

    public static bool IsSystemChannel(string channel) => channel == "system";

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
