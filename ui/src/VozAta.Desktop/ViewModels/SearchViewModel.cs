using System.Collections.ObjectModel;
using System.Globalization;
using System.Text;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>A run of snippet text; <see cref="IsMatch"/> runs are highlighted.</summary>
public sealed record SnippetPart(string Text, bool IsMatch)
{
    /// <summary>Split an engine snippet at its match markers (unclosed markers end at the text end).</summary>
    public static IReadOnlyList<SnippetPart> Parse(string snippet)
    {
        var parts = new List<SnippetPart>();
        var text = new StringBuilder();
        var inMatch = false;
        foreach (var character in snippet)
        {
            if (character is SearchHit.MatchStart or SearchHit.MatchEnd)
            {
                Flush();
                inMatch = character == SearchHit.MatchStart;
            }
            else
            {
                text.Append(character);
            }
        }

        Flush();
        return parts;

        void Flush()
        {
            if (text.Length > 0)
            {
                parts.Add(new SnippetPart(text.ToString(), inMatch));
                text.Clear();
            }
        }
    }
}

/// <summary>One matching segment: time, speaker and the highlighted snippet.</summary>
public sealed record SearchResultRow(SearchHit Hit, string Time, IReadOnlyList<SnippetPart> Parts)
{
    public string Label => Hit.Label;

    /// <summary>What screen readers announce for the result.</summary>
    public override string ToString() => $"{Time} {Label}: {string.Concat(Parts.Select(part => part.Text))}";
}

/// <summary>The matches of one session, in transcript order.</summary>
public sealed record SearchGroup(string SessionId, string Date, IReadOnlyList<SearchResultRow> Rows)
{
    public override string ToString() => Date;
}

/// <summary>
/// Full-text search across every transcript (phase 22): searches once typing pauses, groups the
/// hits by session and asks the history to open a session at the chosen segment.
/// </summary>
public sealed partial class SearchViewModel(
    IEngineClient client,
    ILocalizationService localization,
    Func<TimeSpan, CancellationToken, Task>? delay = null) : ObservableObject
{
    public const int MinLength = 2;

    public const int Limit = 100;

    public static readonly TimeSpan Debounce = TimeSpan.FromMilliseconds(300);

    private readonly Func<TimeSpan, CancellationToken, Task> _delay = delay ?? Task.Delay;

    private CancellationTokenSource? _search;

    public ObservableCollection<SearchGroup> Groups { get; } = [];

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsActive))]
    public partial string Query { get; set; } = "";

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(NoResults))]
    public partial bool IsSearching { get; private set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(NoResults))]
    public partial string? Error { get; private set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(NoResults))]
    public partial bool HasSearched { get; private set; }

    /// <summary>Called with the hit the user picked (the history opens the session there).</summary>
    public Func<SearchHit, Task>? OpenHit { get; set; }

    /// <summary>The search started by the last edit (tests await it).</summary>
    public Task Pending { get; private set; } = Task.CompletedTask;

    /// <summary>Enough text to search: the results replace the session list.</summary>
    public bool IsActive => Query.Trim().Length >= MinLength;

    public bool NoResults => HasSearched && !IsSearching && Error is null && Groups.Count == 0;

    /// <summary>"20261015_202358" as "2026-10-15 20:23" (other ids unchanged).</summary>
    public static string FormatSessionDate(string sessionId) =>
        DateTime.TryParseExact(sessionId.Length >= 15 ? sessionId[..15] : sessionId, "yyyyMMdd_HHmmss",
            CultureInfo.InvariantCulture, DateTimeStyles.None, out var start)
            ? start.ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture)
            : sessionId;

    partial void OnQueryChanged(string value)
    {
        _search?.Cancel();
        _search?.Dispose();
        _search = null;
        if (!IsActive)
        {
            Groups.Clear();
            Error = null;
            IsSearching = false;
            HasSearched = false;
            return;
        }

        _search = new CancellationTokenSource();
        Pending = SearchAsync(value.Trim(), _search.Token);
    }

    [RelayCommand]
    private void Clear() => Query = "";

    [RelayCommand]
    private Task OpenAsync(SearchResultRow? row) =>
        row is not null && OpenHit is not null ? OpenHit(row.Hit) : Task.CompletedTask;

    private async Task SearchAsync(string query, CancellationToken cancellationToken)
    {
        try
        {
            await _delay(Debounce, cancellationToken);
            IsSearching = true;
            var results = await client.SearchAsync(query, Limit, cancellationToken);
            Show(results.Hits);
            Error = null;
            HasSearched = true;
        }
        catch (OperationCanceledException)
        {
            return; // a newer edit replaced this search
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Groups.Clear();
            Error = error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message;
        }

        IsSearching = false;
    }

    private void Show(IReadOnlyList<SearchHit> hits)
    {
        Groups.Clear();
        foreach (var session in hits.GroupBy(hit => hit.SessionId)) // ordered by each session's best hit
        {
            var rows = session
                .OrderBy(hit => hit.Start)
                .Select(hit => new SearchResultRow(hit, TranscriptLine.FormatTime(hit.Start), SnippetPart.Parse(hit.Snippet)))
                .ToList();
            Groups.Add(new SearchGroup(session.Key, FormatSessionDate(session.Key), rows));
        }
    }
}
