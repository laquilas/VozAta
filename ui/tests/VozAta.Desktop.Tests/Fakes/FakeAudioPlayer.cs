using VozAta.Desktop.Services;

namespace VozAta.Desktop.Tests.Fakes;

/// <summary>An in-app player the test drives: records calls, moves the position by hand.</summary>
internal sealed class FakeAudioPlayer : IAudioPlayer
{
    public List<string> Calls { get; } = [];

    public Uri? Opened { get; private set; }

    public Exception? OpenError { get; set; }

    public double Rate { get; set; } = 1;

    public int Volume { get; set; } = 100;

    public double Position { get; private set; }

    public double Duration { get; set; }

    public bool IsPlaying { get; private set; }

    public bool Disposed { get; private set; }

    public event EventHandler? PositionChanged;

    public event EventHandler? StateChanged;

    public Task OpenAsync(Uri uri, CancellationToken cancellationToken = default)
    {
        Calls.Add($"open {uri}");
        if (OpenError is not null)
        {
            return Task.FromException(OpenError);
        }

        Opened = uri;
        Position = 0;
        SetPlaying(false);
        return Task.CompletedTask;
    }

    public void Play()
    {
        Calls.Add("play");
        SetPlaying(true);
    }

    public void Pause()
    {
        Calls.Add("pause");
        SetPlaying(false);
    }

    public void Seek(double seconds)
    {
        Calls.Add(FormattableString.Invariant($"seek {seconds}"));
        Position = seconds;
    }

    /// <summary>Playback reached <paramref name="seconds"/> (as the real player reports it).</summary>
    public void Advance(double seconds)
    {
        Position = seconds;
        PositionChanged?.Invoke(this, EventArgs.Empty);
    }

    public void End() => SetPlaying(false);

    public void Dispose() => Disposed = true;

    private void SetPlaying(bool playing)
    {
        IsPlaying = playing;
        StateChanged?.Invoke(this, EventArgs.Empty);
    }
}
