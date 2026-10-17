using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>One row of the history list.</summary>
public sealed record SessionRow(SessionSummary Summary, string Date, string Duration, string Language)
{
    public string Id => Summary.Id;

    public bool HasMinutes => Summary.HasMinutes;

    /// <summary>The session being recorded (or finalized) right now.</summary>
    public bool IsLive => Summary.Status is "recording" or "paused" or "finalizing";

    /// <summary>What screen readers announce for the row.</summary>
    public override string ToString() => $"{Date}, {Duration}, {Language}";
}

/// <summary>Past sessions, newest first, a page at a time; the selected one opens in <see cref="Detail"/>.</summary>
/// <param name="searchDelay">Waits out the search debounce (tests pass a controllable one).</param>
public sealed partial class HistoryViewModel(
    IEngineClient client,
    IShellService shell,
    ILocalizationService localization,
    IFileSaver saver,
    MinutesTemplatesViewModel? templates = null,
    Func<TimeSpan, CancellationToken, Task>? searchDelay = null,
    IDialogService? dialogs = null)
    : ObservableObject
{
    public const int PageSize = 20;

    private SearchViewModel? _search;

    /// <summary>Search across every transcript (phase 22); its results replace the list while active.</summary>
    public SearchViewModel Search =>
        _search ??= new SearchViewModel(client, localization, searchDelay) { OpenHit = OpenHitAsync };

    private AskViewModel? _ask;

    /// <summary>Questions about the selected meeting or all of them (phase 24).</summary>
    public AskViewModel Ask =>
        _ask ??= new AskViewModel(client, localization)
        {
            OpenCitation = citation => OpenSegmentAsync(citation.SessionId, citation.SegmentId),
            SelectedSessionId = Selected?.Id,
        };

    private static readonly Dictionary<string, string> LanguageKeys = new()
    {
        ["en"] = "LanguageEn",
        ["pt"] = "LanguagePt",
        ["es"] = "LanguageEs",
        ["auto"] = "LanguageAuto",
    };

    public ObservableCollection<SessionRow> Rows { get; } = [];

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(CanLoadMore))]
    [NotifyCanExecuteChangedFor(nameof(LoadMoreCommand))]
    public partial int Total { get; private set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsEmpty))]
    public partial bool IsLoading { get; private set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsEmpty))]
    public partial string? Error { get; private set; }

    [ObservableProperty]
    public partial SessionRow? Selected { get; set; }

    [ObservableProperty]
    public partial SessionDetailViewModel? Detail { get; private set; }

    /// <summary>The load started by the last selection (tests await it).</summary>
    public Task DetailLoading { get; private set; } = Task.CompletedTask;

    /// <summary>The unsaved-edits question started by the last selection (phase 21; tests await it).</summary>
    public Task SelectionGuard { get; private set; } = Task.CompletedTask;

    /// <summary>Whether the open session may be left; asks first when its transcript has unsaved edits.</summary>
    public Task<bool> ConfirmLeaveAsync() => Detail?.Editor.ConfirmLeaveAsync() ?? Task.FromResult(true);

    public bool CanLoadMore => Rows.Count < Total;

    /// <summary>Nothing recorded yet (not while loading or after an error).</summary>
    public bool IsEmpty => Rows.Count == 0 && !IsLoading && Error is null;

    /// <summary>Reload the first page, keeping the selected session.</summary>
    public async Task LoadAsync(CancellationToken cancellationToken = default)
    {
        var keep = Selected?.Id;
        IsLoading = true;
        Error = null;
        try
        {
            var page = await client.ListSessionsAsync(PageSize, 0, cancellationToken);
            Rows.Clear();
            Append(page);
            Selected = Rows.FirstOrDefault(row => row.Id == keep);
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message;
        }
        finally
        {
            IsLoading = false;
        }
    }

    /// <summary>A <c>minutes_ready</c> event: refresh the open detail and the row's minutes flag.</summary>
    public async Task OnMinutesReadyAsync(string? sessionId)
    {
        if (Detail is not null)
        {
            await Detail.OnMinutesReadyAsync(sessionId);
        }

        await LoadAsync();
    }

    /// <summary>A <c>speakers_relabeled</c> event: the open detail reloads its transcript when it is that session.</summary>
    public Task OnSpeakersRelabeledAsync(string? sessionId) =>
        Detail?.OnSpeakersRelabeledAsync(sessionId) ?? Task.CompletedTask;

    public void OnError(string? sessionId, string message) => Detail?.OnError(sessionId, message);

    /// <summary>An <c>action_items_ready</c> event (phase 23): reload the open detail's action items.</summary>
    public Task OnActionItemsReadyAsync(string? sessionId) =>
        Detail?.ActionItems.OnReadyAsync(sessionId) ?? Task.CompletedTask;

    /// <summary>Open a search hit: select its session (loading older pages if needed) at the segment.</summary>
    public Task OpenHitAsync(SearchHit hit) => OpenSegmentAsync(hit.SessionId, hit.SegmentId);

    /// <summary>Select a session (loading older pages if needed) and focus one of its segments.</summary>
    public async Task OpenSegmentAsync(string sessionId, string segmentId)
    {
        var row = Rows.FirstOrDefault(item => item.Id == sessionId);
        while (row is null && CanLoadMore && Error is null)
        {
            await LoadMoreAsync();
            row = Rows.FirstOrDefault(item => item.Id == sessionId);
        }

        if (row is null)
        {
            return; // deleted since it was indexed, or the list failed to load (Error shows why)
        }

        Selected = row;
        await SelectionGuard;
        if (Detail?.Id == row.Id)
        {
            Detail.FocusSegment(segmentId);
        }
    }

    /// <summary>Rebuild the row texts after a UI language switch.</summary>
    public void RefreshTexts()
    {
        var selected = Selected?.Id;
        var summaries = Rows.Select(row => row.Summary).ToList();
        Rows.Clear();
        foreach (var summary in summaries)
        {
            Rows.Add(ToRow(summary));
        }

        Selected = Rows.FirstOrDefault(row => row.Id == selected);
    }

    [RelayCommand]
    private Task RefreshAsync() => LoadAsync();

    [RelayCommand(CanExecute = nameof(CanLoadMore))]
    private async Task LoadMoreAsync()
    {
        try
        {
            Append(await client.ListSessionsAsync(PageSize, Rows.Count));
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message;
        }
    }

    partial void OnSelectedChanged(SessionRow? oldValue, SessionRow? newValue)
    {
        Ask.SelectedSessionId = newValue?.Id;
        if (newValue?.Id == Detail?.Id)
        {
            return; // same session after a refresh: keep the open detail
        }

        if (Detail?.Editor.IsDirty == true)
        {
            // Unsaved transcript edits (phase 21): a list reset (null) keeps them; another session asks first.
            SelectionGuard = newValue is null ? Task.CompletedTask : GuardSelectionAsync(oldValue, newValue);
            return;
        }

        Open(newValue);
    }

    private async Task GuardSelectionAsync(SessionRow? previous, SessionRow target)
    {
        if (await Detail!.Editor.ConfirmLeaveAsync())
        {
            Open(target);
        }
        else
        {
            Selected = previous; // back to the session being edited
        }
    }

    private void Open(SessionRow? row)
    {
        Detail = row is null ? null : new SessionDetailViewModel(client, shell, localization, saver, row.Summary, templates, dialogs);
        DetailLoading = Detail?.LoadAsync() ?? Task.CompletedTask;
    }

    private void Append(SessionPage page)
    {
        foreach (var summary in page.Items)
        {
            Rows.Add(ToRow(summary));
        }

        Total = page.Total;
        OnPropertyChanged(nameof(CanLoadMore));
        OnPropertyChanged(nameof(IsEmpty));
        LoadMoreCommand.NotifyCanExecuteChanged();
    }

    private SessionRow ToRow(SessionSummary summary) => new(
        summary,
        SessionDetailViewModel.FormatStart(summary.StartedAt) ?? summary.Id,
        TranscriptLine.FormatTime(summary.DurationSeconds ?? 0),
        summary.Language is { } code && LanguageKeys.TryGetValue(code, out var key) ? localization[key] : summary.Language ?? "");
}
