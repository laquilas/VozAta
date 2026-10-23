using System.Collections.ObjectModel;
using System.Globalization;
using System.Net;
using System.Text.Json;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>
/// The page of one past (or live) session (phase 37): header (back, editable title, date,
/// duration; regenerate, export, delete), the Minutes, Transcript, Speakers, Action items and Ask
/// tabs, and the in-app player (<see cref="Player"/>, none while live). Clicking a transcript line
/// plays from it; the line being played is highlighted. "Open in external player" downloads a
/// track into <paramref name="audioFolder"/> (default: <c>%TEMP%\VozAta\audio</c>) and opens it.
/// </summary>
public sealed partial class SessionPageViewModel(
    IEngineClient client,
    IShellService shell,
    ILocalizationService localization,
    IFileSaver saver,
    SessionSummary summary,
    MinutesTemplatesViewModel? templates = null,
    IDialogService? dialogs = null,
    string? audioFolder = null,
    IProcessingMarkers? markers = null) : ObservableObject, IDisposable
{
    /// <summary>Export formats and the file-type name shown in the save dialog.</summary>
    private static readonly Dictionary<string, string> ExportTypes = new()
    {
        ["md"] = "FileTypeMarkdown",
        ["docx"] = "FileTypeWord",
        ["pdf"] = "FileTypePdf",
    };

    private IReadOnlyDictionary<string, double> _audio = new Dictionary<string, double>();

    private readonly string _audioFolder = audioFolder ?? AudioPlayback.DefaultFolder;

    private string? _title = summary.Title;

    private double? _cue; // a moment to show once the player exists

    private AskViewModel? _ask;

    public string Id => summary.Id;

    /// <summary>The summary the page was opened with, with the current title.</summary>
    public SessionSummary Summary => summary with { Title = _title };

    /// <summary>The heading: the meeting title (phase 35), else the start date.</summary>
    public string Title => _title ?? Date;

    public string Date => FormatStart(summary.StartedAt) ?? summary.Id;

    /// <summary>A titled meeting shows its date under the title.</summary>
    public bool ShowsDate => _title is not null;

    /// <summary>The recorded length, <c>hh:mm:ss</c>.</summary>
    public string Duration => TranscriptLine.FormatTime(summary.DurationSeconds ?? 0);

    /// <summary>Builds the player bar of a session from its tracks (null: no in-app player).</summary>
    public Func<string, IReadOnlyDictionary<string, double>, PlayerBarViewModel?>? Players { get; init; }

    /// <summary>The title was saved (the meetings list shows it).</summary>
    public Func<SessionSummary, Task>? Renamed { get; init; }

    /// <summary>Delete this meeting (the Meetings page asks first and offers Undo).</summary>
    public Func<SessionSummary, Task>? DeleteMeeting { get; init; }

    /// <summary>Back to the meetings list.</summary>
    public Func<Task>? GoBack { get; init; }

    /// <summary>The in-app player (phase 37); null while live, without audio, or before loading.</summary>
    [ObservableProperty]
    public partial PlayerBarViewModel? Player { get; private set; }

    /// <summary>The line the player is playing.</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ScrollTarget))]
    public partial TranscriptLine? CurrentLine { get; private set; }

    /// <summary>The transcript scrolls to the line being played (the user can turn it off to read elsewhere).</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ScrollTarget))]
    public partial bool FollowPlayback { get; set; } = true;

    /// <summary>The line the transcript scrolls to: the played one while following, else a search hit.</summary>
    public TranscriptLine? ScrollTarget => FollowPlayback && CurrentLine is not null ? CurrentLine : FocusedLine;

    [ObservableProperty]
    public partial bool IsEditingTitle { get; private set; }

    [ObservableProperty]
    public partial string TitleDraft { get; set; } = "";

    /// <summary>The "Ask" tab: questions about this meeting only (phase 24); a citation shows its moment.</summary>
    public AskViewModel Ask => _ask ??= new AskViewModel(client, localization)
    {
        SelectedSessionId = Id,
        SelectedOnly = true,
        OpenCitation = citation =>
        {
            FocusSegment(citation.SegmentId);
            CueAt(citation.Start);
            return Task.CompletedTask;
        },
    };

    /// <summary>Recording, paused or finalizing: no regeneration yet.</summary>
    public bool IsLive => summary.Status is "recording" or "paused";

    public ObservableCollection<TranscriptLine> Lines { get; } = [];

    /// <summary>Some transcript word is highlighted as low confidence (the hint is shown).</summary>
    [ObservableProperty]
    public partial bool HasLowConfidence { get; private set; }

    private TranscriptEditorViewModel? _editor;

    /// <summary>Edit mode of the transcript tab (phase 21).</summary>
    public TranscriptEditorViewModel Editor =>
        _editor ??= new TranscriptEditorViewModel(client, localization, dialogs, Id) { IsLive = IsLive, Reload = ReloadTranscriptAsync };

    private SpeakersViewModel? _speakers;

    /// <summary>The "Speakers" tab (phase 16): saving names reloads this detail.</summary>
    public SpeakersViewModel Speakers => _speakers ??= new SpeakersViewModel(
        client,
        localization,
        summary.Id,
        LoadAsync,
        () => HasMinutes,
        () => RegenerateMinutesCommand.CanExecute(null) ? RegenerateMinutesCommand.ExecuteAsync(null) : Task.CompletedTask);

    private ActionItemsViewModel? _actionItems;

    /// <summary>The "Action items" tab (phase 23).</summary>
    public ActionItemsViewModel ActionItems =>
        _actionItems ??= new ActionItemsViewModel(client, localization, shell, Id) { IsLive = IsLive };

    public ObservableCollection<MarkdownBlock> Blocks { get; } = [];

    private PartialMinutesListViewModel? _partials;

    /// <summary>The "Partial minutes" tab (phase 48).</summary>
    public PartialMinutesListViewModel Partials =>
        _partials ??= new PartialMinutesListViewModel(client, shell, localization, Id);

    [ObservableProperty]
    public partial bool IsLoading { get; private set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ShowsNoMinutes), nameof(MinutesPending))]
    public partial bool HasMinutes { get; private set; }

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(RegenerateMinutesCommand))]
    public partial bool IsBusy { get; private set; }

    [ObservableProperty]
    public partial string? Error { get; private set; }

    /// <summary>Feedback such as "Saved to …".</summary>
    [ObservableProperty]
    public partial string? Message { get; private set; }

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ExportCommand))]
    [NotifyCanExecuteChangedFor(nameof(ExportBundleCommand))]
    public partial bool IsExporting { get; private set; }

    /// <summary>The meeting has audio (the player, "Open in external player" and "Delete audio").</summary>
    public bool HasAudio => _audio.Count > 0;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(OpenFolderCommand))]
    public partial string? Folder { get; private set; }

    /// <summary>The open tab: <see cref="MinutesTab"/> or <see cref="TranscriptTab"/>.</summary>
    [ObservableProperty]
    public partial int SelectedTab { get; set; }

    /// <summary>The transcript line a search result opened; the view scrolls to it.</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(ScrollTarget))]
    public partial TranscriptLine? FocusedLine { get; private set; }

    public const int MinutesTab = 0;

    /// <summary>Phase 48: minutes of parts of the meeting.</summary>
    public const int PartialMinutesTab = 1;

    public const int TranscriptTab = 2;

    public const int SpeakersTab = 3;

    public const int ActionItemsTab = 4;

    public const int AskTab = 5;

    private string? _focusSegmentId;

    /// <summary>Show the transcript at <paramref name="segmentId"/> (now, or once it has loaded).</summary>
    public void FocusSegment(string segmentId)
    {
        _focusSegmentId = segmentId;
        SelectedTab = TranscriptTab;
        ApplyFocus();
    }

    public static string? FormatStart(DateTimeOffset? startedAt) =>
        startedAt?.ToLocalTime().ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture);

    public async Task LoadAsync(CancellationToken cancellationToken = default)
    {
        markers?.Clear(Id); // opened: the "done" check on the list has done its job
        IsLoading = true;
        Error = null;
        try
        {
            var version = _processingVersion;
            var detail = await client.GetSessionAsync(Id, cancellationToken);
            ApplyDetailProcessing(detail.Processing, version);
            SetAudio(detail.Audio ?? new Dictionary<string, double>());
            CreatePlayer();
            Folder = detail.Folder;
            RegenerateTemplate ??= templates?.Find(SessionTemplate(detail));
            await Editor.LoadThresholdAsync(cancellationToken);
            await ShowTranscriptAsync(cancellationToken);
            await LoadMinutesAsync(cancellationToken);
            await Partials.LoadAsync(cancellationToken: cancellationToken);
            if (!IsLive)
            {
                await ActionItems.LoadAsync(cancellationToken);
            }
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error);
        }
        finally
        {
            IsLoading = false;
        }
    }

    /// <summary>A <c>minutes_ready</c> event: reload when it is ours.</summary>
    public async Task OnMinutesReadyAsync(string? sessionId)
    {
        if (sessionId != Id)
        {
            return;
        }

        try
        {
            await LoadMinutesAsync(CancellationToken.None);
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error);
        }
        finally
        {
            IsBusy = false;
        }
    }

    /// <summary>A <c>speakers_relabeled</c> event: reload the transcript (and speakers) when it is ours.</summary>
    public async Task OnSpeakersRelabeledAsync(string? sessionId)
    {
        if (sessionId != Id)
        {
            return;
        }

        try
        {
            await ShowTranscriptAsync(CancellationToken.None);
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error);
        }
    }

    /// <summary>
    /// An <c>error</c> event: ends our regeneration with the engine's message. An Ollama that does
    /// not answer (phase 43) is shown next to "Regenerate minutes" even when nothing was running,
    /// because the meeting's own processing is what failed to reach it.
    /// </summary>
    public void OnError(string? sessionId, string code, string message)
    {
        _actionItems?.OnError(sessionId, message);
        if (sessionId != Id)
        {
            return;
        }

        if (IsBusy)
        {
            IsBusy = false;
            Error = message;
        }
        else if (code == "llm_unreachable")
        {
            Error = message;
        }
    }

    /// <summary>Templates offered for "Regenerate minutes" (phase 20); none without a template list.</summary>
    public IReadOnlyList<TemplateOption> Templates => templates?.Items ?? (IReadOnlyList<TemplateOption>)[];

    /// <summary>Template of the next regeneration; the session's own once loaded (null = the engine picks).</summary>
    [ObservableProperty]
    public partial TemplateOption? RegenerateTemplate { get; set; }

    private bool CanRegenerate() => !IsBusy && !IsLive && Lines.Count > 0;

    [RelayCommand(CanExecute = nameof(CanRegenerate))]
    private async Task RegenerateMinutesAsync()
    {
        Error = null;
        IsBusy = true;
        Editor.SuggestRegenerate = false;
        try
        {
            await client.RegenerateMinutesAsync(Id, RegenerateTemplate?.Id);
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            IsBusy = false;
            Error = ErrorText(error);
        }
    }

    private bool CanExport(string? format) => !IsExporting && !IsLive && format is not null && ExportTypes.ContainsKey(format);

    /// <summary>Download the session as <c>md</c>, <c>docx</c> or <c>pdf</c> and ask where to save it.</summary>
    [RelayCommand(CanExecute = nameof(CanExport))]
    private async Task ExportAsync(string? format)
    {
        Error = Message = null;
        IsExporting = true;
        try
        {
            var file = await client.ExportSessionAsync(Id, format!);
            var path = await saver.SaveAsync(file.FileName, localization[ExportTypes[format!]], format!, file.Content);
            if (path is not null)
            {
                Message = localization.Format("ExportSaved", path);
            }
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException or IOException or UnauthorizedAccessException)
        {
            Error = error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message;
        }
        finally
        {
            IsExporting = false;
        }
    }

    private bool CanExportBundle() => !IsExporting && !IsLive;

    /// <summary>
    /// Save the meeting as a ZIP of its session folder (phase 39): transcripts, minutes, action
    /// items and both audio tracks; "Import meeting" reads it back.
    /// </summary>
    [RelayCommand(CanExecute = nameof(CanExportBundle))]
    private async Task ExportBundleAsync()
    {
        Error = Message = null;
        IsExporting = true;
        try
        {
            var path = await saver.SaveAsync(
                $"{Id}.zip", localization["FileTypeZip"], "zip", stream => client.DownloadBundleAsync(Id, stream));
            if (path is not null)
            {
                Message = localization.Format("ExportSaved", path);
            }
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException or IOException or UnauthorizedAccessException)
        {
            Error = ErrorText(error);
        }
        finally
        {
            IsExporting = false;
        }
    }

    private bool CanDeleteAudio() => !IsLive && HasAudio;

    /// <summary>
    /// Delete the meeting's audio after a confirmation (phase 39); the transcript, minutes and
    /// action items stay, and the player goes away.
    /// </summary>
    [RelayCommand(CanExecute = nameof(CanDeleteAudio))]
    private async Task DeleteAudioAsync()
    {
        if (dialogs is not null && !await dialogs.ConfirmAsync(
                localization["MeetingDeleteAudioTitle"],
                localization.Format("MeetingDeleteAudioMessage", Title),
                localization["MeetingDeleteAudio"],
                localization["MeetingDeleteCancel"]))
        {
            return;
        }

        Error = Message = null;
        try
        {
            await client.DeleteSessionAudioAsync(Id);
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error);
            return;
        }

        RemovePlayer();
        SetAudio(new Dictionary<string, double>());
        Message = localization["MeetingAudioDeleted"];
    }

    private void SetAudio(IReadOnlyDictionary<string, double> audio)
    {
        _audio = audio;
        OnPropertyChanged(nameof(HasAudio));
        OpenAudioCommand.NotifyCanExecuteChanged();
        DeleteAudioCommand.NotifyCanExecuteChanged();
    }

    private void RemovePlayer()
    {
        if (Player is null)
        {
            return;
        }

        Player.PositionMoved -= OnPlayerMoved;
        Player.Dispose();
        Player = null;
        if (CurrentLine is not null && Lines.IndexOf(CurrentLine) is var index and >= 0)
        {
            Lines[index] = CurrentLine with { IsCurrent = false };
        }

        CurrentLine = null;
    }

    private bool HasFolder() => Folder is not null;

    [RelayCommand(CanExecute = nameof(HasFolder))]
    private void OpenFolder() => shell.Open(Folder!);

    private bool HasTrack(string? track) => track is not null && _audio.ContainsKey(track);

    /// <summary>
    /// Download <c>mic</c>, <c>system</c> or <c>mixed</c> as <c>&lt;id&gt;-&lt;track&gt;.wav</c> and open it in the
    /// default player. A file the player still holds is opened again as it is.
    /// </summary>
    [RelayCommand(CanExecute = nameof(HasTrack))]
    private async Task OpenAudioAsync(string? track)
    {
        Error = null;
        try
        {
            await AudioPlayback.OpenAsync(client, shell, _audioFolder, Id, track!);
        }
        catch (Exception error) when (AudioPlayback.IsExpected(error))
        {
            Error = error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message;
        }
    }

    /// <summary>Load the best transcript into the read view (low-confidence words marked) and the editor.</summary>
    private async Task ShowTranscriptAsync(CancellationToken cancellationToken)
    {
        var transcript = await client.GetTranscriptAsync(Id, cancellationToken);
        Editor.Load(transcript);
        Lines.Clear();
        foreach (var segment in transcript.Segments)
        {
            Lines.Add(new TranscriptLine(TranscriptLine.FormatTime(segment.Start), segment.Label, segment.Text, segment.Channel)
            {
                SegmentId = segment.SegmentId,
                Start = segment.Start,
                LowConfidenceParts = Editor.Highlight(segment),
            });
        }

        HasLowConfidence = Lines.Any(line => line.LowConfidenceParts is not null);
        ApplyFocus();
        CurrentLine = null; // the lines were rebuilt: highlight the played one again
        if (Player is not null)
        {
            OnPlayerMoved(this, Player.Position);
        }

        if (!IsLive)
        {
            await Speakers.LoadAsync(transcript.Segments, cancellationToken);
        }

        RefreshPending();
        RegenerateMinutesCommand.NotifyCanExecuteChanged();
    }

    private Task ReloadTranscriptAsync() => ShowTranscriptAsync(CancellationToken.None);

    private async Task LoadMinutesAsync(CancellationToken cancellationToken)
    {
        Blocks.Clear();
        try
        {
            var minutes = await client.GetMinutesAsync(Id, cancellationToken);
            foreach (var block in MarkdownBlocks.Parse(minutes.Markdown))
            {
                Blocks.Add(block);
            }

            HasMinutes = true;
        }
        catch (EngineApiException error) when (error.Status == HttpStatusCode.NotFound)
        {
            HasMinutes = false;
        }
    }

    private static string? SessionTemplate(SessionDetail detail) =>
        detail.Metadata?.TryGetValue("template", out var value) == true && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private void ApplyFocus()
    {
        var index = _focusSegmentId is null ? -1 : Lines.ToList().FindIndex(line => line.SegmentId == _focusSegmentId);
        if (index < 0)
        {
            return; // not loaded yet (or not in this transcript)
        }

        _focusSegmentId = null;
        if (FocusedLine is not null && Lines.IndexOf(FocusedLine) is var previous and >= 0)
        {
            Lines[previous] = FocusedLine with { IsFocused = false };
        }

        FocusedLine = Lines[index] with { IsFocused = true };
        Lines[index] = FocusedLine;
    }

    /// <summary>Show <paramref name="seconds"/> in the player (a search hit or a citation), without playing.</summary>
    public void CueAt(double seconds)
    {
        if (Player is null)
        {
            _cue = seconds;
            return;
        }

        Player.Position = seconds;
    }

    public void Dispose() => RemovePlayer();

    /// <summary>Play the recording from a transcript line.</summary>
    [RelayCommand]
    private Task PlayLineAsync(TranscriptLine? line) =>
        line is null || Player is null ? Task.CompletedTask : Player.PlayFromAsync(line.Start);

    [RelayCommand]
    private void BeginRename()
    {
        TitleDraft = _title ?? "";
        IsEditingTitle = true;
    }

    [RelayCommand]
    private void CancelRename() => IsEditingTitle = false;

    /// <summary><c>PATCH /sessions/{id}</c> with the edited title (blank = untitled).</summary>
    [RelayCommand]
    private async Task SaveRenameAsync()
    {
        if (!IsEditingTitle)
        {
            return;
        }

        var title = string.IsNullOrWhiteSpace(TitleDraft) ? null : TitleDraft.Trim();
        if (title == _title)
        {
            IsEditingTitle = false;
            return;
        }

        try
        {
            var renamed = await client.UpdateSessionTitleAsync(Id, title);
            _title = renamed.Title;
            IsEditingTitle = false;
            Error = null;
            OnPropertyChanged(nameof(Title));
            OnPropertyChanged(nameof(ShowsDate));
            if (Renamed is not null)
            {
                await Renamed(Summary);
            }
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error); // the box stays open with the text
        }
    }

    private bool CanDelete() => !IsLive && DeleteMeeting is not null;

    [RelayCommand(CanExecute = nameof(CanDelete))]
    private Task DeleteAsync() => DeleteMeeting!(Summary);

    [RelayCommand]
    private Task BackAsync() => GoBack?.Invoke() ?? Task.CompletedTask;

    private void CreatePlayer()
    {
        if (Player is not null || IsLive || _audio.Count == 0 || Players is null)
        {
            return;
        }

        Player = Players(Id, _audio);
        if (Player is null)
        {
            return;
        }

        Player.PositionMoved += OnPlayerMoved;
        if (_cue is { } cue)
        {
            _cue = null;
            Player.Position = cue;
        }
    }

    /// <summary>Highlight the last line that started at or before the position.</summary>
    private void OnPlayerMoved(object? sender, double seconds)
    {
        var index = -1;
        for (var i = 0; i < Lines.Count && Lines[i].Start <= seconds; i++)
        {
            index = i;
        }

        var current = CurrentLine is null ? -1 : Lines.IndexOf(CurrentLine);
        if (index == current)
        {
            return;
        }

        if (current >= 0)
        {
            Lines[current] = Lines[current] with { IsCurrent = false };
        }

        CurrentLine = index < 0 ? null : Lines[index] with { IsCurrent = true };
        if (CurrentLine is not null)
        {
            Lines[index] = CurrentLine;
        }
    }

    private string ErrorText(Exception error) =>
        error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message;
}
