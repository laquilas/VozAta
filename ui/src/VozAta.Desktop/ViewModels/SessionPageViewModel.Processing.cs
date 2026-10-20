using CommunityToolkit.Mvvm.ComponentModel;
using VozAta.Client;

namespace VozAta.Desktop.ViewModels;

/// <summary>Background processing (phase 40): the header badge and the tabs that wait for their step.</summary>
public sealed partial class SessionPageViewModel
{
    private int _processingVersion; // bumped by every processing event, so a slow load cannot overwrite a newer one

    /// <summary>The queue's view of this meeting (null: not in the queue).</summary>
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsProcessing), nameof(IsRunning), nameof(ProcessingText), nameof(MinutesPending), nameof(SpeakersPending), nameof(ShowsNoMinutes))]
    public partial ProcessingInfo? Processing { get; private set; } = summary.Processing;

    /// <summary>The meeting finished processing while this page was open (a green check, no percent).</summary>
    [ObservableProperty]
    public partial bool ShowsDoneCheck { get; private set; }

    /// <summary>"Ready": the tooltip of the done check.</summary>
    public string DoneText => localization["Processing_Done"];

    public bool IsProcessing => ProcessingStates.IsActive(Processing);

    public bool IsRunning => Processing is { State: "running" };

    /// <summary>"Queued (2)", "Processing 42 %" or "Paused".</summary>
    public string ProcessingText => ProcessingStates.Text(localization, Processing);

    /// <summary>The minutes tab says "still being processed" while they are on the way and none exist yet.</summary>
    public bool MinutesPending => ProcessingStates.MinutesPending(Processing) && !HasMinutes;

    /// <summary>The speakers tab says "still being processed" while diarization is on the way and no speaker is known yet.</summary>
    public bool SpeakersPending => ProcessingStates.SpeakersPending(Processing) && !Speakers.HasRows;

    /// <summary>"No minutes yet" is only true once nothing is still producing them.</summary>
    public bool ShowsNoMinutes => !HasMinutes && !MinutesPending;

    private void ApplyDetailProcessing(ProcessingInfo? info, int versionAtStart)
    {
        if (versionAtStart == _processingVersion)
        {
            Processing = info; // no newer event arrived while the detail was loading
        }
    }

    private void RefreshPending()
    {
        OnPropertyChanged(nameof(SpeakersPending));
        OnPropertyChanged(nameof(MinutesPending));
        OnPropertyChanged(nameof(ShowsNoMinutes));
    }

    /// <summary>
    /// A <c>processing</c> event of this meeting: update the badge, and reload the speakers or the
    /// minutes when their step has just passed.
    /// </summary>
    public async Task OnProcessingAsync(ProcessingInfo info)
    {
        _processingVersion++;
        var minutesWereComing = ProcessingStates.MinutesPending(Processing);
        var speakersWereComing = ProcessingStates.SpeakersPending(Processing);
        Processing = ProcessingStates.IsActive(info) ? info : null;
        ShowsDoneCheck = info.State == "done";
        try
        {
            if (speakersWereComing && !ProcessingStates.SpeakersPending(Processing))
            {
                await ShowTranscriptAsync(CancellationToken.None); // also loads the speakers
            }

            if ((minutesWereComing && !ProcessingStates.MinutesPending(Processing)) || (info.State == "done" && !HasMinutes))
            {
                await LoadMinutesAsync(CancellationToken.None);
            }
        }
        catch (Exception error) when (error is EngineApiException or EngineUnavailableException)
        {
            Error = ErrorText(error);
        }
    }
}
