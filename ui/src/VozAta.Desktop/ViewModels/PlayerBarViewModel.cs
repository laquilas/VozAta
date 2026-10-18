using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VozAta.Desktop.Services;

namespace VozAta.Desktop.ViewModels;

/// <summary>A playback speed of the player bar, e.g. <c>1.5×</c>.</summary>
public sealed record PlaybackRate(double Value)
{
    public string Label => Value.ToString("0.##", CultureInfo.InvariantCulture) + "×";

    public override string ToString() => Label;
}

/// <summary>
/// The player bar of the session page (phase 37): play/pause, −10 s / +10 s, a position slider,
/// speed, channel (mixed / mic / system: switching keeps the position) and volume. The stream is
/// opened on the first play (<paramref name="uriFor"/> gives a track's URL).
/// </summary>
public sealed partial class PlayerBarViewModel : ObservableObject, IDisposable
{
    public const double Skip = 10;

    private static readonly string[] TrackOrder = ["mixed", "mic", "system"];

    private readonly IAudioPlayer _player;
    private readonly IUiDispatcher _dispatcher;
    private readonly Func<string, Uri> _uriFor;
    private readonly ILocalizationService _localization;
    private string? _openTrack; // the track loaded in the player (null before the first play)
    private bool _fromPlayer; // the slider moves because the player did, not the user

    public PlayerBarViewModel(
        IAudioPlayer player,
        IUiDispatcher dispatcher,
        Func<string, Uri> uriFor,
        IReadOnlyDictionary<string, double> tracks,
        ILocalizationService localization)
    {
        _player = player;
        _dispatcher = dispatcher;
        _uriFor = uriFor;
        _localization = localization;
        Tracks = [.. TrackOrder.Where(tracks.ContainsKey).Select(key => new ChoiceOption(key, TrackKey(key)))];
        foreach (var track in Tracks)
        {
            track.Refresh(localization);
        }

        SelectedTrack = Tracks.Count > 0 ? Tracks[0] : null;
        Duration = tracks.Count == 0 ? 0 : tracks.Values.Max();
        SelectedRate = Rates[1];
        _player.PositionChanged += OnPlayerPositionChanged;
        _player.StateChanged += OnPlayerStateChanged;
    }

    public static IReadOnlyList<PlaybackRate> Rates { get; } =
        [new(0.75), new(1), new(1.25), new(1.5), new(2)];

    public IReadOnlyList<ChoiceOption> Tracks { get; }

    [ObservableProperty]
    public partial ChoiceOption? SelectedTrack { get; set; }

    [ObservableProperty]
    public partial PlaybackRate SelectedRate { get; set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(PositionText))]
    public partial double Position { get; set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(DurationText))]
    public partial double Duration { get; private set; }

    [ObservableProperty]
    public partial bool IsPlaying { get; private set; }

    [ObservableProperty]
    public partial int Volume { get; set; } = 100;

    [ObservableProperty]
    public partial string? Error { get; private set; }

    public string PositionText => TranscriptLine.FormatTime(Position);

    public string DurationText => TranscriptLine.FormatTime(Duration);

    public string PlayPauseText => _localization[IsPlaying ? "PlayerPause" : "PlayerPlay"];

    /// <summary>The position moved (the page highlights the line being played).</summary>
    public event EventHandler<double>? PositionMoved;

    [RelayCommand]
    private Task PlayPauseAsync()
    {
        if (_player.IsPlaying)
        {
            _player.Pause();
            return Task.CompletedTask;
        }

        return PlayFromAsync(Position);
    }

    [RelayCommand]
    private void Back() => SeekBy(-Skip);

    [RelayCommand]
    private void Forward() => SeekBy(Skip);

    /// <summary>Play from <paramref name="seconds"/> (a transcript line or a citation was clicked).</summary>
    public Task PlayFromAsync(double seconds) => StartAsync(seconds);

    public void RefreshTexts()
    {
        foreach (var track in Tracks)
        {
            track.Refresh(_localization);
        }

        OnPropertyChanged(nameof(PlayPauseText));
    }

    public void Dispose()
    {
        _player.PositionChanged -= OnPlayerPositionChanged;
        _player.StateChanged -= OnPlayerStateChanged;
        _player.Dispose();
    }

    partial void OnPositionChanged(double value)
    {
        if (!_fromPlayer && _openTrack is not null)
        {
            _player.Seek(value); // the user dragged the slider
        }

        PositionMoved?.Invoke(this, value);
    }

    partial void OnSelectedTrackChanged(ChoiceOption? value)
    {
        if (_openTrack is not null && value is not null && value.Value != _openTrack)
        {
            var playing = _player.IsPlaying;
            _ = SwitchTrackAsync(Position, playing);
        }
    }

    partial void OnSelectedRateChanged(PlaybackRate value) => _player.Rate = value.Value;

    partial void OnVolumeChanged(int value) => _player.Volume = Math.Clamp(value, 0, 100);

    partial void OnIsPlayingChanged(bool value) => OnPropertyChanged(nameof(PlayPauseText));

    private async Task StartAsync(double seconds)
    {
        if (SelectedTrack is null)
        {
            return;
        }

        if (!await EnsureOpenAsync(SelectedTrack.Value))
        {
            return;
        }

        _player.Seek(seconds);
        SetPosition(seconds);
        _player.Play();
    }

    private async Task SwitchTrackAsync(double position, bool playing)
    {
        if (!await EnsureOpenAsync(SelectedTrack!.Value))
        {
            return;
        }

        _player.Seek(position);
        SetPosition(position);
        if (playing)
        {
            _player.Play();
        }
    }

    private async Task<bool> EnsureOpenAsync(string track)
    {
        if (_openTrack == track)
        {
            return true;
        }

        Error = null;
        try
        {
            await _player.OpenAsync(_uriFor(track));
        }
        catch (Exception error) when (error is InvalidOperationException or IOException or HttpRequestException)
        {
            Error = error.Message;
            return false;
        }

        _openTrack = track;
        _player.Rate = SelectedRate.Value;
        _player.Volume = Volume;
        return true;
    }

    private void SeekBy(double delta)
    {
        var target = Math.Clamp(Position + delta, 0, Duration > 0 ? Duration : double.MaxValue);
        if (_openTrack is null)
        {
            SetPosition(target); // remembered for the first play
            return;
        }

        _player.Seek(target);
        SetPosition(target);
    }

    private void SetPosition(double seconds)
    {
        _fromPlayer = true;
        try
        {
            Position = seconds;
        }
        finally
        {
            _fromPlayer = false;
        }
    }

    private void OnPlayerPositionChanged(object? sender, EventArgs args) =>
        _dispatcher.Post(() =>
        {
            if (_player.Duration > 0)
            {
                Duration = _player.Duration;
            }

            SetPosition(_player.Position);
        });

    private void OnPlayerStateChanged(object? sender, EventArgs args) =>
        _dispatcher.Post(() => IsPlaying = _player.IsPlaying);

    private static string TrackKey(string track) => track switch
    {
        "mic" => "TrackMic",
        "system" => "TrackSystem",
        _ => "TrackMixed",
    };
}
