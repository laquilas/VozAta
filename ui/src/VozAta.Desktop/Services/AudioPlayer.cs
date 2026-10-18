namespace VozAta.Desktop.Services;

/// <summary>
/// Plays one audio stream in the app (phase 37): a session track served by the engine
/// (<c>GET /sessions/{id}/audio/{track}</c>, with HTTP Range), without temp files. Events may be
/// raised on a background thread; ViewModels marshal them with <see cref="IUiDispatcher"/>.
/// </summary>
public interface IAudioPlayer : IDisposable
{
    /// <summary>Load <paramref name="uri"/> paused at the start (replaces the current stream).</summary>
    Task OpenAsync(Uri uri, CancellationToken cancellationToken = default);

    void Play();

    void Pause();

    /// <summary>Move to <paramref name="seconds"/> (clamped to the stream by the player).</summary>
    void Seek(double seconds);

    /// <summary>Playback speed, 1 = normal.</summary>
    double Rate { get; set; }

    /// <summary>Volume, 0–100.</summary>
    int Volume { get; set; }

    /// <summary>The current position in seconds.</summary>
    double Position { get; }

    /// <summary>The length in seconds (0 while unknown).</summary>
    double Duration { get; }

    bool IsPlaying { get; }

    /// <summary>The position moved (several times a second while playing).</summary>
    event EventHandler? PositionChanged;

    /// <summary>Playing, paused or ended.</summary>
    event EventHandler? StateChanged;
}
