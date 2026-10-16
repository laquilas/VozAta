using VozAta.Desktop.Tests.Fakes;
using VozAta.Desktop.ViewModels;

namespace VozAta.Desktop.Tests;

public sealed class LevelMeterViewModelTests
{
    private readonly FakeClock _clock = new();

    private LevelMeterViewModel Meter(bool watchSilence = false) => new(_clock, watchSilence);

    private void Advance(LevelMeterViewModel meter, double seconds)
    {
        _clock.Advance(TimeSpan.FromSeconds(seconds));
        meter.Tick();
    }

    [Theory]
    [InlineData(-90, 0)]
    [InlineData(-60, 0)]
    [InlineData(-30, 0.5)]
    [InlineData(-15, 0.75)]
    [InlineData(0, 1)]
    [InlineData(3, 1)]
    public void Decibels_map_linearly_from_minus_60_to_0(double rmsDb, double expected)
    {
        Assert.Equal(expected, LevelMeterViewModel.Normalize(rmsDb), 6);
    }

    [Fact]
    public void A_louder_reading_shows_at_once_and_falls_at_a_fixed_rate_on_ticks()
    {
        var meter = Meter();
        meter.Begin();

        meter.OnLevel(0);
        Assert.Equal(1, meter.Level);
        meter.OnLevel(-60);
        Assert.Equal(1, meter.Level);  // no jump down
        Advance(meter, 0.2);

        Assert.Equal(1 - LevelMeterViewModel.FallPerSecond * 0.2, meter.Level, 6);
        Advance(meter, 5);
        Assert.Equal(0, meter.Level);
    }

    [Fact]
    public void The_level_never_falls_below_the_current_reading()
    {
        var meter = Meter();
        meter.Begin();
        meter.OnLevel(0);

        meter.OnLevel(-30);
        Advance(meter, 5);

        Assert.Equal(0.5, meter.Level, 6);
    }

    [Fact]
    public void The_peak_holds_for_a_second_then_falls()
    {
        var meter = Meter();
        meter.Begin();
        meter.OnLevel(-15);
        meter.OnLevel(-60);

        Advance(meter, 0.9);
        Assert.Equal(0.75, meter.Peak, 6);
        Advance(meter, 0.2);
        Assert.True(meter.Peak < 0.75);
        Assert.True(meter.Peak >= meter.Level);
        Advance(meter, 5);
        Assert.Equal(0, meter.Peak);
    }

    [Fact]
    public void Silence_on_a_watched_channel_raises_no_signal_after_30_seconds()
    {
        var meter = Meter(watchSilence: true);
        meter.Begin();

        for (var i = 0; i < 29; i++)
        {
            meter.OnLevel(-90);
            Advance(meter, 1);
        }

        Assert.False(meter.NoSignal);
        Advance(meter, 1);
        Assert.True(meter.NoSignal);
        meter.OnLevel(-40);
        Assert.False(meter.NoSignal);
    }

    [Fact]
    public void Paused_or_unwatched_channels_never_raise_no_signal()
    {
        var unwatched = Meter();
        var paused = Meter(watchSilence: true);
        unwatched.Begin();
        paused.Begin();
        paused.SetActive(false);

        Advance(unwatched, 60);
        Advance(paused, 60);
        Assert.False(unwatched.NoSignal || paused.NoSignal);

        paused.SetActive(true);  // the 30 s count restarts on resume
        Advance(paused, 29);
        Assert.False(paused.NoSignal);
        Advance(paused, 1);
        Assert.True(paused.NoSignal);
    }

    [Fact]
    public void End_resets_the_meter()
    {
        var meter = Meter(watchSilence: true);
        meter.Begin();
        meter.OnLevel(-10);
        Advance(meter, 31);

        meter.End();
        Advance(meter, 31);

        Assert.Equal((0d, 0d, false), (meter.Level, meter.Peak, meter.NoSignal));
    }

    [Fact]
    public void The_label_is_settable_for_the_view()
    {
        var meter = Meter();

        meter.Label = "Outros";

        Assert.Equal("Outros", meter.Label);
    }
}
