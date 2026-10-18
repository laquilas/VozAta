using System.Collections.ObjectModel;
using System.Text.Json;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>What a meeting row does: open, rename, play, export, delete (with undo), and search matches.</summary>
public sealed partial class MeetingsPageViewModel
{
    /// <summary>How long "Undo" is offered before a file-backend meeting goes to the Recycle Bin.</summary>
    public static readonly TimeSpan UndoWindow = TimeSpan.FromSeconds(8);

    private static readonly Dictionary<string, string> FileTypes = new()
    {
        ["md"] = "FileTypeMarkdown",
        ["docx"] = "FileTypeWord",
        ["pdf"] = "FileTypePdf",
    };

    private readonly HashSet<string> _hidden = []; // deleted, waiting for the engine or the undo window
    private SessionSummary? _pending; // the delete "Undo" can still cancel
    private CancellationTokenSource? _undo;

    /// <summary>Matching meetings while <see cref="Search"/> is active, best match first.</summary>
    public ObservableCollection<MeetingMatch> Matches { get; } = [];

    /// <summary>The toast at the bottom of the page ("Moved to the Recycle Bin · Undo").</summary>
    [ObservableProperty]
    public partial string? Toast { get; private set; }

    /// <summary>The toast offers "Undo" (a file-backend delete inside its undo window).</summary>
    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(UndoCommand))]
    public partial bool CanUndo { get; private set; }

    /// <summary>The outcome of an export ("Saved to …").</summary>
    [ObservableProperty]
    public partial string? Message { get; private set; }

    /// <summary>The delete waiting for its undo window (tests await it).</summary>
    public Task PendingDelete { get; private set; } = Task.CompletedTask;

    /// <summary>The summaries fetched for search matches outside the loaded weeks (tests await it).</summary>
    public Task MatchesLoading { get; private set; } = Task.CompletedTask;

    /// <summary>Delete the meeting waiting for its undo window now (a new delete, or the app closing).</summary>
    public async Task CommitPendingAsync()
    {
        if (_pending is { } pending)
        {
            _undo?.Cancel();
            await DeleteNowAsync(pending);
        }
    }

    public void Dispose()
    {
        History.PropertyChanged -= OnHistoryChanged;
        _undo?.Dispose();
    }

    /// <summary>Delete a meeting from its page (phase 37): the same question and Undo as a row.</summary>
    public Task DeleteMeetingAsync(SessionSummary summary) => DeleteCommand.ExecuteAsync(NewRow(summary));

    /// <summary>A meeting was renamed on its page (phase 37): show the new title in the list.</summary>
    public Task OnRenamedAsync(SessionSummary summary)
    {
        Replace(summary);
        return Task.CompletedTask;
    }

    /// <summary>Open the meeting as its own page (phase 37).</summary>
    [RelayCommand]
    private void Open(MeetingRow? row)
    {
        if (row is not null && !row.IsEditing)
        {
            History.Show(row.Summary);
        }
    }

    [RelayCommand]
    private void OpenMatch(MeetingMatch? match) => Open(match?.Row);

    /// <summary>Show the title box in place of the title (Enter saves, Esc cancels).</summary>
    [RelayCommand]
    private void BeginRename(MeetingRow? row)
    {
        if (row is null)
        {
            return;
        }

        foreach (var other in AllRows().Where(other => other.IsEditing))
        {
            other.IsEditing = false;
        }

        row.EditTitle = row.Summary.Title ?? "";
        row.IsEditing = true;
    }

    [RelayCommand]
    private static void CancelRename(MeetingRow? row)
    {
        if (row is not null)
        {
            row.IsEditing = false;
        }
    }

    /// <summary><c>PATCH /sessions/{id}</c> with the edited title (blank = untitled).</summary>
    [RelayCommand]
    private async Task SaveRenameAsync(MeetingRow? row)
    {
        if (row is not { IsEditing: true })
        {
            return;
        }

        var title = string.IsNullOrWhiteSpace(row.EditTitle) ? null : row.EditTitle.Trim();
        if (title == row.Summary.Title)
        {
            row.IsEditing = false;
            return;
        }

        try
        {
            var renamed = await _client.UpdateSessionTitleAsync(row.Id, title);
            Error = null;
            Replace(row.Summary with { Title = renamed.Title });
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error); // the box stays open with the text
        }
    }

    /// <summary>Where "Play" downloads the recording (default <c>%TEMP%\VozAta\audio</c>).</summary>
    public string AudioFolder { get; init; } = AudioPlayback.DefaultFolder;

    /// <summary>
    /// Open the mixed recording in the default player: downloaded from the engine (phase 32), so it
    /// works for sqlite sessions, which have no folder.
    /// </summary>
    [RelayCommand]
    private async Task PlayAsync(MeetingRow? row)
    {
        if (row is null)
        {
            return;
        }

        try
        {
            var detail = await _client.GetSessionAsync(row.Id);
            if (detail.Audio is { } audio && audio.ContainsKey("mixed"))
            {
                Error = null;
                await AudioPlayback.OpenAsync(_client, _shell, AudioFolder, row.Id, "mixed");
            }
            else
            {
                Error = _localization["MeetingNoAudio"];
            }
        }
        catch (Exception error) when (AudioPlayback.IsExpected(error))
        {
            Error = error is IOException or UnauthorizedAccessException ? error.Message : ErrorText(error);
        }
    }

    [RelayCommand]
    private void ToggleExport(MeetingRow? row)
    {
        if (row is null)
        {
            return;
        }

        var open = !row.IsExportOpen;
        foreach (var other in AllRows().Where(other => other.IsExportOpen))
        {
            other.IsExportOpen = false;
        }

        row.IsExportOpen = open;
    }

    /// <summary>Download the meeting as Markdown, Word or PDF and ask where to save it.</summary>
    [RelayCommand]
    private async Task ExportAsync(MeetingExport? export)
    {
        if (export is null)
        {
            return;
        }

        export.Row.IsExportOpen = false;
        Message = null;
        try
        {
            var file = await _client.ExportSessionAsync(export.Row.Id, export.Format);
            var path = await _saver.SaveAsync(file.FileName, _localization[FileTypes[export.Format]], export.Format, file.Content);
            if (path is not null)
            {
                Error = null;
                Message = _localization.Format("ExportSaved", path);
            }
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException or IOException or UnauthorizedAccessException)
        {
            Error = ErrorText(error);
        }
    }

    /// <summary>
    /// Ask first (permanent for the database; the Recycle Bin for files), then hide the row. The
    /// database deletes at once; a file-backend meeting waits <see cref="UndoWindow"/> with "Undo".
    /// </summary>
    [RelayCommand]
    private async Task DeleteAsync(MeetingRow? row)
    {
        if (row is not { CanDelete: true })
        {
            return;
        }

        var recycle = _storage == "files";
        var confirmed = await _dialogs.ConfirmAsync(
            _localization["MeetingDeleteTitle"],
            _localization.Format(recycle ? "MeetingDeleteRecycle" : "MeetingDeletePermanent", row.DisplayTitle),
            _localization["MeetingDeleteConfirm"],
            _localization["MeetingDeleteCancel"]);
        if (!confirmed)
        {
            return;
        }

        await CommitPendingAsync();
        History.Forget(row.Id);
        _hidden.Add(row.Id);
        Render();
        RebuildMatches();
        if (!recycle)
        {
            await DeleteNowAsync(row.Summary);
            return;
        }

        _pending = row.Summary;
        _undo?.Dispose();
        _undo = new CancellationTokenSource();
        Toast = _localization.Format("MeetingDeletedUndo", row.DisplayTitle);
        CanUndo = true;
        PendingDelete = DeleteAfterUndoWindowAsync(row.Summary, _undo.Token);
    }

    /// <summary>Bring back the meeting whose delete is waiting for its undo window.</summary>
    [RelayCommand(CanExecute = nameof(CanUndo))]
    private void Undo()
    {
        if (_pending is not { } pending)
        {
            return;
        }

        _undo?.Cancel();
        _pending = null;
        _hidden.Remove(pending.Id);
        Toast = null;
        CanUndo = false;
        Render();
        RebuildMatches();
    }

    /// <summary>Close the toast; a pending delete goes ahead now.</summary>
    [RelayCommand]
    private Task DismissToastAsync()
    {
        Toast = null;
        return CommitPendingAsync();
    }

    private async Task DeleteAfterUndoWindowAsync(SessionSummary summary, CancellationToken cancellationToken)
    {
        try
        {
            await _delay(UndoWindow, cancellationToken);
        }
        catch (OperationCanceledException)
        {
            return; // undone, or deleted early by CommitPendingAsync
        }

        await DeleteNowAsync(summary);
    }

    private async Task DeleteNowAsync(SessionSummary summary)
    {
        var title = summary.Title ?? _localization["Untitled"];
        if (_pending?.Id == summary.Id)
        {
            _pending = null;
            CanUndo = false;
            Toast = null;
        }

        try
        {
            await _client.DeleteSessionAsync(summary.Id);
            Error = null;
            Remove(summary.Id);
            if (_storage != "files")
            {
                Toast = _localization.Format("MeetingDeleted", title);
            }
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error); // the meeting comes back
        }

        _hidden.Remove(summary.Id);
        Render();
        RebuildMatches();
    }

    /// <summary>Replace a meeting's summary in the loaded days (after a rename).</summary>
    private void Replace(SessionSummary summary)
    {
        for (var index = 0; index < _days.Count; index++)
        {
            var day = _days[index];
            if (day.Items.Any(item => item.Id == summary.Id))
            {
                _days[index] = day with { Items = [.. day.Items.Select(item => item.Id == summary.Id ? summary : item)] };
            }
        }

        Render();
        foreach (var match in Matches.Where(match => match.SessionId == summary.Id))
        {
            match.Row = NewRow(summary);
        }

        MarkSelected();
    }

    /// <summary>Drop a deleted meeting from the loaded days (and its day when it was the last one).</summary>
    private void Remove(string sessionId)
    {
        for (var index = _days.Count - 1; index >= 0; index--)
        {
            var day = _days[index];
            var rest = day.Items.Where(item => item.Id != sessionId).ToList();
            if (rest.Count == day.Items.Count)
            {
                continue;
            }

            if (rest.Count == 0)
            {
                _days.RemoveAt(index);
            }
            else
            {
                _days[index] = day with { Items = rest, TotalSeconds = rest.Sum(item => item.DurationSeconds ?? 0) };
            }
        }
    }

    /// <summary>One match per meeting of the search results; meetings outside the loaded weeks are fetched.</summary>
    private void RebuildMatches()
    {
        Matches.Clear();
        var missing = new List<MeetingMatch>();
        foreach (var group in Search.Groups.Where(group => !_hidden.Contains(group.SessionId)))
        {
            var summary = Known(group.SessionId);
            var match = new MeetingMatch(group, summary is null ? null : NewRow(summary));
            Matches.Add(match);
            if (summary is null)
            {
                missing.Add(match);
            }
        }

        MarkSelected();
        if (missing.Count > 0)
        {
            MatchesLoading = FetchMatchesAsync(missing);
        }
    }

    private SessionSummary? Known(string sessionId) =>
        _days.SelectMany(day => day.Items).FirstOrDefault(item => item.Id == sessionId)
        ?? History.Rows.FirstOrDefault(row => row.Id == sessionId)?.Summary;

    private async Task FetchMatchesAsync(IReadOnlyList<MeetingMatch> matches)
    {
        foreach (var match in matches)
        {
            try
            {
                match.Row = NewRow(FromDetail(await _client.GetSessionAsync(match.SessionId)));
            }
            catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
            {
                // The match keeps its date as the title.
            }
        }

        MarkSelected();
    }

    /// <summary>A summary from <c>GET /sessions/{id}</c> (its extra fields are in the metadata).</summary>
    private static SessionSummary FromDetail(SessionDetail detail)
    {
        var meta = detail.Metadata ?? new Dictionary<string, JsonElement>();
        string? Text(string key) => meta.TryGetValue(key, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() : null;
        var speakers = meta.TryGetValue("speaker_count", out var count) && count.ValueKind == JsonValueKind.Number ? count.GetInt32() : 0;
        var actionItems = meta.TryGetValue("has_action_items", out var items) && items.ValueKind == JsonValueKind.True;
        return new SessionSummary(
            detail.Id, detail.Status, detail.StartedAt, detail.EndedAt, detail.DurationSeconds, detail.Language,
            detail.HasMinutes, Text("title"), speakers, actionItems, Text("template"));
    }
}
