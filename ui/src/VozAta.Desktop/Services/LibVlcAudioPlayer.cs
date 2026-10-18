using System.Diagnostics.CodeAnalysis;
using LibVLCSharp.Shared;

namespace VozAta.Desktop.Services;

/// <summary>
/// <see cref="IAudioPlayer"/> over LibVLC (phase 37): plays the engine's HTTP audio stream directly
/// (it seeks with HTTP Range), no temp files; speed keeps the pitch (scaletempo). One LibVLC
/// instance for the app; LibVLC raises events on its own threads and must not be called back from
/// them, so a seek requested before playback starts is applied from the thread pool.
/// </summary>
[ExcludeFromCodeCoverage(Justification = "Native player; ViewModels use a fake, covered by the manual check.")]
public sealed class LibVlcAudioPlayer : IAudioPlayer
{
    private static readonly Lazy<LibVLC> Vlc = new(() =>
    {
        Core.Initialize(); // finds libvlc\win-x64 next to the executable
        return new LibVLC("--no-video", "--quiet");
    });

    private readonly MediaPlayer _player;
    private Media? _media;
    private double? _pendingSeek; // before the stream plays, VLC ignores a seek
    private double _duration;

    public LibVlcAudioPlayer()
    {
        _player = new MediaPlayer(Vlc.Value);
        _player.TimeChanged += (_, _) => PositionChanged?.Invoke(this, EventArgs.Empty);
        _player.LengthChanged += (_, args) =>
        {
            _duration = args.Length / 1000.0;
            PositionChanged?.Invoke(this, EventArgs.Empty);
        };
        _player.Playing += (_, _) =>
        {
            if (_pendingSeek is { } seconds)
            {
                _pendingSeek = null;
                ThreadPool.QueueUserWorkItem(_ => _player.Time = (long)(seconds * 1000));
            }

            StateChanged?.Invoke(this, EventArgs.Empty);
        };
        _player.Paused += (_, _) => StateChanged?.Invoke(this, EventArgs.Empty);
        _player.Stopped += (_, _) => StateChanged?.Invoke(this, EventArgs.Empty);
        _player.EndReached += (_, _) => StateChanged?.Invoke(this, EventArgs.Empty);
    }

    public event EventHandler? PositionChanged;

    public event EventHandler? StateChanged;

    public double Rate
    {
        get => _player.Rate;
        set => _player.SetRate((float)value);
    }

    public int Volume
    {
        get => _player.Volume;
        set => _player.Volume = Math.Clamp(value, 0, 100);
    }

    public double Position => _pendingSeek ?? Math.Max(0, _player.Time / 1000.0);

    public double Duration => _duration;

    public bool IsPlaying => _player.IsPlaying;

    public async Task OpenAsync(Uri uri, CancellationToken cancellationToken = default)
    {
        _player.Stop();
        _media?.Dispose();
        _media = new Media(Vlc.Value, uri);
        var status = await _media.Parse(MediaParseOptions.ParseNetwork, timeout: 10_000, cancellationToken);
        if (status != MediaParsedStatus.Done)
        {
            throw new InvalidOperationException($"The audio could not be opened ({status}).");
        }

        _duration = _media.Duration / 1000.0;
        _player.Media = _media;
        _pendingSeek = 0;
    }

    public void Play()
    {
        if (_player.State is VLCState.Ended or VLCState.Stopped)
        {
            _player.Stop(); // an ended stream starts again from the pending position
        }

        _player.Play();
    }

    public void Pause() => _player.SetPause(true);

    public void Seek(double seconds)
    {
        if (_player.State is VLCState.Playing or VLCState.Paused)
        {
            _player.Time = (long)(Math.Max(0, seconds) * 1000);
        }
        else
        {
            _pendingSeek = Math.Max(0, seconds);
        }
    }

    public void Dispose()
    {
        _player.Stop();
        _player.Dispose();
        _media?.Dispose();
    }
}
