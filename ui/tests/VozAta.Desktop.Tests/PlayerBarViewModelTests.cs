using VozAta.Desktop.Services;
using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

/// <summary>The player bar of the session page (phase 37) over a fake player.</summary>
public sealed class PlayerBarViewModelTests : IDisposable
{
    private readonly FakeAudioPlayer _player = new() { Duration = 120 };
    private readonly LocalizationService _localization = new();

    private static readonly Dictionary<string, double> AllTracks = new() { ["mic"] = 120, ["system"] = 120, ["mixed"] = 120 };

    public void Dispose() => _player.Dispose();

    private PlayerBarViewModel Create(IReadOnlyDictionary<string, double>? tracks = null) =>
        new(_player, new ImmediateDispatcher(), track => new Uri($"http://engine/sessions/s1/audio/{track}"), tracks ?? AllTracks, _localization);

    [Fact]
    public void It_offers_the_recorded_tracks_mixed_first_and_starts_paused()
    {
        var bar = Create(new Dictionary<string, double> { ["system"] = 30, ["mixed"] = 31 });

        Assert.Equal(["mixed", "system"], bar.Tracks.Select(track => track.Value));
        Assert.Equal(_localization["TrackMixed"], bar.SelectedTrack!.Label);
        Assert.Equal(31, bar.Duration);
        Assert.Equal("00:00:31", bar.DurationText);
        Assert.False(bar.IsPlaying);
        Assert.Equal(_localization["PlayerPlay"], bar.PlayPauseText);
        Assert.Empty(_player.Calls); // nothing is opened before the first play
    }

    [Fact]
    public async Task Play_opens_the_selected_track_then_pause_pauses()
    {
        var bar = Create();

        await bar.PlayPauseCommand.ExecuteAsync(null);

        Assert.Equal(new Uri("http://engine/sessions/s1/audio/mixed"), _player.Opened);
        Assert.True(bar.IsPlaying);
        Assert.Equal(_localization["PlayerPause"], bar.PlayPauseText);
        await bar.PlayPauseCommand.ExecuteAsync(null);
        Assert.False(bar.IsPlaying);
        Assert.Equal(["open http://engine/sessions/s1/audio/mixed", "seek 0", "play", "pause"], _player.Calls);
    }

    [Fact]
    public async Task The_position_follows_the_player_and_the_slider_seeks()
    {
        var bar = Create();
        var moved = new List<double>();
        bar.PositionMoved += (_, seconds) => moved.Add(seconds);
        await bar.PlayPauseCommand.ExecuteAsync(null);

        _player.Advance(12.5);
        Assert.Equal(12.5, bar.Position);
        Assert.Equal("00:00:12", bar.PositionText);
        Assert.DoesNotContain("seek 12.5", _player.Calls); // the player moved: no seek back

        bar.Position = 60; // the user dragged the slider
        Assert.Equal(60, _player.Position);
        Assert.Equal([12.5, 60], moved);
    }

    [Fact]
    public async Task Back_and_forward_skip_ten_seconds_within_the_track()
    {
        var bar = Create();
        await bar.PlayPauseCommand.ExecuteAsync(null);
        _player.Advance(5);

        bar.BackCommand.Execute(null);
        Assert.Equal(0, bar.Position);
        bar.ForwardCommand.Execute(null);
        bar.ForwardCommand.Execute(null);
        Assert.Equal(20, _player.Position);
        _player.Advance(115);
        bar.ForwardCommand.Execute(null);
        Assert.Equal(120, bar.Position);
    }

    [Fact]
    public async Task Skipping_before_the_first_play_is_remembered()
    {
        var bar = Create();

        bar.ForwardCommand.Execute(null);
        Assert.Empty(_player.Calls);
        await bar.PlayPauseCommand.ExecuteAsync(null);

        Assert.Equal(10, _player.Position);
    }

    [Fact]
    public async Task Switching_the_channel_keeps_the_position_and_playing_state()
    {
        var bar = Create();
        await bar.PlayPauseCommand.ExecuteAsync(null);
        _player.Advance(42);

        bar.SelectedTrack = bar.Tracks.Single(track => track.Value == "system");

        Assert.Equal(new Uri("http://engine/sessions/s1/audio/system"), _player.Opened);
        Assert.Equal(42, _player.Position);
        Assert.True(_player.IsPlaying);
        Assert.Equal(42, bar.Position);
    }

    [Fact]
    public async Task Switching_the_channel_while_paused_stays_paused()
    {
        var bar = Create();
        await bar.PlayPauseCommand.ExecuteAsync(null);
        _player.Advance(7);
        await bar.PlayPauseCommand.ExecuteAsync(null);

        bar.SelectedTrack = bar.Tracks.Single(track => track.Value == "mic");

        Assert.Equal(new Uri("http://engine/sessions/s1/audio/mic"), _player.Opened);
        Assert.Equal(7, _player.Position);
        Assert.False(_player.IsPlaying);
    }

    [Fact]
    public void Choosing_a_channel_before_playing_opens_nothing()
    {
        var bar = Create();

        bar.SelectedTrack = bar.Tracks.Single(track => track.Value == "mic");

        Assert.Empty(_player.Calls);
    }

    [Fact]
    public async Task Speed_and_volume_reach_the_player_and_survive_a_new_stream()
    {
        var bar = Create();
        bar.SelectedRate = PlayerBarViewModel.Rates[^1];
        bar.Volume = 140;
        Assert.Equal(2, _player.Rate);
        Assert.Equal(100, _player.Volume);
        bar.Volume = 40;

        await bar.PlayPauseCommand.ExecuteAsync(null);

        Assert.Equal((2, 40), (_player.Rate, _player.Volume));
        Assert.Equal(["0.75×", "1×", "1.25×", "1.5×", "2×"], PlayerBarViewModel.Rates.Select(rate => rate.ToString()));
    }

    [Fact]
    public async Task Play_from_a_line_seeks_and_plays()
    {
        var bar = Create();

        await bar.PlayFromAsync(33.2);

        Assert.Equal(["open http://engine/sessions/s1/audio/mixed", "seek 33.2", "play"], _player.Calls);
        await bar.PlayFromAsync(50);
        Assert.Equal(["seek 50", "play"], _player.Calls[3..]);
    }

    [Fact]
    public async Task A_stream_that_cannot_be_opened_shows_the_error()
    {
        _player.OpenError = new InvalidOperationException("no audio output");
        var bar = Create();

        await bar.PlayPauseCommand.ExecuteAsync(null);
        bar.SelectedTrack = bar.Tracks[1];

        Assert.Equal("no audio output", bar.Error);
        Assert.False(bar.IsPlaying);
        Assert.DoesNotContain("play", _player.Calls);
    }

    [Fact]
    public async Task No_tracks_means_nothing_to_play()
    {
        var bar = Create(new Dictionary<string, double>());

        await bar.PlayPauseCommand.ExecuteAsync(null);

        Assert.Null(bar.SelectedTrack);
        Assert.Equal(0, bar.Duration);
        Assert.Empty(_player.Calls);
    }

    [Fact]
    public void An_ended_stream_shows_play_and_texts_follow_the_language()
    {
        var bar = Create();
        _player.Play();
        _player.End();
        Assert.False(bar.IsPlaying);

        _localization.SetLanguage("pt-BR");
        bar.RefreshTexts();

        Assert.Equal(_localization["PlayerPlay"], bar.PlayPauseText);
        Assert.Equal(_localization["TrackMixed"], bar.Tracks[0].Label);
    }

    [Fact]
    public void Dispose_releases_the_player()
    {
        var bar = Create();

        bar.Dispose();
        _player.Advance(3);

        Assert.True(_player.Disposed);
        Assert.Equal(0, bar.Position);
    }
}
