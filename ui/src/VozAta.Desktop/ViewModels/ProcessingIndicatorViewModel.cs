using CommunityToolkit.Mvvm.ComponentModel;
using VozAta.Client;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>
/// The sidebar indicator of the background queue (phase 40): "Processing 1 meeting · 42 %" for the
/// meeting being worked on and "+2 queued" for the rest. It is empty while the queue is.
/// </summary>
public sealed partial class ProcessingIndicatorViewModel(ILocalizationService localization) : ObservableObject
{
    private readonly Dictionary<string, ProcessingInfo> _pending = [];

    /// <summary>Meetings still queued, running or paused: what closing the app would interrupt.</summary>
    public int PendingCount => _pending.Count;

    public bool IsVisible => _pending.Count > 0;

    /// <summary>The meeting being processed (running or paused); false while the queue only waits.</summary>
    public bool HasRunning => Running.Count > 0;

    public bool HasQueued => QueuedCount > 0;

    /// <summary>"Processing 1 meeting · 42 %", empty when nothing is running.</summary>
    public string Text => Running is { Count: > 0 } running
        ? localization.Format("ProcessingIndicator_Text", running.Count, running.Max(info => info.Percent))
        : "";

    /// <summary>"+2 queued", empty when no meeting waits.</summary>
    public string QueuedText => HasQueued ? localization.Format("ProcessingIndicator_Queued", QueuedCount) : "";

    /// <summary>Both lines for the tooltip (the collapsed rail shows only the icon).</summary>
    public string ToolTipText => string.Join('\n', new[] { Text, QueuedText }.Where(line => line.Length > 0));

    private List<ProcessingInfo> Running => _pending.Values.Where(info => info.State != "queued").ToList();

    private int QueuedCount => _pending.Values.Count(info => info.State == "queued");

    /// <summary>A <c>processing</c> event: active states join the count, done and failed leave it.</summary>
    public void OnProcessing(ProcessingEvent processing)
    {
        if (processing.SessionId is not { } id)
        {
            return;
        }

        if (ProcessingStates.IsActive(processing.Info))
        {
            _pending[id] = processing.Info;
        }
        else
        {
            _pending.Remove(id);
        }

        Refresh();
    }

    /// <summary>The engine connection dropped: the snapshot on reconnect rebuilds the queue.</summary>
    public void Clear()
    {
        _pending.Clear();
        Refresh();
    }

    public void RefreshTexts() => Refresh();

    private void Refresh()
    {
        OnPropertyChanged(nameof(PendingCount));
        OnPropertyChanged(nameof(IsVisible));
        OnPropertyChanged(nameof(HasRunning));
        OnPropertyChanged(nameof(HasQueued));
        OnPropertyChanged(nameof(Text));
        OnPropertyChanged(nameof(QueuedText));
        OnPropertyChanged(nameof(ToolTipText));
    }
}
