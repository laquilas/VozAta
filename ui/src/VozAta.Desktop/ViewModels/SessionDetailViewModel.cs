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
/// One past (or live) session: transcript, minutes, minutes regeneration and its files. Audio is
/// opened from the session folder, since the engine runs on this machine.
/// </summary>
public sealed partial class SessionDetailViewModel(
    IEngineClient client,
    IShellService shell,
    ILocalizationService localization,
    IFileSaver saver,
    SessionSummary summary,
    MinutesTemplatesViewModel? templates = null) : ObservableObject
{
    /// <summary>Export formats and the file-type name shown in the save dialog.</summary>
    private static readonly Dictionary<string, string> ExportTypes = new()
    {
        ["md"] = "FileTypeMarkdown",
        ["docx"] = "FileTypeWord",
        ["pdf"] = "FileTypePdf",
    };

    private IReadOnlyList<string> _files = [];

    public string Id => summary.Id;

    public string Title => FormatStart(summary.StartedAt) ?? summary.Id;

    /// <summary>Recording, paused or finalizing: no regeneration yet.</summary>
    public bool IsLive => summary.Status is "recording" or "paused" or "finalizing";

    public ObservableCollection<TranscriptLine> Lines { get; } = [];

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
    [NotifyCanExecuteChangedFor(nameof(OpenFolderCommand), nameof(OpenAudioCommand))]
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
            _files = detail.Files;
            Folder = detail.Folder;
            RegenerateTemplate ??= templates?.Find(SessionTemplate(detail));
            var transcript = await client.GetTranscriptAsync(Id, cancellationToken);
            Lines.Clear();
            foreach (var segment in transcript.Segments)
            {
                Lines.Add(new TranscriptLine(TranscriptLine.FormatTime(segment.Start), segment.Label, segment.Text, segment.Channel)
                {
                    SegmentId = segment.SegmentId,
                });
            }

            ApplyFocus();

            RegenerateMinutesCommand.NotifyCanExecuteChanged();
            await LoadMinutesAsync(cancellationToken);
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

    /// <summary>An <c>error</c> event: ends our regeneration with the engine's message.</summary>
    public void OnError(string? sessionId, string message)
    {
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

    private bool HasAudio(string? track) => Folder is not null && track is not null && _files.Contains($"{track}.wav");

    /// <summary>Open <c>mic</c>, <c>system</c> or <c>mixed</c> <c>.wav</c> in the default player.</summary>
    [RelayCommand(CanExecute = nameof(HasAudio))]
    private void OpenAudio(string? track) => shell.Open(Path.Combine(Folder!, $"{track}.wav"));

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
