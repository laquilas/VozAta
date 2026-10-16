using System.Collections.ObjectModel;
using System.Globalization;
using System.Net;
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
    SessionSummary summary) : ObservableObject
{
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

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(OpenFolderCommand), nameof(OpenAudioCommand))]
    public partial string? Folder { get; private set; }

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
            var transcript = await client.GetTranscriptAsync(Id, cancellationToken);
            Lines.Clear();
            foreach (var segment in transcript.Segments)
            {
                Lines.Add(new TranscriptLine(TranscriptLine.FormatTime(segment.Start), segment.Label, segment.Text, segment.Channel));
            }

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

    private bool CanRegenerate() => !IsBusy && !IsLive && Lines.Count > 0;

    [RelayCommand(CanExecute = nameof(CanRegenerate))]
    private async Task RegenerateMinutesAsync()
    {
        Error = null;
        IsBusy = true;
        try
        {
            await client.RegenerateMinutesAsync(Id);
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            IsBusy = false;
            Error = ErrorText(error);
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

    private string ErrorText(Exception error) =>
        error is EngineUnavailableException ? localization["EngineUnavailable"] : error.Message;
}
