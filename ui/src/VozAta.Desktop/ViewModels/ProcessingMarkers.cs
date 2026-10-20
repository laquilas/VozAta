using VozAta.Client;

namespace VozAta.Desktop.ViewModels;

/// <summary>
/// Meetings whose background processing finished while the user was elsewhere (phase 40): the
/// Meetings list shows a green check on them until the meeting is opened or the app restarts.
/// </summary>
public interface IProcessingMarkers
{
    void MarkDone(string sessionId);

    bool IsUnseen(string sessionId);

    void Clear(string sessionId);
}

/// <summary>In-memory <see cref="IProcessingMarkers"/> (nothing survives a restart, by design).</summary>
public sealed class ProcessingMarkers : IProcessingMarkers
{
    private readonly HashSet<string> _unseen = [];

    public void MarkDone(string sessionId) => _unseen.Add(sessionId);

    public bool IsUnseen(string sessionId) => _unseen.Contains(sessionId);

    public void Clear(string sessionId) => _unseen.Remove(sessionId);
}

/// <summary>What the processing queue is doing with a meeting, as the badges and tabs read it.</summary>
public static class ProcessingStates
{
    /// <summary>The pipeline steps in order (the engine's step names).</summary>
    private static readonly string[] Steps = ["repair", "transcribe", "diarize", "minutes", "action_items", "index"];

    /// <summary>Queued, running or paused: the meeting is still in the queue.</summary>
    public static bool IsActive(ProcessingInfo? info) => info is { State: "queued" or "running" or "paused" };

    /// <summary>The speakers exist once diarization has finished.</summary>
    public static bool SpeakersPending(ProcessingInfo? info) => PendingThrough(info, "diarize");

    /// <summary>The minutes exist once the minutes step has finished.</summary>
    public static bool MinutesPending(ProcessingInfo? info) => PendingThrough(info, "minutes");

    /// <summary>"Queued (2)", "Processing 42 %", "Paused"; empty when the meeting is not in the queue.</summary>
    public static string Text(VozAta.Desktop.Services.ILocalizationService localization, ProcessingInfo? info) => info?.State switch
    {
        "queued" => localization.Format("Processing_Queued", info.Position ?? 1),
        "running" => localization.Format("Processing_Running", info.Percent),
        "paused" => localization["Processing_Paused"],
        _ => "",
    };

    private static bool PendingThrough(ProcessingInfo? info, string step)
    {
        if (!IsActive(info))
        {
            return false;
        }

        // Queued, or at a step we do not know yet: nothing is ready.
        var current = info!.State == "queued" || info.Step is null ? -1 : Array.IndexOf(Steps, info.Step);
        return current <= Array.IndexOf(Steps, step);
    }
}
