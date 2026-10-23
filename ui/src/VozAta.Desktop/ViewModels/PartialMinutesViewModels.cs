using System.Collections.ObjectModel;
using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>
/// The recorder's "Minutes so far" (phase 48): asks the engine for minutes of what was said until
/// now, without stopping, and shows them in a side panel (copy, close) once
/// <c>partial_minutes_ready</c> arrives for this recording.
/// </summary>
public sealed partial class MinutesSoFarViewModel(
    IEngineClient client, IShellService? shell, ILocalizationService localization, Action<string> notify)
    : ObservableObject
{
    /// <summary>Errors that end a partial minutes request of the engine.</summary>
    private static readonly HashSet<string> FailureCodes = ["empty_range", "partial_minutes_failed", "llm_unreachable"];

    private string? _sessionId;
    private string _markdown = "";

    public ObservableCollection<MarkdownBlock> Blocks { get; } = [];

    [ObservableProperty]
    public partial bool IsWriting { get; private set; }

    [ObservableProperty]
    public partial bool IsOpen { get; private set; }

    /// <summary>"Minutes up to 00:12:34".</summary>
    [ObservableProperty]
    public partial string? Caption { get; private set; }

    public async Task RequestAsync(string sessionId)
    {
        _sessionId = sessionId;
        IsWriting = true;
        try
        {
            await client.StartPartialMinutesAsync(sessionId);
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            IsWriting = false;
            notify(error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message);
        }
    }

    /// <summary>A voice command asked for minutes so far (phase 50): wait for them like a click.</summary>
    public void ExpectVoice(string sessionId)
    {
        _sessionId = sessionId;
        IsWriting = true;
    }

    /// <summary>A <c>partial_minutes_ready</c> event: show it when it is the one this recording asked for.</summary>
    public async Task OnReadyAsync(PartialMinutesReadyEvent ready)
    {
        if (!IsWriting || ready.SessionId != _sessionId || _sessionId is null)
        {
            return;
        }

        try
        {
            var item = await client.GetPartialMinutesItemAsync(_sessionId, ready.PartialId);
            _markdown = item.Markdown;
            Blocks.Clear();
            foreach (var block in MarkdownBlocks.Parse(item.Markdown))
            {
                Blocks.Add(block);
            }

            Caption = localization.Format("MinutesSoFarCaption", TranscriptLine.FormatTime(item.End));
            IsOpen = true;
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            notify(error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message);
        }
        finally
        {
            IsWriting = false;
        }
    }

    /// <summary>An <c>error</c> event: a failed request ends (its message is already a notification).</summary>
    public void OnError(string? sessionId, string code)
    {
        if (IsWriting && sessionId == _sessionId && FailureCodes.Contains(code))
        {
            IsWriting = false;
        }
    }

    [RelayCommand]
    private async Task CopyAsync()
    {
        if (shell is not null)
        {
            await shell.CopyTextAsync(_markdown);
            notify(localization["Copied"]);
        }
    }

    [RelayCommand]
    private void Close() => IsOpen = false;
}

/// <summary>One row of the meeting page's "Partial minutes" tab.</summary>
public sealed class PartialMinutesRow(PartialMinutesSummary summary, string title, string detail)
{
    public PartialMinutesSummary Summary { get; } = summary;

    /// <summary>"So far · 00:00:00 – 00:12:34".</summary>
    public string Title { get; } = title;

    /// <summary>When it was written, e.g. "22/10/2026 14:05".</summary>
    public string Detail { get; } = detail;
}

/// <summary>The meeting page's "Partial minutes" tab (phase 48): list, read, copy, delete.</summary>
public sealed partial class PartialMinutesListViewModel(
    IEngineClient client, IShellService shell, ILocalizationService localization, string sessionId)
    : ObservableObject
{
    private string _markdown = "";

    public ObservableCollection<PartialMinutesRow> Items { get; } = [];

    public ObservableCollection<MarkdownBlock> Blocks { get; } = [];

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasSelection))]
    [NotifyCanExecuteChangedFor(nameof(CopyCommand), nameof(DeleteCommand))]
    public partial PartialMinutesRow? Selected { get; set; }

    public bool HasSelection => Selected is not null;

    [ObservableProperty]
    public partial bool HasItems { get; private set; }

    [ObservableProperty]
    public partial string? Error { get; private set; }

    /// <summary>Read the list; keeps the selection, else selects <paramref name="select"/> or the newest.</summary>
    public async Task LoadAsync(string? select = null, CancellationToken cancellationToken = default)
    {
        Error = null;
        try
        {
            var list = await client.GetPartialMinutesAsync(sessionId, cancellationToken);
            var keep = select ?? Selected?.Summary.Id;
            Items.Clear();
            foreach (var item in list.Items)
            {
                Items.Add(Row(item));
            }

            HasItems = Items.Count > 0;
            Selected = Items.FirstOrDefault(row => row.Summary.Id == keep) ?? Items.LastOrDefault();
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error);
        }
    }

    /// <summary>A <c>partial_minutes_ready</c> event: reload and show the new one when it is this meeting's.</summary>
    public Task OnReadyAsync(PartialMinutesReadyEvent ready) =>
        ready.SessionId == sessionId ? LoadAsync(ready.PartialId) : Task.CompletedTask;

    partial void OnSelectedChanged(PartialMinutesRow? value) => _ = ShowAsync(value);

    private async Task ShowAsync(PartialMinutesRow? row)
    {
        Blocks.Clear();
        _markdown = "";
        if (row is null)
        {
            return;
        }

        try
        {
            var item = await client.GetPartialMinutesItemAsync(sessionId, row.Summary.Id);
            if (Selected != row)
            {
                return; // another one was selected meanwhile
            }

            _markdown = item.Markdown;
            foreach (var block in MarkdownBlocks.Parse(item.Markdown))
            {
                Blocks.Add(block);
            }
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error);
        }
    }

    [RelayCommand(CanExecute = nameof(HasSelection))]
    private Task CopyAsync() => shell.CopyTextAsync(_markdown);

    [RelayCommand(CanExecute = nameof(HasSelection))]
    private async Task DeleteAsync()
    {
        if (Selected is not { } row)
        {
            return;
        }

        try
        {
            await client.DeletePartialMinutesAsync(sessionId, row.Summary.Id);
            Selected = null;
            await LoadAsync();
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error);
        }
    }

    private PartialMinutesRow Row(PartialMinutesSummary item)
    {
        var origin = localization[$"PartialOrigin_{item.Origin}"];
        var range = $"{TranscriptLine.FormatTime(item.Start)} – {TranscriptLine.FormatTime(item.End)}";
        var written = DateTimeOffset.TryParse(item.CreatedAt, CultureInfo.InvariantCulture, DateTimeStyles.None, out var at)
            ? at.ToLocalTime().ToString("g", CultureInfo.CurrentCulture)
            : item.CreatedAt;
        return new PartialMinutesRow(item, $"{origin} · {range}", written);
    }

    private string ErrorText(Exception error) =>
        error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message;
}
