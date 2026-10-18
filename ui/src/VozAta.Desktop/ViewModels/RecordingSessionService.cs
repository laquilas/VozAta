using CommunityToolkit.Mvvm.ComponentModel;

namespace VozAta.Desktop.ViewModels;

/// <summary>
/// The recording everyone can see (phase 35): the recorder page drives it; the sidebar, the tray and
/// the other pages read it to show the red "recording" dot, the elapsed time and the title.
/// </summary>
public sealed partial class RecordingSessionService : ObservableObject
{
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsRecording), nameof(IsPaused), nameof(IsActivelyRecording), nameof(IsIdle))]
    public partial RecordingState State { get; set; } = RecordingState.Idle;

    /// <summary>Elapsed session time, <c>hh:mm:ss</c>; frozen while paused.</summary>
    [ObservableProperty]
    public partial string Elapsed { get; set; } = TranscriptLine.FormatTime(0);

    /// <summary>The id of the session being recorded (null until the engine names it).</summary>
    [ObservableProperty]
    public partial string? SessionId { get; set; }

    /// <summary>The title the engine has for the session being recorded; null = untitled.</summary>
    [ObservableProperty]
    public partial string? Title { get; set; }

    public bool IsIdle => State == RecordingState.Idle;

    public bool IsRecording => State is RecordingState.Recording or RecordingState.Paused;

    /// <summary>Paused: amber indicator, frozen timer, audio not transcribed.</summary>
    public bool IsPaused => State == RecordingState.Paused;

    /// <summary>Recording and not paused: red indicator.</summary>
    public bool IsActivelyRecording => State == RecordingState.Recording;
}
