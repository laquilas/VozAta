using VozAta.Client;

namespace VozAta.Desktop.ViewModels;

/// <summary>Background processing (phase 40): each row shows where the queue is with its meeting.</summary>
public sealed partial class MeetingsPageViewModel
{
    private readonly IProcessingMarkers _markers;

    // The latest event per meeting, newer than the last list: a null info means "no longer
    // processing" (it hides a stale summary until the next list). Each entry carries the sequence
    // number of its event, so a list requested before the event never drops it.
    private readonly Dictionary<string, (long Sequence, ProcessingInfo? Info)> _processing = [];
    private long _processingSequence;
    private long _loadsStarted; // list requests sent
    private long _loadApplied; // the newest list request whose answer was shown

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
            Remember(id, info);
            ApplyProcessing(id, info);
            await History.OnProcessingAsync(processing);
            return;
        }

        Remember(id, null);
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
        Remember(sessionId, null);
        return LoadAsync();
    }

    /// <summary>
    /// The engine connection dropped: forget every processing state and clear the rows' badges;
    /// the snapshot sent on reconnect (one <c>processing</c> event per pending meeting) rebuilds them.
    /// </summary>
    public void OnConnectionLost()
    {
        _processing.Clear();
        foreach (var id in AllRows().Where(row => row.IsProcessing).Select(row => row.Id).ToList())
        {
            Remember(id, null); // a stale summary must not bring the badge back before the next list
            ApplyProcessing(id, null);
        }
    }

    /// <summary>The sequence number a list request starts at (see <see cref="ForgetProcessingBefore"/>).</summary>
    private long ProcessingSequence => _processingSequence;

    /// <summary>A list requested at <paramref name="sequence"/> is the truth for every older event.</summary>
    private void ForgetProcessingBefore(long sequence)
    {
        foreach (var id in _processing.Where(entry => entry.Value.Sequence <= sequence).Select(entry => entry.Key).ToList())
        {
            _processing.Remove(id);
        }
    }

    private void Remember(string id, ProcessingInfo? info) => _processing[id] = (++_processingSequence, info);

    private ProcessingInfo? ProcessingOf(SessionSummary summary) =>
        _processing.TryGetValue(summary.Id, out var entry) ? entry.Info : summary.Processing;

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
