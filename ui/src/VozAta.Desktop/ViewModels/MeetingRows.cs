using System.Collections.ObjectModel;
using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using VozAta.Client;

namespace VozAta.Desktop.ViewModels;

/// <summary>One export format a meeting row offers (Markdown, Word, PDF).</summary>
public sealed record MeetingExport(MeetingRow Row, string Format, string Label)
{
    public override string ToString() => Label;
}

/// <summary>
/// One meeting of the Meetings page (phase 36): title (or "Untitled meeting"), tags, speakers,
/// start–end time and duration. The texts are built by <see cref="MeetingsPageViewModel"/>; the row
/// keeps only its editing, export and selection state.
/// </summary>
public sealed partial class MeetingRow : ObservableObject
{
    public MeetingRow(
        SessionSummary summary,
        string displayTitle,
        IReadOnlyList<string> tags,
        string timeRange,
        string duration,
        string speakersText,
        IReadOnlyList<(string Format, string Label)> exports)
    {
        Summary = summary;
        DisplayTitle = displayTitle;
        Tags = tags;
        TimeRange = timeRange;
        Duration = duration;
        SpeakersText = speakersText;
        Exports = [.. exports.Select(export => new MeetingExport(this, export.Format, export.Label))];
    }

    public SessionSummary Summary { get; }

    public string Id => Summary.Id;

    /// <summary>The title, or "Untitled meeting" (shown as secondary text).</summary>
    public string DisplayTitle { get; }

    public bool IsUntitled => Summary.Title is null;

    /// <summary>Pills: the minutes template and the language.</summary>
    public IReadOnlyList<string> Tags { get; }

    /// <summary>"09:00 – 09:42" in local time; "09:00 –" while it is recorded.</summary>
    public string TimeRange { get; }

    /// <summary><c>h:mm:ss</c>, like Toggl.</summary>
    public string Duration { get; }

    public int SpeakerCount => Summary.SpeakerCount;

    public bool HasSpeakers => SpeakerCount > 0;

    /// <summary>"3 speakers": the tooltip and accessible name of the speaker icon.</summary>
    public string SpeakersText { get; }

    public IReadOnlyList<MeetingExport> Exports { get; }

    /// <summary>Recording, paused or finalizing: pinned on top with a pulsing dot; not deletable.</summary>
    public bool IsLive => Summary.Status is "recording" or "paused" or "finalizing";

    public bool CanDelete => !IsLive;

    /// <summary>Opened in the detail on the right.</summary>
    [ObservableProperty]
    public partial bool IsSelected { get; set; }

    /// <summary>The title is being renamed inline (Enter saves, Esc cancels).</summary>
    [ObservableProperty]
    public partial bool IsEditing { get; set; }

    [ObservableProperty]
    public partial string EditTitle { get; set; } = "";

    /// <summary>The export formats are shown next to the row actions.</summary>
    [ObservableProperty]
    public partial bool IsExportOpen { get; set; }

    /// <summary>The row's UI Automation name: title, time and duration.</summary>
    public string AccessibleName => ToString();

    /// <summary>What screen readers announce for the row.</summary>
    public override string ToString() => string.Join(", ", new[] { DisplayTitle, TimeRange, Duration }.Where(text => text.Length > 0));
}

/// <summary>A day of meetings: "Wed, 14 Oct" (or Today / Yesterday) and its total on the right.</summary>
public sealed class MeetingDay(DateOnly date, string label, IReadOnlyList<MeetingRow> rows)
{
    public DateOnly Date { get; } = date;

    public string Label { get; } = label;

    public IReadOnlyList<MeetingRow> Rows { get; } = rows;

    public double TotalSeconds => Rows.Sum(row => row.Summary.DurationSeconds ?? 0);

    public string Total => MeetingsPageViewModel.FormatDuration(TotalSeconds);

    public override string ToString() => $"{Label}, {Total}";
}

/// <summary>A week of day groups (Monday first): "This week", "Last week" or "6 – 12 Oct".</summary>
public sealed class MeetingWeek(DateOnly start, string label, bool showsHeader)
{
    public DateOnly Start { get; } = start;

    public string Label { get; } = label;

    /// <summary>Older weeks show their label and total; the first one is in the page header.</summary>
    public bool ShowsHeader { get; } = showsHeader;

    public ObservableCollection<MeetingDay> Days { get; } = [];

    public string Total => MeetingsPageViewModel.FormatDuration(Days.Sum(day => day.TotalSeconds));

    public override string ToString() => $"{Label}, {Total}";
}

/// <summary>A meeting that matches the search, with its matching lines (snippets).</summary>
public sealed partial class MeetingMatch(SearchGroup group, MeetingRow? row) : ObservableObject
{
    public SearchGroup Group { get; } = group;

    public string SessionId => Group.SessionId;

    /// <summary>The meeting's row; null until its summary is known (then the date stands in).</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(Title), nameof(IsUntitled), nameof(Details))]
    public partial MeetingRow? Row { get; set; } = row;

    public string Title => Row?.DisplayTitle ?? Group.Date;

    public bool IsUntitled => Row?.IsUntitled ?? false;

    /// <summary>"2026-10-15 20:23 · 0:42:00" under the title.</summary>
    public string Details => Row is { Summary.StartedAt: { } start } row
        ? $"{start.ToLocalTime().ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture)} · {row.Duration}"
        : "";

    public IReadOnlyList<SearchResultRow> Snippets => Group.Rows;

    public override string ToString() => Title;
}
