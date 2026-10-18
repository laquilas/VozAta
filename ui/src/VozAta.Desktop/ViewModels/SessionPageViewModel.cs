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
/// One past (or live) session: transcript, minutes, minutes regeneration and its audio. A track
/// is played by downloading it from the engine (phase 32) into <paramref name="audioFolder"/>
/// (default: <c>%TEMP%\VozAta\audio</c>) and opening it in the default player, until the in-app
/// player of phase 37.
/// </summary>
public sealed partial class SessionPageViewModel(
    IEngineClient client,
    IShellService shell,
    ILocalizationService localization,
    IFileSaver saver,
    SessionSummary summary,
    MinutesTemplatesViewModel? templates = null,
    IDialogService? dialogs = null,
    string? audioFolder = null) : ObservableObject
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

    public string Id => summary.Id;

    /// <summary>The heading: the meeting title (phase 35), else the start date.</summary>
    public string Title => summary.Title ?? Date;

    public string Date => FormatStart(summary.StartedAt) ?? summary.Id;

    /// <summary>A titled meeting shows its date under the title.</summary>
    public bool ShowsDate => summary.Title is not null;

    /// <summary>Recording, paused or finalizing: no regeneration yet.</summary>
    public bool IsLive => summary.Status is "recording" or "paused" or "finalizing";

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

    [ObservableProperty]
    public partial bool IsLoading { get; private set; }

    [ObservableProperty]
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
    public partial bool IsExporting { get; private set; }

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(OpenFolderCommand))]
    public partial string? Folder { get; private set; }

    /// <summary>The open tab: <see cref="MinutesTab"/> or <see cref="TranscriptTab"/>.</summary>
    [ObservableProperty]
    public partial int SelectedTab { get; set; }

    /// <summary>The transcript line a search result opened; the view scrolls to it.</summary>
    [ObservableProperty]
    public partial TranscriptLine? FocusedLine { get; private set; }

    public const int MinutesTab = 0;

    public const int TranscriptTab = 1;

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
        IsLoading = true;
        Error = null;
        try
        {
            var detail = await client.GetSessionAsync(Id, cancellationToken);
            _audio = detail.Audio ?? new Dictionary<string, double>();
            OpenAudioCommand.NotifyCanExecuteChanged();
            Folder = detail.Folder;
            RegenerateTemplate ??= templates?.Find(SessionTemplate(detail));
            await Editor.LoadThresholdAsync(cancellationToken);
            await ShowTranscriptAsync(cancellationToken);
            await LoadMinutesAsync(cancellationToken);
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

    /// <summary>An <c>error</c> event: ends our regeneration with the engine's message.</summary>
    public void OnError(string? sessionId, string message)
    {
        _actionItems?.OnError(sessionId, message);
        if (sessionId == Id && IsBusy)
        {
            IsBusy = false;
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

    private bool HasFolder() => Folder is not null;

    [RelayCommand(CanExecute = nameof(HasFolder))]
    private void OpenFolder() => shell.Open(Folder!);

    private bool HasAudio(string? track) => track is not null && _audio.ContainsKey(track);

    /// <summary>
    /// Download <c>mic</c>, <c>system</c> or <c>mixed</c> as <c>&lt;id&gt;-&lt;track&gt;.wav</c> and open it in the
    /// default player. A file the player still holds is opened again as it is.
    /// </summary>
    [RelayCommand(CanExecute = nameof(HasAudio))]
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
                LowConfidenceParts = Editor.Highlight(segment),
            });
        }

        HasLowConfidence = Lines.Any(line => line.LowConfidenceParts is not null);
        ApplyFocus();
        if (!IsLive)
        {
            await Speakers.LoadAsync(transcript.Segments, cancellationToken);
        }

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

    private string ErrorText(Exception error) =>
        error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message;
}
