using VozAta.Client;

namespace VozAta.Desktop.ViewModels;

/// <summary>Background processing (phase 40): each row shows where the queue is with its meeting.</summary>
public sealed partial class MeetingsPageViewModel
{
    private readonly IProcessingMarkers _markers;
    private readonly Dictionary<string, ProcessingInfo> _processing = []; // the latest event per queued meeting

    /// <summary>
    /// A <c>processing</c> event: the matching rows and the open meeting page follow it. When the
    /// meeting is done (or failed) the list reloads so its minutes and speakers appear; a finished
    /// meeting nobody has open gets a green check until it is opened.
    /// </summary>
    public async Task OnProcessingAsync(ProcessingEvent processing)
    {
        if (processing.SessionId is not { } id)
        {
            return;
        }

        var info = processing.Info;
        if (ProcessingStates.IsActive(info))
        {
            _processing[id] = info;
            ApplyProcessing(id, info);
            await History.OnProcessingAsync(processing);
            return;
        }

        _processing.Remove(id);
        if (info.State == "done" && History.Selected?.Id != id)
        {
            _markers.MarkDone(id);
        }

        ApplyProcessing(id, null);
        await History.OnProcessingAsync(processing);
        await LoadAsync();
    }

    /// <summary>A <c>status: done</c> of a meeting that finished in the background: reload its row.</summary>
    public Task OnSessionDoneAsync(string sessionId)
    {
        _processing.Remove(sessionId);
        return LoadAsync();
    }

    private ProcessingInfo? ProcessingOf(SessionSummary summary) =>
        _processing.TryGetValue(summary.Id, out var info) ? info : summary.Processing;

    private void ApplyProcessing(string id, ProcessingInfo? info)
    {
        foreach (var row in AllRows().Concat(Matches.Select(match => match.Row).OfType<MeetingRow>()).Where(row => row.Id == id))
        {
            row.ApplyProcessing(info, ProcessingText(info));
            row.UnseenDone = _markers.IsUnseen(id);
        }
    }

    private string ProcessingText(ProcessingInfo? info) => ProcessingStates.Text(_localization, info);
}
